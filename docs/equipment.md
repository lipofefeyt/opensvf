# Equipment reference

Every model the spacecraft loader knows (`model:` in a spacecraft YAML), the
ports it declares and its fidelity level. Generated at every documentation
build: the ports come from building each model with its defaults, the
fidelity levels from the table `checkcov` checks against the SRDB.
"Not declared" means the model has no entry in that table yet.

How models are written and wired is described in the
[equipment library](equipment-library.md).

## Models

--8<-- "docs/_gen/equipment-summary.md"

## Fidelity

F1 functional, F2 behavioural, F3 high fidelity, F4 validated against
hardware data. A model with calibration curves in the SRDB must be F3 or
higher; `checkcov` and this build fail otherwise.

--8<-- "docs/_gen/fidelity.md"

## Ports

Port names are shown for the default equipment ID; a named instance
replaces the ID in the name (`aocs.rw1.speed` becomes `aocs.rw_pitch.speed`).

--8<-- "docs/_gen/equipment-ports.md"
