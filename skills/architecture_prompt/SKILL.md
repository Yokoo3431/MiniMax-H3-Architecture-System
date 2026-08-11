---
name: architecture_prompt
description: Architectural Natural Language Intent Understanding & MiniMax H3 Optimized Prompt Engine
---

# Architecture Prompt Skill Engine

Converts architectural natural language user requests into structured `ArchitecturalIntentSchema`, MiniMax H3 optimized prompts, and recommended workflows.

## Usage

```python
from skills.architecture_prompt.prompt_engine import ArchitecturePromptEngine

engine = ArchitecturePromptEngine()
res = engine.process_request("把这个博物馆效果图制作成黄昏动画，保持建筑体量不变，镜头缓慢推进，室内增加暖光")

print("Intent Schema    :", res["intent_schema"])
print("Positive Prompt  :", res["positive_prompt"])
print("Negative Prompt  :", res["negative_prompt"])
print("Workflow Target  :", res["recommended_workflow"])
print("Hardware Profile :", res["recommended_profile"])
```
