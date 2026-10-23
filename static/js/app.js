/**
 * Smart AI Safety Camera - Core Frontend Application Logic
 * ========================================================
 * Handles:
 *  - Real-time telemetry polling (landmarks status, 3-stage alert status, multi-frame counters)
 *  - Human-in-the-Loop Emergency Verification Console
 *  - 15-case Benchmark Evaluation Suite & Camera Health Diagnostics
 *  - Emergency Contacts Management with OTP Verification
 *  - "Test SOS System" Interactive Guided Presentation Wizard
 *  - Full-screen emergency siren, countdown timer, and evidence preview
 *  - Edge AI mode and Low-light CCTV (CLAHE) toggles
 *  - Live location tracking breadcrumb trail & Google Maps link copy
 */

// Global Application State
const state = {
  currentTab: 'camera',
  sensitivity: 1.0,
  mode: 'both',
  countdownActive: false,
  countdownInterval: null,
  countdownTotalSeconds: 10,
  countdownSecondsLeft: 10,
  activeAlertId: null,
  activeOtpContactId: null,
  currentVerifFilter: 'all',
  sirenAudioContext: null,
  sirenOscillator: null,
  sirenGain: null,
  sirenPlaying: false,
  trackingLive: false,
  trackingInterval: null,
  breadcrumbPoints: [],
  userCoords: [28.6280, 77.3649],
  policeCoords: [28.6360, 77.3750], // ~1.4 km away in Sector 58
  miniMap: null,
  miniUserMarker: null,
  miniPoliceMarker: null,
  miniPolyline: null,
  nightModeEnabled: false,
  edgeModeEnabled: true,
  wizardActive: false,
};

// ==============================================================================
// 1. WEB AUDIO API EMERGENCY SIREN SYNTHESIZER (100% Offline, Zero Assets)
// ==============================================================================
function initAudio() {
  if (!state.sirenAudioContext) {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    state.sirenAudioContext = new AudioContext();
  }
}

function startSiren() {
  try {
    initAudio();
    if (state.sirenPlaying) return;

    const ctx = state.sirenAudioContext;
    if (ctx.state === 'suspended') {
      ctx.resume();
    }

    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(750, ctx.currentTime);

    // Two-tone sweeping emergency siren
    const now = ctx.currentTime;
    for (let i = 0; i < 30; i++) {
      osc.frequency.linearRampToValueAtTime(1150, now + (i * 0.8) + 0.4);
      osc.frequency.linearRampToValueAtTime(750, now + (i * 0.8) + 0.8);
    }

    gain.gain.setValueAtTime(0.25, ctx.currentTime);
    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start();
    state.sirenOscillator = osc;
    state.sirenGain = gain;
    state.sirenPlaying = true;

    // Trigger physical device vibration if supported (Mobile)
    if ('vibrate' in navigator) {
      navigator.vibrate([400, 200, 400, 200, 600]);
    }
  } catch (err) {
    console.warn('Audio siren autoplay blocked or unavailable:', err);
  }
}

function stopSiren() {
  if (state.sirenPlaying && state.sirenOscillator) {
    try {
      state.sirenOscillator.stop();
      state.sirenOscillator.disconnect();
    } catch (e) {}
    state.sirenPlaying = false;
    state.sirenOscillator = null;
  }
}

// ==============================================================================
// 2. TAB NAVIGATION
// ==============================================================================
function switchTab(tabId) {
  state.currentTab = tabId;
  document.querySelectorAll('.nav-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-panel').forEach(panel => {
    panel.classList.toggle('active', panel.id === `tab-${tabId}`);
  });

  if (tabId === 'control') {
    if (window.controlRoomMap) {
      setTimeout(() => window.controlRoomMap.invalidateSize(), 200);
    }
  } else if (tabId === 'camera') {
    if (state.miniMap) {
      setTimeout(() => state.miniMap.invalidateSize(), 200);
    }
  } else if (tabId === 'verification') {
    refreshIncidentsList();
  } else if (tabId === 'benchmarks') {
    refreshCameraHealth();
  } else if (tabId === 'logs') {
    if (window.loadAlertLogs) {
      window.loadAlertLogs();
    }
  } else if (tabId === 'settings') {
    loadSettings();
    loadEmergencyContacts();
  }
}

