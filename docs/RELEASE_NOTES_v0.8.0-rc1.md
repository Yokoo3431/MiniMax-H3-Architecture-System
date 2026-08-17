# Release Notes — v0.8.0-rc1

**Status:** Release Candidate（非最终稳定版）

---

## Features

- **Architect Video Studio UI**：建筑师视频生成工作站（Reference → Intent →
  Skill Prompt → Workflow → 输出），非 ComfyUI wrapper
- **Native Runtime integration**：ComfyUI Native v0.33.1 + MiniMax H3，
  RuntimeAdapter 边界（Mock/Native 可替换）
- **Five architecture workflows**：01 Exterior Hero · 02 Day Night (FL2VA) ·
  03 Material Detail · 04 Drone Aerial · 05 Slow Walkthrough
- **Production Launcher**：双击启动 + 环境检查 + 进程/锁/日志
- **Distribution package**：分发布局 + 路径独立性 + 干净安装验证

## Requirements

- Windows 10/11 64-bit
- NVIDIA GPU（最低 CUDA 12GB VRAM；推荐 RTX 5070 12.8GB）
- CUDA 环境 + 满足 Free Commit ≥50GB（<30GB 硬停）
- 模型权重**另行提供**（按 `models/manifest.json` 放置，SHA-256 校验）

## Limitations

- Multi-reference（多参考）—— 未来
- Scene sequence（场景序列）—— 未来
- Multi-device（多设备）—— 未来
- 仅 Windows 验证；架构保留跨平台扩展点

## 发布说明

- 示例均为**合成资产**；内部开发记录不随发布
- 本项目为 RC，非最终稳定版；使用前请阅读 `README.md` 与 `THIRD_PARTY_NOTICES.md`
