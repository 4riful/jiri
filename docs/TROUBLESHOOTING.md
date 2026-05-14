# Troubleshooting

## Import Errors In WSL

Set `PYTHONPATH=src` or run `scripts/test_wsl.sh`.

## Missing Config

JIRI uses safe defaults if `config.toml` is absent. Copy `config.example.toml` to `config.toml` only when customization is needed.

## Database Missing

The CLI creates the database schema automatically for normal operations. You can also run:

```bash
python -m jiri.cli init-db
```

## Display Does Not Work In WSL

Use mock display settings. Real display behavior must be confirmed on the Raspberry Pi.
