#!/usr/bin/env python3
"""
Generate XTCE XML mission database from OpenSVF SRDB.

Usage:
    python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml

The generated XTCE contains:
  - PUS-C TM packet definitions with proper container inheritance
  - Restriction criteria so each container only matches its svc/subsvc
  - Parameter definitions from SRDB TM parameters
  - TC definitions for S17/1 and S20/1
"""

from svf.srdb.definitions import Classification
from svf.srdb.loader import SrdbLoader
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


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
        '      <IntegerParameterType name="uint8" sizeInBits="8" signed="false">',
        '        <IntegerDataEncoding sizeInBits="8" encoding="unsigned"/>',
        '        <UnitSet/>',
        '      </IntegerParameterType>',
        '      <IntegerParameterType name="uint16" sizeInBits="16" signed="false">',
        '        <IntegerDataEncoding sizeInBits="16" encoding="unsigned"/>',
        '        <UnitSet/>',
        '      </IntegerParameterType>',
        '    </ParameterTypeSet>',
        '',
        '    <ParameterSet>',
        '      <!-- PUS-C primary + secondary header fields -->',
        '      <Parameter name="pus_svc"    parameterTypeRef="uint8"/>',
        '      <Parameter name="pus_subsvc" parameterTypeRef="uint8"/>',
    ]

    # Add all TM parameters from SRDB
    for name in sorted(tm_params):
        param = srdb.get(name)
        safe_name = name.replace(".", "_").replace("-", "_")
        desc = getattr(param, "description", name) or name
        lines.append(
            f'      <Parameter name="{safe_name}" parameterTypeRef="float32">')
        lines.append(f'        <LongDescription>{desc}</LongDescription>')
        lines.append(f'      </Parameter>')

    lines += [
        '    </ParameterSet>',
        '',
        '    <ContainerSet>',
        '',
        '      <!-- Root PUS-C TM packet — matched by all PUS packets -->',
        '      <!-- PUS-C TM secondary header layout:                  -->',
        '      <!--   byte 6: PUS version + spare (0x20)               -->',
        '      <!--   byte 7: service                                   -->',
        '      <!--   byte 8: subservice                                -->',
        '      <SequenceContainer name="PUS_Packet" abstract="true">',
        '        <EntryList>',
        '          <ParameterRefEntry parameterRef="pus_svc">',
        '            <LocationInContainerInBits referenceLocation="containerStart">',
        '              <FixedValue>56</FixedValue>',
        '            </LocationInContainerInBits>',
        '          </ParameterRefEntry>',
        '          <ParameterRefEntry parameterRef="pus_subsvc">',
        '            <LocationInContainerInBits referenceLocation="containerStart">',
        '              <FixedValue>64</FixedValue>',
        '            </LocationInContainerInBits>',
        '          </ParameterRefEntry>',
        '        </EntryList>',
        '      </SequenceContainer>',
        '',
        '      <!-- TM(1,1) TC Acceptance Success -->',
        '      <SequenceContainer name="TM_1_1_Accept">',
        '        <LongDescription>TC Acceptance Success</LongDescription>',
        '        <BaseContainer containerRef="PUS_Packet">',
        '          <RestrictionCriteria>',
        '            <ComparisonList>',
        '              <Comparison parameterRef="pus_svc"    value="1" comparisonOperator="=="/>',
        '              <Comparison parameterRef="pus_subsvc" value="1" comparisonOperator="=="/>',
        '            </ComparisonList>',
        '          </RestrictionCriteria>',
        '        </BaseContainer>',
        '        <EntryList/>',
        '      </SequenceContainer>',
        '',
        '      <!-- TM(1,7) TC Completion Success -->',
        '      <SequenceContainer name="TM_1_7_Complete">',
        '        <LongDescription>TC Completion Success</LongDescription>',
        '        <BaseContainer containerRef="PUS_Packet">',
        '          <RestrictionCriteria>',
        '            <ComparisonList>',
        '              <Comparison parameterRef="pus_svc"    value="1" comparisonOperator="=="/>',
        '              <Comparison parameterRef="pus_subsvc" value="7" comparisonOperator="=="/>',
        '            </ComparisonList>',
        '          </RestrictionCriteria>',
        '        </BaseContainer>',
        '        <EntryList/>',
        '      </SequenceContainer>',
        '',
        '      <!-- TM(3,25) Housekeeping report -->',
        '      <SequenceContainer name="TM_3_25_HK">',
        '        <LongDescription>Housekeeping parameter report</LongDescription>',
        '        <BaseContainer containerRef="PUS_Packet">',
        '          <RestrictionCriteria>',
        '            <ComparisonList>',
        '              <Comparison parameterRef="pus_svc"    value="3"  comparisonOperator="=="/>',
        '              <Comparison parameterRef="pus_subsvc" value="25" comparisonOperator="=="/>',
        '            </ComparisonList>',
        '          </RestrictionCriteria>',
        '        </BaseContainer>',
        '        <EntryList/>',
        '      </SequenceContainer>',
        '',
        '      <!-- TM(5,1) Event report — informative -->',
        '      <SequenceContainer name="TM_5_1_Event">',
        '        <LongDescription>Event report (informative)</LongDescription>',
        '        <BaseContainer containerRef="PUS_Packet">',
        '          <RestrictionCriteria>',
        '            <ComparisonList>',
        '              <Comparison parameterRef="pus_svc"    value="5" comparisonOperator="=="/>',
        '              <Comparison parameterRef="pus_subsvc" value="1" comparisonOperator="=="/>',
        '            </ComparisonList>',
        '          </RestrictionCriteria>',
        '        </BaseContainer>',
        '        <EntryList/>',
        '      </SequenceContainer>',
        '',
        '      <!-- TM(17,2) Are-You-Alive response -->',
        '      <SequenceContainer name="TM_17_2_Pong">',
        '        <LongDescription>Are-You-Alive response</LongDescription>',
        '        <BaseContainer containerRef="PUS_Packet">',
        '          <RestrictionCriteria>',
        '            <ComparisonList>',
        '              <Comparison parameterRef="pus_svc"    value="17" comparisonOperator="=="/>',
        '              <Comparison parameterRef="pus_subsvc" value="2"  comparisonOperator="=="/>',
        '            </ComparisonList>',
        '          </RestrictionCriteria>',
        '        </BaseContainer>',
        '        <EntryList/>',
        '      </SequenceContainer>',
        '',
        '      <!-- TM(20,2) Parameter value report -->',
        '      <SequenceContainer name="TM_20_2_ParamReport">',
        '        <LongDescription>Parameter value report</LongDescription>',
        '        <BaseContainer containerRef="PUS_Packet">',
        '          <RestrictionCriteria>',
        '            <ComparisonList>',
        '              <Comparison parameterRef="pus_svc"    value="20" comparisonOperator="=="/>',
        '              <Comparison parameterRef="pus_subsvc" value="2"  comparisonOperator="=="/>',
        '            </ComparisonList>',
        '          </RestrictionCriteria>',
        '        </BaseContainer>',
        '        <EntryList/>',
        '      </SequenceContainer>',
        '',
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
        '      <!-- TC(17,1) Are-You-Alive ping -->',
        '      <!-- Binary: 6 primary + 5 secondary = 11 bytes         -->',
        '      <!-- Primary:   1810 C000 0004                          -->',
        '      <!-- Secondary: 11 11 01 00 00                          -->',
        '      <MetaCommand name="TC_17_1_AreYouAlive">',
        '        <LongDescription>Send S17 Are-You-Alive ping to OBC</LongDescription>',
        '        <ArgumentList/>',
        '        <CommandContainer name="TC_17_1_AreYouAlive_cc">',
        '          <EntryList>',
        '            <FixedValueEntry binaryValue="1810C00000041111010000" sizeInBits="88"/>',
        '          </EntryList>',
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
