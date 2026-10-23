# 🛡️ Smart AI Safety Camera & Control Center

> A real-time computer vision system that monitors camera feeds, detects distress signals and suspicious activity, confirms events to prevent false alarms, and dispatches instant SMS alerts with Google Maps location and preserved evidence.

---

## 🚀 Two Ways to Run

| Mode | Command | Description |
| :--- | :--- | :--- |
| **🌐 Web Control Center (Recommended)** | `python app.py` (or `python main.py --web`) | Full interactive web application at `http://127.0.0.1:5000` with Live Camera, Control Room map of Indian cities, Alert Log, Settings, and Audio Siren. |
| **🖥️ Native Desktop Window** | `python main.py` | Direct OpenCV desktop preview window with keyboard shortcuts (`[Q]` Quit, `[S]` Snapshot, `[R]` Reset, `[D]` Toggle Landmarks). |

---

## 📌 Project Overview & Key Features

When a person makes a distress signal (such as the International **"Signal for Help"** or a rapid fist):
1. **Bright 21-Landmark Skeleton**: Full MediaPipe hand landmarks are drawn in vivid neon colors (cyan, magenta, yellow, orange) with glowing fingertips.
2. **Real-Time Telemetry Panel**: Displays Hand Detected (`Yes`/`No`), Fingers Up (`0` to `5`), Instant Posture, and Current State.
3. **Confidence Meter & Sensitivity Slider**: An animated gradient progress bar fills up as the gesture is recognized. The slider allows instant threshold tuning during demos.
4. **Selfie-Mirrored View**: The camera feed is mirrored horizontally for a natural selfie-style experience.
5. **Interactive Alert Experience**:
   - **Full-Screen Flashing Red Overlay** with screen shake animation.
   - **Synthesized Emergency Siren Sound** via Web Audio API (works 100% offline).
   - **10-Second Circular Countdown Ring** with a large **"🛡️ I'm Safe, Cancel"** button.
   - **Step-by-step progress cards**: "Getting location" ➡️ "Finding nearest police station" ➡️ "Sending alert" ➡️ "Alert sent".
   - Instant snapshot thumbnail displayed right on the card.
6. **Live Map & Dispatch Vector**:
   - Dark mode Leaflet.js map with a red pulsing marker.
   - Dashed emergency line from user location to nearest police station (Sector 58 Station, 1.4 km, 4 min ETA).
   - **"Track Live"** toggle with breadcrumb movement trail.
   - One-click **"Copy Link"** for Google Maps coordinates.
7. **National Control Room Dashboard**:
   - Multi-camera surveillance map showing cameras across Indian cities (Delhi, Mumbai, Bengaluru, Noida, Hyderabad, Pune, Kolkata, Chennai).
   - **"🚨 Simulate Alert"** button to trigger instant demo alerts on remote cameras.
   - Real-time counters: Total Cameras, Active Alerts, Alerts Today, Average Response Time.
8. **Alert Log & Audit History**:
   - Backed by SQLite (`safety_camera.db`).
   - Filter by status (`Sent`, `Cancelled`, `Pending`) and live search.
   - One-click **CSV Export** and formatted **Print / PDF**.

---

## 🏗️ System Architecture

```
camera detection (hackathon idea)/
├── app.py                      # Flask web application & REST APIs (port 5000)
├── main.py                     # Desktop OpenCV launcher & CLI options
├── database.py                 # SQLite database manager (alerts, cameras, audit log)
├── config.py                   # Settings loaded from .env
├── camera.py                   # Camera wrapper with selfie mirror & device scanner
├── detectors/
│   ├── base.py                 # Abstract Base Class (BaseDetector) interface
│   └── hand_signal.py          # Multi-mode detector (Signal for Help, Rapid Fist, Zone)
├── decision.py                 # False alarm debouncer (continuous confirmation + cooldown)
├── alerts/
│   ├── sms.py                  # Twilio SMS dispatch with safety blocks for 112/911
│   └── location.py             # Google Maps link builder & GPS stub
├── evidence.py                 # JPEG snapshot saver + pre/post MP4 video ring buffer
├── static/
│   ├── css/style.css           # Modern dark UI, animations & glassmorphism
│   └── js/
│       ├── app.js              # Telemetry polling, audio siren, countdown ring
│       ├── control_room.js     # Multi-camera India map & alert simulation
│       └── alert_log.js        # SQLite table rendering, search, filters & export
├── templates/
│   └── index.html              # Single-page responsive control center interface
├── tests/
│   └── test_safety_system.py   # Automated unit test suite (100% passing)
├── samples/
│   └── demo_feed.mp4           # Synthetic test video for testing without a live camera
├── simulate_stream.py          # Demo video generator utility
├── requirements.txt            # Python dependencies
├── .env.example                # Documented environment template
└── .env                        # Local configuration (DRY_RUN=True)
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- **Python 3.10 to 3.14** installed.
- Webcam, USB camera, or video file.

---

### 2. Setup Virtual Environment

#### On macOS / Linux:
```bash
# 1. Navigate to the project directory
cd "camera detection (hackathon idea)"

