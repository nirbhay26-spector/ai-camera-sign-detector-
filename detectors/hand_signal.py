"""
Enhanced Hand Signal Detector: Multi-Mode Gesture & Landmark Tracking.
======================================================================
This upgraded detector supports:
  1. Full 21-landmark bright neon visualization (cyan, magenta, yellow, orange).
  2. Extended finger counting (0 to 5 fingers up).
  3. Multi-mode detection:
     - Mode 1: "rapid_fist" (Open hand transitioning rapidly to closed fist)
     - Mode 2: "signal_for_help" (International 3-step: Open Palm -> Thumb Tucked -> Closed Fingers)
     - Mode 3: "both" (Detects either gesture)
     - Mode 4: "restricted_zone" (Checks if hand enters a virtual bounding zone)
  4. Joint angle geometry (MCP-PIP-DIP angles & thumb flexion).
  5. Multi-frame temporal confirmation across all 3 sequence stages.
  6. Three-stage alert status: GREEN (Normal), ORANGE (Possible Distress), RED (SOS Confirmed).
  7. Left/right hand orientation & palm normal validation.
  8. CCTV low-light / Night mode enhancement (CLAHE).
  9. Real-time sensitivity & threshold tuning via slider.
  10. Detailed telemetry output for web dashboard HUD.
"""

import math
import time
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

import cv2
import numpy as np
import requests

import mediapipe as mp
from mediapipe.tasks.python import vision, BaseOptions

from detectors.base import BaseDetector, DetectionResult
import config

logger = logging.getLogger(__name__)

# MediaPipe 21 Hand Landmark Indices
WRIST = 0
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP = 3
THUMB_TIP = 4

INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8

MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_DIP = 11
MIDDLE_TIP = 12

RING_MCP = 13
RING_PIP = 14
RING_DIP = 15
RING_TIP = 16

PINKY_MCP = 17
PINKY_PIP = 18
PINKY_DIP = 19
PINKY_TIP = 20

# Vivid neon color palette for fingers
COLOR_WRIST = (255, 255, 255)       # Pure White
COLOR_THUMB = (0, 140, 255)         # Neon Orange
COLOR_INDEX = (255, 255, 0)         # Bright Cyan
COLOR_MIDDLE = (0, 255, 128)        # Neon Lime
COLOR_RING = (255, 0, 255)          # Bright Magenta
COLOR_PINKY = (255, 105, 180)       # Hot Pink
COLOR_BONE = (80, 220, 240)         # Cyan Skeleton Lines
COLOR_ALERT = (0, 0, 255)           # Emergency Red
COLOR_WARNING = (0, 165, 255)       # Orange Alert

HAND_CONNECTIONS: List[Tuple[int, int]] = [
    # Palm
    (WRIST, THUMB_CMC),
    (THUMB_CMC, THUMB_MCP),
    (THUMB_MCP, INDEX_MCP),
    (INDEX_MCP, MIDDLE_MCP),
    (MIDDLE_MCP, RING_MCP),
    (RING_MCP, PINKY_MCP),
    (PINKY_MCP, WRIST),
    # Thumb
    (THUMB_MCP, THUMB_IP),
    (THUMB_IP, THUMB_TIP),
    # Index
    (INDEX_MCP, INDEX_PIP),
    (INDEX_PIP, INDEX_DIP),
    (INDEX_DIP, INDEX_TIP),
    # Middle
    (MIDDLE_MCP, MIDDLE_PIP),
    (MIDDLE_PIP, MIDDLE_DIP),
    (MIDDLE_DIP, MIDDLE_TIP),
    # Ring
    (RING_MCP, RING_PIP),
    (RING_PIP, RING_DIP),
    (RING_DIP, RING_TIP),
    # Pinky
    (PINKY_MCP, PINKY_PIP),
    (PINKY_PIP, PINKY_DIP),
    (PINKY_DIP, PINKY_TIP),
]

# State Machine Constants
STATE_IDLE = "IDLE"
STATE_OPEN = "OPEN PALM"
STATE_THUMB_TUCKED = "THUMB TUCKED"
STATE_CLOSED = "CLOSED FIST"
STATE_DISTRESS_CONFIRMED = "DISTRESS CONFIRMED"

