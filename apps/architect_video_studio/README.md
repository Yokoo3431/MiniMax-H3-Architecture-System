# Architect Video Studio — Local UI Prototype (PATCH2.6-B)

合同优先的本地 UI 原型，验证建筑师完整生产流程：

```
Reference → Intent → Workflow Selection → Official Skill Prompt Preview
→ User Confirmation → Job State Simulation → Output Review
```

**Mock 模式**：不调用 ComfyUI / GPU / Native Runtime，不加载模型。Prompt 生成复用
冻结的 `OfficialSkillAdapter` / `H3PromptBridge`（纯 Python、只读调用、官方结构验证 + provenance）。

## 运行

```bash
python run_prototype.py --port 8788
```

打开 `http://127.0.0.1:8788`。

演示数据（页面截图用）：

```bash
python -c "from mock_api.seed_demo import seed_demo; print(seed_demo())"
```

## 目录结构

```
apps/architect_video_studio/
├── frontend/         原生 HTML/CSS/JS（Home / Workspace / Job Center / Output Review）
├── mock_api/         Mock API 契约 + stdlib HTTP server
├── state_machine/    PATCH2.6A 状态机（项目 + 作业）
├── data/             运行时持久化（projects/…/provenance.json, audit_log.jsonl…）
└── run_prototype.py  启动入口
```

## Mock API 契约

| API | 端点 | 说明 |
| --- | --- | --- |
| Project | `POST /api/projects`, `GET /api/projects[/<id>]` | 创建/读取项目 |
| Reference | `POST /api/projects/<id>/references`, `…/approve`, `…/reject` | 上传/批准/拒绝（质量卡咨询性） |
| Intent | `POST /api/projects/<id>/intent` | 冻结分类器 `classify_intent` |
| Prompt | `POST /api/projects/<id>/prompt` | 冻结 `build_prompt`（只读） |
| Job | `POST /api/projects/<id>/jobs`, `GET /api/jobs/<id>` | Mock 进度模拟 |
| Output | `GET /api/jobs/<id>/result` | Output Package manifest |

## 安全门禁（服务端强制，UI 只是第一层）

1. 未批准参考图 → `generate_prompt` / `submit_job` 抛错
2. Prompt 只读（无编辑端点）
3. Workflow 只允许冻结 01–05，无编辑能力
4. 每个 Mock Job 保存 `provenance.json`
5. 审计日志 `audit_log.jsonl`（谁 / 何时 / 什么状态迁移）

## 已知边界

- `output.mp4` 是占位文本，非真实视频（PATCH2.6-C 接 Native）
- 质量卡在无 cv2 或文件缺失时降级为确定性 Mock 卡
