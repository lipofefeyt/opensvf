"""
SMP-aligned assembly configuration generator tests (M50).

Groups:
  G1  -  XML structure (SVF-DEV-185)
  G2  -  Instance entries (SVF-DEV-185)
  G3  -  checksmp command (SVF-DEV-185)
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from svf.smp.interfaces import SMP_ALIGNED_NS
from svf.srdb.loader import Srdb, SrdbLoader

NS      = SMP_ALIGNED_NS
SC_YAML = Path("mission_mysat1/spacecraft.yaml")


def _load_srdb() -> Srdb:
    loader = SrdbLoader()
    for baseline in sorted(Path("srdb/baseline").glob("*.yaml")):
        loader.load_baseline(baseline)
    return loader.build()


def _generate(srdb: Srdb) -> ET.Element:
    sys.path.insert(0, str(Path("tools").resolve()))
    from generate_smpconf import generate_smpconf  # type: ignore[import-not-found]
    return ET.fromstring(generate_smpconf(SC_YAML, srdb))


@pytest.fixture(scope="module")
def srdb() -> Srdb:
    return _load_srdb()


@pytest.fixture(scope="module")
def assembly(srdb: Srdb) -> ET.Element:
    return _generate(srdb)


# ── G1: XML structure ─────────────────────────────────────────────────────────

class SmpConfStructureSuite:

    @pytest.mark.requirement("SVF-DEV-185")
    def test_root_element_is_assembly(self, assembly: ET.Element) -> None:
        """Root element is Assembly in the opensvf SMP-aligned namespace."""
        assert assembly.tag == f"{{{NS}}}Assembly"

    @pytest.mark.requirement("SVF-DEV-185")
    def test_assembly_has_name_attribute(self, assembly: ET.Element) -> None:
        """Assembly carries a Name attribute derived from spacecraft.yaml."""
        assert "Name" in assembly.attrib
        assert assembly.attrib["Name"] != ""

    @pytest.mark.requirement("SVF-DEV-185")
    def test_assembly_contains_instances_element(
        self, assembly: ET.Element
    ) -> None:
        """Assembly contains an Instances container element."""
        assert assembly.find(f"{{{NS}}}Instances") is not None

    @pytest.mark.requirement("SVF-DEV-185")
    def test_assembly_contains_connections_element(
        self, assembly: ET.Element
    ) -> None:
        """Assembly contains a Connections container element."""
        assert assembly.find(f"{{{NS}}}Connections") is not None


# ── G2: Instance entries ──────────────────────────────────────────────────────

class SmpConfInstancesSuite:

    @pytest.mark.requirement("SVF-DEV-185")
    def test_instances_count_matches_equipment_list(
        self, assembly: ET.Element
    ) -> None:
        """One Instance per equipment entry in spacecraft.yaml."""
        config: dict[str, Any] = yaml.safe_load(SC_YAML.read_text())
        expected  = len(config.get("equipment", []))
        instances = assembly.findall(f".//{{{NS}}}Instance")
        assert len(instances) == expected

    @pytest.mark.requirement("SVF-DEV-185")
    def test_instance_has_name_attribute(self, assembly: ET.Element) -> None:
        """Every Instance carries a Name attribute."""
        instances = assembly.findall(f".//{{{NS}}}Instance")
        assert instances, "no instances found"
        assert all("Name" in i.attrib for i in instances)

    @pytest.mark.requirement("SVF-DEV-185")
    def test_instance_typename_contains_opensvf_prefix(
        self, assembly: ET.Element
    ) -> None:
        """Every Instance TypeName is prefixed 'opensvf.<domain>.<id>'."""
        for inst in assembly.findall(f".//{{{NS}}}Instance"):
            tn = inst.attrib.get("TypeName", "")
            assert tn.startswith("opensvf."), (
                f"Instance '{inst.attrib.get('Name')}' TypeName='{tn}' "
                f"does not start with 'opensvf.'"
            )

    @pytest.mark.requirement("SVF-DEV-185")
    def test_instance_name_matches_equipment_id(
        self, assembly: ET.Element
    ) -> None:
        """Instance Name matches the equipment id from spacecraft.yaml."""
        config: dict[str, Any] = yaml.safe_load(SC_YAML.read_text())
        expected_ids = {str(e["id"]) for e in config.get("equipment", [])}
        actual_ids   = {
            i.attrib["Name"]
            for i in assembly.findall(f".//{{{NS}}}Instance")
        }
        assert actual_ids == expected_ids

    @pytest.mark.requirement("SVF-DEV-185")
    def test_typename_domain_resolves_from_srdb(
        self, assembly: ET.Element, srdb: Srdb
    ) -> None:
        """TypeName domain segment matches the SRDB domain for the equipment.

        Checks both the exact id and the base name (trailing digits stripped),
        mirroring the generator's two-pass domain inference.
        """
        for inst in assembly.findall(f".//{{{NS}}}Instance"):
            eq_id          = inst.attrib["Name"]
            type_name      = inst.attrib.get("TypeName", "")
            parts          = type_name.split(".")  # ['opensvf', domain, eq_id]
            if len(parts) < 3:
                continue
            domain_in_type = parts[1]
            base_id        = re.sub(r"\d+$", "", eq_id)
            match = any(
                n.split(".")[0] == domain_in_type
                and len(n.split(".")) >= 2
                and n.split(".")[1] in (eq_id, base_id)
                for n in srdb.parameter_names
            )
            assert match, (
                f"TypeName '{type_name}' domain '{domain_in_type}' "
                f"not found in SRDB for equipment '{eq_id}' (tried base '{base_id}')"
            )


# ── G3: checksmp command ──────────────────────────────────────────────────────

class CheckSmpSuite:

    @pytest.mark.requirement("SVF-DEV-185")
    def test_checksmp_passes_with_current_smpcat(self) -> None:
        """checksmp exits 0 when smp/opensvf.smpcat is in sync with SRDB."""
        from svf.tools.checksmp import run_checks
        assert run_checks() == 0

    @pytest.mark.requirement("SVF-DEV-185")
    def test_checksmp_fails_when_smpcat_missing(self, tmp_path: Path) -> None:
        """checksmp exits non-zero when the smpcat file does not exist."""
        from svf.tools import checksmp
        from svf.tools.checksmp import run_checks
        with patch.object(checksmp, "_SMPCAT", tmp_path / "missing.smpcat"):
            assert run_checks() != 0

    @pytest.mark.requirement("SVF-DEV-185")
    def test_checksmp_fails_on_malformed_xml(self, tmp_path: Path) -> None:
        """checksmp exits non-zero when smpcat is not valid XML."""
        bad = tmp_path / "bad.smpcat"
        bad.write_text("<not valid xml")
        from svf.tools import checksmp
        from svf.tools.checksmp import run_checks
        with patch.object(checksmp, "_SMPCAT", bad):
            assert run_checks() != 0


# ── SMP claim boundary (M63) ─────────────────────────────────────────────────

class SmpConfClaimSuite:

    @pytest.mark.requirement("SVF-DEV-203")
    def test_assembly_does_not_use_esa_namespace(self, assembly: ET.Element) -> None:
        assert "http://www.esa.int/2005/10/Smp" not in assembly.tag

    @pytest.mark.requirement("SVF-DEV-203")
    def test_assembly_header_states_non_conformance(self, srdb: Srdb) -> None:
        sys.path.insert(0, str(Path("tools").resolve()))
        from generate_smpconf import generate_smpconf  # type: ignore[import-not-found]
        assert "Not SMDL-conformant" in generate_smpconf(SC_YAML, srdb)