// ==============================================================================
// 3. TELEMETRY POLLING & LIVE HUD
// ==============================================================================
async function pollTelemetry() {
  try {
    const res = await fetch('/api/telemetry');
    if (!res.ok) return;
    const data = await res.json();

    // 1. Hand Detected & Finger Count
    const handBadge = document.getElementById('handDetectedBadge');
    if (handBadge) {
      if (data.hand_detected) {
        handBadge.className = 'status-badge green';
        handBadge.textContent = 'YES';
      } else {
        handBadge.className = 'status-badge';
        handBadge.textContent = 'NO';
      }
    }

    const fingersVal = document.getElementById('fingersUpVal');
    if (fingersVal) {
      fingersVal.textContent = `${data.fingers_up} / 5`;
    }

    const handednessVal = document.getElementById('handednessVal');
    if (handednessVal) {
      handednessVal.textContent = data.handedness ? `${data.handedness} Hand` : 'Detecting...';
    }

    const postureVal = document.getElementById('postureVal');
    if (postureVal) {
      postureVal.textContent = data.posture;
    }

    const clarityVal = document.getElementById('clarityVal');
    if (clarityVal) {
      const score = data.clarity_score || 100.0;
      clarityVal.textContent = `${score.toFixed(1)} (${score > 80 ? 'Sharp' : 'Blurry'})`;
      clarityVal.style.color = score > 80 ? '#10b981' : '#f59e0b';
    }

    const fpsBadge = document.getElementById('cameraFpsBadge');
    if (fpsBadge) {
      fpsBadge.textContent = `${data.fps || 0} FPS`;
    }

    // 2. 3-STAGE ALERT PILL & STATUS
    const stage = data.alert_stage || 'GREEN';
    const alertStageBadge = document.getElementById('alertStageBadge');
    if (alertStageBadge) {
      alertStageBadge.className = `stage-status-badge ${stage.toLowerCase()}`;
      if (stage === 'RED') {
        alertStageBadge.textContent = '🔴 RED: SOS CONFIRMED';
      } else if (stage === 'ORANGE') {
        alertStageBadge.textContent = '🟠 ORANGE: DISTRESS SUSPECTED';
      } else {
        alertStageBadge.textContent = '🟢 GREEN: NORMAL';
      }
    }

    // Floating video stage pill overlay
    const videoStageText = document.getElementById('videoStageOverlayText');
    const videoStageDot = document.querySelector('.stage-overlay-badge .stage-pill-dot');
    if (videoStageText && videoStageDot) {
      videoStageDot.className = `stage-pill-dot ${stage.toLowerCase()}`;
      videoStageText.textContent = `STAGE ${stage === 'RED' ? '3: SOS CONFIRMED' : (stage === 'ORANGE' ? '2: SUSPECTED' : '1: NORMAL')}`;
    }

    // Dynamic Video Card & Wrapper Stage Styling
    const videoCard = document.querySelector('.video-card');
    const videoWrapper = document.querySelector('.video-wrapper');
    if (videoCard) {
      videoCard.classList.remove('stage-green', 'stage-orange', 'stage-red');
      videoCard.classList.add(`stage-${stage.toLowerCase()}`);
    }
    if (videoWrapper) {
      videoWrapper.classList.remove('stage-green', 'stage-orange', 'stage-red');
      videoWrapper.classList.add(`stage-${stage.toLowerCase()}`);
    }

    // Stepper active states
    const stepGreen = document.getElementById('stepPillGreen');
    const stepOrange = document.getElementById('stepPillOrange');
    const stepRed = document.getElementById('stepPillRed');
    if (stepGreen && stepOrange && stepRed) {
      stepGreen.classList.toggle('active', true);
      stepOrange.classList.toggle('active', stage === 'ORANGE' || stage === 'RED');
      stepOrange.classList.toggle('pulsing', stage === 'ORANGE');
      stepRed.classList.toggle('active', stage === 'RED');
      stepRed.classList.toggle('pulsing', stage === 'RED');
    }

    // 3. MULTI-FRAME STAGE CHIPS
    const s1Val = document.getElementById('stage1FramesVal');
    const s2Val = document.getElementById('stage2FramesVal');
    const s3Val = document.getElementById('stage3FramesVal');
    const chip1 = document.getElementById('chipStage1');
    const chip2 = document.getElementById('chipStage2');
    const chip3 = document.getElementById('chipStage3');

    const f1 = data.stage1_frames || 0;
    const f2 = data.stage2_frames || 0;
    const f3 = data.stage3_frames || 0;

    if (s1Val) s1Val.textContent = `${f1} / 3 frames`;
    if (s2Val) s2Val.textContent = `${f2} / 3 frames`;
    if (s3Val) s3Val.textContent = `${f3} / 4 frames`;

    if (chip1) {
      chip1.className = `frame-chip ${f1 >= 3 ? 'done' : (f1 > 0 ? 'active' : '')}`;
    }
    if (chip2) {
      chip2.className = `frame-chip ${f2 >= 3 ? 'done' : (f2 > 0 ? 'active' : '')}`;
    }
    if (chip3) {
      chip3.className = `frame-chip ${f3 >= 4 ? 'done' : (f3 > 0 ? 'active' : '')}`;
    }

    // 4. Night Mode & Edge AI Badges
    state.nightModeEnabled = !!data.night_mode;
    state.edgeModeEnabled = !!data.edge_mode;

    const nightBadge = document.getElementById('nightModeBadge');
    if (nightBadge) {
      nightBadge.textContent = state.nightModeEnabled ? 'Night: CLAHE ON' : 'Night: Normal';
      nightBadge.style.color = state.nightModeEnabled ? '#fbbf24' : '#c084fc';
    }

    const edgeBadge = document.getElementById('edgeModeBadge');
    if (edgeBadge) {
      edgeBadge.textContent = state.edgeModeEnabled ? 'Edge AI: Active' : 'Edge AI: Cloud Stream';
      edgeBadge.style.color = state.edgeModeEnabled ? '#22d3ee' : '#94a3b8';
    }

    const bwSavings = document.getElementById('edgeBandwidthSavings');
    if (bwSavings) {
      const saved = (data.bandwidth_saved_percent !== undefined) ? data.bandwidth_saved_percent : 99.4;
      bwSavings.textContent = `Edge Bandwidth Saved: ${saved.toFixed(1)}%`;
    }

    // 5. Confidence Meter
    const meterFill = document.getElementById('confidenceMeterFill');
    const meterPercent = document.getElementById('confidenceMeterPercent');
    if (meterFill && meterPercent) {
      const pct = Math.round((data.confirmation_progress || 0) * 100);
      meterFill.style.width = `${pct}%`;
      meterPercent.textContent = `${pct}%`;
      if (stage === 'RED' || data.is_confirmed) {
        meterFill.classList.add('distress');
      } else {
        meterFill.classList.remove('distress');
      }
    }

    // 6. Cooldown Banner
    const cooldownBanner = document.getElementById('cooldownBanner');
    if (cooldownBanner) {
      if (data.is_in_cooldown) {
        cooldownBanner.style.display = 'block';
        cooldownBanner.textContent = `COOLDOWN ACTIVE (${data.cooldown_remaining}s remaining before next alert)`;
      } else {
        cooldownBanner.style.display = 'none';
      }
    }

    // 7. Update Guided Wizard if open
    if (state.wizardActive) {
      updateSOSTestWizard(data);
    }

    // 8. Emergency Countdown Check
    if (data.countdown_active && !state.countdownActive) {
      triggerEmergencyCountdown(data.active_alert_id, data.last_snapshot);
    }

  } catch (err) {
    // Gracefully ignore intermittent network blips
  }
}

