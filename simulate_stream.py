"""
Camera Simulation & Demo Feed Generator.
=========================================
This utility generates a sample test video file ('samples/demo_feed.mp4')
so you can test the entire Smart AI Safety Camera software even without
a physical webcam attached or if you are running in a restricted cloud VM.

Usage:
  python simulate_stream.py
  python main.py --source samples/demo_feed.mp4
"""

import sys
from pathlib import Path
import cv2
import numpy as np

import config

SAMPLES_DIR = config.BASE_DIR / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = SAMPLES_DIR / "demo_feed.mp4"


def create_demo_video(output_path: Path, num_seconds: int = 10, fps: int = 15):
    """Generates an MP4 video with countdown and simulated hand gesture stages."""
    print(f"Creating demo test video: {output_path} ({num_seconds}s @ {fps} FPS)...")
    width, height = 640, 480
    total_frames = num_seconds * fps

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, float(fps), (width, height))

    if not writer.isOpened():
        # Fallback to XVID / AVI if mp4v is not compiled
        output_path = output_path.with_suffix(".avi")
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        writer = cv2.VideoWriter(str(output_path), fourcc, float(fps), (width, height))

    for frame_idx in range(total_frames):
        second = frame_idx / fps
        frame = np.zeros((height, width, 3), dtype=np.uint8)

        # Gradient background
        for y in range(height):
            color_val = int(30 + (y / height) * 40)
            frame[y, :] = [color_val, color_val, color_val]

        # Draw simulated surveillance timestamp
        cv2.putText(
            frame,
            f"TEST FEED - TIME: {second:.1f}s / {num_seconds:.1f}s",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        # Instructions banner
        cv2.putText(
            frame,
            "Smart AI Safety Camera - Video Pipeline Test",
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )

        cv2.putText(
            frame,
            "Place your live hand in front of your webcam to test live detection,",
            (20, 200),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "or run: python main.py --source 0",
            (20, 230),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

        # Draw a moving reference box to verify video playback
        box_x = int(50 + (frame_idx % (width - 150)))
        cv2.rectangle(frame, (box_x, 320), (box_x + 80, 400), (0, 165, 255), -1)
        cv2.putText(
            frame,
            "Motion",
            (box_x + 10, 365),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        writer.write(frame)

    writer.release()
    print(f"Demo video successfully created at: {output_path}")
    print(f"You can now test running: python main.py --source {output_path}")


if __name__ == "__main__":
    create_demo_video(OUTPUT_FILE)
