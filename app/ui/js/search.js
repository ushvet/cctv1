/**
 * Hikvision AI CCTV Platform — Semantic Search & Face/Plate Management UI Logic
 * Handles natural language video search via MobileCLIP + pgvector.
 */

// ============================================================
// Semantic Search
// ============================================================
let searchAbortController = null;

async function runSearch() {
    const input = document.getElementById('search-input');
    const query = input?.value?.trim();
    if (!query || query.length < 3) {
        showToast('⚠️', 'Search', 'Please enter at least 3 characters');
        return;
    }

    const resultsEl = document.getElementById('search-results');

    // Show loading state
    resultsEl.innerHTML = `
        <div class="empty-state" style="grid-column:1/-1;">
            <div class="icon" style="animation: spin 1s linear infinite;">🔄</div>
            <div class="title">Searching...</div>
            <div class="description">Analyzing "${escapeHtml(query)}" across all event embeddings</div>
        </div>`;

    // Abort previous search if still running
    if (searchAbortController) searchAbortController.abort();
    searchAbortController = new AbortController();

    try {
        const params = new URLSearchParams({
            q: query,
            limit: 24,
            threshold: 0.2,
        });

        const response = await fetch(`${API_BASE}/api/search?${params}`, {
            signal: searchAbortController.signal,
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        if (!data.results || data.results.length === 0) {
            resultsEl.innerHTML = `
                <div class="empty-state" style="grid-column:1/-1;">
                    <div class="icon">🔍</div>
                    <div class="title">No results found</div>
                    <div class="description">Try a different description or adjust the search threshold</div>
                </div>`;
            return;
        }

        resultsEl.innerHTML = data.results.map((result, idx) => buildSearchResultCard(result, idx)).join('');
        showToast('🔍', 'Search Complete', `Found ${data.results.length} matching events`);

    } catch (e) {
        if (e.name === 'AbortError') return;
        console.error('Search error:', e);
        resultsEl.innerHTML = `
            <div class="empty-state" style="grid-column:1/-1;">
                <div class="icon">❌</div>
                <div class="title">Search Failed</div>
                <div class="description">${escapeHtml(e.message)}</div>
            </div>`;
    }
}

function buildSearchResultCard(result, index) {
    const similarityPercent = (result.similarity * 100).toFixed(1);
    const snapshotSrc = result.snapshot_path
        ? `/media/${result.snapshot_path.split('/media/').pop()}`
        : '';

    const animDelay = index * 50;

    return `
        <div class="search-result-card" style="animation-delay:${animDelay}ms;animation:fadeIn 0.4s ease-out ${animDelay}ms both;">
            ${snapshotSrc
                ? `<img src="${snapshotSrc}" alt="Event snapshot" loading="lazy" 
                        onerror="this.style.display='none'">`
                : `<div style="aspect-ratio:16/9;background:var(--bg-tertiary);display:flex;align-items:center;justify-content:center;font-size:2rem;opacity:0.3;">📷</div>`}
            <div class="search-result-info">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <span class="target-badge ${result.target_type || ''}">${result.target_type || 'event'}</span>
                    <span style="font-family:var(--font-mono);font-size:0.78rem;color:var(--accent-cyan);">
                        ${similarityPercent}% match
                    </span>
                </div>
                <div style="font-size:0.78rem;color:var(--text-muted);">
                    ${result.camera_name ? `📷 ${escapeHtml(result.camera_name)}` : ''}
                    ${result.timestamp ? ` · ${formatTimestamp(result.timestamp)}` : ''}
                </div>
                ${result.description ? `<div style="font-size:0.75rem;color:var(--text-secondary);margin-top:4px;">${escapeHtml(result.description)}</div>` : ''}
                <div class="similarity-bar">
                    <div class="similarity-fill" style="width:${similarityPercent}%;"></div>
                </div>
            </div>
        </div>`;
}

// ============================================================
// Face Similarity Search UI
// ============================================================
async function searchSimilarFaces(faceId) {
    try {
        const params = new URLSearchParams({
            face_id: faceId,
            threshold: 0.55,
            limit: 20,
        });

        const results = await apiFetch(`/api/faces/search/similar?${params}`);

        if (!results || results.length === 0) {
            showToast('🔍', 'Face Search', 'No similar detections found');
            return;
        }

        // Show results in modal
        const html = `
            <div class="card-header">
                <div class="card-title">👤 Similar Face Detections</div>
            </div>
            <div style="max-height:400px;overflow-y:auto;">
                ${results.map(r => `
                    <div style="display:flex;gap:12px;padding:8px;border-bottom:1px solid var(--border-glass);">
                        ${r.crop_path
                            ? `<img src="/media/${r.crop_path.split('/media/').pop()}" 
                                   style="width:60px;height:60px;border-radius:8px;object-fit:cover;">`
                            : '<div style="width:60px;height:60px;border-radius:8px;background:var(--bg-tertiary);display:flex;align-items:center;justify-content:center;">👤</div>'}
                        <div>
                            <div style="font-family:var(--font-mono);color:var(--accent-cyan);">
                                ${(r.similarity * 100).toFixed(1)}% match
                            </div>
                            <div style="font-size:0.78rem;color:var(--text-muted);">
                                ${r.created_at ? formatTimestamp(r.created_at) : ''}
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
            <div style="text-align:right;margin-top:16px;">
                <button class="btn btn-ghost" onclick="closeModal()">Close</button>
            </div>
        `;

        showModal(html);
        showToast('👤', 'Face Search', `Found ${results.length} similar detections`);
    } catch (e) {
        showToast('❌', 'Search Error', e.message);
    }
}

// ============================================================
// CSS Animation for search spinner
// ============================================================
const spinStyle = document.createElement('style');
spinStyle.textContent = `
    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
`;
document.head.appendChild(spinStyle);
