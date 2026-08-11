# Modular Agent Runtime API Guide (V0.5)

## Overview

In V0.5, the Agent integration layer is refactored into modular components inside `runtime/`:

```python
from runtime.h3_orchestrator import H3Orchestrator

orchestrator = H3Orchestrator(profile_override="H3_STANDARD")

res = orchestrator.process_agent_request(
    image_path="architectural_rendering.png",
    task_description="Breathtaking aerial drone view of modern masterplan"
)

print("Selected Workflow:", res["workflow_selected"])
print("Hardware Profile :", res["hardware_profile"])
print("Output Video Path:", res["video_path"])
```

## Agent Engine Architecture

- `TaskPlanner`: Intent parsing.
- `WorkflowSelector`: Categorized registry matching.
- `PromptComposer`: Positive/negative architectural preset composition.
- `HardwareAdapter`: HAL parameter adaptation.
- `ComfyExecutor`: ComfyUI REST API execution backend.