// ==============================================================================
// 4. INTERACTIVE EMERGENCY COUNTDOWN & ALERT EXPERIENCE
// ==============================================================================
function triggerEmergencyCountdown(alertId, snapshotFilename) {
  state.countdownActive = true;
  state.activeAlertId = alertId;
  state.countdownSecondsLeft = state.countdownTotalSeconds;

  // Show Red Alert Overlay
  const overlay = document.getElementById('emergencyOverlay');
  if (overlay) overlay.classList.add('active');

  // Start Audio Siren
  startSiren();

  // Reset SVG countdown ring
  const circle = document.getElementById('countdownCircleProgress');
  const numText = document.getElementById('countdownNumber');
  const totalOffset = 440; // 2 * PI * r (r=70)
  if (circle) circle.style.strokeDashoffset = '0';
  if (numText) numText.textContent = state.countdownSecondsLeft;

  clearInterval(state.countdownInterval);
  state.countdownInterval = setInterval(() => {
    state.countdownSecondsLeft -= 1;
    if (numText) numText.textContent = Math.max(0, state.countdownSecondsLeft);

    if (circle) {
      const progressFraction = (state.countdownTotalSeconds - state.countdownSecondsLeft) / state.countdownTotalSeconds;
      circle.style.strokeDashoffset = String(totalOffset * progressFraction);
    }

    if (state.countdownSecondsLeft <= 0) {
      clearInterval(state.countdownInterval);
      stopSiren();
      showDispatchProgress(alertId, snapshotFilename);
    }
  }, 1000);
}

// "I'm Safe, Cancel" Handler
async function cancelEmergencyAlert() {
  clearInterval(state.countdownInterval);
  stopSiren();

  const overlay = document.getElementById('emergencyOverlay');
  if (overlay) overlay.classList.remove('active');

  state.countdownActive = false;

  try {
    await fetch('/api/alert/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alert_id: state.activeAlertId }),
    });
    showToast('Alert Cancelled: Marked Safe.');
    if (state.currentTab === 'verification') refreshIncidentsList();
  } catch (err) {
    console.error('Cancel alert failed:', err);
  }
}

// Manual "Confirm & Dispatch Immediately" Handler
async function confirmEmergencyAlertNow() {
  clearInterval(state.countdownInterval);
  stopSiren();
  try {
    await fetch('/api/alert/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alert_id: state.activeAlertId }),
    });
    showDispatchProgress(state.activeAlertId);
    if (state.currentTab === 'verification') refreshIncidentsList();
  } catch (err) {
    console.error('Confirm alert failed:', err);
  }
}

// Step-by-Step Dispatch Progress Card
function showDispatchProgress(alertId, snapshotFilename) {
  const overlay = document.getElementById('emergencyOverlay');
  const modal = document.getElementById('dispatchProgressModal');
  const snapshotImg = document.getElementById('dispatchSnapshotPreview');

  if (overlay) overlay.classList.remove('active');
  if (modal) modal.classList.add('active');

  if (snapshotImg && snapshotFilename) {
    snapshotImg.src = `/evidence/${snapshotFilename}`;
    snapshotImg.style.display = 'block';
  }

  const stepIds = ['step1', 'step2', 'step3', 'step4'];
  stepIds.forEach((id, idx) => {
    setTimeout(() => {
      const el = document.getElementById(id);
      if (el) {
        const icon = el.querySelector('.step-icon');
        if (icon) {
          icon.classList.add('done');
          icon.innerHTML = '✓';
        }
      }
    }, (idx + 1) * 700);
  });

  // Display permanent SOS dispatch success banner
  showEmergencyDispatchBanner({
    coordinates_str: `${state.userCoords[0].toFixed(6)} N, ${state.userCoords[1].toFixed(6)} E`,
    target_phone: '+919876543210',
    delivery_status: 'Dispatched (SMS/WhatsApp)',
    message: 'Stage 3 Signal-for-Help SOS confirmed! Event permanently committed to SQLite incident database and dispatched to verified contacts.',
  });
}

function closeDispatchModal() {
  const modal = document.getElementById('dispatchProgressModal');
  if (modal) modal.classList.remove('active');
  state.countdownActive = false;
}

// ==============================================================================
// 4B. EMERGENCY DISPATCH SUCCESS BANNER
// ==============================================================================
function showEmergencyDispatchBanner(data) {
  const banner = document.getElementById('sosDispatchSuccessBanner');
  if (!banner) return;

  const coordsEl = document.getElementById('bannerCoords');
  const phoneEl = document.getElementById('bannerPhone');
  const statusEl = document.getElementById('bannerStatus');
  const timeEl = document.getElementById('bannerTime');
  const messageEl = document.getElementById('bannerMessage');

  if (coordsEl) {
    const coordsStr = data.coordinates_str || (data.latitude ? `${Number(data.latitude).toFixed(6)} N, ${Number(data.longitude).toFixed(6)} E` : '28.628000 N, 77.364900 E');
    coordsEl.textContent = `📍 GPS: ${coordsStr}`;
  }
  if (phoneEl) {
    phoneEl.textContent = `📱 Target: ${data.target_phone || '+919876543210'}`;
  }
  if (statusEl) {
    statusEl.textContent = `⚡ Status: ${data.delivery_status || 'Dispatched (SMS/WhatsApp Demo)'}`;
  }
  if (timeEl) {
    timeEl.textContent = `🕒 Time: ${new Date().toLocaleTimeString()}`;
  }
  if (messageEl) {
    messageEl.textContent = data.message || 'Signal-for-Help SOS incident permanently saved to SQLite database with live GPS coordinates and dispatched to emergency contacts.';
  }

  banner.style.display = 'flex';
  banner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function dismissDispatchBanner() {
  const banner = document.getElementById('sosDispatchSuccessBanner');
  if (banner) banner.style.display = 'none';
}

// ==============================================================================
// 5. MINI LIVE MAP & POLICE STATION VECTOR
// ==============================================================================
function initMiniMap() {
  const mapContainer = document.getElementById('miniMapBox');
  if (!mapContainer || typeof L === 'undefined') return;

  state.miniMap = L.map('miniMapBox', {
    zoomControl: false,
    attributionControl: false,
  }).setView(state.userCoords, 14);

  // OpenStreetMap Tile Layer (100% Free, Open Source, No API Key Required, Clean Rendering)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors',
  }).addTo(state.miniMap);

  // User Marker
  state.miniUserMarker = L.circleMarker(state.userCoords, {
    radius: 9,
    color: '#ef4444',
    fillColor: '#ef4444',
    fillOpacity: 0.9,
    weight: 2,
  }).addTo(state.miniMap);
  state.miniUserMarker.bindPopup('<b>Your Camera Location</b><br>Distress Signal Monitoring');

  // Police Station Marker
  state.miniPoliceMarker = L.circleMarker(state.policeCoords, {
    radius: 9,
    color: '#06b6d4',
    fillColor: '#3b82f6',
    fillOpacity: 0.9,
    weight: 2,
  }).addTo(state.miniMap);
  state.miniPoliceMarker.bindPopup('<b>Nearest Police Station</b><br>Sector 58 Unit (1.4 km, 4 min ETA)');

  state.miniPolyline = L.polyline([state.userCoords, state.policeCoords], {
    color: '#f59e0b',
    weight: 3,
    dashArray: '6, 8',
    opacity: 0.85,
  }).addTo(state.miniMap);
}

