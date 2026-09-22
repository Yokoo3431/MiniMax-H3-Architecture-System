"""Prompt contract for the isolated Advanced A2 experiment.

A2 intentionally changes only the semantic conditioning text.  The native
15-node/18-link graph and inherited generation controls remain explicit in the
workflow assets and acceptance adapter.
"""

from __future__ import annotations


A2_CAMERA_MOTION_BLOCK = (
    "A controlled slow forward aerial push along a shallow oblique path. "
    "Travel continuously at a steady speed with smooth acceleration and "
    "deceleration. Show clear but restrained parallax across the building, "
    "shoreline, and trees. Keep the horizon stable and the architecture as "
    "the primary subject."
)

A2_ARCHITECTURE_PRESERVATION_BLOCK = (
    "Preserve the building's original massing, roof silhouette, façade "
    "proportions, openings, structural edges, and material boundaries "
    "throughout. Maintain the reference identity and site relationship, "
    "including concrete texture, glass reflections, landscape, shoreline, "
    "and horizon."
)

A2_MINIMAL_NEGATIVE_BLOCK = (
    "No structural morphing, no spontaneous architectural additions, "
    "no disappearing major building elements."
)

A2_OVERALL_SOUNDSCAPE = (
    "Gentle ambient environment sound consistent with the architectural site, "
    "subtle wind, and restrained spatial room tone; no dialogue."
)

A2_NON_DIEGETIC_MUSIC = (
    "Minimal ambient cinematic score, slow tempo, warm and restrained, "
    "fading in softly."
)


def build_a2_prompt() -> str:
    """Build the public, deterministic A2 prompt profile."""
    return (
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        "integrated_multimodal_description: [Shot 1] "
        f"CAMERA MOTION BLOCK: {A2_CAMERA_MOTION_BLOCK}\n\n"
        f"ARCHITECTURE PRESERVATION BLOCK: {A2_ARCHITECTURE_PRESERVATION_BLOCK}\n\n"
        f"MINIMAL NEGATIVE CONSTRAINT BLOCK: {A2_MINIMAL_NEGATIVE_BLOCK}\n\n"
        f"overall_soundscape: {A2_OVERALL_SOUNDSCAPE}\n\n"
        f"non_diegetic_music: {A2_NON_DIEGETIC_MUSIC}"
    )


__all__ = [
    "A2_ARCHITECTURE_PRESERVATION_BLOCK",
    "A2_CAMERA_MOTION_BLOCK",
    "A2_MINIMAL_NEGATIVE_BLOCK",
    "A2_NON_DIEGETIC_MUSIC",
    "A2_OVERALL_SOUNDSCAPE",
    "build_a2_prompt",
]
