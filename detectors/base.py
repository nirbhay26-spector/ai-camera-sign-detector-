"""
Base Detector Interface.
========================
This module defines the abstract contract that EVERY detector in the system
must implement.

For beginners:
- An Abstract Base Class (ABC) is like a blueprint or a contract.
- Any new detector you create in the future (e.g., YOLOv8 person detector,
  falling person detector, violence detection) just needs to inherit from
  `BaseDetector` and implement `detect()` and `draw_annotations()`.
- Because all detectors share the same interface, `main.py` does not need
  to know the internal details of any specific detector!
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import numpy as np


@dataclass
class DetectionResult:
    """Standardized result returned by any detector on each frame.

    Attributes:
        is_detected: True if the target event/signal is actively triggered.
        confidence: Detection confidence between 0.0 and 1.0.
        label: Human-readable name of the detection (e.g., 'Signal for Help').
        state_name: Current state of any internal state machine
                    (e.g., 'IDLE', 'STEP 1: PALM OPEN', 'STEP 2: THUMB TUCKED').
        details: Extra diagnostic information (e.g., which fingers are curled).
        raw_data: Low-level detector payload (e.g., MediaPipe landmark objects).
    """

    is_detected: bool = False
    confidence: float = 0.0
    label: str = "None"
    state_name: str = "IDLE"
    details: Dict[str, Any] = field(default_factory=dict)
    raw_data: Optional[Any] = None


class BaseDetector(ABC):
    """Abstract base class for all computer vision detectors."""

    @abstractmethod
    def detect(self, frame: np.ndarray) -> DetectionResult:
        """Processes a single BGR image frame from the camera.

        Args:
            frame: A NumPy array containing the BGR image from OpenCV.

        Returns:
            A DetectionResult object with detection status and diagnostics.
        """
        pass

    @abstractmethod
    def draw_annotations(
        self, frame: np.ndarray, result: DetectionResult
    ) -> np.ndarray:
        """Draws visual feedback (landmarks, boxes, status badges) onto the frame.

        Args:
            frame: The BGR image frame to annotate.
            result: The DetectionResult produced by this detector for this frame.

        Returns:
            The annotated BGR image frame.
        """
        pass

    def reset(self) -> None:
        """Resets any internal temporal state machine (optional override)."""
        pass

    def close(self) -> None:
        """Releases heavy model resources or background threads (optional override)."""
        pass