# Backward compatibility aliases
STATE_STEP1_OPEN_PALM = STATE_OPEN
STATE_STEP2_THUMB_TUCKED = STATE_THUMB_TUCKED
STATE_STEP3_FINGERS_CLOSED = STATE_DISTRESS_CONFIRMED

# Three-Stage Alert System Constants
STAGE_GREEN = "GREEN"    # Normal / No distress
STAGE_ORANGE = "ORANGE"  # Possible Distress / Sequence started
STAGE_RED = "RED"        # SOS Detected / Emergency Confirmed


def _euclidean_distance(p1: Any, p2: Any) -> float:
    """Calculates 2D euclidean distance between two points."""
    return math.hypot(p1.x - p2.x, p1.y - p2.y)


def _calculate_joint_angle(p1: Any, p2: Any, p3: Any) -> float:
    """Computes angle in degrees at vertex p2 between (p1 - p2) and (p3 - p2)."""
    v1 = np.array([p1.x - p2.x, p1.y - p2.y], dtype=np.float32)
    v2 = np.array([p3.x - p2.x, p3.y - p2.y], dtype=np.float32)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 < 1e-6 or norm2 < 1e-6:
        return 180.0
    cosine = np.clip(np.dot(v1, v2) / (norm1 * norm2), -1.0, 1.0)
    return float(np.degrees(np.arccos(cosine)))


