#!/usr/bin/env python3
"""
Generate XTCE XML mission database from OpenSVF SRDB.

Usage:
    python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml

The generated XTCE contains:
  - PUS-C TM packet definitions for TM(3,25) HK and TM(17,2)
  - Parameter definitions from SRDB TM parameters
  - TC definitions for S17/1 and S20/1
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from svf.srdb.loader import SrdbLoader
from svf.srdb.definitions import Classification


def load_srdb():
    loader = SrdbLoader()
    for baseline in sorted(Path("srdb/baseline").glob("*.yaml")):
        loader.load_baseline(baseline)
    return loader.build()


def generate_xtce(srdb) -> str:
    tm_params = [
        p for p in srdb.parameter_names
        if srdb.get(p) and srdb.get(p).classification == Classification.TM
    ]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<SpaceSystem name="opensvf"',
        '  xmlns="http://www.omg.org/spec/XTCE/20180204"',
        '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        '',
        '  <Header date="2026-01" version="1.0"',
        '    classification="opensvf SVF auto-generated from SRDB"/>',
        '',
        '  <TelemetryMetaData>',
        '    <ParameterTypeSet>',
        '      <FloatParameterType name="float32" sizeInBits="32">',
        '        <UnitSet/>',
        '      </FloatParameterType>',
        '      <IntegerParameterType name="uint16" sizeInBits="16" signed="false">',
        '        <UnitSet/>',
        '      </IntegerParameterType>',
        '    </ParameterTypeSet>',
        '',
        '    <ParameterSet>',
    ]

    # Add all TM parameters from SRDB
    for name in sorted(tm_params):
        param = srdb.get(name)
        safe_name = name.replace(".", "_").replace("-", "_")
        unit = getattr(param, "unit", "") or ""
        desc = getattr(param, "description", name) or name
        lines.append(f'      <Parameter name="{safe_name}" parameterTypeRef="float32">')
        lines.append(f'        <LongDescription>{desc}</LongDescription>')
        lines.append(f'      </Parameter>')

    lines += [
        '    </ParameterSet>',
        '',
        '    <ContainerSet>',
        '      <!-- PUS-C TM(17,2) Are-You-Alive response -->',
        '      <SequenceContainer name="TM_17_2">',
        '        <LongDescription>Are-You-Alive response</LongDescription>',
        '        <EntryList/>',
        '      </SequenceContainer>',
        '',
        '      <!-- PUS-C TM(3,25) Housekeeping report -->',
        '      <SequenceContainer name="TM_3_25">',
        '        <LongDescription>Housekeeping parameter report</LongDescription>',
        '        <EntryList>',
    ]

    # Add HK parameters to container
    hk_params = [p for p in sorted(tm_params) if "dhs" in p or "eps" in p or "aocs" in p]
    for name in hk_params[:16]:  # YAMCS handles up to 16 in a simple HK packet
        safe_name = name.replace(".", "_").replace("-", "_")
        lines.append(f'          <ParameterRefEntry parameterRef="{safe_name}"/>')

    lines += [
        '        </EntryList>',
        '      </SequenceContainer>',
        '    </ContainerSet>',
        '  </TelemetryMetaData>',
        '',
        '  <CommandMetaData>',
        '    <ArgumentTypeSet>',
        '      <IntegerArgumentType name="uint16_arg" sizeInBits="16" signed="false">',
        '        <UnitSet/>',
        '      </IntegerArgumentType>',
        '      <FloatArgumentType name="float32_arg" sizeInBits="32">',
        '        <UnitSet/>',
        '      </FloatArgumentType>',
        '    </ArgumentTypeSet>',
        '    <MetaCommandSet>',
        '',
        '      <!-- TC(17,1) Are-You-Alive -->',
        '      <MetaCommand name="TC_17_1_AreYouAlive">',
        '        <LongDescription>Send S17 Are-You-Alive ping to OBC</LongDescription>',
        '        <ArgumentList/>',
        '        <CommandContainer name="TC_17_1_AreYouAlive_cc">',
        '          <EntryList/>',
        '        </CommandContainer>',
        '      </MetaCommand>',
        '',
        '      <!-- TC(20,1) Set Parameter -->',
        '      <MetaCommand name="TC_20_1_SetParameter">',
        '        <LongDescription>Set on-board parameter value (S20)</LongDescription>',
        '        <ArgumentList>',
        '          <Argument name="parameter_id" argumentTypeRef="uint16_arg"/>',
        '          <Argument name="value" argumentTypeRef="float32_arg"/>',
        '        </ArgumentList>',
        '        <CommandContainer name="TC_20_1_SetParameter_cc">',
        '          <EntryList>',
        '            <ArgumentRefEntry argumentRef="parameter_id"/>',
        '            <ArgumentRefEntry argumentRef="value"/>',
        '          </EntryList>',
        '        </CommandContainer>',
        '      </MetaCommand>',
        '',
        '    </MetaCommandSet>',
        '  </CommandMetaData>',
        '</SpaceSystem>',
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    srdb = load_srdb()
    print(generate_xtce(srdb))
