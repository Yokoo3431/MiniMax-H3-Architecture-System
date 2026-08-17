# PATCH2.8-I0 — Public User Entry Point Fix Report

**Phase:** RC3.4 PATCH2.8-I0 — Public User Entry Point Fix
**Date:** 2026-08-17
**Status:** READY_FOR_RELEASE（等待人工审核后继续 PATCH2.8-I 正式发布）

---

## 1. Root launcher added

仓库根目录新增 **`Start_ArchitectVideoStudio.bat`**：

- 自动定位仓库根（`%~dp0`，任意绝对路径可用）
- 解析 Native 运行时根：`%H3_NATIVE_ROOT%` → `native_env.path`（用户配置，
  gitignored；模板 `native_env.path.example`）
- 导出 H3_NATIVE_ROOT / H3_MODELS_ROOT / H3_COMFY_INPUT / H3_COMFY_OUTPUT /
  H3_BASELINE / H3_STUDIO_DATA / H3_WINDOWS_SAFE_LOAD=pread
- 调用 `launcher\launcher.py start`；失败保持窗口并显示
  MODEL MISSING / CUDA NOT AVAILABLE / FREE COMMIT TOO LOW /
  PORT 8189 OCCUPIED + 提示 `logs\launcher.log`

## 2. Advanced ComfyUI launcher added

仓库根目录新增 **`Open_Native_ComfyUI.bat`**（Advanced / Developer only）：

- `H3_WINDOWS_SAFE_LOAD=pread`
- 直接启动 Native ComfyUI（端口 8189，`--disable-dynamic-vram
  --disable-pinned-memory`），不创建新 Runtime、不打开 Studio
- README 已标记为高级用户专用

## 3. README synchronized

Quick Start 改为 Windows 步骤：配置模型 → **双击仓库根目录
`Start_ArchitectVideoStudio.bat`** → 等待环境检查 → 浏览器自动打开 Studio；
新增 Advanced Users 段（`Open_Native_ComfyUI.bat`）。不再要求普通用户进入
`launcher/` 找启动文件。

## 4. Distribution synchronized

`distribution_test/ArchitectVideoStudio/` 与 `install_test/ArchitectVideoStudio/`
均已同步两个入口 + `native_env.path.example`；测试断言分发包含两个启动器。

## 5. Path portability

- 入口文件/README/.gitignore 无 `AntigravityWorkspace` 或任何开发机绝对路径
- Native 根由 `native_env.path` 或环境变量提供（用户一次性配置，不入库）
- 仓库根与解压后的任意绝对路径均可启动

## 6. Tests

- 新增 `tests/test_patch28i0_entry_points.py`（7 项）：root launcher 存在/
  调用 launcher.py / 无开发路径 / README 与真实文件一致 / advanced launcher
  存在 / 分发包含两个启动器 / gitignore 不排除公开 bat
- 完整回归 **295/295 PASS**（288 + 7；无 GPU）

## 7. Files changed

| 文件 | 变更 |
| --- | --- |
| `Start_ArchitectVideoStudio.bat` | 新增（根一键启动） |
| `Open_Native_ComfyUI.bat` | 新增（Advanced） |
| `native_env.path.example` | 新增（配置模板） |
| `.gitignore` | 修复 `launcher/Start_*.bat` 大小写误伤；新增 `native_env.path` |
| `README.md` | Quick Start + Advanced Users 同步 |
| `launcher/start_architect_video_studio.bat` | 重新纳入提交（此前被 gitignore 误排除） |
| `tests/test_patch28i0_entry_points.py` | 新增 7 项测试 |

提交：`d7a69c0`（release/v0.8.0-rc1；未 push / 未 tag）

## 8. Architecture Drift Check

```
PATCH2.6-D.2 UI: FROZEN
PATCH2.7 Runtime: FROZEN
PATCH2.8-B Launcher: FROZEN
PATCH2.8-C Distribution: FROZEN
PATCH2.8-G Documentation: FROZEN
PATCH2.8-H Release Preparation: FROZEN
PATCH2.8-I0 Entry Point Fix: IMPLEMENTED
```

## 9. Ready for GitHub tag?

**READY_FOR_RELEASE** —— 但按 STOP 要求：未创建/推送 tag、未创建 GitHub
Release、未 force push、未删除旧 tag；等待人工审核后继续 PATCH2.8-I 正式发布
（届时需处理旧 tag `v0.8.0-rc1` 冲突决策）。
