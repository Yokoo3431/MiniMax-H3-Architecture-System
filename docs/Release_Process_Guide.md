# Release Packaging & Distribution Guide (`v0.6.0`)

## Automated Packaging Command

To generate the standalone release archive (`MiniMax-H3-Architecture-System-v0.6.0.zip`):

```bash
python release/package_builder.py
```

The script automatically packages `launcher/`, `runtime/`, `configs/`, `hardware/`, `models/`, `prompts/`, `scripts/`, `skills/`, `workflows/`, `sync/`, `plugins/`, `tests/`, `.github/`, and `docs/`, while excluding 40GB model weights, `userdata/` files, and generated MP4 outputs.
