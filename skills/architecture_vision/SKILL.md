---
name: architecture-vision
description: Architecture Vision Intelligence Skill Engine for MiniMax H3 Architecture System.
version: 0.7.3
---

# Architecture Vision Skill Engine

The **Architecture Vision Skill Engine** analyzes architectural renderings and photographs to extract key features:
- **Building Typology**: Museum, Gallery, Campus, Villa, Skyscraper, Courtyard, Landscape.
- **Architectural Style**: Minimal Concrete Architecture, Brutalism, Scandinavian Timber, High-Tech Glass.
- **Material System**: Fair-faced concrete, timber louvers, double-glazed curtainwall, granite stone.
- **Spatial & Camera Character**: Two-point perspective, tilt-shift, eye-level pedestrian, high-altitude drone.

## Usage Pipeline

```python
from skills.architecture_vision.image_analyzer import ArchitectureImageAnalyzer

analyzer = ArchitectureImageAnalyzer()
analysis_res = analyzer.analyze_image("userdata/custom_prompts/building.jpg", prompt_hint="安藤风格混凝土美术馆黄昏推进")
```
