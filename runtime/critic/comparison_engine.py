"""Comparison Engine (V0.7.7).
Compares Generation 1 vs Generation 2 evaluation scores across 5 dimensions and calculates score deltas.
"""

from typing import Dict, Any

class ComparisonEngine:
    """Evaluates initial vs revised score deltas and improvement status."""

    def compare_generations(
        self,
        initial_score_data: Dict[str, Any],
        final_score_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        init_overall = float(initial_score_data.get("overall_score", 80.0))
        final_overall = float(final_score_data.get("overall_score", 85.0))

        delta = round(final_overall - init_overall, 1)
        delta_str = f"+{delta}" if delta >= 0 else str(delta)

        status_val = "improved" if delta > 0 else ("unchanged" if delta == 0 else "regressed")

        # Compare dimensions
        init_dims = initial_score_data.get("dimensions", {})
        final_dims = final_score_data.get("dimensions", {})
        dimension_deltas = {}
        for dim_k, dim_v in final_dims.items():
            init_v = init_dims.get(dim_k, init_overall)
            d_val = round(dim_v - init_v, 1)
            dimension_deltas[dim_k] = f"+{d_val}" if d_val >= 0 else str(d_val)

        return {
            "before": init_overall,
            "after": final_overall,
            "delta": delta_str,
            "status": status_val,
            "dimension_deltas": dimension_deltas
        }
