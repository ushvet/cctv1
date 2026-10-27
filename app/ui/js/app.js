/**
 * Hikvision AI CCTV Platform — Core SPA Controller
 * Manages navigation, WebSocket connection, data fetching,
 * toast notifications, and modal interactions.
 */

// ============================================================
// API Configuration
// ============================================================
const API_BASE = window.location.origin;
const WS_URL = `ws://${window.location.host}/ws/events`;

// ============================================================
// State
// ============================================================
let ws = null;
let wsReconnectTimer = null;
let currentPage = 'dashboard';
let eventsPage = 1;

// ============================================================
// Initialization
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    connectWebSocket();
    loadDashboardData();

    // Search enter key
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') runSearch();
        });
    }
});

// ============================================================
// Navigation
// ============================================================
function initNavigation() {
    document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
        btn.addEventListener('click', () => {
            navigateTo(btn.dataset.page);
        });
    });
}

function navigateTo(page) {
    // Update nav active state
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navBtn = document.querySelector(`.nav-item[data-page="${page}"]`);
    if (navBtn) navBtn.classList.add('active');

    // Show target page
    document.querySelectorAll('.page-content').forEach(p => p.classList.remove('active'));
    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add('active');

    currentPage = page;

    // Load page-specific data
    switch (page) {
        case 'dashboard': loadDashboardData(); break;
        case 'cameras': loadCameras(); break;
        case 'events': loadEvents(); break;
        case 'faces': loadFaces(); break;
        case 'plates': loadPlates(); break;
    }
}

// ============================================================
// WebSocket — Real-time AI Event Stream
// ============================================================
function connectWebSocket() {
    if (ws && ws.readyState <= 1) return;

    try {
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            updateWsBadge(true);
            console.log('[WS] Connected to event stream');
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleWsMessage(data);
            } catch (e) {
                console.warn('[WS] Invalid message:', e);
            }
        };

        ws.onclose = () => {
            updateWsBadge(false);
            console.log('[WS] Disconnected — reconnecting in 5s');
            wsReconnectTimer = setTimeout(connectWebSocket, 5000);
        };

        ws.onerror = () => {
            updateWsBadge(false);
        };
    } catch (e) {
        console.error('[WS] Connection error:', e);
        wsReconnectTimer = setTimeout(connectWebSocket, 5000);
    }
}

function updateWsBadge(connected) {
    const badge = document.getElementById('ws-badge');
    const text = document.getElementById('ws-status-text');
    const dot = document.getElementById('status-dot');

    if (connected) {
        badge.className = 'connection-badge connected';
        text.textContent = 'Live';
        dot.className = 'status-dot online';
    } else {
        badge.className = 'connection-badge disconnected';
        text.textContent = 'Offline';
        dot.className = 'status-dot offline';
    }
}

function handleWsMessage(data) {
    if (data.type === 'ai_alert') {
        // Show toast notification
        showToast(
            getTargetIcon(data.target_type),
            `${formatEventType(data.event_type)}`,
            `${data.target_type} detected on ${data.camera_name} (${(data.confidence * 100).toFixed(0)}%)`,
        );

        // Prepend to live alert feed
        prependAlertItem(data);

        // Refresh stats if on dashboard
        if (currentPage === 'dashboard') {
            loadStats();
        }
    } else if (data.type === 'pong') {
        // Heartbeat response
    }
}

// ============================================================
// API Helpers
// ============================================================
async function apiFetch(path, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${path}`, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        });
        if (!response.ok) {
            const errText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errText}`);
        }
        if (response.status === 204) return null;
        return await response.json();
    } catch (error) {
        console.error(`API Error [${path}]:`, error);
        throw error;
    }
}

// ============================================================
// Dashboard Data Loading
// ============================================================
async function loadDashboardData() {
    await Promise.all([loadStats(), loadDashboardCameras(), loadRecentAlerts()]);
}

