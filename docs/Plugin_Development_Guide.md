# Plugin Development Guide for MiniMax H3 V0.5

## Overview

The MiniMax H3 Architecture System supports third-party plugin extensions under `plugins/`.

---

## Plugin Structure

```
plugins/
└── your_custom_plugin/
    ├── plugin.json
    ├── workflows/
    ├── prompts/
    └── skills/
```

## Manifest (`plugin.json`) Example

```json
{
  "plugin_id": "custom_facade_plugin",
  "name": "Custom Facade Animation Plugin",
  "version": "1.0.0",
  "author": "Architecture Studio",
  "workflows": ["custom_facade.json"]
}
```
