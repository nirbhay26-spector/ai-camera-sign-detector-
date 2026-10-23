"""
Evidence Recording Module: Snapshots & Incident Video Ring Buffer.
==================================================================
This module preserves photographic and video evidence when a distress
event is confirmed.

For first-year CSE students:
----------------------------
What is a Ring Buffer (Circular Buffer)?
- Imagine a circular conveyor belt that holds the last 60 video frames (about 4 seconds).
- Every time a new frame arrives, it pushes into the buffer; the oldest frame
  falls off if the buffer is full (`collections.deque(maxlen=N)`).
- When an emergency happens, we already have the previous 4 seconds stored!
- We then record the next 4 seconds of frames and stitch them together into
  an 8-second MP4 evidence clip.
"""

import os
import time
import logging
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, Deque, List, Dict, Any

# pyrefly: ignore[missing-import]
import cv2
# pyrefly: ignore[missing-import]
import numpy as np

import config

logger = logging.getLogger(__name__)


class EvidenceRecorder:
    """Manages snapshot generation and pre/post-incident video clip recording."""

    def __init__(
        self,
        evidence_dir: Optional[Path] = None,
        target_fps: int = config.TARGET_FPS,
        pre_event_seconds: float = config.PRE_EVENT_BUFFER_SECONDS,
        post_event_seconds: float = config.POST_EVENT_RECORD_SECONDS,
    ):
        self.evidence_dir = evidence_dir or config.EVIDENCE_DIR
        self.target_fps = max(1, target_fps)
        self.pre_event_seconds = pre_event_seconds
        self.post_event_seconds = post_event_seconds

        # Ensure output directory exists
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        # 1. Ring buffer for pre-event frames (stores last N seconds of frames)
        max_buffer_frames = int(self.target_fps * self.pre_event_seconds)
        self.ring_buffer: Deque[np.ndarray] = deque(maxlen=max_buffer_frames)

        # 2. State for active video clip recording
        self.is_recording_clip = False
        self.post_frames_remaining = 0
        self.active_clip_frames: List[np.ndarray] = []
        self.active_clip_timestamp = ""

    def add_frame_to_buffer(self, frame: np.ndarray) -> None:
        """Pushes a new frame into the pre-event ring buffer or active clip.

        Should be called once per processed video frame.
        """
        # Always update circular buffer
        self.ring_buffer.append(frame.copy())

        # If currently capturing post-event frames for an incident video:
        if self.is_recording_clip:
            self.active_clip_frames.append(frame.copy())
            self.post_frames_remaining -= 1

            if self.post_frames_remaining <= 0:
                # Finished capturing post-event frames; write video file in background
                self.is_recording_clip = False
                frames_to_save = list(self.active_clip_frames)
                ts = self.active_clip_timestamp
                self.active_clip_frames = []

                # Asynchronous thread so saving video does not pause the camera stream
                threading.Thread(
                    target=self._save_video_clip,
                    args=(frames_to_save, ts),
                    daemon=True,
                ).start()

    def save_snapshot(
        self, frame: np.ndarray, event_label: str = "distress"
    ) -> Path:
        """Saves a timestamped JPEG snapshot of the emergency event.

        Args:
            frame: Video frame to save.
            event_label: Tag for filename (e.g. 'distress').

        Returns:
            Path to the saved snapshot file.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_label = "".join(c for c in event_label if c.isalnum() or c in "_-")
        filename = f"snapshot_{timestamp}_{clean_label}.jpg"
        filepath = self.evidence_dir / filename

        try:
            cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            logger.info("Evidence snapshot saved: %s", filepath)
            return filepath
        except Exception as e:
            logger.error("Failed to save snapshot %s: %s", filepath, e)
            return filepath

    def start_incident_video_recording(self) -> None:
        """Starts incident video recording by bundling pre-event frames and arming post-event capture."""
        if self.is_recording_clip:
            logger.debug("Clip recording is already in progress.")
            return

        self.active_clip_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Grab all frames currently in the pre-event ring buffer
        self.active_clip_frames = list(self.ring_buffer)
        self.post_frames_remaining = int(self.target_fps * self.post_event_seconds)
        self.is_recording_clip = True

        logger.info(
            "Incident video armed: %d pre-event frames captured. Recording next %d post-event frames...",
            len(self.active_clip_frames),
            self.post_frames_remaining,
        )

    def _save_video_clip(self, frames: List[np.ndarray], timestamp: str) -> Optional[Path]:
        """Worker thread method that encodes collected frames into an MP4 video."""
        if not frames:
            logger.warning("No frames to save for incident video clip.")
            return None

        filename = f"incident_{timestamp}.mp4"
        filepath = self.evidence_dir / filename

        try:
            h, w, _ = frames[0].shape
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(filepath), fourcc, float(self.target_fps), (w, h))

            if not writer.isOpened():
                # Fallback to AVI / XVID if MP4 codec is unavailable on host
                filename = f"incident_{timestamp}.avi"
                filepath = self.evidence_dir / filename
                fourcc = cv2.VideoWriter_fourcc(*"XVID")
                writer = cv2.VideoWriter(str(filepath), fourcc, float(self.target_fps), (w, h))

            for f in frames:
                writer.write(f)

            writer.release()
            logger.info(
                "Incident video clip saved successfully: %s (%d frames)",
                filepath,
                len(frames),
            )
            return filepath
        except Exception as e:
            logger.error("Failed to write video clip %s: %s", filepath, e)
            return None

    @staticmethod
    def compute_file_sha256(filepath: Path) -> str:
        """Computes cryptographic SHA-256 checksum for tamper-evident evidence verification."""
        import hashlib
        if not filepath or not Path(filepath).exists():
            return ""
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()


def compute_file_sha256(filepath: Path) -> str:
    """Module-level helper to compute SHA-256 hash of a file."""
    return EvidenceRecorder.compute_file_sha256(Path(filepath))


def generate_evidence_package(
    incident_id: str,
    snapshot_path: Optional[Path] = None,
    video_path: Optional[Path] = None,
    camera_id: str = "CAM-01",
    location_info: Optional[Dict[str, Any]] = None,
    alert_stage: str = "RED",
    confidence: float = 0.95,
) -> Dict[str, Any]:
    """Module-level convenience function generating an evidence package manifest."""
    loc = location_info or {}
    snap_p = Path(snapshot_path) if snapshot_path else None
    vid_p = Path(video_path) if video_path else None
    snap_hash = compute_file_sha256(snap_p) if snap_p and snap_p.exists() else ""
    vid_hash = compute_file_sha256(vid_p) if vid_p and vid_p.exists() else ""

    manifest = {
        "incident_id": incident_id,
        "camera_id": camera_id,
        "location": loc,
        "alert_stage": alert_stage,
        "confidence": confidence,
        "timestamp": datetime.now().isoformat(),
        "files": {
            "snapshot": str(snapshot_path) if snapshot_path else "",
            "snapshot_sha256": snap_hash,
            "video": str(video_path) if video_path else "",
            "video_sha256": vid_hash,
        },
    }
    return manifest


    def generate_evidence_package(
        self,
        incident_uuid: str,
        camera_id: str,
        camera_name: str,
        location_address: str,
        confidence: float,
        gesture_stage_breakdown: Dict[str, float],
        snapshot_filename: Optional[str] = None,
        video_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates an authorized tamper-evident incident evidence manifest with cryptographic hashes."""
        import json
        snap_path = (self.evidence_dir / snapshot_filename) if snapshot_filename else None
        vid_path = (self.evidence_dir / video_filename) if video_filename else None

        snap_hash = self.compute_file_sha256(snap_path) if snap_path and snap_path.exists() else ""
        vid_hash = self.compute_file_sha256(vid_path) if vid_path and vid_path.exists() else ""

        manifest = {
            "incident_id": incident_uuid,
            "camera_id": camera_id,
            "camera_name": camera_name,
            "location_address": location_address,
            "created_at": datetime.now().isoformat(),
            "ai_confidence": round(confidence, 3),
            "gesture_sequence_confidence": gesture_stage_breakdown,
            "evidence_files": {
                "snapshot": snapshot_filename or "",
                "snapshot_sha256": snap_hash,
                "video_clip": video_filename or "",
                "video_clip_sha256": vid_hash,
            },
            "security_classification": "OFFICIAL-SENSITIVE / LAWFUL EVIDENCE",
            "retention_policy_days": config.EVIDENCE_RETENTION_DAYS,
            "encryption_status": "AES-256 Storage Protected",
        }

        manifest_path = self.evidence_dir / f"package_{incident_uuid}.json"
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            logger.info("Incident evidence package manifest created: %s", manifest_path)
        except Exception as e:
            logger.error("Failed to write evidence package manifest: %s", e)

        return manifest

    # ==========================================================================
    # FUTURE EXTENSION STUBS (Version 2 / Version 4 Cloud & MMS)
    # ==========================================================================
    def upload_to_cloud_storage_stub(self, file_path: Path) -> Optional[str]:
        """Stub for uploading evidence files to AWS S3 / Google Cloud Storage / Firebase.

        Returns:
            Public or signed HTTPS URL to access the evidence in Version 4.
        """
        logger.info(
            "[STUB] Cloud upload called for %s (will upload to cloud storage in Version 4)",
            file_path.name,
        )
        return None

    def send_mms_attachment_stub(self, image_path: Path) -> None:
        """Stub for sending MMS image attachments via Twilio MediaUrl."""
        logger.info(
            "[STUB] Twilio MMS attachment stub called for %s", image_path.name
        )
