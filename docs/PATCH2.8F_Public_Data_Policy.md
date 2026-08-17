# PATCH2.8-F — Public Data Policy

**适用范围**：本 GitHub 公开仓库。

---

## Repository does NOT include

- 用户数据（userdata/、personal_workspace）
- 客户项目 / 项目渲染图 / 竞赛材料 / 私有效果图
- 训练图像 / 摄影原图 / BIM·CAD 导出
- 模型权重（DiT / TE / Video VAE / Audio VAE 的 `.safetensors`）
- 日志、输出视频、runtime.lock、环境报告
- 密钥/凭据（.env、*.key、*.pem 等）

## Repository includes

- 软件（launcher / studio / runtime / workflows / configs / tests / docs）
- 契约（VideoGenerationRequest / workflow_mapping / native_runtime）
- Workflow 引用（01-05 Native JSON，只读；不含权重）
- 合成示例（samples/ 程序化生成，可公开）
- 公开上游 Skill 参考（references/known_good_h3）
- 合规声明（THIRD_PARTY_NOTICES）

## 规则

1. 任何新提交不得包含用户/客户项目图像或私有渲染
2. 示例图像必须是合成资产（生成脚本可复现）
3. 含真实项目名或机器路径的文档默认不进入公开文档集
4. 模型权重一律经清单引用（models/manifest.json + SHA-256），不入库