async function loadStats() {
    try {
        const [stats, cameras] = await Promise.all([
            apiFetch('/api/events/stats'),
            apiFetch('/api/cameras?active_only=true'),
        ]);

        document.getElementById('stat-cameras').textContent = cameras.length;
        document.getElementById('stat-today').textContent = stats.today_events;
        document.getElementById('stat-humans').textContent = stats.humans_today;
        document.getElementById('stat-vehicles').textContent = stats.vehicles_today;
        document.getElementById('stat-faces').textContent = stats.faces_today;
        document.getElementById('stat-unack').textContent = stats.unacknowledged;
        document.getElementById('header-cam-count').textContent = cameras.length;
        document.getElementById('header-today-count').textContent = stats.today_events;
    } catch (e) {
        console.warn('Failed to load stats:', e);
    }
}

async function loadDashboardCameras() {
    try {
        const cameras = await apiFetch('/api/cameras?active_only=true');
        const grid = document.getElementById('dashboard-camera-grid');
        if (!cameras.length) {
            grid.innerHTML = `
                <div class="empty-state" style="grid-column:1/-1;">
                    <div class="icon">📷</div>
                    <div class="title">No cameras registered</div>
                    <div class="description">Add cameras via the Cameras tab or API</div>
                </div>`;
            return;
        }
        grid.innerHTML = cameras.slice(0, 4).map(cam => buildCameraCard(cam, 'dash', false)).join('');
        // Initialize WebRTC streams for dashboard cameras
        cameras.slice(0, 4).forEach(cam => initCameraStream(cam, 'dash'));
    } catch (e) {
        console.warn('Failed to load dashboard cameras:', e);
    }
}

async function loadRecentAlerts() {
    try {
        const data = await apiFetch('/api/events?per_page=15&acknowledged=false');
        const feed = document.getElementById('live-alert-feed');
        if (!data.events.length) {
            feed.innerHTML = `
                <div class="empty-state">
                    <div class="icon">✅</div>
                    <div class="title">All clear</div>
                    <div class="description">No unacknowledged events</div>
                </div>`;
            return;
        }
        feed.innerHTML = data.events.map(evt => buildAlertItem(evt)).join('');
    } catch (e) {
        console.warn('Failed to load alerts:', e);
    }
}

// ============================================================
// Camera Management
// ============================================================
async function loadCameras() {
    try {
        const cameras = await apiFetch('/api/cameras');
        const grid = document.getElementById('cameras-full-grid');
        if (!cameras.length) {
            grid.innerHTML = `
                <div class="empty-state" style="grid-column:1/-1;">
                    <div class="icon">📷</div>
                    <div class="title">No cameras registered</div>
                    <div class="description">Click "+ Add Camera" to register your first camera</div>
                </div>`;
            return;
        }
        grid.innerHTML = cameras.map(cam => buildCameraCard(cam, 'live', true)).join('');
        // Initialize WebRTC stream for each camera on the Live Cameras page
        cameras.forEach(cam => initCameraStream(cam, 'live'));
    } catch (e) {
        console.warn('Failed to load cameras:', e);
    }
}

