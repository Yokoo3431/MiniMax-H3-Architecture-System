# Architect Video Studio — Developer Architecture

面向开发者。说明生产链与扩展点。**本文档不包含任何密钥/凭据。**

> **路径约定**：本公开文档不包含机器绝对路径。如需要引用本地位置，使用
> 占位符 `<PROJECT_ROOT>`（仓库根）、`<USER_HOME>`（用户目录）、
> `<SAMPLE_PROJECT>`（示例项目）。内部开发细节见 `docs/internal_archive/`
> （不随公开发布）。

---

## 1. 生产链

```
Reference
  ↓ 上传 + 质量卡（ReferenceQualityAssistant，咨询性）+ 人工批准
Intent
  ↓ 自然语言 → OfficialSkillAdapter.classify_intent（置信度/候选）
Skill Prompt
  ↓ OfficialSkillAdapter.build_prompt（Skill 版本门禁 + 官方结构 + provenance）
Workflow Mapping
  ↓ runtime/contracts/workflow_mapping.yaml（01-05 → native asset）
Native Runtime
  ↓ RuntimeAdapter → NativeRuntimeAdapter → ComfyUIClient → ComfyUI Native
Output Package
  ↓ input / workflow / prompt / output / report（video + runtime_info +
    provenance + generation_report）
```

## 2. 分层与职责

| 层 | 位置 | 职责 |
| --- | --- | --- |
| UI | `apps/architect_video_studio/frontend` | 建筑师工作台（Study 流程） |
| API | `apps/architect_video_studio/mock_api` | Project/Reference/Intent/Prompt/Job/Output 契约（端点冻结） |
| State Machine | `apps/architect_video_studio/state_machine` | 项目/作业状态机（非法跳转拒绝） |
| Prompt | `runtime/prompt_bridge` | OfficialSkillAdapter / H3PromptBridge / skill_version（冻结） |
| Contracts | `runtime/contracts` | VideoGenerationRequest / workflow_mapping / native_runtime |
| Adapters | `runtime/adapters` | RuntimeAdapter（generate/status/cancel）、NativeRuntimeAdapter、ComfyUIClient |
| Launcher | `launcher` | 环境检查 / 进程 / 锁 / 日志 / 双击入口 |
| Validation | `runtime/validation` | 探测与运行脚本 |

## 3. 冻结边界（不得修改）

- H3 Runtime / ComfyUI / 模型 / PREAD shim / sampler / VAE
- 01-05 workflow JSON
- OfficialSkillAdapter / H3PromptBridge / Skill Pin
- RuntimeAdapter / WorkflowMapping / NativeRuntimeAdapter
- API Contract Existing Endpoints

## 4. 扩展点

- **新工作流**：注册 workflow_mapping.yaml（display_name / asset / camera /
  input）+ 已验证 Native 图 + 前端标签映射；UI 无需结构性改动
- **新输入策略**：WorkflowController（Single/Multi/Keyframe/Scene）在既有
  工作流之上组合（设计已记录，未实现生成）
- **新运行时**：实现 `RuntimeAdapter` 接口（generate/status/cancel），
  JobAPI 注入即可替换 Mock/Native

## 5. 安全与可追溯

- 参考批准 / 意图确认 / Prompt 验证 / 风险审阅四重门禁，服务端强制
- 每次生成写入 provenance（skill/bridge/profile 哈希、参考哈希、审批、
  prompt 哈希）；`runtime.lock` 阻止重复启动与 GPU 作业运行中关闭
- 本地运行；无云端调用；无密钥（环境敏感值经 env 变量注入，不入库）
