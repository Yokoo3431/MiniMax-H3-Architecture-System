"""Architecture Image Analyzer Entrance (V0.7.3).
"""

from skills.architecture_vision.architectural_feature_extractor import ArchitecturalFeatureExtractor
from skills.architecture_vision.vision_schema import ArchitectureVisualAnalysis

class ArchitectureImageAnalyzer:
    """Image Analysis entrance for architectural rendering feature extraction."""

    def __init__(self):
        self.extractor = ArchitecturalFeatureExtractor()

    def analyze_image(self, image_path: str, prompt_hint: str = "") -> dict:
        analysis: ArchitectureVisualAnalysis = self.extractor.extract_features(image_path, prompt_hint)
        return analysis.to_dict()
