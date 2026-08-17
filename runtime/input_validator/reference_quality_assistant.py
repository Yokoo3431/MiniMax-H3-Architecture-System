"""Reference Image Quality Assistant (RC3.3 PATCH2.5, Phase 5).

Automatically assesses a user-supplied architectural image BEFORE workflow
selection / GPU inference, so the production chain can warn against
single-image large-motion generation.

    Output shape:
        {
          "reference_quality": {"resolution": "PASS", "geometry": "HIGH|MEDIUM|LOW",
                            "motion_risk": "LOW|MEDIUM|HIGH",
                            "motion_risk_details": [...]},
          "recommended_workflow": "...",
          "prompt_recommendation": "...",
          "guidance": "..."
        }

    Metrics are advisory; the human architect remains the final gate
    (user reference approval is mandatory before any GPU run).

    PATCH2.5-A motion-risk contract (extended):
    - excessive orbit request
    - very large forward travel / deep walkthrough
    - major perspective reconstruction
    - interior corner-turn from one image
    - aerial 180/360 rotation
    - material-detail large translation
    The assistant NEVER auto-rejects: it reports risk and recommends
    FL2VA / multi-reference / segmented alternatives.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import cv2
import numpy as np


def _imread_unicode(path: str, flags: int = cv2.IMREAD_COLOR):
    data = np.fromfile(str(path), dtype=np.uint8)
    return None if data.size == 0 else cv2.imdecode(data, flags)


class ReferenceQualityAssistant:
    _RISK_PATTERNS = [
        ("large_orbit", ["orbit", "环绕", "circular", "arc shot", "arc-shooting"]),
        ("aerial_180_360", ["180", "360", "full rotation", "反向", "rotate"]),
        ("large_forward_travel", ["deep walkthrough", "corridor turn", "very far", "long travel",
                                   "deep push", "很深", "很远"]),
        ("major_perspective_reconstruction", ["new angle", "reconstruction", "opposite side",
                                               "背面", "重新构建", "多视角", "unseen side"]),
        ("interior_corner_turn", ["corner", "转角", "拐弯", "turn into", "corridor turn"]),
        ("material_large_translation", ["lateral translation", "lateral move", "横移", "平移"]),
    ]

    def assess(self, image_path: str, intended_motion: str = "") -> Dict[str, Any]:
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")
        img = _imread_unicode(str(path))
        if img is None:
            raise ValueError(f"Unreadable image: {path}")

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        short_edge = min(w, h)

        # --- resolution ---
        if short_edge >= 1600:
            resolution = "PASS (high)"
        elif short_edge >= 1024:
            resolution = "PASS"
        elif short_edge >= 768:
            resolution = "MARGINAL"
        else:
            resolution = "FAIL (below 768px short edge)"

        # --- sharpness / detail ---
        lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        edges = cv2.Canny(gray, 80, 200)
        edge_density = float((edges > 0).mean() * 100)

        # --- straight-line / perspective evidence ---
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=120,
                                minLineLength=max(40, int(short_edge * 0.1)), maxLineGap=12)
        n_lines = 0
        diagonal = 0.0
        if lines is not None:
            arr = np.asarray(lines)
            if arr.ndim == 3:
                arr = arr[:, 0, :]
            n_lines = len(arr)
            if n_lines:
                angles = np.abs(np.degrees(np.arctan2(arr[:, 3] - arr[:, 1], arr[:, 2] - arr[:, 0])))
                diagonal = float((np.abs(np.abs(angles) - 90) >= 8).mean() * 100)

        # --- geometry score ---
        if n_lines >= 40 and lap >= 150:
            geometry = "HIGH"
        elif n_lines >= 12 and lap >= 60:
            geometry = "MEDIUM"
        else:
            geometry = "LOW"

        # --- motion risk (PATCH2.5-A extended contract) ---
        low_text = intended_motion.lower()
        risk_details = [name for name, pats in self._RISK_PATTERNS if any(p in low_text for p in pats)]
        large_motion_words = ("orbit", "arc", "360", "fast", "dolly", "drone")
        wants_large = any(k in low_text for k in large_motion_words)
        if risk_details:
            motion_risk = "HIGH"
        elif wants_large and geometry in ("MEDIUM", "LOW"):
            motion_risk = "HIGH"
        elif geometry == "LOW":
            motion_risk = "MEDIUM"
        else:
            motion_risk = "LOW"

        motion_risk_details = []
        for name, pats in self._RISK_PATTERNS:
            if name in risk_details:
                motion_risk_details.append({
                    "risk": name,
                    "matched_terms": [p for p in pats if p in low_text],
                    "recommended_alternative": self._risk_recommendation(name),
                })

        # --- recommended workflow (heuristic) ---
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        top_val = float(hsv[: max(20, int(h * 0.1))].mean(axis=(0, 1))[2])
        sky_fraction = float(np.mean(hsv[..., 2] > 200) * 100) if top_val > 150 else 0.0
        if intended_motion and any(k in intended_motion.lower() for k in ("walkthrough", "漫游")):
            recommended_workflow = "05_Slow_Walkthrough"
            prompt_recommendation = "slow_push (very small amplitude, slow speed)"
        elif intended_motion and any(k in intended_motion.lower() for k in ("aerial", "drone", "鸟瞰")):
            recommended_workflow = "04_Drone_Aerial"
            prompt_recommendation = "aerial_reveal (small amplitude, slow speed)"
        elif intended_motion and any(k in intended_motion.lower() for k in ("material", "detail", "材质")):
            recommended_workflow = "03_Material_Detail"
            prompt_recommendation = "static (micro motion)"
        elif intended_motion and any(k in intended_motion.lower() for k in ("night", "day", "lighting", "夜景")):
            recommended_workflow = "02_Day_Night_Transition"
            prompt_recommendation = "static (FL2VA; requires matched DAY+NIGHT pair)"
        else:
            recommended_workflow = "01_Exterior_Hero"
            prompt_recommendation = "slow_push (small amplitude, slow speed)"

        guidance = ""
        if motion_risk == "HIGH":
            guidance = ("This single image is unsuitable for large camera movement. "
                        "Recommend FL2VA / multiple keyframes / multiple rendered "
                        "viewpoints / segmented clip stitching instead of shortening "
                        "the prompt and proceeding.")
        elif resolution.startswith("FAIL") or resolution == "MARGINAL":
            guidance = "Low-resolution source; clarity may degrade after 1344x768 generation."

        return {
            "source": str(path),
            "reference_quality": {
                "resolution": resolution,
                "geometry": geometry,
                "motion_risk": motion_risk,
                "motion_risk_details": motion_risk_details,
                "metrics": {
                    "width": w,
                    "height": h,
                    "laplacian_var": round(lap, 1),
                    "edge_density_pct": round(edge_density, 2),
                    "straight_line_count": n_lines,
                    "diagonal_line_pct": round(diagonal, 1),
                },
            },
            "recommended_workflow": recommended_workflow,
            "prompt_recommendation": prompt_recommendation,
            "guidance": guidance,
        }

    @staticmethod
    def _risk_recommendation(risk: str) -> str:
        recommendations = {
            "large_orbit": "FL2VA or segmented arc clips; never orbit from one image",
            "aerial_180_360": "multiple rendered aerial viewpoints or FL2VA; no 180/360 from one image",
            "large_forward_travel": "first+last keyframes (FL2VA) or segmented clip stitching",
            "major_perspective_reconstruction": "provide multiple rendered viewpoints / reference frames",
            "interior_corner_turn": "separate clips per corridor segment; do not turn a corner from one image",
            "material_large_translation": "keep camera static/micro-motion for single-frame material detail",
        }
        return recommendations.get(risk, "multi-reference generation (FL2VA / keyframes / segments)")


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "samples/05_Slow_Walkthrough.png"
    print(json.dumps(ReferenceQualityAssistant().assess(path), indent=2, ensure_ascii=False))
