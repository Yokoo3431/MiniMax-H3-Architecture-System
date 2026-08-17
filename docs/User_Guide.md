# Architect Video Studio — 用户指南（建筑师）

面向非开发者的建筑师。目标：**5 步内完成第一次视频生成**。

> **路径约定**：本公开文档只使用相对路径；任何机器特定位置以
> `<PROJECT_ROOT>` / `<USER_HOME>` / `<SAMPLE_PROJECT>` 占位。

---

## 1. 安装（5 步以内）

1. **下载**：获取 `ArchitectVideoStudio` 压缩包并解压到本地（建议 SSD，需约
   100GB 可用空间）。
2. **检查模型**：确认 `models/manifest.json` 对应的四个模型已按清单放置
   （DiT / Text Encoder / Video VAE / Audio VAE）。Launcher 启动时会自动校验
   SHA-256，不匹配会提示。
3. **启动 Launcher**：双击 `launcher\start_architect_video_studio.bat`。
   首次启动会执行环境检查（GPU、模型、内存、端口），约 1–3 分钟。
4. **打开 Studio**：浏览器自动打开 `http://127.0.0.1:8788`（或按提示手动打开）。
5. **生成视频**：新建 Study → 上传参考图 → 描述意图 → 确认工作流与参数 →
   Generate → 在任务中心查看结果。

> 若启动提示 BLOCK：按提示查看 `Logs\launcher.log`；常见原因：模型缺失/哈希
> 不匹配、Free Commit 低于 30GB、端口 8189/8788 被占用。

## 2. 第一次视频教程 — Exterior Hero（建筑外观展示）

输入：一张建筑效果图（立面/入口视角）
输出：约 4 秒的建筑展示视频（1344×768，24fps）

步骤：

1. Home 点击 **+ New Study**，命名（如 "入口展示"）。
2. 左侧 **Reference**：上传效果图，点击 **Approve**。
3. 右侧 **AI Assistant**：输入意图，例如
   "做一个建筑外观主视角展示视频"。
4. 确认 **Workflow = Architecture Presentation**，参数保持默认
   （Resolution 1344×768 · FPS 24 · Duration 4s），点击 **生成 Prompt 预览**。
5. 阅读 Prompt（只读，官方 Skill 生成），勾选"我已审阅风险"，
   点击 **Generate**。
6. 在 **Job Center** 等待完成（Preparing → Loading → Sampling → Encoding →
   Exporting），完成后进入 **Output Review** 查看视频与生成记录。

## 3. 其他工作流

| 用户名称 | 参考图要求 | 适用 |
| --- | --- | --- |
| Architecture Presentation | 1 张外观效果图 | 立面展示 |
| Day Night | 日景图 + 夜景图（同机位） | 日夜过渡 |
| Material Detail | 1 张材质/细节特写 | 材质保真 |
| Drone Reveal | 1 张鸟瞰/总图 | 场地展示 |
| Slow Walkthrough | 1 张透视图（有纵深） | 慢速漫游 |

## 4. 安全与隐私

- 全部在本机运行，不上传云端
- 每次生成自动记录 provenance（Skill 版本、Prompt 哈希、参考图哈希、审批状态）
- 未批准参考图时无法生成；Prompt 与 Workflow 只读
