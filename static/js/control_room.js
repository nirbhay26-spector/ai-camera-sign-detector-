/**
 * Control Room Dashboard Logic
 * =============================
 * Interactive Leaflet multi-camera map for Indian cities, live status markers,
 * Esri satellite imagery layer toggle, instant alert simulations, and metrics counters.
 */

window.controlRoomMap = null;
const cameraMarkers = {};
let currentMapLayer = 'dark'; // 'dark' or 'satellite'
let darkTileLayer = null;
let satelliteTileLayer = null;

async function initControlRoomMap() {
  const container = document.getElementById('controlRoomMap');
  if (!container || typeof L === 'undefined') return;

  // Center map on India
  window.controlRoomMap = L.map('controlRoomMap', {
    zoomControl: true,
  }).setView([21.7679, 78.8718], 5);

  // 1. OpenStreetMap Vector tiles (100% Free, No Watermark, No API Key Required)
  darkTileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors',
  }).addTo(window.controlRoomMap);

  // 2. Esri World Imagery (Satellite Layer)
  satelliteTileLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 18,
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
  });

  await refreshControlRoomData();
}

function toggleSatelliteLayer() {
  if (!window.controlRoomMap || !darkTileLayer || !satelliteTileLayer) return;

  const btn = document.getElementById('btnToggleSatellite');
  if (currentMapLayer === 'dark') {
    window.controlRoomMap.removeLayer(darkTileLayer);
    window.controlRoomMap.addLayer(satelliteTileLayer);
    currentMapLayer = 'satellite';
    if (btn) btn.innerHTML = '<span>🌑</span> Switch to Dark Grid';
    if (typeof showToast === 'function') {
      showToast('Switched to Esri World Imagery Satellite Layer.');
    }
  } else {
    window.controlRoomMap.removeLayer(satelliteTileLayer);
    window.controlRoomMap.addLayer(darkTileLayer);
    currentMapLayer = 'dark';
    if (btn) btn.innerHTML = '<span>🛰️</span> Switch to Satellite';
    if (typeof showToast === 'function') {
      showToast('Switched to Dark Vector Grid.');
    }
  }
}

async function refreshControlRoomData() {
  try {
    // 1. Fetch Cameras
    const camRes = await fetch('/api/cameras');
    if (!camRes.ok) return;
    const cameras = await camRes.json();

    // 2. Fetch Metrics
    const metRes = await fetch('/api/metrics');
    if (metRes.ok) {
      const metrics = await metRes.json();
      updateMetricCounters(metrics);
    }

    // Render Markers & Sidebar
    renderCameraMarkers(cameras);
    renderCameraSidebar(cameras);
  } catch (err) {
    console.error('Failed to load control room data:', err);
  }
}

function updateMetricCounters(metrics) {
  const elTotal = document.getElementById('metricTotalCameras');
  const elActive = document.getElementById('metricActiveAlerts');
  const elToday = document.getElementById('metricAlertsToday');
  const elAvg = document.getElementById('metricAvgResponse');

  if (elTotal) elTotal.textContent = metrics.total_cameras;
  if (elActive) elActive.textContent = metrics.active_alerts;
  if (elToday) elToday.textContent = metrics.alerts_today;
  if (elAvg) elAvg.textContent = metrics.avg_response_time;
}

