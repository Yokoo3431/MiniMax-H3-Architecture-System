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

## Quick Start（Windows）

1. **下载并运行**：运行 `ArchitectVideoStudio-Setup.exe`，选择安装目录。
   安装器自动取得嵌入式 Runtime；用户不需要安装 Python、Git 或 ComfyUI。
2. **完成首次配置**：Environment Center 会展示硬件、Runtime、模型、PREAD、Skill、磁盘需求与安装来源。
   审阅安装计划和上游许可提示后，点击 **Install / Repair Everything**；已有可验证的 Runtime / Models 也可以选择复用。
3. **System Ready**：所有检查项通过后点击 **Continue to Studio**，浏览器自动打开 Architect Video Studio `http://127.0.0.1:8788`。也可直接运行安装目录中的 `Start_ArchitectVideoStudio.bat`。
4. **生成视频**：新建 Study → 上传参考图 → 批准 → 选择五个工作流之一 → 输入意图 → 审阅 Prompt → Generate → 任务中心查看输出。

模型权重不会随 GitHub 仓库分发；首次安装会在用户明确确认后，按上游许可从清单中的官方来源下载并校验 SHA-256。

启动失败时窗口会保持可见并显示原因和日志路径，详细日志见 `Logs\launcher.log`。

### Advanced Users（高级/开发者）

**`Open_Native_ComfyUI.bat`**（仓库根目录）：直接进入 Native ComfyUI
（端口 8189，PREAD safe-load）。普通用户不需要使用，也不会自动打开 Studio。

**Manual Configuration（手动配置 fallback）**：高级用户可不使用页面配置，
直接在仓库根目录创建 `native_env.path`（第一行为 Native ComfyUI 根目录，
模板见 `native_env.path.example`）。首次配置已由 System Setup 页面自动完成时
无需手工编辑。

首次生成教程见 [docs/User_Guide.md](docs/User_Guide.md)（Exterior Hero 示例）。

## Hardware

| | 最低 | 推荐 |
| --- | --- | --- |
| GPU | NVIDIA CUDA 24GB VRAM（支持基线） | RTX 4090/5090-class 或更高 |
| 低显存 | 12–23GB：实验状态，不保证生成 | — |
| 内存 | 64GB RAM（开发证据基线） | 96GB+ RAM |
| 磁盘 | 模型下载前至少 100GB 可用 | 200GB+ SSD |
| 系统 | Windows 10/11 64-bit | Windows 11 |
| 页面文件（Free Commit） | 由 Environment Center 按机器状态检查 | 由 Environment Center 按机器状态检查 |

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