function buildCameraCard(cam, context = 'dash', showActions = false) {
    const statusBadges = cam.is_active
        ? '<span class="camera-badge badge-live">● LIVE</span><span class="camera-badge badge-ai">AI</span>'
        : '<span class="camera-badge" style="background:rgba(100,100,100,0.7);color:#ccc;">OFFLINE</span>';

    const actions = showActions ? `
        <div class="camera-actions">
            <button onclick="triggerSnapshot('${cam.id}')" title="Capture Snapshot">📸</button>
            <button onclick="deleteCameraConfirm('${cam.id}','${cam.name}')" title="Remove">🗑️</button>
        </div>` : '';

    const frigateId = cam.name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');

    return `
        <div class="camera-card" id="cam-card-${context}-${cam.id}">
            <div class="camera-feed" id="cam-feed-${context}-${cam.id}">
                <div class="placeholder">
                    <div class="icon">📷</div>
                    <div>Loading stream...</div>
                </div>
                <div class="camera-overlay">
                    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
                        ${statusBadges}
                        <span class="camera-badge badge-intercom-active" id="talk-badge-${context}-${cam.id}" style="display:none;">🔴 TALKING</span>
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;">
                        <button class="btn-talk" id="talk-btn-${context}-${cam.id}" onclick="toggleCameraIntercom('${cam.id}','${escapeHtml(cam.name)}','${context}')" title="Two-way audio: Speak through camera speaker">🎙️ Talk</button>
                        <button onclick="triggerSnapshot('${cam.id}')" class="btn-snap" title="Capture High-Res Snapshot" style="background:rgba(0,0,0,0.65);border:1px solid rgba(255,255,255,0.25);color:#fff;border-radius:4px;padding:2px 7px;cursor:pointer;font-size:0.85rem;">📸</button>
                        <a href="http://${window.location.hostname}:1984/stream.html?src=${frigateId}&mode=webrtc" target="_blank"
                           title="Open stream in go2rtc standalone window"
                           style="background:rgba(0,0,0,0.65);border:1px solid rgba(255,255,255,0.25);color:#38bdf8;border-radius:4px;padding:2px 7px;font-size:0.85rem;text-decoration:none;display:inline-flex;align-items:center;">↗️</a>
                        <span class="camera-badge badge-rec">REC</span>
                    </div>
                </div>
            </div>
            <div class="camera-info">
                <div>
                    <div class="camera-name">${escapeHtml(cam.name)}</div>
                    <div class="camera-location">${escapeHtml(cam.location || `Ch${cam.channel_number} @ ${cam.recorder_ip}`)}</div>
                </div>
                ${actions}
            </div>
        </div>`;
}

async function triggerSnapshot(cameraId) {
    try {
        showToast('📸', 'Snapshot', 'Capturing high-res snapshot...');
        const result = await apiFetch(`/api/cameras/${cameraId}/snapshot`, { method: 'POST' });
        showToast('✅', 'Snapshot Captured', result.snapshot_path || 'Saved successfully');
    } catch (e) {
        showToast('❌', 'Snapshot Failed', e.message);
    }
}

function openAddCameraModal() {
    showModal(`
        <div class="card-header"><div class="card-title">📷 Add New Camera</div></div>
        <form onsubmit="submitAddCamera(event)">
            <div class="form-group">
                <label class="form-label">Camera Name</label>
                <input class="form-input" id="cam-name" placeholder="e.g. Front Gate Panoramic" required>
            </div>
            <div class="form-group">
                <label class="form-label">Recorder Type</label>
                <select class="form-select" id="cam-type">
                    <option value="hikvision_nvr">Hikvision NVR</option>
                    <option value="hikvision_dvr">Hikvision DVR</option>
                    <option value="standalone_ip">Standalone IP Camera</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">Recorder / Camera IP</label>
                <input class="form-input" id="cam-ip" placeholder="192.168.1.100" required>
            </div>
            <div class="form-group">
                <label class="form-label">Channel Number</label>
                <input class="form-input" type="number" id="cam-channel" value="1" min="1" max="32" required>
            </div>
            <div class="form-group">
                <label class="form-label">RTSP Main Stream URL</label>
                <input class="form-input" id="cam-rtsp-main" placeholder="rtsp://admin:pass@ip:554/Streaming/Channels/101" required>
            </div>
            <div class="form-group">
                <label class="form-label">RTSP Sub Stream URL</label>
                <input class="form-input" id="cam-rtsp-sub" placeholder="rtsp://admin:pass@ip:554/Streaming/Channels/102" required>
            </div>
            <div class="form-group">
                <label class="form-label">Location / Notes</label>
                <input class="form-input" id="cam-location" placeholder="Main entrance">
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
                <button type="button" class="btn btn-ghost" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Add Camera</button>
            </div>
        </form>
    `);
}

