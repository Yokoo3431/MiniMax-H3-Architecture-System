"""MiniMax H3 Orchestrator (V0.7.3 Upgraded Vision Engine)
Integrates Vision Intelligence Layer -> Intent Parser -> Architecture Reasoning -> Memory Retriever -> Prompt Engine -> Workflow Selector -> ComfyUI Payload.
"""

import os
import sys
import json
import argparse
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_vision.image_analyzer import ArchitectureImageAnalyzer
from skills.architecture_vision.vision_intent_bridge import VisionIntentBridge
from skills.architecture_prompt.prompt_engine import ArchitecturePromptEngine
from runtime.workflow_intelligence.workflow_selector import WorkflowIntelligenceSelector
from runtime.hardware_adapter import HardwareAdapter
from runtime.comfy_workflow_adapter import ComfyWorkflowAdapter
from runtime.comfy_executor import ComfyExecutor

class H3Orchestrator:
    """Main Agent Orchestrator for MiniMax H3 Architecture System V0.7.3."""

    def __init__(self, comfy_url: str = "http://127.0.0.1:8188", profile_override: str = None):
        self.system_root = SYSTEM_ROOT
        self.vision_analyzer = ArchitectureImageAnalyzer()
        self.bridge = VisionIntentBridge()
        self.prompt_engine = ArchitecturePromptEngine()
        self.workflow_selector = WorkflowIntelligenceSelector()
        self.adapter = HardwareAdapter(profile_override=profile_override)
        self.comfy_adapter = ComfyWorkflowAdapter()
        self.executor = ComfyExecutor(comfy_url=comfy_url)
        self.output_dir = self.system_root / "userdata" / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def process_agent_request(
        self,
        image_path: str,
        task_description: str = "制作黄昏慢推进建筑动画",
        workflow_override: str = None,
        duration_override: float = None,
        seed: int = 123456
    ) -> dict:
        # 1. Vision Intelligence Feature Analysis
        v_analysis = self.vision_analyzer.analyze_image(image_path, task_description)

        # 2. Architecture Intent & Prompt Intelligence Core Processing
        prompt_res = self.prompt_engine.process_request(task_description)
        intent_schema = prompt_res["intent_schema"]
        pos_prompt = prompt_res["positive_prompt"]
        neg_prompt = prompt_res["negative_prompt"]

        # 3. Workflow Intelligence Selection
        wf_pkg = self.workflow_selector.select_intelligence_workflow(intent_schema["scene_type"], task_description)

        # 4. HAL Hardware Adaptation
        hw_params = self.adapter.adapt_parameters(duration_override=duration_override)

        print(f"[H3 Orchestrator V0.7.3] Vision Analysis : Style: {v_analysis['style']}, Typology: {v_analysis['type']}", flush=True)
        print(f"[H3 Orchestrator V0.7.3] Request Task     : '{task_description}'", flush=True)
        print(f"[H3 Orchestrator V0.7.3] Selected WF      : {wf_pkg.workflow_filename} (Preset: {wf_pkg.preset_id})", flush=True)
        print(f"[H3 Orchestrator V0.7.3] HAL Profile      : {hw_params['profile_key']} ({hw_params['width']}x{hw_params['height']})", flush=True)

        # 5. ComfyUI Workflow Parameter Payload Adaptation
        payload = self.comfy_adapter.prepare_execution_payload(
            image_path=image_path,
            positive_prompt=pos_prompt,
            negative_prompt=neg_prompt,
            hw_params=hw_params,
            seed=seed
        )

        # 6. ComfyUI Backend Execution
        res = self.executor.execute_payload(payload, self.system_root.parent / "ComfyUI" / "output")

        res["vision_analysis"] = v_analysis
        res["architectural_intent"] = intent_schema
        res["generated_prompt"] = {
            "positive": pos_prompt,
            "negative": neg_prompt
        }
        res["selected_workflow"] = wf_pkg.to_dict()
        res["hardware_profile"] = hw_params["profile_key"]
        return res

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniMax H3 Orchestrator CLI V0.7.3")
    parser.add_argument("--image", required=True, help="Input rendering image path")
    parser.add_argument("--task", default="把这个安藤风格混凝土美术馆效果图制作成黄昏推进动画", help="Task description")
    parser.add_argument("--profile", choices=["H3_LOW", "H3_STANDARD", "H3_PRO"], default=None, help="Hardware profile override")

    args = parser.parse_args()
    orchestrator = H3Orchestrator(profile_override=args.profile)
    res = orchestrator.process_agent_request(image_path=args.image, task_description=args.task)
    print("\n[H3 Orchestrator V0.7.3 Result]:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
