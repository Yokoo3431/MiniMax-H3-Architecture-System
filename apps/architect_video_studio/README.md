# Architect Video Studio — Local Desktop Service

Architect Video Studio 的本地服务层，供桌面壳承载 Studio、环境中心和项目工作区：

```
Reference → Intent → Workflow Selection → Official Skill Prompt Preview
→ User Confirmation → Job State Simulation → Output Review
```

`--runtime mock` 仅用于离线 UI/契约测试；正常桌面启动使用 `--runtime real`，连接托管
Native ComfyUI。Prompt 生成复用冻结的 `OfficialSkillAdapter` / `H3PromptBridge`。

## 运行

```bash
python run_architect_video_studio.py --port 8788
```

打开 `http://127.0.0.1:8788`。

开发/离线数据种子：

```bash
python -c "from mock_api.seed_demo import seed_demo; print(seed_demo())"
```

## 目录结构

```
apps/architect_video_studio/
├── frontend/         原生 HTML/CSS/JS（Home / Workspace / Job Center / Output Review）
├── mock_api/         Local API contract + stdlib HTTP server
├── state_machine/    PATCH2.6A 状态机（项目 + 作业）
├── data/             运行时持久化（projects/…/provenance.json, audit_log.jsonl…）
└── run_architect_video_studio.py  Production service entry
```

## Local API 契约

| API | 端点 | 说明 |
| --- | --- | --- |
| Project | `POST /api/projects`, `GET /api/projects[/<id>]` | 创建/读取项目 |
| Reference | `POST /api/projects/<id>/references`, `…/approve`, `…/reject` | 上传/批准/拒绝（质量卡咨询性） |
| Intent | `POST /api/projects/<id>/intent` | 冻结分类器 `classify_intent` |
| Prompt | `POST /api/projects/<id>/prompt` | 冻结 `build_prompt`（只读） |
| Job | `POST /api/projects/<id>/jobs`, `GET /api/jobs/<id>` | 作业状态与进度 |
| Output | `GET /api/jobs/<id>/result` | Output Package manifest |

## 安全门禁（服务端强制，UI 只是第一层）

1. 未批准参考图 → `generate_prompt` / `submit_job` 抛错
2. Prompt 只读（无编辑端点）
3. Workflow 只允许冻结 01–05，无编辑能力
4. 每个 Job 保存 `provenance.json`
5. 审计日志 `audit_log.jsonl`（谁 / 何时 / 什么状态迁移）

## 运行边界

- 真实视频生成由 Native ComfyUI 后端负责；桌面服务只负责项目、提示词、工作流和作业状态。
- 缺少可选图像质量依赖时，环境中心会显示可解释的降级状态，不会伪报 GPU 或 H3 支持故障。