async function submitAddCamera(e) {
    e.preventDefault();
    const data = {
        name: document.getElementById('cam-name').value,
        recorder_type: document.getElementById('cam-type').value,
        recorder_ip: document.getElementById('cam-ip').value,
        channel_number: parseInt(document.getElementById('cam-channel').value),
        rtsp_main_url: document.getElementById('cam-rtsp-main').value,
        rtsp_sub_url: document.getElementById('cam-rtsp-sub').value,
        location: document.getElementById('cam-location').value,
    };
    try {
        await apiFetch('/api/cameras', { method: 'POST', body: JSON.stringify(data) });
        closeModal();
        showToast('✅', 'Camera Added', `${data.name} registered successfully`);
        loadCameras();
        loadStats();
    } catch (e) {
        showToast('❌', 'Error', e.message);
    }
}

async function deleteCameraConfirm(id, name) {
    if (!confirm(`Remove camera "${name}"? This will delete all associated events.`)) return;
    try {
        await apiFetch(`/api/cameras/${id}`, { method: 'DELETE' });
        showToast('🗑️', 'Camera Removed', name);
        loadCameras();
    } catch (e) {
        showToast('❌', 'Error', e.message);
    }
}

// ============================================================
// Events Management
// ============================================================
async function loadEvents(page = 1) {
    eventsPage = page;
    const filterType = document.getElementById('event-filter-type')?.value || '';
    const params = new URLSearchParams({ page, per_page: 30 });
    if (filterType) params.set('target_type', filterType);

    try {
        const data = await apiFetch(`/api/events?${params}`);
        const tbody = document.getElementById('events-tbody');

        if (!data.events.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No events found</td></tr>';
            return;
        }

        tbody.innerHTML = data.events.map(evt => `
            <tr>
                <td style="font-family:var(--font-mono);font-size:0.78rem;">
                    ${formatTimestamp(evt.timestamp)}
                </td>
                <td>${escapeHtml(evt.camera_name || '—')}</td>
                <td style="font-size:0.78rem;color:var(--text-muted);">${formatEventType(evt.event_source)}</td>
                <td><span class="target-badge ${evt.target_type}">${evt.target_type}</span></td>
                <td>
                    <span class="alert-confidence">${(evt.confidence * 100).toFixed(0)}%</span>
                </td>
                <td>${evt.is_acknowledged
                    ? '<span style="color:var(--accent-emerald);">✓</span>'
                    : '<span style="color:var(--accent-amber);">●</span>'}
                </td>
                <td>
                    ${!evt.is_acknowledged
                        ? `<button class="btn btn-ghost" style="padding:2px 8px;font-size:0.72rem;" onclick="ackEvent('${evt.id}')">Ack</button>`
                        : ''}
                </td>
            </tr>
        `).join('');

        // Pagination
        const totalPages = Math.ceil(data.total / data.per_page);
        renderPagination('events-pagination', data.page, totalPages, loadEvents);
    } catch (e) {
        console.warn('Failed to load events:', e);
    }
}

async function ackEvent(id) {
    try {
        await apiFetch(`/api/events/${id}/acknowledge`, { method: 'POST' });
        loadEvents(eventsPage);
        loadStats();
    } catch (e) {
        showToast('❌', 'Error', e.message);
    }
}

async function acknowledgeAll() {
    try {
        const result = await apiFetch('/api/events/acknowledge-all', { method: 'POST' });
        showToast('✅', 'Acknowledged', `${result.acknowledged_count} events acknowledged`);
        loadEvents(eventsPage);
        loadStats();
        loadRecentAlerts();
    } catch (e) {
        showToast('❌', 'Error', e.message);
    }
}