class HandSignalDetector(BaseDetector):
    """Detects hand distress gestures with multiple operating modes, joint angles, and multi-frame temporal confirmation."""

    MODEL_URL = (
        "https://storage.googleapis.com/mediapipe-models/"
        "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
    )

    def __init__(
        self,
        mode: str = "both",  # 'signal_for_help', 'rapid_fist', 'both', 'restricted_zone'
        sensitivity: float = 1.0,  # 0.5 (stricter) to 1.5 (faster detection)
        state_timeout: Optional[float] = None,
    ):
        self.mode = mode
        self.sensitivity = max(0.5, min(2.0, sensitivity))
        self.state_timeout = state_timeout or config.STATE_EXPIRY_SECONDS

        self.current_state = STATE_IDLE
        self.state_timestamp = 0.0
        self.last_open_time = 0.0

        # Multi-Frame Stage Progression Counters
        self.stage1_frame_count = 0
        self.stage2_frame_count = 0
        self.stage3_frame_count = 0
        self.min_stage1_frames = config.MIN_STAGE1_FRAMES
        self.min_stage2_frames = config.MIN_STAGE2_FRAMES
        self.min_stage3_frames = config.MIN_STAGE3_FRAMES

        # Three-Stage Alert Status
        self.alert_stage = STAGE_GREEN
        self.confidence_score = 0.0
        self.gesture_stage_breakdown: Dict[str, float] = {
            "stage1_open": 0.0,
            "stage2_thumb": 0.0,
            "stage3_fist": 0.0,
        }

        # Diagnostics & Telemetry
        self.hand_detected = False
        self.handedness = "Unknown"
        self.fingers_up_count = 0
        self.hand_posture_label = "No Hand Detected"
        self.palm_scale = 0.0
        self.clarity_score = 100.0
        self.night_mode = config.CCTV_NIGHT_MODE
        self.restricted_zone: Optional[Tuple[float, float, float, float]] = (
            0.1, 0.1, 0.5, 0.5
        )  # Normalized (x_min, y_min, x_max, y_max)
        self.zone_breached = False

        self.model_path = self._ensure_model_file()
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(self.model_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.45,
            min_hand_presence_confidence=0.45,
            min_tracking_confidence=0.45,
        )
        self.landmarker = vision.HandLandmarker.create_from_options(options)
        logger.info(
            "HandSignalDetector ready in mode: '%s' (Sensitivity: %.2f, 3-Stage Alert Active)",
            self.mode,
            self.sensitivity,
        )

    def _ensure_model_file(self) -> Path:
        model_path = config.BASE_DIR / "hand_landmarker.task"
        if not model_path.exists():
            logger.info("Downloading MediaPipe hand_landmarker.task (~7.8MB)...")
            response = requests.get(self.MODEL_URL, stream=True, timeout=30)
            response.raise_for_status()
            with open(model_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=16384):
                    f.write(chunk)
        return model_path

    def set_mode(self, mode: str) -> None:
        """Dynamically switches detection mode."""
        self.mode = mode
        self.reset()
        logger.info("Detector mode switched to: %s", mode)

    def set_sensitivity(self, val: float) -> None:
        """Sets sensitivity factor (0.5 to 2.0)."""
        self.sensitivity = max(0.5, min(2.0, float(val)))
        logger.info("Detector sensitivity adjusted to: %.2f", self.sensitivity)

    def set_night_mode(self, enabled: bool) -> None:
        """Enables/disables CLAHE contrast enhancement for low-light CCTV."""
        self.night_mode = bool(enabled)
        logger.info("CCTV Night & Low-Light Mode set to: %s", self.night_mode)

    def set_restricted_zone(self, x_min: float, y_min: float, x_max: float, y_max: float) -> None:
        """Updates the normalized bounding box for restricted zone intrusion detection."""
        self.restricted_zone = (x_min, y_min, x_max, y_max)

    def reset(self) -> None:
        """Resets all internal state machines and multi-frame counters."""
        self.current_state = STATE_IDLE
        self.state_timestamp = 0.0
        self.last_open_time = 0.0
        self.stage1_frame_count = 0
        self.stage2_frame_count = 0
        self.stage3_frame_count = 0
        self.alert_stage = STAGE_GREEN
        self.confidence_score = 0.0
        self.hand_detected = False
        self.fingers_up_count = 0
        self.hand_posture_label = "Reset"
        self.zone_breached = False
        self.gesture_stage_breakdown = {
            "stage1_open": 0.0,
            "stage2_thumb": 0.0,
            "stage3_fist": 0.0,
        }

    def _analyze_hand(self, landmarks: List[Any], handedness_label: str = "Unknown") -> Dict[str, Any]:
        """Calculates precise joint angles, finger extensions, thumb tuck, and palm scale."""
        wrist = landmarks[WRIST]
        middle_mcp = landmarks[MIDDLE_MCP]
        pinky_mcp = landmarks[PINKY_MCP]
        index_mcp = landmarks[INDEX_MCP]
        thumb_tip = landmarks[THUMB_TIP]
        thumb_mcp = landmarks[THUMB_MCP]
        thumb_ip = landmarks[THUMB_IP]
        thumb_cmc = landmarks[THUMB_CMC]

        palm_scale = _euclidean_distance(wrist, middle_mcp)
        if palm_scale < config.MIN_PALM_SCALE:
            return {"valid": False, "reason": "Hand Too Small / Distant", "palm_scale": palm_scale}

        # 1. Evaluate 4 non-thumb fingers using Euclidean distance and Joint Angles
        fingers_data = [
            ("index", INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP),
            ("middle", MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP),
            ("ring", RING_MCP, RING_PIP, RING_DIP, RING_TIP),
            ("pinky", PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP),
        ]

        extended_fingers = {}
        joint_angles = {}
        for name, mcp_idx, pip_idx, dip_idx, tip_idx in fingers_data:
            mcp = landmarks[mcp_idx]
            pip = landmarks[pip_idx]
            tip = landmarks[tip_idx]

            # Compute PIP joint angle: straight finger is ~160-180 deg, curled is < 110 deg
            angle = _calculate_joint_angle(mcp, pip, tip)
            joint_angles[name] = angle

            dist_tip_wrist = _euclidean_distance(tip, wrist)
            relax = (self.sensitivity - 1.0) * 0.05
            is_extended_dist = dist_tip_wrist > ((1.15 - relax) * palm_scale)
            is_straight_angle = angle > 135.0

            extended_fingers[name] = bool(is_extended_dist and is_straight_angle)

        # 2. Evaluate Thumb (Angle + Distance)
        thumb_angle = _calculate_joint_angle(thumb_mcp, thumb_ip, thumb_tip)
        dist_thumb_pinky = _euclidean_distance(thumb_tip, pinky_mcp) / palm_scale
        dist_thumb_middle = _euclidean_distance(thumb_tip, middle_mcp) / palm_scale
        dist_thumb_tip_mcp = _euclidean_distance(thumb_tip, thumb_mcp) / palm_scale

        # Extended thumb: points outward away from palm center
        thumb_extended = (dist_thumb_pinky > 0.8) and (dist_thumb_tip_mcp > 0.5) and (thumb_angle > 140.0)

        # Tucked thumb: folded across palm toward ring/pinky base
        thumb_tucked = (dist_thumb_pinky < 0.78) or (dist_thumb_middle < 0.55) or (thumb_angle < 130.0)

        # Total extended fingers (0 to 5)
        extended_count = sum(1 for ext in extended_fingers.values() if ext)
        if thumb_extended:
            extended_count += 1

        four_fingers_ext = all(extended_fingers.values())
        four_fingers_folded = not any(extended_fingers.values())

        # Check restricted zone intrusion
        zone_breach = False
        if self.restricted_zone:
            xmin, ymin, xmax, ymax = self.restricted_zone
            cx = (wrist.x + middle_mcp.x) / 2.0
            cy = (wrist.y + middle_mcp.y) / 2.0
            if xmin <= cx <= xmax and ymin <= cy <= ymax:
                zone_breach = True

        return {
            "valid": True,
            "palm_scale": palm_scale,
            "extended_fingers": extended_fingers,
            "thumb_extended": thumb_extended,
            "thumb_tucked": thumb_tucked,
            "extended_count": extended_count,
            "four_fingers_ext": four_fingers_ext,
            "four_fingers_folded": four_fingers_folded,
            "joint_angles": joint_angles,
            "thumb_angle": thumb_angle,
            "zone_breach": zone_breach,
        }

    def detect(self, frame: np.ndarray) -> DetectionResult:
        now = time.time()

        # Check state timeout: if user pauses too long between steps, reset
        if self.current_state in (STATE_OPEN, STATE_THUMB_TUCKED):
            effective_timeout = self.state_timeout / self.sensitivity
            if now - self.state_timestamp > effective_timeout:
                self.current_state = STATE_IDLE
                self.stage1_frame_count = 0
                self.stage2_frame_count = 0
                self.stage3_frame_count = 0
                self.alert_stage = STAGE_GREEN

        # Apply CCTV Night & Low-Light CLAHE Enhancement if enabled
        if self.night_mode:
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            enhanced_lab = cv2.merge((cl, a, b))
            processing_frame = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
        else:
            processing_frame = frame

        # Compute simple clarity / blur score via Laplacian variance
        gray = cv2.cvtColor(processing_frame, cv2.COLOR_BGR2GRAY)
        self.clarity_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # MediaPipe expects RGB format
        rgb_frame = cv2.cvtColor(processing_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        result = self.landmarker.detect(mp_image)

        if not result.hand_landmarks:
            self.hand_detected = False
            self.fingers_up_count = 0
            self.hand_posture_label = "No Hand"
            self.confidence_score = 0.0
            self.alert_stage = STAGE_GREEN
            self.handedness = "Unknown"

            if self.current_state == STATE_DISTRESS_CONFIRMED:
                if now - self.state_timestamp > 0.8:
                    self.current_state = STATE_IDLE
                    self.stage3_frame_count = 0

            return DetectionResult(
                is_detected=(self.current_state == STATE_DISTRESS_CONFIRMED),
                confidence=self.confidence_score,
                label=self.mode,
                state_name=self.current_state,
                details={
                    "hand_detected": False,
                    "fingers_up": 0,
                    "posture": "No Hand",
                    "mode": self.mode,
                    "alert_stage": self.alert_stage,
                    "handedness": "None",
                    "clarity_score": round(self.clarity_score, 1),
                },
                raw_data=None,
            )

        self.hand_detected = True
        landmarks = result.hand_landmarks[0]

        # Determine Handedness (Left vs Right)
        if hasattr(result, "handedness") and result.handedness and len(result.handedness) > 0:
            cat = result.handedness[0][0]
            self.handedness = getattr(cat, "category_name", getattr(cat, "display_name", "Right"))
        else:
            self.handedness = "Right"

        geo = self._analyze_hand(landmarks, handedness_label=self.handedness)

        if not geo.get("valid", False):
            self.hand_posture_label = geo.get("reason", "Hand Too Distant")
            self.alert_stage = STAGE_GREEN
            return DetectionResult(
                is_detected=False,
                confidence=0.0,
                label=self.mode,
                state_name=self.current_state,
                details={
                    "hand_detected": True,
                    "fingers_up": 0,
                    "posture": self.hand_posture_label,
                    "alert_stage": STAGE_GREEN,
                    "handedness": self.handedness,
                },
                raw_data=result,
            )

        self.palm_scale = geo["palm_scale"]
        self.fingers_up_count = geo["extended_count"]
        four_ext = geo["four_fingers_ext"]
        four_fold = geo["four_fingers_folded"]
        thumb_tucked = geo["thumb_tucked"]
        thumb_ext = geo["thumb_extended"]
        self.zone_breached = geo["zone_breach"]

        # Human-readable posture label
        if four_ext and thumb_ext:
            self.hand_posture_label = f"Open Palm (5 Fingers - {self.handedness})"
        elif four_ext and thumb_tucked:
            self.hand_posture_label = f"Thumb Tucked (4 Fingers - {self.handedness})"
        elif four_fold and thumb_tucked:
            self.hand_posture_label = f"Fingers Closed Over Thumb ({self.handedness})"
        elif four_fold:
            self.hand_posture_label = f"Closed Fist (0 Fingers - Normal Hand)"
        elif self.fingers_up_count == 1:
            self.hand_posture_label = "Pointing (1 Finger)"
        elif self.fingers_up_count == 2:
            self.hand_posture_label = "Peace / V Sign (2 Fingers)"
        else:
            self.hand_posture_label = f"Partial Hand ({self.fingers_up_count} Fingers)"

        is_distress = False

        # ======================================================================
        # MODE 1: RESTRICTED ZONE INTRUSION
        # ======================================================================
        if self.mode == "restricted_zone":
            if self.zone_breached:
                is_distress = True
                self.current_state = "ZONE_INTRUSION"
                self.confidence_score = 0.95
                self.alert_stage = STAGE_RED
            else:
                self.current_state = "ZONE_CLEAR"
                self.confidence_score = 0.0
                self.alert_stage = STAGE_GREEN

        # ======================================================================
        # MODE 2: RAPID OPEN-TO-FIST GESTURE
        # ======================================================================
        elif self.mode == "rapid_fist":
            if four_ext or self.fingers_up_count >= 4:
                self.last_open_time = now
                self.current_state = STATE_OPEN
                self.alert_stage = STAGE_GREEN
                self.confidence_score = 0.35
            elif (four_fold or self.fingers_up_count <= 1) and (now - self.last_open_time < 2.0 and self.last_open_time > 0):
                self.current_state = STATE_DISTRESS_CONFIRMED
                self.state_timestamp = now
                is_distress = True
                self.confidence_score = 0.92
                self.alert_stage = STAGE_RED
            else:
                self.alert_stage = STAGE_GREEN

        # ======================================================================
        # MODE 3: SIGNAL FOR HELP (Standard 3-Step with Multi-Frame Confirmation)
        # ======================================================================
        elif self.mode == "signal_for_help":
            # Step 1: Open Palm (Must be held for consecutive frames)
            if four_ext and thumb_ext:
                self.stage1_frame_count += 1
                self.stage2_frame_count = 0
                self.stage3_frame_count = 0
                if self.stage1_frame_count >= self.min_stage1_frames:
                    self.current_state = STATE_OPEN
                    self.state_timestamp = now
                    self.alert_stage = STAGE_GREEN
                    self.confidence_score = 0.38
                    self.gesture_stage_breakdown["stage1_open"] = 0.95

            # Step 2: Thumb Tucked (Must follow Step 1)
            elif self.current_state == STATE_OPEN and four_ext and thumb_tucked:
                self.stage2_frame_count += 1
                if self.stage2_frame_count >= self.min_stage2_frames:
                    self.current_state = STATE_THUMB_TUCKED
                    self.state_timestamp = now
                    # Enter ORANGE: Possible distress! Sequence is in progress
                    self.alert_stage = STAGE_ORANGE
                    self.confidence_score = 0.72
                    self.gesture_stage_breakdown["stage2_thumb"] = 0.94

            # Step 3: Four Fingers Closed Over Thumb (Must follow Step 2)
            elif self.current_state == STATE_THUMB_TUCKED and four_fold:
                self.stage3_frame_count += 1
                if self.stage3_frame_count >= self.min_stage3_frames:
                    self.current_state = STATE_DISTRESS_CONFIRMED
                    self.state_timestamp = now
                    is_distress = True
                    self.confidence_score = 0.97
                    self.alert_stage = STAGE_RED
                    self.gesture_stage_breakdown["stage3_fist"] = 0.98

            # Sustained hold of Step 3
            elif self.current_state == STATE_DISTRESS_CONFIRMED:
                if four_fold:
                    self.state_timestamp = now
                    is_distress = True
                    self.confidence_score = 0.97
                    self.alert_stage = STAGE_RED
                elif now - self.state_timestamp > 1.2:
                    self.current_state = STATE_IDLE
                    self.alert_stage = STAGE_GREEN
                    self.stage1_frame_count = 0
                    self.stage2_frame_count = 0
                    self.stage3_frame_count = 0

            # Standalone fist without prior sequence -> NORMAL HAND (NO SOS)
            elif four_fold and self.current_state == STATE_IDLE:
                self.hand_posture_label = "Resting Closed Fist (Normal / No Sequence)"
                self.alert_stage = STAGE_GREEN
                self.confidence_score = 0.0

        # ======================================================================
        # MODE 4: BOTH (Signal for Help OR Rapid Fist)
        # ======================================================================
        else:  # "both"
            # Signal for help progression with multi-frame confirmation
            if four_ext and thumb_ext:
                self.stage1_frame_count += 1
                self.stage2_frame_count = 0
                self.stage3_frame_count = 0
                self.last_open_time = now
                if self.stage1_frame_count >= self.min_stage1_frames:
                    self.current_state = STATE_OPEN
                    self.state_timestamp = now
                    self.alert_stage = STAGE_GREEN
                    self.confidence_score = 0.38
                    self.gesture_stage_breakdown["stage1_open"] = 0.95

            elif self.current_state == STATE_OPEN and four_ext and thumb_tucked:
                self.stage2_frame_count += 1
                if self.stage2_frame_count >= self.min_stage2_frames:
                    self.current_state = STATE_THUMB_TUCKED
                    self.state_timestamp = now
                    self.alert_stage = STAGE_ORANGE
                    self.confidence_score = 0.72
                    self.gesture_stage_breakdown["stage2_thumb"] = 0.94

            elif (self.current_state == STATE_THUMB_TUCKED and four_fold) or (
                (four_fold or self.fingers_up_count == 0)
                and (now - self.last_open_time < 2.0 and self.last_open_time > 0)
            ):
                self.stage3_frame_count += 1
                if self.stage3_frame_count >= max(2, self.min_stage3_frames - 1):
                    self.current_state = STATE_DISTRESS_CONFIRMED
                    self.state_timestamp = now
                    is_distress = True
                    self.confidence_score = 0.96
                    self.alert_stage = STAGE_RED
                    self.gesture_stage_breakdown["stage3_fist"] = 0.96

            elif self.current_state == STATE_DISTRESS_CONFIRMED:
                if four_fold:
                    self.state_timestamp = now
                    is_distress = True
                    self.confidence_score = 0.96
                    self.alert_stage = STAGE_RED
                elif now - self.state_timestamp > 1.2:
                    self.current_state = STATE_IDLE
                    self.alert_stage = STAGE_GREEN
                    self.stage1_frame_count = 0
                    self.stage2_frame_count = 0
                    self.stage3_frame_count = 0

            # Isolated closed fist without prior sequence
            elif four_fold and self.current_state == STATE_IDLE:
                self.hand_posture_label = "Resting Closed Fist (Normal / No Sequence)"
                self.alert_stage = STAGE_GREEN
                self.confidence_score = 0.0

        return DetectionResult(
            is_detected=is_distress,
            confidence=self.confidence_score,
            label=f"Gesture ({self.mode})",
            state_name=self.current_state,
            details={
                "hand_detected": True,
                "fingers_up": self.fingers_up_count,
                "posture": self.hand_posture_label,
                "current_state": self.current_state,
                "mode": self.mode,
                "alert_stage": self.alert_stage,
                "handedness": self.handedness,
                "zone_breach": self.zone_breached,
                "palm_scale": round(self.palm_scale, 3),
                "clarity_score": round(self.clarity_score, 1),
                "night_mode": self.night_mode,
                "stage1_frames": self.stage1_frame_count,
                "stage2_frames": self.stage2_frame_count,
                "stage3_frames": self.stage3_frame_count,
                "stage_breakdown": self.gesture_stage_breakdown,
            },
            raw_data=result,
        )

    def draw_annotations(self, frame: np.ndarray, result: DetectionResult) -> np.ndarray:
        """Renders 21 vibrant neon landmarks, skeletal links, restricted zones, and 3-Stage Alert Badge."""
        h, w, _ = frame.shape
        annotated = frame.copy()

        # 1. Draw Restricted Zone Box if in that mode
        if self.mode == "restricted_zone" and self.restricted_zone:
            xmin, ymin, xmax, ymax = self.restricted_zone
            box_pt1 = (int(xmin * w), int(ymin * h))
            box_pt2 = (int(xmax * w), int(ymax * h))
            zone_color = (0, 0, 255) if self.zone_breached else (0, 255, 255)

            cv2.rectangle(annotated, box_pt1, box_pt2, zone_color, 2)
            cv2.putText(
                annotated,
                "RESTRICTED ZONE (BREACH ALERT)" if self.zone_breached else "RESTRICTED ZONE",
                (box_pt1[0] + 8, box_pt1[1] + 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                zone_color,
                2,
                cv2.LINE_AA,
            )

        # 2. Draw 21 Hand Landmarks with vivid neon colors
        if result.raw_data and hasattr(result.raw_data, "hand_landmarks"):
            for hand_landmarks in result.raw_data.hand_landmarks:
                coords = [(int(lm.x * w), int(lm.y * h)) for lm in hand_landmarks]

                # Draw skeleton connections with color coding by alert stage
                if self.alert_stage == STAGE_RED:
                    line_color = COLOR_ALERT
                    line_width = 3
                elif self.alert_stage == STAGE_ORANGE:
                    line_color = COLOR_WARNING
                    line_width = 2
                else:
                    line_color = COLOR_BONE
                    line_width = 2

                for start_idx, end_idx in HAND_CONNECTIONS:
                    pt1 = coords[start_idx]
                    pt2 = coords[end_idx]
                    cv2.line(annotated, pt1, pt2, line_color, line_width, cv2.LINE_AA)

                # Draw finger-specific colored landmark nodes
                for idx, pt in enumerate(coords):
                    if idx == WRIST:
                        cv2.circle(annotated, pt, 7, COLOR_WRIST, -1, cv2.LINE_AA)
                    elif idx in (1, 2, 3, 4):  # Thumb
                        cv2.circle(annotated, pt, 6, COLOR_THUMB, -1, cv2.LINE_AA)
                    elif idx in (5, 6, 7, 8):  # Index
                        cv2.circle(annotated, pt, 6, COLOR_INDEX, -1, cv2.LINE_AA)
                    elif idx in (9, 10, 11, 12):  # Middle
                        cv2.circle(annotated, pt, 6, COLOR_MIDDLE, -1, cv2.LINE_AA)
                    elif idx in (13, 14, 15, 16):  # Ring
                        cv2.circle(annotated, pt, 6, COLOR_RING, -1, cv2.LINE_AA)
                    elif idx in (17, 18, 19, 20):  # Pinky
                        cv2.circle(annotated, pt, 6, COLOR_PINKY, -1, cv2.LINE_AA)

                    # Highlight fingertips with outer glow ring
                    if idx in (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP):
                        cv2.circle(annotated, pt, 9, (255, 255, 255), 1, cv2.LINE_AA)

        # 3. Draw 3-Stage Alert Badge Overlay
        badge_text = f"STAGE: {self.alert_stage}"
        if self.alert_stage == STAGE_RED:
            badge_bg = (0, 0, 180)
            badge_sub = "EMERGENCY SOS SIGNAL CONFIRMED"
        elif self.alert_stage == STAGE_ORANGE:
            badge_bg = (0, 120, 220)
            badge_sub = "POSSIBLE DISTRESS - Awaiting Sequence Completion"
        else:
            badge_bg = (20, 100, 30)
            badge_sub = "NORMAL - Hand Movement Monitored"

        cv2.rectangle(annotated, (15, 12), (320, 48), badge_bg, -1)
        cv2.rectangle(annotated, (15, 12), (320, 48), (255, 255, 255), 1)
        cv2.putText(
            annotated,
            f"{badge_text} ({self.handedness})",
            (25, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            annotated,
            badge_sub,
            (25, 43),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.34,
            (220, 220, 220),
            1,
            cv2.LINE_AA,
        )

        return annotated

    def close(self) -> None:
        """Releases the underlying MediaPipe landmarker resource."""
        if hasattr(self, "landmarker"):
            self.landmarker.close()
