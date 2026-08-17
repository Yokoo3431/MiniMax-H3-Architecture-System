# Architect Video Studio

**建筑师 AI 视频生成工作站** —— 用参考图 + 自然语言，在本地 Native 运行时上生成
建筑展示视频。

> **路径约定**：本仓库不包含机器绝对路径。需要引用本地位置时使用占位符
> `<PROJECT_ROOT>`（仓库根）、`<USER_HOME>`（用户目录）、`<SAMPLE_PROJECT>`
> （示例项目）；内部开发记录在 `docs/internal_archive/`，不随公开发布。

> 这不是 ComfyUI 的包装器，也不是项目管理工具。它是面向建筑师的
> **视频生成工作流控制层**：Reference → Intent → Official Skill Prompt →
> Native Workflow → 视频输出。

---

## Features

- **Reference guided video**：上传效果图 → 质量卡 → 人工批准 → 生成
- **Native H3 runtime**：ComfyUI Native v0.33.1 + MiniMax H3（PREAD safe-load，
  Windows mmap 缓解）
- **Official Skill prompt**：MiniMax H3 官方 `h3-prompt-writing` 是唯一
  prompt 权威（版本 pin，自动 provenance）
- **Five architecture workflows**：

| 用户名称 | 模式 | 说明 |
| --- | --- | --- |
| Architecture Presentation | I2VA | 建筑外观展示 |
| Day Night | FL2VA | 日景 → 夜景过渡 |
| Material Detail | I2VA | 材质保真特写 |
| Drone Reveal | I2VA | 鸟瞰/总图揭示 |
| Slow Walkthrough | I2VA | 慢速空间漫游 |

## Quick Start（5 步）

1. **下载**：获取 `ArchitectVideoStudio` 压缩包并解压（SSD，~100GB 可用空间）。
2. **检查模型**：按 `models/manifest.json` 放置四个模型
   （DiT / Text Encoder / Video VAE / Audio VAE）；Launcher 自动校验 SHA-256。
3. **启动 Launcher**：双击 `launcher\start_architect_video_studio.bat`
   （自动环境检查 → 启动 ComfyUI 8189 → 启动 Studio 8788）。
4. **打开 Studio**：浏览器自动打开 `http://127.0.0.1:8788`。
5. **生成视频**：新建 Study → 上传参考图 → 批准 → 输入意图 → 确认 → Generate
   → 任务中心查看输出。

首次生成教程见 [docs/User_Guide.md](docs/User_Guide.md)（Exterior Hero 示例）。

## Hardware

| | 最低 | 推荐 |
| --- | --- | --- |
| GPU | NVIDIA CUDA 12GB VRAM | RTX 5070 12.8GB（已验证基线） |
| 内存 | 32GB RAM | 64GB RAM |
| 磁盘 | 100GB 可用 | 200GB+ SSD |
| 系统 | Windows 10/11 64-bit | Windows 11 |
| 页面文件（Free Commit） | ≥ 50GB | ≥ 80GB |

## Architecture

生产链与分层说明见
[docs/Developer_Architecture.md](docs/Developer_Architecture.md)：

```
Reference → Intent → Skill Prompt → Workflow Mapping → Native Runtime
→ Output Package
```

冻结边界：H3 Runtime / 01-05 Workflow JSON / Prompt Pipeline /
RuntimeAdapter / WorkflowMapping / NativeRuntimeAdapter 不可修改。

## Repository Layout

```
launcher/   production launcher（env check / process / lock / logs）
apps/       architect_video_studio（UI + mock API + state machine）
runtime/    contracts / adapters / prompt bridge（冻结）
workflows/  01-05 native workflow JSON（只读）
configs/    baseline / schema / profiles / catalog
references/ frozen official skill reference
samples/    example reference images
docs/       user guide / developer architecture / phase reports
tests/      regression suite（288）
```

`core/ hardware/ installer/ interface/ plugins/ prompts/ release/ skills/
sync/ updater/` 为早期开发遗留目录（[LEGACY]，保留历史证据，不属于生产链）。

## License

- **项目 License**：Apache License 2.0（见 [LICENSE](LICENSE)）
- **第三方许可**：见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- **模型许可分离**：模型权重（DiT / TE / Video VAE / Audio VAE）不随仓库分发；
  需单独获取并遵守上游（MiniMax / Qwen）各自的授权条款