// ============================================================
// Faces Management
// ============================================================
async function loadFaces() {
    try {
        const faces = await apiFetch('/api/faces');
        const tbody = document.getElementById('faces-tbody');

        // Update category counts
        document.getElementById('face-total').textContent = faces.length;
        document.getElementById('face-vip').textContent = faces.filter(f => f.category === 'vip').length;
        document.getElementById('face-staff').textContent = faces.filter(f => f.category === 'staff').length;
        document.getElementById('face-blacklist').textContent = faces.filter(f => f.category === 'blacklist').length;

        if (!faces.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No faces enrolled yet</td></tr>';
            return;
        }

        tbody.innerHTML = faces.map(face => `
            <tr>
                <td>
                    ${face.sample_image_path
                        ? `<img src="/media/${face.sample_image_path.split('/media/').pop()}" 
                               style="width:40px;height:40px;border-radius:50%;object-fit:cover;">`
                        : '<div style="width:40px;height:40px;border-radius:50%;background:var(--bg-tertiary);display:flex;align-items:center;justify-content:center;">👤</div>'}
                </td>
                <td style="font-weight:600;">${escapeHtml(face.name)}</td>
                <td><span class="category-badge ${face.category}">${face.category}</span></td>
                <td style="font-family:var(--font-mono);">${face.detection_count}</td>
                <td style="font-size:0.78rem;color:var(--text-muted);">${formatTimestamp(face.created_at)}</td>
                <td>
                    <button class="btn btn-ghost" style="padding:2px 8px;font-size:0.72rem;"
                            onclick="deleteFace('${face.id}','${escapeHtml(face.name)}')">🗑️</button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        console.warn('Failed to load faces:', e);
    }
}

function openEnrollFaceModal() {
    showModal(`
        <div class="card-header"><div class="card-title">👤 Enroll New Face</div></div>
        <form id="enroll-face-form" onsubmit="submitEnrollFace(event)">
            <div class="form-group">
                <label class="form-label">Name</label>
                <input class="form-input" id="face-name" placeholder="John Doe" required>
            </div>
            <div class="form-group">
                <label class="form-label">Category</label>
                <select class="form-select" id="face-category">
                    <option value="general">General</option>
                    <option value="vip">VIP</option>
                    <option value="staff">Staff</option>
                    <option value="family">Family</option>
                    <option value="blacklist">Blacklist</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">Face Photo</label>
                <input class="form-input" type="file" id="face-photo" accept="image/*" required
                       style="padding:8px;">
            </div>
            <div class="form-group">
                <label class="form-label">Notes (optional)</label>
                <input class="form-input" id="face-notes" placeholder="e.g. Building A resident">
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
                <button type="button" class="btn btn-ghost" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Enroll Face</button>
            </div>
        </form>
    `);
}

async function submitEnrollFace(e) {
    e.preventDefault();
    const formData = new FormData();
    formData.append('name', document.getElementById('face-name').value);
    formData.append('category', document.getElementById('face-category').value);
    formData.append('notes', document.getElementById('face-notes').value);
    formData.append('photo', document.getElementById('face-photo').files[0]);

    try {
        const response = await fetch(`${API_BASE}/api/faces/enroll`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Enrollment failed');
        }
        closeModal();
        showToast('✅', 'Face Enrolled', 'Face added to watchlist');
        loadFaces();
    } catch (e) {
        showToast('❌', 'Enrollment Failed', e.message);
    }
}

async function deleteFace(id, name) {
    if (!confirm(`Remove "${name}" from face registry?`)) return;
    try {
        await apiFetch(`/api/faces/${id}`, { method: 'DELETE' });
        showToast('🗑️', 'Face Removed', name);
        loadFaces();
    } catch (e) {
        showToast('❌', 'Error', e.message);
    }
}

// ============================================================
// Plates Management
// ============================================================
async function loadPlates() {
    try {
        const [plates, detections] = await Promise.all([
            apiFetch('/api/plates'),
            apiFetch('/api/plates/detections?limit=20'),
        ]);

        // Plates table
        const tbody = document.getElementById('plates-tbody');
        if (!plates.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No plates registered</td></tr>';
        } else {
            tbody.innerHTML = plates.map(plate => `
                <tr>
                    <td style="font-family:var(--font-mono);font-weight:700;font-size:1rem;letter-spacing:1px;">
                        ${escapeHtml(plate.plate_number)}
                    </td>
                    <td>${escapeHtml(plate.owner_name || '—')}</td>
                    <td><span class="category-badge ${plate.category}">${plate.category}</span></td>
                    <td style="font-size:0.8rem;color:var(--text-muted);">${escapeHtml(plate.vehicle_description || '—')}</td>
                    <td style="font-family:var(--font-mono);">${plate.detection_count}</td>
                    <td style="font-size:0.78rem;color:var(--text-muted);">${plate.last_seen ? formatTimestamp(plate.last_seen) : 'Never'}</td>
                    <td>
                        <button class="btn btn-ghost" style="padding:2px 8px;font-size:0.72rem;"
                                onclick="deletePlate('${plate.id}')">🗑️</button>
                    </td>
                </tr>
            `).join('');
        }

        // Detections table
        const detTbody = document.getElementById('plate-detections-tbody');
        if (!detections.length) {
            detTbody.innerHTML = '<tr><td colspan="4" class="empty-state">No detections yet</td></tr>';
        } else {
            detTbody.innerHTML = detections.map(d => `
                <tr>
                    <td style="font-family:var(--font-mono);font-weight:600;">${escapeHtml(d.detected_text)}</td>
                    <td>${d.confidence ? (d.confidence * 100).toFixed(0) + '%' : '—'}</td>
                    <td>${d.matched_category
                        ? `<span class="category-badge ${d.matched_category}">${d.matched_category}</span>`
                        : '<span style="color:var(--text-muted);">Unknown</span>'}</td>
                    <td style="font-size:0.78rem;">${formatTimestamp(d.created_at)}</td>
                </tr>
            `).join('');
        }
    } catch (e) {
        console.warn('Failed to load plates:', e);
    }
}

function openAddPlateModal() {
    showModal(`
        <div class="card-header"><div class="card-title">🚗 Register License Plate</div></div>
        <form onsubmit="submitAddPlate(event)">
            <div class="form-group">
                <label class="form-label">Plate Number</label>
                <input class="form-input" id="plate-number" placeholder="MH 12 AB 1234"
                       style="font-family:var(--font-mono);font-size:1.1rem;letter-spacing:2px;text-transform:uppercase;" required>
            </div>
            <div class="form-group">
                <label class="form-label">Owner Name</label>
                <input class="form-input" id="plate-owner" placeholder="Vehicle owner name">
            </div>
            <div class="form-group">
                <label class="form-label">Category</label>
                <select class="form-select" id="plate-category">
                    <option value="registered">Registered</option>
                    <option value="whitelist">Whitelist</option>
                    <option value="blacklist">Blacklist</option>
                    <option value="resident">Resident</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">Vehicle Description</label>
                <input class="form-input" id="plate-vehicle" placeholder="e.g. Black Toyota Innova">
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
                <button type="button" class="btn btn-ghost" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Register Plate</button>
            </div>
        </form>
    `);
}

async function submitAddPlate(e) {
    e.preventDefault();
    const data = {
        plate_number: document.getElementById('plate-number').value,
        owner_name: document.getElementById('plate-owner').value,
        category: document.getElementById('plate-category').value,
        vehicle_description: document.getElementById('plate-vehicle').value,
    };
    try {
        await apiFetch('/api/plates', { method: 'POST', body: JSON.stringify(data) });
        closeModal();
        showToast('✅', 'Plate Registered', data.plate_number);
        loadPlates();
    } catch (e) {
        showToast('❌', 'Error', e.message);
    }
}

async function deletePlate(id) {
    if (!confirm('Remove this plate from the registry?')) return;
    try {
        await apiFetch(`/api/plates/${id}`, { method: 'DELETE' });
        showToast('🗑️', 'Plate Removed', '');
        loadPlates();
    } catch (e) {
        showToast('❌', 'Error', e.message);
    }
}

// ============================================================
// Alert Feed Helpers
// ============================================================
function buildAlertItem(evt) {
    const ack = evt.is_acknowledged ? '' : 'unread';
    return `
        <div class="alert-item ${ack}" onclick="ackEvent('${evt.id}')">
            ${evt.snapshot_path
                ? `<img class="alert-thumbnail" src="/media/${evt.snapshot_path.split('/media/').pop()}" alt="snapshot">`
                : '<div class="alert-thumbnail" style="display:flex;align-items:center;justify-content:center;font-size:1.5rem;">📷</div>'}
            <div class="alert-content">
                <div class="alert-title">
                    ${getTargetIcon(evt.target_type)}
                    <span class="target-badge ${evt.target_type}">${evt.target_type}</span>
                    on ${escapeHtml(evt.camera_name || 'Unknown')}
                </div>
                <div class="alert-meta">
                    <span>${formatTimestamp(evt.timestamp)}</span>
                    <span class="alert-confidence">${(evt.confidence * 100).toFixed(0)}%</span>
                    <span>${formatEventType(evt.event_source)}</span>
                </div>
            </div>
        </div>`;
}

function prependAlertItem(data) {
    const feed = document.getElementById('live-alert-feed');
    const emptyState = feed.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    const evt = {
        id: '',
        snapshot_path: data.snapshot_path,
        target_type: data.target_type,
        camera_name: data.camera_name,
        timestamp: data.timestamp,
        confidence: data.confidence,
        event_source: data.event_type,
        is_acknowledged: false,
    };

    const temp = document.createElement('div');
    temp.innerHTML = buildAlertItem(evt);
    const newItem = temp.firstElementChild;
    feed.prepend(newItem);

    // Keep max 20 items
    while (feed.children.length > 20) {
        feed.lastElementChild.remove();
    }
}

// ============================================================
// Toast Notifications
// ============================================================
function showToast(icon, title, message) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <div class="toast-body">
            <div class="toast-title">${escapeHtml(title)}</div>
            <div class="toast-message">${escapeHtml(message)}</div>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
    `;

    container.appendChild(toast);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        toast.classList.add('removing');
        setTimeout(() => toast.remove(), 300);
    }, 5000);

    // Keep max 5 toasts
    while (container.children.length > 5) {
        container.firstElementChild.remove();
    }
}

