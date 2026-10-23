"""
Camera Source Wrapper Module.
=============================
This module provides a robust interface to capture frames from:
  - Local Webcams (Index 0, 1, 2...)
  - USB Cameras / External Webcams
  - IP Cameras / CCTV Streams (RTSP or HTTP URLs)
  - Pre-recorded video files (e.g. MP4 / AVI)

For first-year CSE students:
----------------------------
In OpenCV, `cv2.VideoCapture(0)` opens the default webcam.
However, in real-world security software:
  - Users might have multiple webcams or an external USB camera.
  - Video feeds can stutter or drop frames.
  - IP cameras use RTSP network links that need timeout protection.
  - High-FPS cameras (60 FPS) can overheat a laptop CPU if not throttled
    to an optimal 15 FPS.

This class wraps all of that complexity into a clean, easy-to-use Python interface.
"""

import time
import logging
import threading
from typing import Union, Tuple, Optional, List, Dict, Any

import cv2
import numpy as np

import config

logger = logging.getLogger(__name__)


class Camera:
    """Wrapper around cv2.VideoCapture supporting local webcams and network streams with background capture threading."""

    def __init__(
        self,
        source: Union[int, str] = config.CAMERA_SOURCE,
        target_fps: int = config.TARGET_FPS,
        width: int = config.FRAME_WIDTH,
        height: int = config.FRAME_HEIGHT,
        mirror: bool = True,
    ):
        """Initializes the camera source.

        Args:
            source: Integer index (0, 1...) for webcam, or string (RTSP URL / video file path).
            target_fps: Frame rate target (e.g. 15 FPS).
            width: Requested capture width.
            height: Requested capture height.
            mirror: If True, horizontally flips frames like a selfie mirror.
        """
        self.source = source
        self.target_fps = target_fps
        self.width = width
        self.height = height
        self.mirror = mirror

        self.cap: Optional[cv2.VideoCapture] = None
        self.is_opened = False
        self.frame_delay = 1.0 / target_fps if target_fps > 0 else 0.0
        self.last_frame_time = 0.0
        self.actual_fps = 0.0
        self._fps_counter = 0
        self._fps_timer = time.time()

        # Background Thread Frame Capture State (Prevents buffer lag and frame drops)
        self._thread_lock = threading.Lock()
        self._capture_thread: Optional[threading.Thread] = None
        self._is_capturing = False
        self._latest_ret = False
        self._latest_frame: Optional[np.ndarray] = None

        # Camera Health Monitoring State
        self.last_frame: Optional[np.ndarray] = None
        self.consecutive_identical_frames = 0
        self.health_status = "Healthy"
        self.blur_score = 150.0
        self.brightness_score = 120.0

        self._open()

    @staticmethod
    def calculate_blur_score(frame: np.ndarray) -> float:
        """Calculates optical sharpness using Laplacian variance."""
        if frame is None or frame.size == 0:
            return 0.0
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def check_health(self, frame: Optional[np.ndarray]) -> str:
        """Evaluates health conditions: Offline, Frozen, Blurry, or Obstructed."""
        if not self.is_opened or frame is None:
            self.health_status = "Offline"
            return self.health_status

        # 1. Blur evaluation via Laplacian variance
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.blur_score = self.calculate_blur_score(gray)

        # 2. Brightness evaluation for obstruction or whiteout
        self.brightness_score = float(np.mean(gray))

        # 3. Freeze evaluation (frame difference)
        if self.last_frame is not None:
            diff = float(np.mean(cv2.absdiff(frame, self.last_frame)))
            if diff < 0.35:
                self.consecutive_identical_frames += 1
            else:
                self.consecutive_identical_frames = 0

        self.last_frame = frame.copy()

        # Diagnosis logic
        if self.consecutive_identical_frames >= 25:
            self.health_status = "Frozen"
        elif self.brightness_score < config.BRIGHTNESS_MIN:
            self.health_status = "Obstructed (Dark)"
        elif self.brightness_score > config.BRIGHTNESS_MAX:
            self.health_status = "Obstructed (Whiteout)"
        elif self.blur_score < config.BLUR_THRESHOLD:
            self.health_status = "Blurry"
        else:
            self.health_status = "Healthy"

        return self.health_status

    def get_health_report(self) -> Dict[str, Any]:
        """Returns comprehensive diagnostic health metrics."""
        return {
            "health_status": self.health_status,
            "blur_score": round(self.blur_score, 1),
            "brightness": round(self.brightness_score, 1),
            "fps": round(self.actual_fps, 1),
            "is_opened": self.is_opened,
            "consecutive_static_frames": self.consecutive_identical_frames,
        }

    def _open(self) -> bool:
        """Opens the video capture device and configures properties."""
        logger.info("Opening camera source: %s", self.source)

        # On macOS, cv2.CAP_AVFOUNDATION provides fast hardware camera access.
        # On Linux/Windows, OpenCV defaults to V4L2 or DirectShow.
        if isinstance(self.source, int):
            self.cap = cv2.VideoCapture(self.source)
        else:
            self.cap = cv2.VideoCapture(str(self.source))

        if not self.cap or not self.cap.isOpened():
            logger.error("Failed to open camera source: %s", self.source)
            self.is_opened = False
            return False

        # Attempt to set desired frame dimensions (webcams will snap to closest supported resolution)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

        self.is_opened = True
        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info(
            "Camera stream active! Resolution: %dx%d (Target: %dx%d @ %d FPS)",
            actual_w,
            actual_h,
            self.width,
            self.height,
            self.target_fps,
        )

        self._start_background_capture()
        return True

    def _start_background_capture(self) -> None:
        """Initializes and starts the non-blocking background camera capture thread."""
        if self._is_capturing:
            return

        # Synchronously capture first frame to guarantee instant availability
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret and frame is not None:
                if self.mirror:
                    frame = cv2.flip(frame, 1)
                with self._thread_lock:
                    self._latest_ret = ret
                    self._latest_frame = frame

        self._is_capturing = True
        self._capture_thread = threading.Thread(target=self._capture_worker, daemon=True)
        self._capture_thread.start()
        logger.info("Background camera capture thread started.")

    def _capture_worker(self) -> None:
        """Continuous background thread fetching latest optical frames to prevent lag."""
        while self._is_capturing and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret or frame is None:
                # Loop video file if end reached
                if isinstance(self.source, str) and not self.source.startswith(("rtsp://", "http://")):
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = self.cap.read()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue

            if self.mirror and frame is not None:
                frame = cv2.flip(frame, 1)

            with self._thread_lock:
                self._latest_ret = ret
                self._latest_frame = frame

            # Throttle slightly to conserve system resources
            if self.frame_delay > 0:
                time.sleep(self.frame_delay * 0.5)

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Reads the freshest frame from the background capture thread with zero lag.

        Returns:
            Tuple of (success: bool, frame: Optional[np.ndarray])
        """
        if not self.is_opened or not self.cap:
            return False, None

        with self._thread_lock:
            if self._latest_frame is not None:
                ret = self._latest_ret
                frame = self._latest_frame.copy()
            else:
                ret = False
                frame = None

        if ret and frame is not None:
            # Measure actual observed FPS
            self._fps_counter += 1
            cur_time = time.time()
            if cur_time - self._fps_timer >= 1.0:
                self.actual_fps = self._fps_counter / (cur_time - self._fps_timer)
                self._fps_counter = 0
                self._fps_timer = cur_time

        return ret, frame

    def release(self) -> None:
        """Releases the camera capture hardware and closes any active stream."""
        self._is_capturing = False
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=0.5)
            self._capture_thread = None

        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.is_opened = False

        with self._thread_lock:
            self._latest_frame = None
            self._latest_ret = False

        logger.info("Camera device released cleanly.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    @staticmethod
    def list_available_cameras(max_tested: int = 6) -> List[Dict[str, Any]]:
        """Utility method to probe local hardware and discover all connected webcams.

        Probes device indices 0 through max_tested - 1.

        Returns:
            List of dictionaries with 'index', 'width', 'height', and 'status'.
        """
        available = []
        logger.info("Scanning for connected camera devices (indices 0 to %d)...", max_tested - 1)

        for idx in range(max_tested):
            test_cap = cv2.VideoCapture(idx)
            if test_cap and test_cap.isOpened():
                ret, frame = test_cap.read()
                if ret and frame is not None:
                    h, w, _ = frame.shape
                    available.append({
                        "index": idx,
                        "width": w,
                        "height": h,
                        "status": "Available / Working",
                    })
                test_cap.release()

        return available
