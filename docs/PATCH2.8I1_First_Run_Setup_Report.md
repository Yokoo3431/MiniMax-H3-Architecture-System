# PATCH2.8-I1 — First-Run Setup Report

**Phase:** RC3.4 PATCH2.8-I1
**Date:** 2026-08-17
**Status:** **PATCH2.8-I1 STATUS: PASS**

---

## 1. Bootstrap behavior

`Start_ArchitectVideoStudio.bat` → launcher 轻量环境探测（`light=True`，不哈希
38GB）：python 缺失 = HARD BLOCK；Native/模型缺失 = **SETUP_REQUIRED** →
仅启动 Studio（Setup Mode，8788），不启动 ComfyUI；READY = 双服务 + 浏览器。

## 2. Setup Mode

Studio 首次运行自动进入 **Environment Center**（`/setup.html`），完成
Native/Models 路径配置 → Re-check → Continue to Studio。

## 3. Environment API

- `GET /api/system/environment` → READY/WARNING/SETUP_REQUIRED/BLOCK +
  system/runtime/models/skill/workflows/paths/gates
- `POST /api/system/configure` → 写入 native_root/models_root（+ 自动生成
  `native_env.path`）
- `POST /api/system/recheck` → 重跑环境
- `POST /api/system/open-comfyui` → 高级入口（返回 bat 路径，不自动 spawn）

## 4. Path configuration

用户选择目录保存；生产组件优先读环境配置（H3_*），无开发机路径；`setup_state.json`
gitignored（userdata/）；`native_env.path` gitignored。

## 5. Model status

四模型按冻结基线显示 filename/size/status；仅状态与路径，不下载。

## 6. Skill status

Pinned/Installed/Latest + READY/UPDATE_AVAILABLE/REVISION_MISMATCH；
`installed != pinned` → REVISION_MISMATCH 阻断生成；upstream 更新只标记不切换。

## 7. Workflow status

workflow registry 5/5 Ready（仅名称 + Ready/Missing/Invalid）。

## 8. System UI

Home 显示 "System Ready / Setup Required" + ⚙ System 入口；Workspace 顶部
⚙ System；首次 SETUP_REQUIRED/BLOCK 自动跳转 setup.html；PATCH2.6-D.2 主视觉
结构未重做。

## 9. Tests

- 新增 `tests/test_patch28i1_first_run_setup.py`（15 项）
- 完整回归 **310/310 PASS**（295 + 15；无 GPU）

## 10. Distribution validation

`distribution_test/` 与 `install_test/` 已同步；**Clean Copy 验证（install_test）**：

```
Start（模拟 Launcher 环境）→ GET environment → SETUP_REQUIRED, setup_completed=False
→ POST configure(现有 Native/Models) → READY, setup_completed=True
   models 4/4 · workflows 5/5 · skill READY · gpu True
```

## 11. Security

- `setup_state.json` 禁止 token/api_key/credential/prompt/project/session 键
  （save 时校验拒绝）
- 无自动下载 / 自动安装 / 自动升级 / 磁盘扫描 / 局域网扫描
- 前端不能修改 workflow JSON / runtime contract / prompt pipeline / registry

## 12. Files changed

后端：`mock_api/setup_state.py`、`mock_api/environment_service.py`、
`mock_api/system_api.py`、`mock_api/server.py`
前端：`frontend/setup.html`、`frontend/js/setup.js`、`frontend/index.html`、
`frontend/workspace.html`、`frontend/js/home.js`、`frontend/js/workspace.js`
Launcher：`launcher/env_check.py`（light mode）、`launcher/launcher.py`
（SETUP_REQUIRED 分支）
测试：`tests/test_patch28i1_first_run_setup.py`、`tests/test_patch28b_launcher.py`
文档：`docs/PATCH2.8I1_First_Run_Setup.md`、`docs/PATCH2.8I1_First_Run_Setup_Report.md`、
`README.md`

## 13. Architecture Drift Check

```
PATCH2.6-D.2 UI: FROZEN
PATCH2.7 Runtime: FROZEN
PATCH2.8-B Launcher: FROZEN
PATCH2.8-C Distribution: FROZEN
PATCH2.8-G Documentation: FROZEN
PATCH2.8-I0 Entry Point: FROZEN
PATCH2.8-I1 First Run Setup: IMPLEMENTED
```

是否修改了：Runtime inference **NO** · Workflow JSON **NO** · Prompt Pipeline
**NO** · Main Studio architecture **NO**（仅新增 System 页面与状态入口）。

## 14. Next stage recommendation

进入 **PATCH2.8-I2 Automated Runtime & Model Installer**（自动下载/放置模型、
ComfyUI 安装引导）前，先由人工审核本阶段；正式 tag/Release 仍按旧 tag 冲突
决策后执行。