function toggleLiveTracking() {
  const toggle = document.getElementById('trackLiveToggle');
  state.trackingLive = toggle ? toggle.checked : !state.trackingLive;

  if (state.trackingLive) {
    showToast('Live Tracking ON: Monitoring coordinate drift');
    state.trackingInterval = setInterval(() => {
      const jitterLat = state.userCoords[0] + (Math.random() - 0.5) * 0.0003;
      const jitterLon = state.userCoords[1] + (Math.random() - 0.5) * 0.0003;
      const newPoint = [jitterLat, jitterLon];

      state.breadcrumbPoints.push(newPoint);
      if (state.breadcrumbPoints.length > 20) state.breadcrumbPoints.shift();

      if (state.miniMap && state.miniUserMarker) {
        state.miniUserMarker.setLatLng(newPoint);
        L.circleMarker(newPoint, {
          radius: 3,
          color: '#3b82f6',
          fillColor: '#3b82f6',
          fillOpacity: 0.6,
        }).addTo(state.miniMap);
      }
    }, 3000);
  } else {
    clearInterval(state.trackingInterval);
    showToast('Live Tracking OFF');
  }
}

function copyMapsLink() {
  const url = `https://www.google.com/maps/search/?api=1&query=${state.userCoords[0].toFixed(6)},${state.userCoords[1].toFixed(6)}`;
  navigator.clipboard.writeText(url).then(() => {
    showToast('Google Maps Link copied to clipboard!');
  });
}

// ==============================================================================
// 6. VIDEO CONTROLS: NIGHT MODE, EDGE AI, VIDEO UPLOAD, RESET
// ==============================================================================
async function resetDetectionState() {
  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sensitivity: state.sensitivity }),
    });
    showToast('Detection state reset to GREEN (IDLE).');
  } catch (err) {
    console.error('Reset error:', err);
  }
}

async function toggleNightMode() {
  const nextVal = !state.nightModeEnabled;
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cctv_night_mode: nextVal }),
    });
    if (res.ok) {
      state.nightModeEnabled = nextVal;
      showToast(`CCTV Night Mode (CLAHE): ${nextVal ? 'ON (Contrast Boosted)' : 'OFF'}`);
    }
  } catch (err) {
    console.error('Toggle night mode failed:', err);
  }
}

async function toggleEdgeMode() {
  const nextVal = !state.edgeModeEnabled;
  try {
    const res = await fetch('/api/edge/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: nextVal }),
    });
    if (res.ok) {
      state.edgeModeEnabled = nextVal;
      showToast(`Edge AI Processing: ${nextVal ? 'ON (99.4% Bandwidth Saved)' : 'OFF (Continuous Stream)'}`);
    }
  } catch (err) {
    console.error('Toggle edge mode failed:', err);
  }
}

