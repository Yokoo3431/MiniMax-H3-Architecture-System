"""Workflow Intelligence Selector Engine (V0.7.2 Upgraded).
Converts architectural intent & request text into complete WorkflowSelectionPackage.
"""

from runtime.workflow_intelligence.workflow_schema import WorkflowSelectionPackage
from runtime.workflow_intelligence.workflow_matcher import WorkflowMatcher
from runtime.workflow_intelligence.workflow_parameter_mapper import WorkflowParameterMapper

class WorkflowIntelligenceSelector:
    """Intelligent Workflow Selector combining semantic matching and video preset mapping."""

    def __init__(self):
        self.matcher = WorkflowMatcher()
        self.mapper = WorkflowParameterMapper()

    def select_intelligence_workflow(self, scene_type: str, text: str, quality_profile: str = "H3_STANDARD") -> WorkflowSelectionPackage:
        wf_id = self.matcher.match_intent_to_workflow(scene_type, text)
        preset_data = self.mapper.get_preset_for_workflow(wf_id)
        params = preset_data.get("parameters", {})

        filename_map = {
            "1_image_to_video": "1_建筑效果图_ImageToVideo.json",
            "2_aerial_view": "2_建筑鸟瞰动画_AerialView.json",
            "3_night_transition": "3_建筑夜景灯光变化_NightTransition.json",
            "5_walkthrough": "1_建筑效果图_ImageToVideo.json",
            "6_massing_evolution": "1_建筑效果图_ImageToVideo.json",
            "8_exploded_axon": "1_建筑效果图_ImageToVideo.json"
        }

        return WorkflowSelectionPackage(
            workflow_id=wf_id,
            workflow_filename=filename_map.get(wf_id, "1_建筑效果图_ImageToVideo.json"),
            workflow_type="architecture_visualization" if "analysis" not in wf_id else "architecture_analysis",
            camera_motion=params.get("camera_motion", "slow_push"),
            lighting_atmosphere=params.get("lighting_atmosphere", "soft_twilight"),
            duration_seconds=params.get("duration_seconds", 5.0),
            quality_profile=quality_profile,
            preset_id=preset_data.get("preset_id", "exterior_hero")
        )