# 2. Create virtual environment
python3 -m venv .venv

# 3. Activate virtual environment
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

#### On Windows:
```cmd
cd "camera detection (hackathon idea)"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

### 3. Launch the Web Application

```bash
python app.py
```
Open your browser to:
👉 **`http://127.0.0.1:5000`**

---

### 4. Camera Hardware Access

The software automatically discovers and connects to cameras:

1. **Scan available webcams**:
   ```bash
   python main.py --list-cameras
   ```
2. **Switch cameras**:
   - Primary webcam: `--source 0`
   - USB camera: `--source 1`
   - IP / CCTV camera: `--source "rtsp://username:password@192.168.1.100:554/stream1"`
   - Phone Camera (IP Webcam / DroidCam): `--source "http://192.168.1.50:8080/video"`
   - Offline test video: `--source samples/demo_feed.mp4`

*(Note for macOS users: Grant camera permission under **System Settings ➡️ Privacy & Security ➡️ Camera** if prompted).*

---

## 🖐️ How to Perform the "Signal for Help" Gesture

1. **Step 1 (Open Palm)**: Raise your hand facing the camera with your palm open and thumb held outward.
2. **Step 2 (Tuck Thumb)**: Fold your thumb into the center of your palm while keeping the four fingers up.
3. **Step 3 (Close Fingers)**: Fold the four fingers down over your thumb, trapping it inside a fist.
4. **Hold the Pose**: Hold the fist steady for **2.0 seconds** until the confidence meter fills to 100%!

### Extra Detection Modes (Available in UI):
- **Rapid Fist**: A fast transition from an open hand directly into a closed fist.
- **Signal for Help**: The standard 3-step international protocol.
- **Both**: Recognizes either gesture.
- **Zone Breach**: Alerts when hand or movement crosses into the on-screen restricted area.

---

## 🧪 Testing Without Spending Money: `DRY_RUN` Mode

By default, the software runs with **`DRY_RUN=true`**:
- All computer vision, gesture tracking, and confirmation timers work in real time.
- The siren sounds, the 10s countdown ring triggers, and snapshots are captured to `evidence/`.
- The exact SMS alert text and Google Maps link are logged to your terminal.
- **NO real SMS is sent, and zero Twilio credits are consumed!**

---

## 📲 Setting Up Real Twilio SMS Alerts

When you are ready to receive real emergency alerts on your phone:
1. Sign up at [twilio.com](https://www.twilio.com) and get a free virtual number.
2. Open `.env` and set:
   ```ini
   DRY_RUN=false
   TEST_MODE=true
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=your_auth_token_here
   TWILIO_PHONE_NUMBER=+12015550123
   ALERT_RECIPIENT_PHONE=+919876543210
   ```

---

## ⚠️ Important Safety & Legal Notice

> [!CAUTION]
> **NEVER configure automated dialers to call or text 112 (India) or 911 (USA).**
> In India, emergency service 112 does **not** accept automated or bot-generated calls. False or unverified automated emergency calls to law enforcement are strictly illegal under Indian law.
> This software is designed exclusively to notify the **owner or designated safety contact**, who can then verify the situation and take appropriate action.

---

## 🧪 Running the Unit Tests

To run the automated verification suite:
```bash
python -m unittest tests/test_safety_system.py
```
Output:
```
Ran 7 tests in 1.49s - OK
```

---

## 📄 License
This project is open-source under the **Apache-2.0 License**.
