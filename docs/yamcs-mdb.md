# YAMCS mission database

The XTCE mission database YAMCS loads, `yamcs/mdb/opensvf.xml`, is generated
from the SRDB by `tools/generate_xtce.py`. The documentation build checks
that the committed file is what the generator produces, then lists its
content below.

## TM packets

--8<-- "docs/_gen/yamcs-tm.md"

## TM parameters

--8<-- "docs/_gen/yamcs-parameters.md"

## Telecommands

--8<-- "docs/_gen/yamcs-commands.md"
