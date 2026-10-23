"""
Decision Engine: False Alarm Reduction & Cooldown Logic.
========================================================
This module filters instantaneous detections to prevent false alarms.

For first-year CSE students:
----------------------------
Computer vision detections are noisy. A hand waving quickly or an accidental
fist might match a gesture for a fraction of a second (e.g., 0.2 seconds).
If we sent an SMS immediately, you would get dozens of false alarms every day!

To solve this:
  1. Time-Based Confirmation (Debounce):
     The gesture must be held CONTINUOUSLY for `confirmation_seconds`
     (e.g., 2.5 seconds). If the person stops the gesture before 2.5s,
     the timer immediately cancels.
  2. Cooldown Window:
     Once an emergency alert triggers, the system enters a cooldown
     (e.g., 60 seconds). During this time, the camera continues monitoring
     and logging, but will NOT flood the owner's phone with duplicate SMS alerts.
"""

import time
import logging
from dataclasses import dataclass
from typing import Tuple

# pyrefly: ignore[missing-import]
import cv2
# pyrefly: ignore[missing-import]
import numpy as np

import config

logger = logging.getLogger(__name__)


@dataclass
class DecisionState:
    """Represents the current state of the confirmation and cooldown timers."""

    should_trigger_alert: bool
    is_confirmed: bool
    is_in_cooldown: bool
    confirmation_progress: float  # 0.0 to 1.0
    seconds_detected: float
    cooldown_remaining: float
    status_message: str
    alert_stage: str = "GREEN"  # 'GREEN', 'ORANGE', 'RED'
    candidate_sos: bool = False
    multi_frame_count: int = 0