async function uploadCCTVVideo(inputEl) {
  if (!inputEl.files || inputEl.files.length === 0) return;
  const file = inputEl.files[0];
  const formData = new FormData();
  formData.append('file', file);

  showToast(`Uploading CCTV Video: ${file.name}...`);
  try {
    const res = await fetch('/api/video/upload', {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Video Loaded! Streaming ${file.name}`);
    } else {
      showToast(`Upload failed: ${data.message}`);
    }
  } catch (err) {
    console.error('Upload error:', err);
    showToast('Error uploading video file.');
  }
}

// Mode & Sensitivity
function setMode(modeName) {
  state.mode = modeName;
  document.querySelectorAll('.mode-pill-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === modeName);
  });

  fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: modeName }),
  });
  showToast(`Detection Mode: ${modeName.replace('_', ' ').toUpperCase()}`);
}

function onSensitivityChange(e) {
  const val = parseFloat(e.target.value);
  state.sensitivity = val;
  const label = document.getElementById('sensitivityValLabel');
  if (label) label.textContent = `${val.toFixed(1)}x`;

  fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sensitivity: val }),
  });
}

// ==============================================================================
// 7. HUMAN-IN-THE-LOOP VERIFICATION CONSOLE
// ==============================================================================
async function refreshIncidentsList() {
  const tbody = document.getElementById('verificationTableBody');
  if (!tbody) return;

  try {
    const res = await fetch(`/api/incidents?status=${encodeURIComponent(state.currentVerifFilter)}`);
    if (!res.ok) return;
    const incidents = await res.json();

    // Update stats
    let pending = 0, confirmed = 0, falseAlarms = 0;
    incidents.forEach(inc => {
      if (inc.status === 'PENDING' || inc.status === 'Pending') pending++;
      else if (inc.status === 'CONFIRMED' || inc.status === 'Sent') confirmed++;
      else if (inc.status === 'FALSE_ALARM') falseAlarms++;
    });

    const elP = document.getElementById('verifPendingCount');
    const elC = document.getElementById('verifConfirmedCount');
    const elF = document.getElementById('verifFalseAlarmCount');
    if (elP) elP.textContent = pending;
    if (elC) elC.textContent = confirmed;
    if (elF) elF.textContent = falseAlarms;

    tbody.innerHTML = '';
    if (incidents.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" style="text-align: center; color: var(--text-dim); padding: 30px;">
            No emergency candidate incidents in queue.
          </td>
        </tr>
      `;
      return;
    }

    incidents.forEach(inc => {
      const tr = document.createElement('tr');
      const stage = inc.alert_stage || 'RED';
      const confPct = Math.round((inc.confidence || 0.95) * 100);
      const isPending = inc.status === 'PENDING' || inc.status === 'Pending';
      const shaShort = inc.evidence_sha256 ? `${inc.evidence_sha256.substring(0, 10)}...` : 'e3b0c44298...';

      tr.innerHTML = `
        <td>
          <div style="font-family: 'JetBrains Mono'; font-weight: 600; font-size: 0.82rem; color: #93c5fd;">
            ${(inc.incident_uuid || `INC-${inc.id}`).substring(0, 12)}
          </div>
          <div style="font-size: 0.72rem; color: var(--text-dim);">#${inc.id}</div>
        </td>
        <td style="font-size: 0.78rem; color: var(--text-muted);">${inc.timestamp}</td>
        <td>
          <div style="font-weight: 600; font-size: 0.85rem;">${inc.camera_id || 'CAM-01'}</div>
          <div style="font-size: 0.74rem; color: var(--text-dim);">${inc.zone || 'Zone A'} &bull; ${inc.location || 'Local Video'}</div>
        </td>
        <td>
          <span class="stage-status-badge ${stage.toLowerCase()}">${stage}</span>
          <div style="font-size: 0.74rem; font-family: 'JetBrains Mono'; color: #93c5fd; margin-top: 3px;">
            ${confPct}% Confidence
          </div>
        </td>
        <td>
          <span style="font-family: 'JetBrains Mono'; font-size: 0.74rem; background: rgba(255,255,255,0.06); padding: 3px 6px; border-radius: 4px;" title="${inc.evidence_sha256 || 'SHA-256 Validated'}">
            🔒 ${shaShort}
          </span>
        </td>
        <td>
          ${inc.snapshot_path ? `
            <img class="thumb-preview" src="/evidence/${inc.snapshot_path}" alt="Incident Snapshot" onclick="viewSnapshotModal('/evidence/${inc.snapshot_path}')">
          ` : '<span style="color: var(--text-dim); font-size: 0.75rem;">None</span>'}
        </td>
        <td>
          <span class="status-badge ${inc.status === 'CONFIRMED' || inc.status === 'Sent' ? 'red' : (inc.status === 'FALSE_ALARM' ? 'yellow' : 'blue')}">
            ${inc.status}
          </span>
        </td>
        <td>
          <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            ${isPending ? `
              <button class="verif-action-btn confirm" onclick="submitOperatorAction(${inc.id}, 'CONFIRM_EMERGENCY')">Confirm</button>
              <button class="verif-action-btn monitor" onclick="submitOperatorAction(${inc.id}, 'CONTINUE_MONITORING')">Monitor</button>
              <button class="verif-action-btn false-alarm" onclick="openFalseAlarmModal(${inc.id})">False Alarm</button>
            ` : `
              <button class="verif-action-btn" style="background: rgba(255,255,255,0.08); color: var(--text-muted);" onclick="submitOperatorAction(${inc.id}, 'RESOLVED')">Resolve</button>
            `}
            <button class="verif-action-btn timeline" onclick="openCrossCameraTimeline(${inc.id})">Timeline</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });

  } catch (err) {
    console.error('Failed to load verification incidents:', err);
  }
}

function filterVerificationIncidents(status) {
  state.currentVerifFilter = status;
  document.querySelectorAll('.verif-filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.vfilter === status);
  });
  refreshIncidentsList();
}

async function submitOperatorAction(incidentId, action, notes = '') {
  try {
    const res = await fetch('/api/incidents/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        incident_id: incidentId,
        action: action,
        operator_notes: notes,
      }),
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Incident #${incidentId}: Action ${action} recorded.`);
      refreshIncidentsList();
    }
  } catch (err) {
    console.error('Operator action error:', err);
  }
}

// False Alarm Modal
function openFalseAlarmModal(incidentId) {
  const el = document.getElementById('faIncidentId');
  if (el) el.value = incidentId;
  const modal = document.getElementById('falseAlarmFeedbackModal');
  if (modal) modal.classList.add('active');
}

function closeFalseAlarmModal() {
  const modal = document.getElementById('falseAlarmFeedbackModal');
  if (modal) modal.classList.remove('active');
}

async function submitFalseAlarmFeedback(e) {
  if (e) e.preventDefault();
  const incId = parseInt(document.getElementById('faIncidentId')?.value || 0);
  const cat = document.getElementById('faCategory')?.value || 'Resting Closed Fist';
  const lighting = document.getElementById('faLighting')?.value || 'Normal Day';
  const notes = document.getElementById('faNotes')?.value || '';

  try {
    // 1. Submit false alarm feedback
    await fetch('/api/false-alarms/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        incident_id: incId,
        category: cat,
        sub_gesture: cat,
        lighting_condition: lighting,
        operator_notes: notes,
      }),
    });

    // 2. Mark incident as FALSE_ALARM
    await submitOperatorAction(incId, 'FALSE_ALARM', `Categorized as: ${cat}. ${notes}`);
    closeFalseAlarmModal();
    showToast(`Feedback saved for retraining: "${cat}"`);
  } catch (err) {
    console.error('Feedback submit failed:', err);
  }
}

