# Compatibility

Which openobsw release this version of opensvf is tested against, and the
wire protocol between them. The tables are generated from the source at
every documentation build: `pyproject.toml`, `.openobsw-version`, the
adapter's wire protocol constants and the CI workflow.

## This version

--8<-- "docs/_gen/compatibility-current.md"

The L3 system tests (`tests/system`) run in CI against `obsw_sim` built from
the pinned openobsw tag. The wire protocol itself is owned by openobsw and
described in its [ICD](https://openobsw.readthedocs.io/en/latest/icd/).

## Releases

--8<-- "docs/_gen/compatibility-history.md"

The rows come from `docs/compatibility.yaml`; the build fails when the row
for this version disagrees with the source.
