"""
Unit tests for M42 OrbitalEnvironment.
All math helpers tested without sgp4 installed.
SGP4-dependent tests mock the Satrec object.
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

from svf.models.environment.orbital_environment import (
    OrbitalEnvironment,
    _dipole_field_ned,
    _eci_to_ecef,
    _ecef_to_geodetic,
    _gmst,
    _in_eclipse,
    _sun_unit_eci,
    _norm3,
    _R_EARTH_KM,
    _SOLAR_CONST,
)
from svf.stores.parameter_store import ParameterStore
from svf.core.abstractions import SyncProtocol


class _NoopSync(SyncProtocol):
    def reset(self) -> None:
        pass

    def publish_ready(self, model_id: str, t: float) -> None:
        pass

    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


def _make_env() -> tuple[OrbitalEnvironment, ParameterStore]:
    store = ParameterStore()
    env = OrbitalEnvironment(
        tle_line1="1 25544U 98067A   21001.00000000  .00001234  00000-0  29032-4 0  9999",
        tle_line2="2 25544  51.6432 228.3417 0001397 349.5283 135.8144 15.49309475265695",
        sync_protocol=_NoopSync(),
        store=store,
        epoch_jd=2451545.0,
    )
    return env, store


# ---------------------------------------------------------------------------
# GMST
# ---------------------------------------------------------------------------

def test_gmst_at_j2000() -> None:
    """GMST at J2000.0 epoch is ~280.46° (about 4.895 rad)."""
    gmst_rad = _gmst(2451545.0)
    assert 4.8 < gmst_rad < 5.0


def test_gmst_one_sidereal_day() -> None:
    """GMST returns to approximately the same value after one sidereal day."""
    jd0 = 2451545.0
    jd1 = jd0 + 0.9972  # one sidereal day ≈ 86164 s
    # Both outputs are in [0, 2π); the advance is ~360° so the residual is
    # near zero (within a fraction of a degree of rounding in the formula).
    assert abs(_gmst(jd1) - _gmst(jd0)) < 0.01


# ---------------------------------------------------------------------------
# ECI → ECEF
# ---------------------------------------------------------------------------

def test_eci_to_ecef_zero_gmst() -> None:
    """At a JD where GMST ≈ 0, ECI x-axis aligns with ECEF x-axis."""
    jd = 2451545.0 + (360.0 - 280.46061837) / 360.98564736629
    r_eci = (7000.0, 0.0, 0.0)
    r_ecef = _eci_to_ecef(r_eci, jd)
    assert abs(r_ecef[0] - 7000.0) < 10.0


def test_eci_to_ecef_rotation_preserves_magnitude() -> None:
    """ECI → ECEF rotation is rigid; vector magnitude is preserved."""
    r_eci = (5000.0, 3000.0, 2000.0)
    r_ecef = _eci_to_ecef(r_eci, 2451545.0)
    assert abs(_norm3(r_ecef) - _norm3(r_eci)) < 1e-6


# ---------------------------------------------------------------------------
# Geodetic conversion
# ---------------------------------------------------------------------------

def test_ecef_to_geodetic_equatorial_x_axis() -> None:
    """Point on equator along x-axis: lat=0, lon=0, alt=r-R_E."""
    r = _R_EARTH_KM + 400.0
    lat, lon, alt = _ecef_to_geodetic((r, 0.0, 0.0))
    assert abs(lat) < 0.01
    assert abs(lon) < 0.01
    assert abs(alt - 400.0) < 0.1


def test_ecef_to_geodetic_north_pole() -> None:
    """Point above north pole: lat≈90, alt correct."""
    r = _R_EARTH_KM + 500.0
    lat, _lon, alt = _ecef_to_geodetic((0.0, 0.0, r))
    assert abs(lat - 90.0) < 0.01
    assert abs(alt - 500.0) < 0.1


# ---------------------------------------------------------------------------
# Sun ephemeris
# ---------------------------------------------------------------------------

def test_sun_unit_is_unit_vector() -> None:
    """Sun direction is a unit vector."""
    s = _sun_unit_eci(2451545.0)
    assert abs(_norm3(s) - 1.0) < 1e-10


def test_sun_unit_changes_with_time() -> None:
    """Sun direction is approximately opposite after 6 months."""
    s0 = _sun_unit_eci(2451545.0)
    s1 = _sun_unit_eci(2451545.0 + 182.0)
    dot = sum(a * b for a, b in zip(s0, s1))
    assert dot < -0.9


# ---------------------------------------------------------------------------
# Eclipse
# ---------------------------------------------------------------------------

def test_eclipse_behind_earth() -> None:
    """Spacecraft directly behind Earth (anti-sun side) is in eclipse."""
    sun = (1.0, 0.0, 0.0)
    r   = (-8000.0, 0.0, 0.0)
    assert _in_eclipse(r, sun) is True


def test_eclipse_sunlit_side() -> None:
    """Spacecraft on sunlit side is not in eclipse."""
    sun = (1.0, 0.0, 0.0)
    r   = (8000.0, 0.0, 0.0)
    assert _in_eclipse(r, sun) is False


def test_eclipse_outside_shadow_cylinder() -> None:
    """Spacecraft behind Earth but far off the shadow axis is not in eclipse."""
    sun = (1.0, 0.0, 0.0)
    r   = (-8000.0, 10000.0, 0.0)
    assert _in_eclipse(r, sun) is False


# ---------------------------------------------------------------------------
# Dipole magnetic field
# ---------------------------------------------------------------------------

@pytest.mark.requirement("SVF-DEV-172")
def test_dipole_field_magnitude_leo() -> None:
    """Tilted-dipole field magnitude at 500 km altitude is 20–70 µT."""
    r_km = _R_EARTH_KM + 500.0
    for lat in (-60.0, 0.0, 45.0, 80.0):
        b_n, b_e, b_d = _dipole_field_ned(lat, 0.0, r_km)
        b_total = math.sqrt(b_n**2 + b_e**2 + b_d**2)
        assert 20e-6 < b_total < 70e-6, (
            f"lat={lat}: |B|={b_total*1e9:.1f} nT out of range"
        )


def test_dipole_field_pole_stronger_than_equator() -> None:
    """Field at high latitude is stronger than at equator (dipole law)."""
    r_km = _R_EARTH_KM + 500.0
    b_eq = _norm3(_dipole_field_ned(0.0,  0.0, r_km))
    b_np = _norm3(_dipole_field_ned(80.0, 0.0, r_km))
    assert b_np > 1.5 * b_eq


def test_dipole_field_decreases_with_altitude() -> None:
    """Field magnitude decreases as 1/r³ with altitude."""
    b_low  = _norm3(_dipole_field_ned(0.0, 0.0, _R_EARTH_KM + 400.0))
    b_high = _norm3(_dipole_field_ned(0.0, 0.0, _R_EARTH_KM + 1200.0))
    # (r_1200/r_400)^3 = (7571/6771)^3 ≈ 1.40
    assert b_low > b_high * 1.3


# ---------------------------------------------------------------------------
# OrbitalEnvironment integration (mock sgp4)
# ---------------------------------------------------------------------------

_ISS_V_TEME = (0.1, 7.6, 0.1)  # km/s


def _make_satrec_mock(eclipse: bool = False) -> MagicMock:
    """Return a mock Satrec that places the satellite in sun or eclipse."""
    sat = MagicMock()
    r = (-7000.0, 0.0, 0.0) if eclipse else (7000.0, 0.0, 0.0)
    sat.sgp4.return_value = (0, list(r), list(_ISS_V_TEME))
    return sat


@pytest.mark.requirement("SVF-DEV-170")
def test_orbital_tick_publishes_all_ports() -> None:
    """do_step() publishes all expected orbital ports to ParameterStore."""
    env, store = _make_env()
    with patch("svf.models.environment.orbital_environment._HAS_SGP4", True):
        with patch("svf.models.environment.orbital_environment._Satrec") as mock_cls:
            mock_cls.twoline2rv.return_value = _make_satrec_mock(eclipse=False)
            env.initialise()
            env.do_step(0.0, 1.0)

    expected_ports = [
        "orbital.position_eci_x", "orbital.position_eci_y", "orbital.position_eci_z",
        "orbital.velocity_eci_x", "orbital.velocity_eci_y", "orbital.velocity_eci_z",
        "orbital.altitude", "orbital.latitude", "orbital.longitude",
        "orbital.eclipse", "orbital.illumination", "orbital.solar_irradiance",
        "orbital.sun_eci_x", "orbital.sun_eci_y", "orbital.sun_eci_z",
        "orbital.mag_field_n", "orbital.mag_field_e", "orbital.mag_field_d",
    ]
    for port in expected_ports:
        assert store.read(port) is not None, f"Port {port} not published"


@pytest.mark.requirement("SVF-DEV-171")
def test_orbital_tick_eclipse_zero_irradiance() -> None:
    """When in eclipse, solar_irradiance = 0 and illumination = 0."""
    env, store = _make_env()
    with patch("svf.models.environment.orbital_environment._HAS_SGP4", True):
        with patch("svf.models.environment.orbital_environment._Satrec") as mock_cls:
            mock_cls.twoline2rv.return_value = _make_satrec_mock(eclipse=True)
            env.initialise()
            with patch(
                "svf.models.environment.orbital_environment._sun_unit_eci",
                return_value=(1.0, 0.0, 0.0),
            ):
                env.do_step(0.0, 1.0)

    assert store.read("orbital.eclipse").value == 1.0           # type: ignore[union-attr]
    assert store.read("orbital.illumination").value == 0.0      # type: ignore[union-attr]
    assert store.read("orbital.solar_irradiance").value == 0.0  # type: ignore[union-attr]


def test_orbital_tick_sunlit_full_irradiance() -> None:
    """When not in eclipse, solar_irradiance equals the solar constant."""
    env, store = _make_env()
    with patch("svf.models.environment.orbital_environment._HAS_SGP4", True):
        with patch("svf.models.environment.orbital_environment._Satrec") as mock_cls:
            mock_cls.twoline2rv.return_value = _make_satrec_mock(eclipse=False)
            env.initialise()
            with patch(
                "svf.models.environment.orbital_environment._sun_unit_eci",
                return_value=(0.0, 0.0, 1.0),
            ):
                env.do_step(0.0, 1.0)

    irr = store.read("orbital.solar_irradiance")
    assert irr is not None
    assert abs(irr.value - _SOLAR_CONST) < 1.0


def test_no_sgp4_raises_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """initialise() raises ImportError with install hint when sgp4 missing."""
    import svf.models.environment.orbital_environment as _mod
    monkeypatch.setattr(_mod, "_HAS_SGP4", False)
    env, _ = _make_env()
    with pytest.raises(ImportError, match="sgp4"):
        env.initialise()
