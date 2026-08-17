# PATCH2.8-F — Final RC Gate

公开发布前最终检查：

---

## Repository

- [x] 生产结构齐全（launcher/apps/runtime/workflows/configs/references/samples/
      docs/tests）
- [x] Legacy 目录已标注（历史证据保留）
- [x] `.gitignore` 覆盖模型/输出/日志/锁/密钥

## Documentation

- [x] README / User Guide / Developer Architecture
- [x] Public Data Policy / Public Data Audit

## License

- [x] THIRD_PARTY_NOTICES（ComfyUI GPL-3.0 / MiniMax H3 / Qwen / Python 依赖）

## Privacy

- [x] samples 全部为合成资产（无用户/客户图片）
- [x] 15 份运维文档标记（脱敏/排除）
- [x] 参考图目录在仓库外

## Security

- [x] 无密钥入库；冻结组件未修改
- [x] runtime.lock / 门禁 / provenance 保持

## Tests

- [x] 288/288 PASS（仅回归；无 GPU / ComfyUI inference / 模型加载）

---

## 发布动作（需人工）

1. 人工审核本门禁 + Final Report
2. 决定运维文档去留/脱敏
3. 确认 commit/push/tag 策略后执行