// Cross-Camera Continuity Timeline
async function openCrossCameraTimeline(incidentId) {
  const modal = document.getElementById('crossCameraModal');
  const timelineBox = document.getElementById('crossCameraTimeline');
  if (!modal || !timelineBox) return;

  timelineBox.innerHTML = '<div style="color: var(--text-dim); padding: 12px;">Loading tracking continuum...</div>';
  modal.classList.add('active');

  try {
    const res = await fetch(`/api/incidents/${incidentId}`);
    if (!res.ok) return;
    const data = await res.json();
    const inc = data.incident || {};
    const linked = data.linked_cameras || [];

    let html = `
      <div class="timeline-item">
        <div class="timeline-dot" style="background: #ef4444; box-shadow: 0 0 10px #ef4444;"></div>
        <div class="timeline-content">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <b style="color: #f87171;">Primary Distress Signal Detected</b>
            <span style="font-size: 0.74rem; font-family: 'JetBrains Mono'; color: var(--text-dim);">${inc.timestamp || 'Just now'}</span>
          </div>
          <div style="font-size: 0.8rem; margin-top: 4px;">
            Camera: <b>${inc.camera_id || 'CAM-01'}</b> (${inc.location || 'Local Feed'}) &bull; Zone: <b>${inc.zone || 'Zone A'}</b>
          </div>
          <div style="font-size: 0.74rem; color: #94a3b8; margin-top: 2px;">
            Signal: Open Palm → Thumb Tuck → Closed Fist (Stage 3 Red)
          </div>
        </div>
      </div>
    `;

    if (linked.length > 0) {
      linked.forEach(link => {
        html += `
          <div class="timeline-item">
            <div class="timeline-dot" style="background: #38bdf8;"></div>
            <div class="timeline-content">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <b>Adjacent Node Handover: ${link.linked_camera_id}</b>
                <span style="font-size: 0.74rem; font-family: 'JetBrains Mono'; color: var(--text-dim);">${link.handover_timestamp}</span>
              </div>
              <div style="font-size: 0.78rem; color: #94a3b8; margin-top: 4px;">
                Visual Similarity: <b>${Math.round((link.similarity_score || 0.88) * 100)}%</b> &bull; ${link.tracking_notes || 'Continuous tracking in sector'}
              </div>
            </div>
          </div>
        `;
      });
    } else {
      html += `
        <div class="timeline-item">
          <div class="timeline-dot" style="background: #10b981;"></div>
          <div class="timeline-content">
            <div style="font-weight: 600; color: #6ee7b7;">Adjacent Cameras Synced</div>
            <div style="font-size: 0.78rem; color: #94a3b8; margin-top: 2px;">
              Surveillance perimeter nodes in Sector 62 on heightened alert. No unauthorized exit detected.
            </div>
          </div>
        </div>
      `;
    }

    timelineBox.innerHTML = html;
  } catch (err) {
    timelineBox.innerHTML = '<div style="color: #ef4444;">Failed to load timeline.</div>';
  }
}

function closeCrossCameraModal() {
  const modal = document.getElementById('crossCameraModal');
  if (modal) modal.classList.remove('active');
}

// ==============================================================================
// 8. BENCHMARKS & CAMERA HEALTH
// ==============================================================================
async function runModelBenchmark() {
  const btnText = document.getElementById('benchmarkBtnText');
  const btnIcon = document.getElementById('benchmarkBtnIcon');
  if (btnText) btnText.textContent = 'Evaluating 15 Cases...';
  if (btnIcon) btnIcon.textContent = '⏳';

  try {
    const res = await fetch('/api/benchmark/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    if (data.success && data.metrics) {
      const m = data.metrics;
      document.getElementById('bmPrecision').textContent = `${(m.precision * 100).toFixed(1)}%`;
      document.getElementById('bmRecall').textContent = `${(m.recall * 100).toFixed(1)}%`;
      document.getElementById('bmF1').textContent = m.f1_score.toFixed(3);
      document.getElementById('bmFPR').textContent = `${(m.fpr * 100).toFixed(1)}%`;
      document.getElementById('bmFNR').textContent = `${(m.fnr * 100).toFixed(1)}%`;
      document.getElementById('bmLatency').textContent = `${m.mean_latency_ms.toFixed(1)} ms`;

      const tsEl = document.getElementById('benchmarkTimestamp');
      if (tsEl) tsEl.textContent = `Evaluated: ${new Date().toLocaleTimeString()} (15 Test Cases)`;

      // Render Table
      const tbody = document.getElementById('benchmarkTableBody');
      if (tbody && data.results) {
        tbody.innerHTML = '';
        data.results.forEach(r => {
          const tr = document.createElement('tr');
          const isPass = r.passed;
          tr.innerHTML = `
            <td style="font-weight: 600; font-size: 0.85rem;">${r.case_name}</td>
            <td><span class="status-badge ${r.category === 'SOS Positive' ? 'red' : 'blue'}">${r.category}</span></td>
            <td style="font-family: 'JetBrains Mono'; font-size: 0.8rem;">${r.expected ? 'SOS Distress' : 'Normal / Benign'}</td>
            <td style="font-family: 'JetBrains Mono'; font-size: 0.8rem; color: ${r.predicted ? '#f87171' : '#34d399'};">
              ${r.predicted ? 'SOS Distress' : 'Normal / Benign'}
            </td>
            <td style="font-family: 'JetBrains Mono'; font-size: 0.8rem;">${Math.round(r.confidence * 100)}%</td>
            <td style="font-family: 'JetBrains Mono'; font-size: 0.8rem;">${r.latency_ms.toFixed(1)} ms</td>
            <td>
              <span class="status-badge ${isPass ? 'green' : 'red'}">${isPass ? 'PASS' : 'FAIL'}</span>
            </td>
          `;
          tbody.appendChild(tr);
        });
      }

      showToast(`Benchmark complete: F1 = ${m.f1_score.toFixed(3)}, FPR = ${(m.fpr * 100).toFixed(1)}%`);
    }
  } catch (err) {
    console.error('Benchmark failed:', err);
    showToast('Benchmark run failed.');
  } finally {
    if (btnText) btnText.textContent = 'Run Benchmark Suite';
    if (btnIcon) btnIcon.textContent = '🚀';
  }
}

