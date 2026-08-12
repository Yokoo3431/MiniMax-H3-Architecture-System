"""VRAM Optimizer Engine (V0.7.5).
Configures H3_LOW (8GB), H3_STANDARD (12GB), and H3_PRO (24GB+) profiles.
"""

from runtime.acceleration.acceleration_schema import AccelerationProfile

class VRAMOptimizer:
    """Optimizes VRAM profiles based on hardware target and GPU memory constraints."""

    def get_profile(self, profile_key: str = "H3_STANDARD") -> AccelerationProfile:
        key = profile_key.upper() if profile_key else "H3_STANDARD"

        if key == "H3_LOW":
            return AccelerationProfile(
                profile_key="H3_LOW",
                resolution="1024x576",
                width=1024,
                height=576,
                frames=48,
                duration_seconds=4.0,
                sampler="dual_sigma",
                steps=20,
                offload=True,
                batch_size=1
            )
        elif key == "H3_PRO":
            return AccelerationProfile(
                profile_key="H3_PRO",
                resolution="1280x720",
                width=1280,
                height=720,
                frames=96,
                duration_seconds=8.0,
                sampler="dual_sigma",
                steps=35,
                offload=False,
                batch_size=1
            )
        else: # H3_STANDARD
            return AccelerationProfile(
                profile_key="H3_STANDARD",
                resolution="1280x720",
                width=1280,
                height=720,
                frames=48,
                duration_seconds=5.0,
                sampler="dual_sigma",
                steps=25,
                offload=True,
                batch_size=1
            )