class DecisionEngine:
    """Manages continuous confirmation timing and alert cooldowns."""

    def __init__(
        self,
        confirmation_seconds: float = config.CONFIRMATION_SECONDS,
        cooldown_seconds: float = config.COOLDOWN_SECONDS,
        sensitivity: float = 1.0,
    ):
        self.confirmation_seconds = confirmation_seconds
        self.cooldown_seconds = cooldown_seconds
        self.sensitivity = max(0.5, min(2.0, sensitivity))

        # Internal timing state
        self.detection_start_time = 0.0
        self.is_currently_detecting = False
        self.cooldown_start_time = 0.0
        self.alert_dispatched_for_current_event = False
        self.multi_frame_count = 0

    def set_sensitivity(self, sensitivity: float) -> None:
        """Sets sensitivity factor (0.5 to 2.0). Higher sensitivity triggers faster."""
        self.sensitivity = max(0.5, min(2.0, float(sensitivity)))

    def set_confirmation_seconds(self, seconds: float) -> None:
        """Sets baseline confirmation duration."""
        self.confirmation_seconds = max(0.5, float(seconds))

    def set_cooldown_seconds(self, seconds: float) -> None:
        """Sets alert cooldown duration."""
        self.cooldown_seconds = max(5.0, float(seconds))

    def update(
        self,
        is_detected: bool,
        alert_stage: str = "GREEN",
        confidence: float = 0.0,
    ) -> DecisionState:
        """Updates internal timers based on whether the signal is seen this frame.

        Args:
            is_detected: True if the detector identified the distress gesture.
            alert_stage: Three-stage status ('GREEN', 'ORANGE', 'RED').
            confidence: Current detection confidence score.

        Returns:
            DecisionState with flags indicating if an alert should trigger.
        """
        now = time.time()

        # Check if we are currently in cooldown
        time_since_last_alert = now - self.cooldown_start_time
        in_cooldown = time_since_last_alert < self.cooldown_seconds
        cooldown_remaining = max(0.0, self.cooldown_seconds - time_since_last_alert) if in_cooldown else 0.0

        should_trigger = False
        is_confirmed = False
        progress = 0.0
        seconds_detected = 0.0
        candidate_sos = False

        effective_stage = alert_stage if alert_stage in ("GREEN", "ORANGE", "RED") else ("RED" if is_detected else "GREEN")

        # Active distress detection condition
        is_signal_active = is_detected or (effective_stage == "RED")

        if is_signal_active:
            self.multi_frame_count += 1
            if not self.is_currently_detecting:
                # Gesture just started appearing
                self.is_currently_detecting = True
                self.detection_start_time = now
                logger.info("Distress gesture seen! Beginning confirmation timer (Stage: %s)...", effective_stage)

            effective_confirm = max(0.05, self.confirmation_seconds / self.sensitivity)
            seconds_detected = now - self.detection_start_time
            progress = min(1.0, seconds_detected / effective_confirm)

            if seconds_detected >= effective_confirm:
                is_confirmed = True
                candidate_sos = True

                # Check if we can trigger an alert (only if NOT in cooldown and not already triggered)
                if not in_cooldown and not self.alert_dispatched_for_current_event:
                    should_trigger = True
                    self.cooldown_start_time = now
                    self.alert_dispatched_for_current_event = True
                    in_cooldown = True
                    cooldown_remaining = self.cooldown_seconds
                    logger.warning(
                        "DISTRESS CONFIRMED for %.2fs! Triggering emergency alert!",
                        seconds_detected,
                    )
        else:
            # Gesture was interrupted or dropped
            if self.is_currently_detecting:
                logger.debug(
                    "Gesture stopped before confirmation (held for %.2fs). Resetting timer.",
                    now - self.detection_start_time,
                )
            self.is_currently_detecting = False
            self.detection_start_time = 0.0
            self.alert_dispatched_for_current_event = False
            self.multi_frame_count = 0
            progress = 0.0
            seconds_detected = 0.0

        # Construct status message for HUD
        if should_trigger:
            status_message = "EMERGENCY ALERT TRIGGERED!"
        elif in_cooldown:
            if is_signal_active:
                status_message = f"DISTRESS (COOLDOWN: {int(cooldown_remaining)}s left)"
            else:
                status_message = f"STANDBY (Cooldown: {int(cooldown_remaining)}s left)"
        elif is_signal_active:
            status_message = (
                f"CONFIRMING DISTRESS: {seconds_detected:.1f}s / {self.confirmation_seconds:.1f}s"
            )
        elif effective_stage == "ORANGE":
            status_message = "ORANGE: POSSIBLE DISTRESS (Thumb Tucked - Awaiting Close)"
        else:
            status_message = "MONITORING (Normal)"

        return DecisionState(
            should_trigger_alert=should_trigger,
            is_confirmed=is_confirmed,
            is_in_cooldown=in_cooldown,
            confirmation_progress=progress,
            seconds_detected=seconds_detected,
            cooldown_remaining=cooldown_remaining,
            status_message=status_message,
            alert_stage=effective_stage,
            candidate_sos=candidate_sos,
            multi_frame_count=self.multi_frame_count,
        )

    def draw_hud(self, frame: np.ndarray, state: DecisionState) -> np.ndarray:
        """Renders confirmation progress bar and alert banner on the camera preview."""
        h, w, _ = frame.shape
        annotated = frame.copy()

        # Bottom HUD panel background
        hud_height = 50
        cv2.rectangle(
            annotated,
            (0, h - hud_height),
            (w, h),
            (20, 20, 20),
            -1,
        )

        # Status text color coding
        if state.should_trigger_alert or (state.is_confirmed and not state.is_in_cooldown):
            status_color = (0, 0, 255)  # Bright Red
        elif state.is_in_cooldown:
            status_color = (0, 165, 255)  # Orange
        elif state.seconds_detected > 0:
            status_color = (0, 255, 255)  # Yellow
        else:
            status_color = (0, 255, 0)  # Green

        cv2.putText(
            annotated,
            f"SYSTEM: {state.status_message}",
            (20, h - 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            status_color,
            2,
            cv2.LINE_AA,
        )

        # Draw confirmation progress bar if user is currently performing the gesture
        if state.seconds_detected > 0 and not state.is_in_cooldown:
            bar_x = w - 240
            bar_y = h - 35
            bar_w = 200
            bar_h = 18

            # Background bar
            cv2.rectangle(
                annotated,
                (bar_x, bar_y),
                (bar_x + bar_w, bar_y + bar_h),
                (50, 50, 50),
                -1,
            )
            # Fill bar
            fill_w = int(bar_w * state.confirmation_progress)
            bar_fill_color = (0, 0, 255) if state.confirmation_progress >= 1.0 else (0, 200, 255)
            cv2.rectangle(
                annotated,
                (bar_x, bar_y),
                (bar_x + fill_w, bar_y + bar_h),
                bar_fill_color,
                -1,
            )
            # Border
            cv2.rectangle(
                annotated,
                (bar_x, bar_y),
                (bar_x + bar_w, bar_y + bar_h),
                (255, 255, 255),
                1,
            )
            # Label
            cv2.putText(
                annotated,
                f"{int(state.confirmation_progress * 100)}%",
                (bar_x + bar_w + 5, bar_y + 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

        # Flashing emergency border when alert triggers
        if state.should_trigger_alert:
            cv2.rectangle(annotated, (0, 0), (w, h), (0, 0, 255), 10)

        return annotated