async function refreshCameraHealth() {
  const grid = document.getElementById('cameraHealthGrid');
  if (!grid) return;

  try {
    const res = await fetch('/api/camera/health');
    if (!res.ok) return;
    const data = await res.json();
    const networkCams = data.network_cameras || [];

    grid.innerHTML = '';
    networkCams.forEach(cam => {
      const card = document.createElement('div');
      card.className = 'health-card';
      const statusClass = (cam.health_status || 'Healthy').toLowerCase();

      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <b style="font-size: 0.92rem;">${cam.name}</b>
          <span class="health-badge ${statusClass}">${cam.health_status || 'Healthy'}</span>
        </div>
        <div style="font-size: 0.78rem; color: var(--text-muted);">
          ID: <b style="font-family: 'JetBrains Mono';">${cam.id}</b> &bull; ${cam.city} &bull; ${cam.zone || 'Zone A'}
        </div>
        <div style="font-size: 0.78rem; color: var(--text-dim);">
          Installation: ${cam.installation_location || 'Perimeter Pole'} &bull; ${cam.camera_type || 'CCTV-RTSP'}
        </div>
        <div style="display: flex; justify-content: space-between; margin-top: 6px; font-size: 0.75rem; font-family: 'JetBrains Mono';">
          <span>Blur Index: <b>${(cam.blur_score || 145.0).toFixed(1)}</b></span>
          <span style="color: #10b981;">Online &bull; 30 FPS</span>
        </div>
      `;
      grid.appendChild(card);
    });

  } catch (err) {
    console.error('Failed to load camera health:', err);
  }
}

// Register New CCTV Node
function openRegisterCameraModal() {
  const modal = document.getElementById('registerCameraModal');
  if (modal) modal.classList.add('active');
}

function closeRegisterCameraModal() {
  const modal = document.getElementById('registerCameraModal');
  if (modal) modal.classList.remove('active');
}

async function submitRegisterCamera(e) {
  if (e) e.preventDefault();
  const cid = document.getElementById('rcCamId')?.value;
  const name = document.getElementById('rcCamName')?.value;
  const city = document.getElementById('rcCity')?.value || 'Noida';
  const zone = document.getElementById('rcZone')?.value || 'Sector 62';
  const lat = parseFloat(document.getElementById('rcLat')?.value || 28.6280);
  const lon = parseFloat(document.getElementById('rcLon')?.value || 77.3649);
  const org = document.getElementById('rcOrg')?.value || 'Municipal Surveillance';

  try {
    const res = await fetch('/api/camera/network/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        camera_id: cid,
        name: name,
        city: city,
        zone: zone,
        latitude: lat,
        longitude: lon,
        organization: org,
        installation_location: 'Integrated CCTV Stream',
        camera_type: 'CCTV-RTSP',
      }),
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Camera ${cid} registered to network.`);
      closeRegisterCameraModal();
      if (window.refreshControlRoomData) window.refreshControlRoomData();
      refreshCameraHealth();
    } else {
      showToast(data.message || 'Registration failed');
    }
  } catch (err) {
    console.error('Register camera failed:', err);
  }
}

// ==============================================================================
// 9. EMERGENCY CONTACTS & OTP VERIFICATION
// ==============================================================================
async function loadEmergencyContacts() {
  const tbody = document.getElementById('contactsTableBody');
  if (!tbody) return;

  try {
    const res = await fetch('/api/contacts');
    if (!res.ok) return;
    const contacts = await res.json();

    tbody.innerHTML = '';
    if (contacts.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" style="text-align: center; color: var(--text-dim); padding: 24px;">
            No emergency contacts registered. Click "+ Add Contact" above.
          </td>
        </tr>
      `;
      return;
    }

    contacts.forEach(c => {
      const tr = document.createElement('tr');
      const isVerified = !!c.is_verified;

      tr.innerHTML = `
        <td><b style="font-size: 0.88rem;">${c.name}</b></td>
        <td style="font-family: 'JetBrains Mono'; font-size: 0.82rem;">${c.phone}</td>
        <td><span class="status-badge blue">${c.relationship}</span></td>
        <td>${c.is_primary ? '<span class="status-badge green">PRIMARY</span>' : '<span style="color: var(--text-dim);">-</span>'}</td>
        <td>
          <span class="status-badge ${isVerified ? 'green' : 'yellow'}">
            ${isVerified ? '✓ Verified' : 'Pending OTP'}
          </span>
        </td>
        <td>
          <div style="display: flex; gap: 6px;">
            ${!isVerified ? `
              <button class="ctrl-btn" style="padding: 4px 8px; font-size: 0.72rem; background: var(--accent-blue);" onclick="triggerSendContactOtp(${c.id}, '${c.phone}')">Verify OTP</button>
            ` : ''}
            <button class="ctrl-btn danger" style="padding: 4px 8px; font-size: 0.72rem;" onclick="deleteEmergencyContact(${c.id})">Delete</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });

  } catch (err) {
    console.error('Failed to load contacts:', err);
  }
}

function openAddContactModal() {
  const modal = document.getElementById('addContactModal');
  if (modal) modal.classList.add('active');
}

function closeAddContactModal() {
  const modal = document.getElementById('addContactModal');
  if (modal) modal.classList.remove('active');
}

async function submitAddContact(e) {
  if (e) e.preventDefault();
  const name = document.getElementById('contactNameInput')?.value;
  const phone = document.getElementById('contactPhoneInput')?.value;
  const role = document.getElementById('contactRoleInput')?.value || 'Family';
  const isPrimary = document.getElementById('contactPrimaryInput')?.checked || false;

  try {
    const res = await fetch('/api/contacts/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name,
        phone: phone,
        relationship: role,
        is_primary: isPrimary,
      }),
    });
    const data = await res.json();
    if (data.success) {
      closeAddContactModal();
      loadEmergencyContacts();
      // Prompt OTP verification immediately
      triggerSendContactOtp(data.contact_id, phone, data.simulated_otp);
    } else {
      showToast(data.message || 'Failed to add contact');
    }
  } catch (err) {
    console.error('Add contact failed:', err);
  }
}

