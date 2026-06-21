"""
SMP 2.0 catalogue generator tests (M50).

Groups:
  G1  -  XML structure and well-formedness (SVF-DEV-184)
  G2  -  Field count and direction mapping (SVF-DEV-184)
  G3  -  Package / Model grouping (SVF-DEV-184)
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from svf.srdb.definitions import Classification
from svf.srdb.loader import SrdbLoader

NS = "http://www.esa.int/2005/10/Smp"


def _load_srdb():
    loader = SrdbLoader()
    for baseline in sorted(Path("srdb/baseline").glob("*.yaml")):
        loader.load_baseline(baseline)
    return loader.build()


def _generate(srdb) -> ET.Element:
    """Return the parsed Catalogue root element."""
    import sys
    sys.path.insert(0, str(Path("tools").resolve()))
    from generate_smpcat import generate_smpcat  # type: ignore[import]
    return ET.fromstring(generate_smpcat(srdb))


@pytest.fixture(scope="module")
def srdb():
    return _load_srdb()


@pytest.fixture(scope="module")
def catalogue(srdb):
    return _generate(srdb)


# ── G1: XML structure ─────────────────────────────────────────────────────────

class SmpCatalogStructureSuite:

    @pytest.mark.requirement("SVF-DEV-184")
    def test_root_element_is_catalogue(self, catalogue: ET.Element) -> None:
        """Root element is Catalogue in the SMP 2.0 namespace."""
        assert catalogue.tag == f"{{{NS}}}Catalogue"

    @pytest.mark.requirement("SVF-DEV-184")
    def test_catalogue_has_title_attribute(self, catalogue: ET.Element) -> None:
        """Catalogue carries a Title attribute."""
        assert "Title" in catalogue.attrib

    @pytest.mark.requirement("SVF-DEV-184")
    def test_catalogue_has_version_attribute(self, catalogue: ET.Element) -> None:
        """Catalogue carries a Version attribute."""
        assert "Version" in catalogue.attrib

    @pytest.mark.requirement("SVF-DEV-184")
    def test_top_level_package_is_opensvf(self, catalogue: ET.Element) -> None:
        """Outermost Package is named 'opensvf'."""
        pkg = catalogue.find(f"{{{NS}}}Package")
        assert pkg is not None
        assert pkg.attrib["Name"] == "opensvf"

    @pytest.mark.requirement("SVF-DEV-184")
    def test_all_fields_have_type_float64(self, catalogue: ET.Element) -> None:
        """Every Field carries Type='Float64'."""
        fields = list(catalogue.iter(f"{{{NS}}}Field"))
        assert fields, "no fields found"
        assert all(f.attrib.get("Type") == "Float64" for f in fields)

    @pytest.mark.requirement("SVF-DEV-184")
    def test_all_fields_have_kind_attribute(self, catalogue: ET.Element) -> None:
        """Every Field carries a Kind attribute."""
        fields = list(catalogue.iter(f"{{{NS}}}Field"))
        assert all("Kind" in f.attrib for f in fields)

    @pytest.mark.requirement("SVF-DEV-184")
    def test_kind_values_are_input_or_output(self, catalogue: ET.Element) -> None:
        """Kind is either 'Input' or 'Output' - no other values."""
        kinds = {f.attrib["Kind"] for f in catalogue.iter(f"{{{NS}}}Field")}
        assert kinds <= {"Input", "Output"}


# ── G2: Field count and direction mapping ─────────────────────────────────────

class SmpCatalogFieldsSuite:

    @pytest.mark.requirement("SVF-DEV-184")
    def test_field_count_matches_srdb(
        self, catalogue: ET.Element, srdb
    ) -> None:
        """One Field element per SRDB parameter - none missing, none extra."""
        fields = list(catalogue.iter(f"{{{NS}}}Field"))
        assert len(fields) == len(srdb.parameter_names)

    @pytest.mark.requirement("SVF-DEV-184")
    def test_tm_parameters_map_to_output(
        self, catalogue: ET.Element, srdb
    ) -> None:
        """Every TM parameter appears as Kind='Output'."""
        output_names = {
            f.attrib["Name"]
            for f in catalogue.iter(f"{{{NS}}}Field")
            if f.attrib["Kind"] == "Output"
        }
        for param in srdb.by_classification(Classification.TM):
            field_name = ".".join(param.name.split(".")[2:]) or param.name.split(".")[-1]
            assert field_name in output_names, (
                f"TM param '{param.name}' not found as Output field"
            )

    @pytest.mark.requirement("SVF-DEV-184")
    def test_tc_parameters_map_to_input(
        self, catalogue: ET.Element, srdb
    ) -> None:
        """Every TC parameter appears as Kind='Input'."""
        input_names = {
            f.attrib["Name"]
            for f in catalogue.iter(f"{{{NS}}}Field")
            if f.attrib["Kind"] == "Input"
        }
        for param in srdb.by_classification(Classification.TC):
            field_name = ".".join(param.name.split(".")[2:]) or param.name.split(".")[-1]
            assert field_name in input_names, (
                f"TC param '{param.name}' not found as Input field"
            )

    @pytest.mark.requirement("SVF-DEV-184")
    def test_fields_with_units_carry_unit_attribute(
        self, catalogue: ET.Element, srdb
    ) -> None:
        """Fields whose SRDB entry has a unit expose a Unit attribute."""
        params_with_unit = {
            ".".join(p.name.split(".")[2:]) or p.name.split(".")[-1]
            for p in [srdb.get(n) for n in srdb.parameter_names]
            if p and p.unit
        }
        for field in catalogue.iter(f"{{{NS}}}Field"):
            if field.attrib["Name"] in params_with_unit:
                assert "Unit" in field.attrib, (
                    f"Field '{field.attrib['Name']}' missing Unit attribute"
                )


# ── G3: Package / Model grouping ─────────────────────────────────────────────

class SmpCatalogGroupingSuite:

    @pytest.mark.requirement("SVF-DEV-184")
    def test_domain_packages_present(self, catalogue: ET.Element) -> None:
        """A sub-Package exists for each SRDB domain."""
        top = catalogue.find(f"{{{NS}}}Package")
        assert top is not None
        pkg_names = {p.attrib["Name"] for p in top.findall(f"{{{NS}}}Package")}
        assert {"aocs", "eps", "thermal", "ttc"} <= pkg_names

    @pytest.mark.requirement("SVF-DEV-184")
    def test_models_nested_inside_domain_packages(
        self, catalogue: ET.Element
    ) -> None:
        """Model elements appear inside domain Packages, not at top level."""
        top = catalogue.find(f"{{{NS}}}Package")
        assert top is not None
        # top-level Package should have no direct Model children
        direct_models = top.findall(f"{{{NS}}}Model")
        assert direct_models == [], "Models found directly under opensvf Package"

    @pytest.mark.requirement("SVF-DEV-184")
    def test_each_model_contains_at_least_one_field(
        self, catalogue: ET.Element
    ) -> None:
        """No empty Model elements in the catalogue."""
        for model in catalogue.iter(f"{{{NS}}}Model"):
            fields = model.findall(f"{{{NS}}}Field")
            assert fields, f"Model '{model.attrib.get('Name')}' has no fields"

