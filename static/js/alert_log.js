/**
 * Alert Log & Settings Management Logic
 * =====================================
 * Handles SQLite incident history rendering, real-time filtering & search,
 * CSV export, snapshot preview modal, and settings persistence.
 */

let currentFilter = 'all';
let currentSearch = '';

window.loadAlertLogs = async function() {
  const tableBody = document.getElementById('alertTableBody');
  if (!tableBody) return;

  try {
    const url = `/api/alerts?status=${encodeURIComponent(currentFilter)}&search=${encodeURIComponent(currentSearch)}`;
    const res = await fetch(url);
    if (!res.ok) return;
    const logs = await res.json();

    tableBody.innerHTML = '';
    if (logs.length === 0) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; color: var(--text-dim); padding: 30px;">
            No alert logs found for current filter.
          </td>
        </tr>
      `;
      return;
    }

    logs.forEach(item => {
      const tr = document.createElement('tr');
      const badgeClass = item.status === 'Sent' ? 'red' : (item.status === 'Cancelled' ? 'yellow' : 'green');

      tr.innerHTML = `
        <td style="font-family: 'JetBrains Mono'; font-weight: 600;">#${item.id}</td>
        <td style="color: var(--text-muted); font-size: 0.8rem;">${item.timestamp}</td>
        <td>
          <div style="font-weight: 500;">${item.camera_name}</div>
          <div style="font-size: 0.75rem; color: var(--text-dim);">${item.location_address}</div>
        </td>
        <td><span style="font-size: 0.82rem; font-weight: 600;">${item.gesture_type}</span></td>
        <td>
          ${item.snapshot_path ? `
            <img class="thumb-preview" src="/evidence/${item.snapshot_path}" alt="Snapshot" onclick="viewSnapshotModal('/evidence/${item.snapshot_path}')">
          ` : '<span style="color: var(--text-dim); font-size: 0.75rem;">None</span>'}
        </td>
        <td><span class="status-badge ${badgeClass}">${item.status}</span></td>
        <td style="font-size: 0.78rem; color: var(--text-muted); max-width: 180px;">${item.notes || '-'}</td>
      `;
      tableBody.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to load alert logs:', err);
  }
};

function filterAlerts(status) {
  currentFilter = status;
  document.querySelectorAll('.log-filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.status === status);
  });
  window.loadAlertLogs();
}

function onSearchInput(e) {
  currentSearch = e.target.value.trim();
  window.loadAlertLogs();
}

function exportAlertsCSV() {
  window.location.href = '/api/alerts/export';
}

function printAlertReport() {
  window.print();
}

function viewSnapshotModal(src) {
  let modal = document.getElementById('snapshotModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'snapshotModal';
    modal.className = 'modal-backdrop';
    modal.innerHTML = `
      <div class="modal-card" style="max-width: 650px; text-align: center;">
        <h3 style="margin-bottom: 14px; font-family: 'Outfit';">Incident Evidence Snapshot</h3>
        <img id="snapshotModalImg" style="width: 100%; border-radius: 8px; border: 1px solid var(--border-color);" src="">
        <button class="ctrl-btn" style="margin-top: 16px;" onclick="closeSnapshotModal()">Close</button>
      </div>
    `;
    document.body.appendChild(modal);
  }
  document.getElementById('snapshotModalImg').src = src;
  modal.classList.add('active');
}

function closeSnapshotModal() {
  const modal = document.getElementById('snapshotModal');
  if (modal) modal.classList.remove('active');
}

// ==============================================================================
// SETTINGS FORM MANAGEMENT
// ==============================================================================
async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) return;
    const cfg = await res.json();

    const phoneInput = document.getElementById('settingPhone');
    const testModeInput = document.getElementById('settingTestMode');
    const dryRunInput = document.getElementById('settingDryRun');
    const sirenInput = document.getElementById('settingSiren');
    const countdownInput = document.getElementById('settingCountdown');

    if (phoneInput) phoneInput.value = cfg.alert_recipient_phone || '';
    if (testModeInput) testModeInput.checked = !!cfg.test_mode;
    if (dryRunInput) dryRunInput.checked = !!cfg.dry_run;
    if (sirenInput) sirenInput.checked = !!cfg.siren_enabled;
    if (countdownInput) countdownInput.value = cfg.countdown_duration || 10;
  } catch (err) {
    console.error('Load settings error:', err);
  }
}

async function saveSettings(e) {
  if (e) e.preventDefault();
  const phone = document.getElementById('settingPhone')?.value || '';
  const testMode = document.getElementById('settingTestMode')?.checked || false;
  const dryRun = document.getElementById('settingDryRun')?.checked || false;
  const siren = document.getElementById('settingSiren')?.checked || false;
  const countdown = parseFloat(document.getElementById('settingCountdown')?.value || 10);

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        alert_recipient_phone: phone,
        test_mode: testMode,
        dry_run: dryRun,
        siren_enabled: siren,
        countdown_duration: countdown,
      }),
    });
    if (res.ok) {
      showToast('Settings saved successfully!');
    }
  } catch (err) {
    console.error('Save settings error:', err);
  }
}

window.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  const searchInput = document.getElementById('logSearchInput');
  if (searchInput) {
    searchInput.addEventListener('input', onSearchInput);
  }
  const settingsForm = document.getElementById('settingsForm');
  if (settingsForm) {
    settingsForm.addEventListener('submit', saveSettings);
  }
});
