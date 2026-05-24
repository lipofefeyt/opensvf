"""
Orbital Environment Model — M42
SGP4 propagator + eclipse + solar irradiance + tilted-dipole magnetic field.

Publishes orbital truth state to ParameterStore each tick so that sensor
models (magnetometer, CSS, GPS, solar array) receive physically meaningful
inputs without requiring the KDE C++ FMU.

Migration note: the SGP4 propagation and dipole model are intentionally
kept in pure Python for this milestone. M48 will migrate them into the
opensvf-kde FMU once the interface is stable (SVF-DEV-175).

Implements: SVF-DEV-170, SVF-DEV-171, SVF-DEV-172

Output ports (equipment_id='orbital')
--------------------------------------
orbital.position_eci_x/y/z   km       Spacecraft position in ECI TEME
orbital.velocity_eci_x/y/z   km/s     Spacecraft velocity in ECI TEME
orbital.altitude              km       Altitude above mean sphere
orbital.latitude              deg      Geocentric latitude
orbital.longitude             deg      Longitude (ECEF)
orbital.eclipse               0/1      1.0 = in Earth's shadow
orbital.illumination          0–1      Solar illumination fraction
orbital.solar_irradiance      W/m²     Solar irradiance at spacecraft
orbital.sun_eci_x/y/z         –        Unit sun-direction vector in ECI
orbital.mag_field_n           T        True B-field, north (NED)
orbital.mag_field_e           T        True B-field, east  (NED)
orbital.mag_field_d           T        True B-field, down  (NED)

Frame note: mag_field_n/e/d are in NED (north-east-down) at the
spacecraft's sub-satellite point.  M48 will rotate these into body
frame once attitude is available from the KDE FMU.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import Equipment, PortDefinition, PortDirection
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore

try:
    from sgp4.api import Satrec as _Satrec
    _HAS_SGP4 = True
except ImportError:
    _Satrec = None  # type: ignore[assignment,misc]
    _HAS_SGP4 = False

logger = logging.getLogger(__name__)

# ── Physical constants ────────────────────────────────────────────────────────
_R_EARTH_KM    = 6371.0          # mean Earth radius (km)
_AU_KM         = 1.495978707e8   # astronomical unit (km)
_SOLAR_CONST   = 1361.0          # solar irradiance at 1 AU (W/m²)

# IGRF-13 first-degree Gauss coefficients (nT), epoch 2020.0
# Used for the dipole (n=1) terms only.
_G10 = -29404.5  # nT
_G11 =  -1450.9  # nT
_H11 =   4652.5  # nT
_R_IGRF_KM = 6371.2              # reference radius for IGRF (km)


# ── Pure-math helpers (no numpy) ──────────────────────────────────────────────

def _dot3(a: tuple[float, float, float],
          b: tuple[float, float, float]) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _norm3(v: tuple[float, float, float]) -> float:
    return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])


def _unit3(v: tuple[float, float, float]) -> tuple[float, float, float]:
    n = _norm3(v)
    if n < 1e-30:
        return (0.0, 0.0, 1.0)
    return (v[0]/n, v[1]/n, v[2]/n)


def _rotate_z(v: tuple[float, float, float],
              theta: float) -> tuple[float, float, float]:
    """Rotate vector v around z-axis by angle theta (radians)."""
    c, s = math.cos(theta), math.sin(theta)
    return (c*v[0] + s*v[1], -s*v[0] + c*v[1], v[2])


# ── Coordinate transforms ──────────────────────────────────────────────────────

def _gmst(jd: float) -> float:
    """Greenwich Mean Sidereal Time in radians at Julian date jd."""
    T = (jd - 2451545.0) / 36525.0
    deg = (280.46061837
           + 360.98564736629 * (jd - 2451545.0)
           + 0.000387933 * T * T)
    return math.radians(deg % 360.0)


def _eci_to_ecef(
    r_eci: tuple[float, float, float],
    jd: float,
) -> tuple[float, float, float]:
    """Rotate ECI position to ECEF using GMST."""
    return _rotate_z(r_eci, _gmst(jd))


def _ecef_to_geodetic(
    r_ecef: tuple[float, float, float],
) -> tuple[float, float, float]:
    """
    Convert ECEF (km) to (geocentric_lat_deg, lon_deg, alt_km).
    Uses spherical Earth — adequate for dipole model.
    """
    x, y, z = r_ecef
    r   = _norm3(r_ecef)
    lat = math.degrees(math.asin(z / r)) if r > 1e-10 else 0.0
    lon = math.degrees(math.atan2(y, x))
    alt = r - _R_EARTH_KM
    return lat, lon, alt


# ── Sun ephemeris ──────────────────────────────────────────────────────────────

def _sun_unit_eci(jd: float) -> tuple[float, float, float]:
    """
    Low-precision sun direction unit vector in ECI J2000 (Vallado, 2013).
    Accurate to ~0.01° — sufficient for eclipse and irradiance models.
    """
    T   = (jd - 2451545.0) / 36525.0
    L   = math.radians((280.460 + 36000.77 * T) % 360.0)
    g   = math.radians((357.528 + 35999.05 * T) % 360.0)
    lam = L + math.radians(1.914666 * math.sin(g) + 0.019994 * math.sin(2*g))
    eps = math.radians(23.439291 - 0.013004 * T)
    return _unit3((
        math.cos(lam),
        math.sin(lam) * math.cos(eps),
        math.sin(lam) * math.sin(eps),
    ))


# ── Eclipse ────────────────────────────────────────────────────────────────────

def _in_eclipse(
    r_eci: tuple[float, float, float],
    sun_unit: tuple[float, float, float],
) -> bool:
    """
    Cylindrical shadow model.
    Returns True if r_eci is inside Earth's geometric shadow.
    """
    dot_rs = _dot3(r_eci, sun_unit)
    if dot_rs > 0.0:
        return False                          # spacecraft on sunlit side
    r2        = _dot3(r_eci, r_eci)
    r_perp_sq = r2 - dot_rs * dot_rs
    return r_perp_sq < _R_EARTH_KM * _R_EARTH_KM


# ── Tilted-dipole magnetic field ───────────────────────────────────────────────

def _dipole_field_ned(
    lat_deg: float,
    lon_deg: float,
    r_km: float,
) -> tuple[float, float, float]:
    """
    IGRF-13 first-degree tilted-dipole field in NED (T) at (lat, lon, r_km).

    Uses Gauss coefficients g₁₀, g₁₁, h₁₁ only (dipole terms).
    Accurate to ~10 % for LEO; IGRF higher-degree terms are M43.

    Returns:
        (B_N, B_E, B_D) in Tesla.
    """
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    # geocentric colatitude
    colat  = math.pi / 2.0 - lat
    sin_co = math.sin(colat)
    cos_co = math.cos(colat)
    sin_lo = math.sin(lon)
    cos_lo = math.cos(lon)

    # (R_ref / r)^3 — dipole field falls off as r^-3
    ratio3 = (_R_IGRF_KM / r_km) ** 3

    # Radial component (positive outward)
    B_r = -2.0 * ratio3 * (
        _G10 * cos_co
        + _G11 * sin_co * cos_lo
        + _H11 * sin_co * sin_lo
    )
    # Southward (−colatitudinal) component
    B_theta = -ratio3 * (
        -_G10 * sin_co
        +  _G11 * cos_co * cos_lo
        +  _H11 * cos_co * sin_lo
    )
    # Eastward component
    B_phi = -ratio3 * (
        -_G11 * sin_lo
        +  _H11 * cos_lo
    )

    # NED convention: N = -B_theta, E = B_phi, D = -B_r
    # Convert nT → T
    B_N = -B_theta * 1e-9
    B_E =  B_phi   * 1e-9
    B_D = -B_r     * 1e-9
    return B_N, B_E, B_D


# ── Equipment class ────────────────────────────────────────────────────────────

class OrbitalEnvironment(Equipment):
    """
    Orbital environment truth model.

    Propagates a TLE with SGP4 each tick and computes eclipse, solar
    irradiance, sun direction, and a tilted-dipole magnetic field.  The
    results are published to ParameterStore so sensor models receive
    realistic, orbit-varying inputs without the KDE C++ FMU.

    This is the pure-Python counterpart to the orbital environment that
    will eventually live inside opensvf-kde (M48 / SVF-DEV-175).

    Args:
        tle_line1:    TLE line 1 string.
        tle_line2:    TLE line 2 string.
        epoch_jd:     Julian date corresponding to simulation time t = 0.
                      Defaults to J2000.0 (2000-01-01 12:00 UTC).
        equipment_id: Equipment ID used for wiring (default "orbital").
    """

    def __init__(
        self,
        tle_line1: str,
        tle_line2: str,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
        epoch_jd: float = 2451545.0,
        equipment_id: str = "orbital",
    ) -> None:
        self._tle1      = tle_line1
        self._tle2      = tle_line2
        self._epoch_jd  = epoch_jd
        self._satrec: Optional[object] = None

        super().__init__(
            equipment_id=equipment_id,
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

    # ── Equipment interface ───────────────────────────────────────────────────

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("orbital.position_eci_x",  PortDirection.OUT, unit="km"),
            PortDefinition("orbital.position_eci_y",  PortDirection.OUT, unit="km"),
            PortDefinition("orbital.position_eci_z",  PortDirection.OUT, unit="km"),
            PortDefinition("orbital.velocity_eci_x",  PortDirection.OUT, unit="km/s"),
            PortDefinition("orbital.velocity_eci_y",  PortDirection.OUT, unit="km/s"),
            PortDefinition("orbital.velocity_eci_z",  PortDirection.OUT, unit="km/s"),
            PortDefinition("orbital.altitude",         PortDirection.OUT, unit="km"),
            PortDefinition("orbital.latitude",         PortDirection.OUT, unit="deg"),
            PortDefinition("orbital.longitude",        PortDirection.OUT, unit="deg"),
            PortDefinition("orbital.eclipse",          PortDirection.OUT),
            PortDefinition("orbital.illumination",     PortDirection.OUT),
            PortDefinition("orbital.solar_irradiance", PortDirection.OUT, unit="W/m2"),
            PortDefinition("orbital.sun_eci_x",        PortDirection.OUT),
            PortDefinition("orbital.sun_eci_y",        PortDirection.OUT),
            PortDefinition("orbital.sun_eci_z",        PortDirection.OUT),
            PortDefinition("orbital.mag_field_n",      PortDirection.OUT, unit="T"),
            PortDefinition("orbital.mag_field_e",      PortDirection.OUT, unit="T"),
            PortDefinition("orbital.mag_field_d",      PortDirection.OUT, unit="T"),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        if not _HAS_SGP4:
            raise ImportError(
                "sgp4 is required for OrbitalEnvironment. "
                "Install with: pip install 'opensvf[orbital]'"
            )
        self._satrec = _Satrec.twoline2rv(self._tle1, self._tle2)  # type: ignore[union-attr]
        logger.info("[orbital] SGP4 satellite loaded from TLE")

    def teardown(self) -> None:
        self._satrec = None

    def do_step(self, t: float, dt: float) -> None:
        jd = self._epoch_jd + t / 86400.0
        jd_whole = math.floor(jd)
        jd_frac  = jd - jd_whole

        # Propagate
        assert self._satrec is not None
        e, r_teme, v_teme = self._satrec.sgp4(  # type: ignore[union-attr]
            float(jd_whole), float(jd_frac)
        )
        if e != 0:
            logger.warning(f"[orbital] SGP4 error code {e} at t={t:.1f}s")
            return

        r_eci: tuple[float, float, float] = (r_teme[0], r_teme[1], r_teme[2])
        v_eci: tuple[float, float, float] = (v_teme[0], v_teme[1], v_teme[2])

        # Sun direction
        sun_unit = _sun_unit_eci(jd)

        # Eclipse
        eclipse    = 1.0 if _in_eclipse(r_eci, sun_unit) else 0.0
        illumination = 1.0 - eclipse

        # Solar irradiance (1 AU nominal; could scale by r_sun_km / AU later)
        irradiance = _SOLAR_CONST * illumination

        # ECEF position for geodetic coordinates and dipole field
        r_ecef = _eci_to_ecef(r_eci, jd)
        lat_deg, lon_deg, alt_km = _ecef_to_geodetic(r_ecef)
        r_km = _norm3(r_ecef)

        # Tilted-dipole magnetic field in NED
        mag_n, mag_e, mag_d = _dipole_field_ned(lat_deg, lon_deg, r_km)

        # Publish
        self.write_port("orbital.position_eci_x",  r_eci[0])
        self.write_port("orbital.position_eci_y",  r_eci[1])
        self.write_port("orbital.position_eci_z",  r_eci[2])
        self.write_port("orbital.velocity_eci_x",  v_eci[0])
        self.write_port("orbital.velocity_eci_y",  v_eci[1])
        self.write_port("orbital.velocity_eci_z",  v_eci[2])
        self.write_port("orbital.altitude",         alt_km)
        self.write_port("orbital.latitude",         lat_deg)
        self.write_port("orbital.longitude",        lon_deg)
        self.write_port("orbital.eclipse",          eclipse)
        self.write_port("orbital.illumination",     illumination)
        self.write_port("orbital.solar_irradiance", irradiance)
        self.write_port("orbital.sun_eci_x",        sun_unit[0])
        self.write_port("orbital.sun_eci_y",        sun_unit[1])
        self.write_port("orbital.sun_eci_z",        sun_unit[2])
        self.write_port("orbital.mag_field_n",      mag_n)
        self.write_port("orbital.mag_field_e",      mag_e)
        self.write_port("orbital.mag_field_d",      mag_d)

        logger.debug(
            f"[orbital] t={t:.1f}s  alt={alt_km:.1f}km  "
            f"lat={lat_deg:.1f}°  lon={lon_deg:.1f}°  "
            f"eclipse={int(eclipse)}  "
            f"|B|={math.sqrt(mag_n**2+mag_e**2+mag_d**2)*1e9:.1f}nT"
        )


def make_orbital_environment(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "orbital",
    tle_line1: str = "",
    tle_line2: str = "",
    epoch_jd: float = 2451545.0,
    **_kwargs: object,
) -> OrbitalEnvironment:
    """Factory function registered in the spacecraft loader under 'orbital_environment'."""
    if not tle_line1 or not tle_line2:
        raise ValueError(
            "OrbitalEnvironment requires 'tle_line1' and 'tle_line2' "
            "in the equipment configuration."
        )
    return OrbitalEnvironment(
        tle_line1=tle_line1,
        tle_line2=tle_line2,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
        epoch_jd=epoch_jd,
        equipment_id=equipment_id,
    )