function renderCameraMarkers(cameras) {
  if (!window.controlRoomMap) return;

  cameras.forEach(cam => {
    const isAlert = cam.status === 'Alert';
    const isHealthIssue = cam.health_status && cam.health_status !== 'Healthy';
    const markerColor = isAlert ? '#ef4444' : (isHealthIssue ? '#f59e0b' : '#10b981');
    const radius = isAlert ? 14 : 9;

    if (cameraMarkers[cam.id]) {
      cameraMarkers[cam.id].setStyle({
        color: markerColor,
        fillColor: markerColor,
        radius: radius,
      });
    } else {
      const marker = L.circleMarker([cam.latitude, cam.longitude], {
        radius: radius,
        color: markerColor,
        fillColor: markerColor,
        fillOpacity: 0.85,
        weight: 3,
      }).addTo(window.controlRoomMap);

      marker.bindPopup(`
        <div style="font-family: 'Inter', sans-serif; color: #1e293b; min-width: 200px;">
          <h4 style="margin: 0 0 4px; font-weight: 700; color: #0f172a;">${cam.name}</h4>
          <p style="margin: 0 0 4px; font-size: 0.8rem; color: #64748b;">
            <b>ID:</b> ${cam.id} &bull; ${cam.city} (${cam.zone || 'Zone A'})
          </p>
          <p style="margin: 0 0 4px; font-size: 0.78rem; color: #475569;">
            <b>Org:</b> ${cam.organization || 'Authorized Security'}
          </p>
          <p style="margin: 0 0 6px; font-size: 0.78rem; color: #475569;">
            <b>Location:</b> ${cam.installation_location || 'Perimeter Pole'} &bull; ${cam.camera_type || 'CCTV-RTSP'}
          </p>
          <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #e2e8f0; padding-top: 4px;">
            <span style="font-size: 0.8rem;">Status: <b style="color: ${isAlert ? '#dc2626' : '#16a34a'};">${cam.status}</b></span>
            <span style="font-size: 0.74rem; color: #64748b;">Blur: ${(cam.blur_score || 140).toFixed(0)}</span>
          </div>
        </div>
      `);

      cameraMarkers[cam.id] = marker;
    }
  });
}

function renderCameraSidebar(cameras) {
  const list = document.getElementById('cameraListScroll');
  if (!list) return;

  list.innerHTML = '';
  cameras.forEach(cam => {
    const isAlert = cam.status === 'Alert';
    const card = document.createElement('div');
    card.className = `camera-item-card ${isAlert ? 'alert-active' : ''}`;

    card.innerHTML = `
      <div>
        <div style="font-weight: 600; font-size: 0.9rem;">${cam.name}</div>
        <div style="font-size: 0.76rem; color: var(--text-muted);">
          ${cam.city} &bull; ${cam.id} &bull; <span style="color: #93c5fd;">${cam.zone || 'Zone A'}</span>
        </div>
        <div style="font-size: 0.72rem; color: var(--text-dim); margin-top: 2px;">
          ${cam.installation_location || 'Perimeter Pole'} &bull; ${cam.organization ? cam.organization.substring(0, 22) + '...' : ''}
        </div>
      </div>
      <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">
        <span class="status-badge ${isAlert ? 'red' : 'green'}">${cam.status}</span>
        ${isAlert ? `<button class="ctrl-btn" style="padding: 3px 8px; font-size: 0.7rem;" onclick="resolveCameraAlert('${cam.id}', event)">Resolve</button>` : ''}
      </div>
    `;

    card.addEventListener('click', () => {
      if (window.controlRoomMap) {
        window.controlRoomMap.flyTo([cam.latitude, cam.longitude], 12, { duration: 1.2 });
        if (cameraMarkers[cam.id]) {
          cameraMarkers[cam.id].openPopup();
        }
      }
    });

    list.appendChild(card);
  });
}

// "🚨 Simulate Alert" button handler
async function simulateAlert(cameraId) {
  try {
    const camId = cameraId || 'CAM-01'; // Uses live local device camera by default
    const res = await fetch('/api/alert/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ camera_id: camId, phone: '+919876543210' }),
    });
    const data = await res.json();
    if (data.success) {
      // Trigger prominent success notification banner
      if (typeof showEmergencyDispatchBanner === 'function') {
        showEmergencyDispatchBanner(data);
      }
      if (typeof showToast === 'function') {
        showToast(data.message);
      }
      await refreshControlRoomData();

      // Pan to alerting camera
      if (window.controlRoomMap && data.camera) {
        window.controlRoomMap.flyTo([data.camera.latitude, data.camera.longitude], 12, { duration: 1.5 });
      }
    }
  } catch (err) {
    console.error('Simulation error:', err);
  }
}

async function resolveCameraAlert(camId, e) {
  if (e) e.stopPropagation();
  try {
    const res = await fetch('/api/camera/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ camera_id: camId }),
    });
    if (res.ok) {
      if (typeof showToast === 'function') {
        showToast(`Camera ${camId} marked resolved.`);
      }
      await refreshControlRoomData();
    }
  } catch (err) {
    console.error('Resolve error:', err);
  }
}

window.addEventListener('DOMContentLoaded', () => {
  initControlRoomMap();
  setInterval(refreshControlRoomData, 3000);
});