async function triggerSendContactOtp(contactId, phone, preCode = '') {
  state.activeOtpContactId = contactId;
  const phoneEl = document.getElementById('otpTargetPhone');
  if (phoneEl) phoneEl.textContent = phone;

  let simCode = preCode;
  if (!simCode) {
    try {
      const res = await fetch('/api/contacts/send-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contact_id: contactId }),
      });
      const data = await res.json();
      simCode = data.simulated_otp || '123456';
    } catch (e) {
      simCode = '123456';
    }
  }

  const simCodeEl = document.getElementById('simulatedOtpCode');
  if (simCodeEl) simCodeEl.textContent = simCode;

  const modal = document.getElementById('otpVerifyModal');
  if (modal) modal.classList.add('active');
}

function closeOtpModal() {
  const modal = document.getElementById('otpVerifyModal');
  if (modal) modal.classList.remove('active');
}

async function submitOtpVerification() {
  const code = document.getElementById('otpCodeInput')?.value.trim();
  if (!code || code.length !== 6) {
    showToast('Please enter the 6-digit OTP code.');
    return;
  }

  try {
    const res = await fetch('/api/contacts/verify-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contact_id: state.activeOtpContactId,
        otp: code,
      }),
    });
    const data = await res.json();
    if (data.success) {
      showToast('Contact verified successfully!');
      closeOtpModal();
      loadEmergencyContacts();
    } else {
      showToast(data.message || 'OTP verification failed');
    }
  } catch (err) {
    console.error('OTP verification failed:', err);
  }
}

async function deleteEmergencyContact(contactId) {
  if (!confirm('Are you sure you want to remove this emergency contact?')) return;
  try {
    const res = await fetch('/api/contacts/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contact_id: contactId }),
    });
    if (res.ok) {
      showToast('Contact removed.');
      loadEmergencyContacts();
    }
  } catch (err) {
    console.error('Delete contact failed:', err);
  }
}

// ==============================================================================
// 10. TEST SOS SYSTEM GUIDED WIZARD
// ==============================================================================
function openSOSTestWizard() {
  state.wizardActive = true;
  const modal = document.getElementById('sosTestWizardModal');
  if (modal) modal.classList.add('active');
  // Switch to live camera tab
  switchTab('camera');
}

function closeSOSTestWizard() {
  state.wizardActive = false;
  const modal = document.getElementById('sosTestWizardModal');
  if (modal) modal.classList.remove('active');
}

function updateSOSTestWizard(data) {
  const w1 = document.getElementById('wStep1');
  const w2 = document.getElementById('wStep2');
  const w3 = document.getElementById('wStep3');
  const ind1 = document.getElementById('wInd1');
  const ind2 = document.getElementById('wInd2');
  const ind3 = document.getElementById('wInd3');

  const f1 = data.stage1_frames || 0;
  const f2 = data.stage2_frames || 0;
  const f3 = data.stage3_frames || 0;
  const stage = data.alert_stage || 'GREEN';

  // Step 1: Open Palm
  if (f1 >= 3 || (data.hand_detected && data.fingers_up >= 4)) {
    if (w1) { w1.className = 'wizard-step completed'; }
    if (ind1) { ind1.textContent = '✓ Step 1 Confirmed! (Open Palm Detected)'; ind1.style.color = '#34d399'; }
    if (w2) { w2.className = 'wizard-step active'; }
    if (ind2) { ind2.textContent = 'Now fold thumb across your palm...'; ind2.style.color = '#fbbf24'; }
  } else {
    if (w1) { w1.className = 'wizard-step active'; }
    if (ind1) { ind1.textContent = `Tracking Open Palm: ${f1} / 3 frames...`; }
  }

  // Step 2: Thumb Tuck
  if (f2 >= 3 || stage === 'ORANGE' || stage === 'RED') {
    if (w2) { w2.className = 'wizard-step completed'; }
    if (ind2) { ind2.textContent = '✓ Step 2 Confirmed! (Thumb Tucked in Palm)'; ind2.style.color = '#34d399'; }
    if (w3) { w3.className = 'wizard-step active'; }
    if (ind3) { ind3.textContent = 'Now fold 4 fingers over thumb and hold...'; ind3.style.color = '#f87171'; }
  }

  // Step 3: Closed Fingers
  if (f3 >= 4 || stage === 'RED') {
    if (w3) { w3.className = 'wizard-step completed'; }
    if (ind3) { ind3.textContent = '✓ SOS DISTRESS CONFIRMED (Stage 3 Red!)'; ind3.style.color = '#f87171'; }
  }
}

// Toast helper
function showToast(msg) {
  let toast = document.getElementById('toastNotification');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toastNotification';
    toast.style.cssText = `
      position: fixed; bottom: 24px; right: 24px;
      background: #1e293b; color: #fff; border: 1px solid #3b82f6;
      padding: 12px 20px; border-radius: 8px; font-size: 0.88rem;
      z-index: 9999; box-shadow: 0 4px 15px rgba(0,0,0,0.5);
      transition: all 0.3s ease;
    `;
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.style.opacity = '1';
  setTimeout(() => {
    toast.style.opacity = '0';
  }, 2800);
}

// ==============================================================================
// 11. INITIALIZATION ON PAGE LOAD
// ==============================================================================
window.addEventListener('DOMContentLoaded', () => {
  // Navigation tabs
  document.querySelectorAll('.nav-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Mode buttons
  document.querySelectorAll('.mode-pill-btn').forEach(btn => {
    btn.addEventListener('click', () => setMode(btn.dataset.mode));
  });

  // Sensitivity slider
  const slider = document.getElementById('sensitivitySlider');
  if (slider) slider.addEventListener('input', onSensitivityChange);

  // Initialize mini map
  initMiniMap();

  // Start polling telemetry every 150ms
  setInterval(pollTelemetry, 150);

  // Unlock AudioContext on first user interaction
  document.body.addEventListener('click', () => initAudio(), { once: true });
});
