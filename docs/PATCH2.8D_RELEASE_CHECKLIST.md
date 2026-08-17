# PATCH2.8-D — Release Checklist

发布前逐项确认（全部应为 PASS）：

---

## Runtime

- [x] Native ComfyUI v0.33.1 环境可用（`/system_stats` 200）
- [x] PREAD safe-load（`H3_WINDOWS_SAFE_LOAD=pread` + shim）
- [x] 模型校验：DiT / TE / Video VAE / Audio VAE SHA-256 匹配冻结基线
- [x] Free Commit 预检（≥50GB 优先；<30GB 硬停）

## Workflow

- [x] 01 Exterior Hero —— 真实 GPU PASS（C2-A / C2-B）
- [x] 02 Day Night —— 真实 GPU PASS（C2-B）
- [x] 03 Material Detail —— 真实 GPU PASS（C2-B）
- [x] 04 Drone Aerial —— 真实 GPU PASS（C2-B）
- [x] 05 Slow Walkthrough —— 真实 GPU PASS（C2-B）

## UI

- [x] Architect Video Studio（PATCH2.6-D.2 基线）UI 可访问
- [x] UI ↔ Runtime 绑定（PATCH2.7-D）：JobAPI → NativeRuntimeAdapter

## Distribution

- [x] 分发布局（launcher/comfyui/models/runtime/studio/workflows/samples/
      userdata/logs/README）
- [x] 路径独立性（distribution_config.yaml 全相对；无开发机路径）
- [x] 干净安装模拟（install_test 全新目录启动，~74s）
- [x] 分发布局真实 GPU Smoke（01，seed 777888999，输出包齐全）

## Tests

- [x] 完整回归 288/288 PASS（含 launcher / distribution / runtime 契约测试）
- [x] 自动化测试无 GPU / ComfyUI / 模型调用

## 文档与合规

- [x] User Guide（5 步安装 + 首次生成教程）
- [x] Developer Architecture
- [x] THIRD_PARTY_NOTICES（ComfyUI GPL-3.0 / MiniMax H3 / Qwen / Python 依赖）
- [x] Repository Audit + .gitignore（模型/输出/日志/锁/密钥不提交）
- [x] 上游复检（发布前最后执行）：ComfyUI #15424/#15438、MiniMax Skill 版本

---

## 结论

发布技术条件已具备；最终 RC Release 需人工审核 + 上游复检后执行。
