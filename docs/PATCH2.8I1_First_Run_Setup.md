# PATCH2.8-I1 — First-Run Setup & Environment Center

**Phase:** RC3.4 PATCH2.8-I1
**Status:** IMPLEMENTED

---

## First Run

用户流程：

```
Start_ArchitectVideoStudio.bat
  → Bootstrap / Environment Probe（轻量）
  → Environment Ready?
       ├─ YES → Production Studio
       └─ NO  → Setup Mode → Environment Center → READY → Production Studio
```

首次下载后双击启动：如果 Native 运行时/模型未配置，不再直接黑窗 BLOCK，而是
进入 **Environment Center** 完成配置。

## Environment Center

Studio 的 System 页面（`/setup.html`），架构工作站风格，左侧 System Groups：

- SYSTEM：Windows / GPU / CUDA / Memory / Free Commit / Disk
- RUNTIME：ComfyUI / Version / Frontend / PREAD / Port
- MODELS：DiT / Text Encoder / Video VAE / Audio VAE（文件名 + 大小 + 状态）
- PROMPT：Official H3 Skill（Pinned / Installed / Latest / Status）
- WORKFLOWS：5/5 Ready（仅显示 Ready/Missing/Invalid）
- ADVANCED：Open Native ComfyUI（高级入口）

右侧 Environment Inspector 显示对应分组状态；页面不暴露 JSON/YAML。

## System Status

统一状态模型：`READY / WARNING / SETUP_REQUIRED / BLOCK`

- READY：所有生产必需组件存在并验证成功
- WARNING：可运行但有非阻断问题（如 Skill UPDATE_AVAILABLE、版本未验证）
- SETUP_REQUIRED：缺 native_root / ComfyUI / models / models_root（可配置解决）
- BLOCK：无 CUDA GPU、Free Commit <30GB、Bootstrap 失败等

缺少模型不是应用崩溃——显示为 SETUP_REQUIRED。

## Models

- 数据来自 `configs/native_production_baseline.json`（文件名/大小/SHA-256）
- 仅显示状态与路径；**不自动下载模型**
- 四个模型逐项显示 READY / MISSING

## Prompt Skill

- 数据来自 `runtime/prompt_bridge/skill_version.py`（Skill Pin）
- 显示 Pinned / Installed / Latest upstream / Status
- Status：READY / UPDATE_AVAILABLE / REVISION_MISMATCH
- `installed != pinned` → REVISION_MISMATCH（阻断生成）
- `upstream newer` → UPDATE_AVAILABLE（不自动升级）

## Native ComfyUI

- 显示路径 / Version / Frontend / PREAD / Port(8189)
- Advanced 入口：Open Native ComfyUI（高级用户）
- Studio 前端不直接控制节点图

## Advanced Access

- 根目录 `Open_Native_ComfyUI.bat`（Advanced / Developer only）
- 普通用户无需使用

## 边界

- Launcher 管进程；Studio 管配置/环境 UX；Runtime 管推理
- 禁止：自动下载模型、自动安装 ComfyUI、自动升级 Skill、扫描磁盘/局域网
- 配置仅允许用户主动选择目录（或标准相对位置 `runtime/native/`）
