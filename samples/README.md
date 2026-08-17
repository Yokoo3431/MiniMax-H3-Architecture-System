# Samples（合成示例）

示例参考图为**程序化生成的合成建筑示意图**（deterministic synthetic demo
assets），不含任何用户项目、客户项目、私有渲染或真实摄影内容，可公开分发。

| 文件 | 用途 |
| --- | --- |
| `01_Exterior_Hero.png` | Architecture Presentation（外观展示）合成示例（1344×768） |
| `05_Slow_Walkthrough.png` | Slow Walkthrough（慢速漫游）合成示例（1344×768） |

使用方式：在 Studio 中新建 Study → 上传示例图 → 批准 → 输入意图 → Generate。

> 模型权重不在本仓库；运行前请按 `models/manifest.json` 放置并校验。
> 生成脚本：`runtime/validation/generate_synthetic_samples.py`（可复现）。
