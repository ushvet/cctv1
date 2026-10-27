/**
 * Hikvision AI CCTV Platform — WebRTC Stream Player & Two-Way Intercom
 * Connects camera feeds directly to go2rtc WebRTC streams.
 */

const GO2RTC_BASE = `http://${window.location.hostname}:1984`;

/**
 * Initialize a live camera stream in the camera feed element.
 * Embeds go2rtc native stream player in an iframe with WebRTC mode.
 * Works seamlessly across all browsers and isolates H.264/H.265 decoders.
 */
function initCameraStream(camera, context = 'dash') {
    const feedEl = document.getElementById(`cam-feed-${context}-${camera.id}`);
    if (!feedEl) return;

    // Map camera name to Frigate / go2rtc stream ID (lowercase, underscores)
    const frigateId = camera.name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');

    // Clear any previous stream elements
    feedEl.querySelectorAll('iframe, video-stream, video, img').forEach(el => el.remove());

    const iframe = document.createElement('iframe');
    iframe.id = `player-${context}-${camera.id}`;
    iframe.src = `${GO2RTC_BASE}/stream.html?src=${encodeURIComponent(frigateId)}&mode=webrtc&background=true`;
    iframe.style.cssText = 'width:100%;height:100%;border:none;display:block;position:absolute;top:0;left:0;z-index:1;background:#000;';
    iframe.allow = 'autoplay; camera; microphone; fullscreen';

    // Hide loading placeholder once the frame loads
    iframe.onload = () => {
        const placeholder = feedEl.querySelector('.placeholder');
        if (placeholder) {
            placeholder.style.display = 'none';
        }
    };

    feedEl.insertBefore(iframe, feedEl.firstChild);
}

// ============================================================
// Two-Way Audio Intercom (Browser Mic -> Camera Speaker)
// ============================================================
let activeIntercom = null;

/**
 * Broadcast browser microphone audio to the camera speaker via go2rtc ISAPI backchannel.
 * Handles Front Gate Panoramic and any other camera with two-way audio.
 */
async function toggleCameraIntercom(cameraId, cameraName, context = 'dash') {
    // If already talking to this camera, stop talking
    if (activeIntercom && activeIntercom.cameraId === cameraId) {
        stopIntercom();
        return;
    }

    // If talking to another camera, stop that session first
    if (activeIntercom) {
        stopIntercom();
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const pc = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        });

        // Add mic audio track as sendonly
        stream.getAudioTracks().forEach(track => {
            pc.addTransceiver(track, { direction: 'sendonly' });
        });

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        const frigateId = cameraName.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
        const response = await fetch(`${GO2RTC_BASE}/api/webrtc?src=${encodeURIComponent(frigateId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/sdp' },
            body: offer.sdp
        });

        if (!response.ok) {
            throw new Error(`go2rtc returned HTTP ${response.status}`);
        }

        const answerSDP = await response.text();
        await pc.setRemoteDescription(new RTCSessionDescription({
            type: 'answer',
            sdp: answerSDP
        }));

        activeIntercom = { pc, stream, cameraId, cameraName };
        updateIntercomUI(cameraId, true);

        if (typeof showToast === 'function') {
            showToast('🎙️ Intercom Live', `Broadcasting to ${cameraName} speaker!`);
        }
    } catch (err) {
        console.error('[Intercom Error]', err);
        stopIntercom();
        if (typeof showToast === 'function') {
            showToast('❌ Intercom Error', err.message || 'Microphone access denied');
        }
    }
}

function stopIntercom() {
    if (!activeIntercom) return;
    const { pc, stream, cameraId, cameraName } = activeIntercom;
    if (stream) {
        stream.getTracks().forEach(t => t.stop());
    }
    if (pc) {
        pc.close();
    }
    updateIntercomUI(cameraId, false);
    if (typeof showToast === 'function') {
        showToast('🎙️ Intercom Stopped', `Stopped broadcasting to ${cameraName}`);
    }
    activeIntercom = null;
}

function updateIntercomUI(cameraId, isTalking) {
    document.querySelectorAll(`[id^="talk-btn-"][id$="-${cameraId}"]`).forEach(btn => {
        if (isTalking) {
            btn.classList.add('talking');
            btn.innerHTML = '🔴 Talking...';
            btn.title = 'Click to stop talking';
        } else {
            btn.classList.remove('talking');
            btn.innerHTML = '🎙️ Talk';
            btn.title = 'Two-way audio: Speak through camera speaker';
        }
    });

    document.querySelectorAll(`[id^="talk-badge-"][id$="-${cameraId}"]`).forEach(badge => {
        badge.style.display = isTalking ? 'inline-flex' : 'none';
    });
}
