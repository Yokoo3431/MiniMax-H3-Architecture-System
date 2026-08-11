# Release Package Builder Guide

## Automated Packaging Command

To generate the standalone release archive (`MiniMax-H3-Architecture-System-v0.5.0.zip`):

```bash
python release/package_builder.py
```

The script automatically packages `launcher/`, `runtime/`, `configs/`, `hardware/`, `models/`, `prompts/`, `scripts/`, `skills/`, `workflows/`, `sync/`, `plugins/`, and `docs/`, while excluding 40GB model weights and generated MP4 outputs.