// ============================================================
// Modal System
// ============================================================
function showModal(content) {
    const overlay = document.getElementById('modal-overlay');
    const modalContent = document.getElementById('modal-content');
    modalContent.innerHTML = content;
    overlay.style.display = 'flex';

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeModal();
    });
}

function closeModal() {
    document.getElementById('modal-overlay').style.display = 'none';
}

// ============================================================
// Pagination
// ============================================================
function renderPagination(containerId, current, total, callback) {
    const container = document.getElementById(containerId);
    if (total <= 1) { container.innerHTML = ''; return; }

    let html = '';
    if (current > 1) {
        html += `<button class="btn btn-ghost" onclick="${callback.name}(${current - 1})">← Prev</button>`;
    }
    html += `<span style="padding:8px 12px;font-size:0.8rem;color:var(--text-muted);">Page ${current} of ${total}</span>`;
    if (current < total) {
        html += `<button class="btn btn-ghost" onclick="${callback.name}(${current + 1})">Next →</button>`;
    }
    container.innerHTML = html;
}

// ============================================================
// Utility Functions
// ============================================================
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTimestamp(isoStr) {
    if (!isoStr) return '—';
    try {
        const date = new Date(isoStr);
        const now = new Date();
        const diff = now - date;

        if (diff < 60000) return 'Just now';
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;

        return date.toLocaleDateString('en-IN', {
            day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
        });
    } catch {
        return isoStr;
    }
}

function formatEventType(source) {
    const map = {
        'isapi_linedetection': 'Line Crossing',
        'isapi_fielddetection': 'Intrusion',
        'isapi_VMD': 'Motion',
        'isapi_facedetection': 'Face',
        'frigate_detection': 'Object Detected',
        'isapi_regionEntrance': 'Region Entry',
        'isapi_regionExiting': 'Region Exit',
        'isapi_loitering': 'Loitering',
    };
    return map[source] || source?.replace(/_/g, ' ').replace(/isapi /i, '') || 'Unknown';
}

function getTargetIcon(type) {
    const icons = {
        human: '🚶', person: '🚶', vehicle: '🚗', car: '🚗',
        truck: '🚛', motorcycle: '🏍️', face: '👤',
        license_plate: '🔢', dog: '🐕', cat: '🐈',
    };
    return icons[type] || '🎯';
}

// WebSocket heartbeat every 30s
setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
    }
}, 30000);
