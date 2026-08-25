# Architect Video Studio Quick Start

1. Run `ArchitectVideoStudio-Setup.exe` and choose an install directory.
2. Review the MiniMax H3 license notice in Environment Center.
3. Click **Install / Repair Everything**. The pinned ComfyUI runtime, H3 support layers, sidecar files and model weights are downloaded only after confirmation. Existing shared model roots may be selected to avoid duplication.
4. When Environment Center reports **READY**, click **Continue to Studio**.
5. Create a project, upload a reference image, click **Approve**, select one of the five workflow cards, review the prompt, and click **Generate**.

The application uses the embedded Runtime Python; no system Python, Git, ComfyUI or custom-node installation is required. Downloads resume after interruption and are SHA-256 checked before promotion.

The application package does not contain model weights. H3 weights remain subject to the upstream MiniMax H3 Community License and the user's territory/licensing obligations.
