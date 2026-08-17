"""Reference image quality assistant for the Native H3 production chain.

Usage:
    from runtime.input_validator.reference_quality_assistant import ReferenceQualityAssistant
    report = ReferenceQualityAssistant().assess("path/to/render.png")
"""

from runtime.input_validator.reference_quality_assistant import ReferenceQualityAssistant

__all__ = ["ReferenceQualityAssistant"]
