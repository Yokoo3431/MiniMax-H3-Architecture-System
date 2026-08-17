# Runtime Layer — Video Generation Runtime Boundary

**RC3.4 PATCH2.7-A — Runtime Boundary Preparation**

本层是 **Video Generation Runtime Contract**：UI / API 与真实 GPU 运行时之间的
独立边界。本阶段只有契约与 Mock 实现，**不接入 GPU / ComfyUI / Native Runtime**。

## 目录

```
runtime/
├── contracts/
│   └── video_generation_request.yaml   VideoGenerationRequest 契约
├── adapters/
│   └── runtime_adapter.py              RuntimeAdapter 接口 + MockRuntimeAdapter
└── README.md
```

## 设计原则

1. **Adapter 独立**：运行时实现可替换（Mock → Native），UI / API / 状态机零改动。
2. **契约先行**：请求与输出以
   `contracts/video_generation_request.yaml` 为单一事实来源。
3. **状态机不修改**：Runtime Status → 既有 Job Status 只做映射文档，不改
   `apps/architect_video_studio/state_machine/`。
4. **Mock 边界**：`MockRuntimeAdapter` 返回 Mock Job，不调用 GPU / CUDA /
   ComfyUI / 真实模型。

## 冻结边界

以下内容在本阶段（及未来接入前）保持不动：

- H3 Runtime Core / ComfyUI / Workflow JSON
- Prompt Pipeline（`OfficialSkillAdapter` / `H3PromptBridge` / skill_version / profiles / schema）
- API Contract Existing Endpoints（Project / Reference / Intent / Prompt / Job / Output）
- State Machine Logic
- Frontend UI Architecture / Study 产品模型
- Existing tests（169/169 保持）

## 未来接入（不在本阶段实现）

- PATCH2.7-C：`JobAPI` 内部委托 `RuntimeAdapter`（真实实现），端点与响应不变
- ComfyUI 提交：适配器内实现 `generate → /prompt` + 轮询，映射真实阶段
- 输出：`video_path` 由 `mock://` 换成 Native 输出路径 + ffprobe 验证
