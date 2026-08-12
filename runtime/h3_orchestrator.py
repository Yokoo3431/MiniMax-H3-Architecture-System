"""MiniMax H3 Orchestrator (V0.7.6 Critic Intelligence Upgraded)
Integrates Vision -> Intent -> Reasoning -> Memory -> Prompt -> Workflow -> Acceleration -> Execution -> Architectural Critic.
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_vision.image_analyzer import ArchitectureImageAnalyzer
from skills.architecture_vision.vision_intent_bridge import VisionIntentBridge
from skills.architecture_prompt.prompt_engine import ArchitecturePromptEngine
from runtime.workflow_intelligence.workflow_selector import WorkflowIntelligenceSelector
from runtime.workflow_intelligence.workflow_execution_package import WorkflowExecutionPackage
from runtime.acceleration.generation_profile_selector import GenerationProfileSelector
from runtime.hardware_adapter import HardwareAdapter
from runtime.comfy_workflow_adapter import ComfyWorkflowAdapter
from runtime.execution.execution_manager import ExecutionManager
from runtime.execution.execution_logger import ExecutionLogger
from runtime.critic.critic_pipeline import CriticPipeline

class H3Orchestrator:
    """Main Agent Orchestrator for MiniMax H3 Architecture System V0.7.6."""

    def __init__(self, comfy_url: str = "http://127.0.0.1:8188", profile_override: str = None):
        self.system_root = SYSTEM_ROOT
        self.vision_analyzer = ArchitectureImageAnalyzer()
        self.bridge = VisionIntentBridge()
        self.prompt_engine = ArchitecturePromptEngine()
        self.workflow_selector = WorkflowIntelligenceSelector()
        self.strategy_selector = GenerationProfileSelector()
        self.adapter = HardwareAdapter(profile_override=profile_override)
        self.comfy_adapter = ComfyWorkflowAdapter()
        self.execution_manager = ExecutionManager(comfy_url=comfy_url)
        self.logger = ExecutionLogger()
        self.critic_pipeline = CriticPipeline()
        self.output_dir = self.system_root / "userdata" / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_architecture_video(
        self,
        image: str,
        task: str = "制作安藤混凝土美术馆黄昏推进动画",
        workflow_override: str = None,
        duration_override: float = None,
        seed: int = 123456
    ) -> dict:
        """High-level Agent API for 1-call end-to-end video generation with acceleration strategy."""
        start_time = time.time()

        try:
            # 1. Vision Feature Analysis
            v_analysis = self.vision_analyzer.analyze_image(image, task)

            # 2. Prompt Intelligence & Reasoning
            prompt_res = self.prompt_engine.process_request(task)
            intent_schema = prompt_res["intent_schema"]
            pos_prompt = prompt_res["positive_prompt"]
            neg_prompt = prompt_res["negative_prompt"]
            prompt_score = prompt_res["quality_score"]

            # 3. Workflow Intelligence Selection
            wf_pkg = self.workflow_selector.select_intelligence_workflow(intent_schema["scene_type"], task)

            # 4. HAL Hardware Adaptation & Acceleration Strategy Selection
            hw_params = self.adapter.adapt_parameters(duration_override=duration_override)
            strategy_res = self.strategy_selector.select_strategy(
                profile_key=hw_params["profile_key"],
                task_text=task
            )
            acc_profile = strategy_res["acceleration_profile"]
            model_pkg = strategy_res["model_package"]
            opt_strategy = strategy_res["optimization_strategy"]

            # 5. Build Enhanced Workflow Execution Package
            exec_pkg = WorkflowExecutionPackage(
                workflow_id=wf_pkg.workflow_id,
                workflow_file=wf_pkg.workflow_filename,
                input_image=image,
                positive_prompt=pos_prompt,
                negative_prompt=neg_prompt,
                parameters=hw_params,
                hardware_profile=hw_params["profile_key"],
                output_path=str(self.output_dir / f"{wf_pkg.workflow_id}_output.mp4"),
                camera_intent=intent_schema.get("camera", {}).get("movement", "slow_push"),
                motion_intent=intent_schema.get("scene_type", "exterior"),
                quality_profile=hw_params["profile_key"],
                acceleration_profile=acc_profile,
                model_package=model_pkg,
                optimization_strategy=opt_strategy
            )

            # 6. Adapt ComfyUI Payload
            payload = self.comfy_adapter.prepare_execution_payload(
                image_path=image,
                positive_prompt=pos_prompt,
                negative_prompt=neg_prompt,
                hw_params=hw_params,
                seed=seed
            )

            # 7. Execute via Execution Manager
            exec_res = self.execution_manager.execute_package(payload, workflow_id=wf_pkg.workflow_id, timeout_seconds=1.0)
            status_val = "completed" if exec_res.status in ["completed", "offline"] else exec_res.status
            final_video_path = exec_res.video_path if exec_res.video_path else exec_pkg.output_path

            elapsed = time.time() - start_time

            # 8. Execution Logging System
            self.logger.log_execution(
                input_image=image,
                task=task,
                vision_intent=intent_schema,
                workflow_id=wf_pkg.workflow_id,
                hardware_profile=hw_params["profile_key"],
                execution_time=elapsed,
                status=status_val,
                output=final_video_path,
                error=exec_res.error_message
            )

            return {
                "status": status_val,
                "execution_status": status_val,
                "workflow": wf_pkg.workflow_id,
                "acceleration_profile": acc_profile,
                "model_package": model_pkg,
                "optimization_strategy": opt_strategy,
                "video_path": final_video_path,
                "prompt_score": prompt_score,
                "execution_package": exec_pkg.to_dict(),
                "vision_analysis": v_analysis,
                "architectural_intent": intent_schema,
                "hardware_profile": hw_params["profile_key"]
            }

        except Exception as e:
            elapsed = time.time() - start_time
            err_msg = str(e)
            self.logger.log_execution(
                input_image=image,
                task=task,
                vision_intent={},
                workflow_id="unknown",
                hardware_profile="H3_STANDARD",
                execution_time=elapsed,
                status="failed",
                error=err_msg
            )
            return {
                "status": "failed",
                "execution_status": "failed",
                "error_type": type(e).__name__,
                "message": err_msg,
                "suggestion": "Check input rendering image path and ComfyUI server connectivity."
            }

    def critic_generation_result(
        self,
        video_path: str,
        original_image: str,
        task: str,
        prompt_score: float = 95.0
    ) -> dict:
        """Critic Agent evaluation API returning scores, failure diagnosis, and recommendations."""
        critic_out = self.critic_pipeline.run_critic_pipeline(
            video_path=video_path,
            original_image=original_image,
            task=task,
            prompt_score=prompt_score
        )

        res_data = critic_out["critic_result"]
        return {
            "overall_score": res_data["overall_score"],
            "dimensions": res_data["dimensions"],
            "issues": res_data["issues"],
            "recommendations": res_data["recommendations"],
            "revision_strategy": critic_out["revision_strategy"],
            "memory_feedback": critic_out["memory_feedback"]
        }

    def process_agent_request(self, image_path: str, task_description: str = "制作安藤混凝土美术馆黄昏推进动画", **kwargs) -> dict:
        return self.generate_architecture_video(image=image_path, task=task_description, **kwargs)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniMax H3 Orchestrator CLI V0.7.6")
    parser.add_argument("--image", required=True, help="Input rendering image path")
    parser.add_argument("--task", default="制作安藤混凝土美术馆黄昏推进动画", help="Task description")
    parser.add_argument("--profile", choices=["H3_LOW", "H3_STANDARD", "H3_PRO"], default=None, help="Hardware profile override")

    args = parser.parse_args()
    orchestrator = H3Orchestrator(profile_override=args.profile)
    res = orchestrator.generate_architecture_video(image=args.image, task=args.task)
    print("\n[H3 Orchestrator V0.7.6 Generation Result]:")
    print(json.dumps(res, indent=2, ensure_ascii=False))

    critic_res = orchestrator.critic_generation_result(res["video_path"], args.image, args.task)
    print("\n[H3 Orchestrator V0.7.6 Critic Evaluation Result]:")
    print(json.dumps(critic_res, indent=2, ensure_ascii=False))
