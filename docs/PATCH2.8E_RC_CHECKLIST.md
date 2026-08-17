# PATCH2.8-E — Release Candidate Checklist

RC 发布前逐项确认：

---

## Repository

- [x] 生产目录齐全（launcher / apps / runtime / workflows / configs /
      references / samples / docs / tests）
- [x] Legacy 目录已 README 标注（历史证据保留，未删除）
- [x] `.gitignore` 覆盖模型/输出/日志/锁/密钥

## Documentation

- [x] README（What / Features / Quick Start / Hardware / Architecture）
- [x] User Guide（5 步安装 + 首次生成）
- [x] Developer Architecture（生产链 + 冻结边界）

## License

- [x] THIRD_PARTY_NOTICES（ComfyUI GPL-3.0 / MiniMax H3 / Qwen / Python 依赖）
- [x] 模型权重不随仓库分发（独立授权）

## Workflow

- [x] 01-05 全部真实 GPU PASS（PATCH2.7-C2-B 证据）
- [x] workflow JSON 未修改（冻结）

## Runtime

- [x] Native ComfyUI v0.33.1 + PREAD safe-load
- [x] UI ↔ Runtime 绑定（PATCH2.7-D）
- [x] 模型 SHA-256 冻结清单

## Distribution

- [x] 分发布局 + 路径独立性（distribution_config.yaml 全相对）
- [x] 干净安装模拟 PASS（install_test）
- [x] 分发真实 GPU Smoke PASS

## Security

- [x] 参考批准 / Prompt 只读 / Workflow 只读 / Provenance 自动记录
- [x] runtime.lock 防重复启动 + GPU 作业运行中禁止关闭
- [x] 无密钥入库；环境敏感值经 env 注入
- [x] 回归 288/288 PASS

---

## 发布前最终动作（需人工执行）

1. 人工审核本清单与最终报告
2. 上游复检：ComfyUI #15424/#15438、MiniMax H3 Skill 版本
3. 确认 commit/push/tag 策略（当前未执行）
