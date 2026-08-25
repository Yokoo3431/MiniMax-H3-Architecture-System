# Hardware Requirements

## Support tiers

- **Supported baseline:** Windows 10/11 64-bit, NVIDIA CUDA GPU with 24GB or more VRAM, 64GB system RAM, SSD with at least 100GB free before model download.
- **Experimental:** NVIDIA GPUs below 24GB VRAM. The product may install and inspect the environment, but generation is not guaranteed.
- **Unsupported:** non-NVIDIA systems for the current local H3 production path, or systems without enough disk/commit capacity for the selected model set.

The current 12GB-class development path is not a supported generation baseline. The installer reports it as **EXPERIMENTAL**, not promise success, and does not silently apply developer-only memory patches.

The exact H3 model set is approximately 40GB on disk before temporary download space. Keep additional free space for extraction and output video files. Environment Center reports the actual manifest-derived requirement before downloading.
