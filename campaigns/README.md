# SVF Campaigns

This directory contains two types of campaign files:

## New format (M20) — use with `svf campaign`

Files: `spacecraft.yaml`, `example_campaign.yaml`

```bash
svf campaign campaigns/example_campaign.yaml --report
```

Procedures are Python files with `Procedure` subclasses.
See `campaigns/procedures/` for examples.

## Old format (pre-M20) — use with `pytest`

Files: `platform_validation.yaml`, `eps_validation.yaml`,
       `nominal_ops.yaml`, `safe_mode_recovery.yaml`,
       `fdir_chain.yaml`, `contact_pass.yaml`,
       `mil1553_validation.yaml`, `pus_validation.yaml`,
       `realtime_detumbling.yaml`

These reference pytest test functions directly and run via:

```bash
pytest tests/spacecraft/ -v
```

They cannot be loaded by `svf campaign` — that command expects
the new format with `campaign:` and `procedures:` fields.
