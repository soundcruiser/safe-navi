/** 教習所パック・事故クラスタ（静的JSON） */
const School = {
  id: 'toyota-chuo',
  pack: null,
  accidents: null,

  async init() {
    const params = new URLSearchParams(location.search);
    this.id = params.get('school') || 'toyota-chuo';
    const base = `data/${this.id}`;
    try {
      const [packRes, accRes] = await Promise.all([
        fetch(`${base}/school-pack.json`),
        fetch(`${base}/accidents.json`),
      ]);
      if (!packRes.ok) throw new Error('school-pack');
      this.pack = await packRes.json();
      this.accidents = accRes.ok ? await accRes.json() : { clusters: [] };
    } catch (e) {
      console.warn('School pack load failed', e);
      this.pack = null;
      this.accidents = { clusters: [] };
    }
    return this;
  },

  inBounds(lat, lng) {
    const b = this.pack?.bounds;
    if (!b) return true;
    return lat >= b.minLat && lat <= b.maxLat && lng >= b.minLng && lng <= b.maxLng;
  },

  coordKey(lat, lng) {
    return `${lat.toFixed(4)},${lng.toFixed(4)}`;
  },

  packLandmark(turn) {
    const lm = this.pack?.landmarks?.[this.coordKey(turn.lat, turn.lng)];
    if (!lm) return null;
    return { tags: { name: lm.name }, _pack: lm };
  },

  instructorNote(clusterId) {
    return this.pack?.intersectionNotes?.[clusterId] || '';
  },

  destinationHint(label) {
    const hints = this.pack?.destinationHints || {};
    for (const [k, v] of Object.entries(hints)) {
      if (label.includes(k)) return v;
    }
    return '';
  },

  haversineM(lat1, lng1, lat2, lng2) {
    const R = 6371000;
    const φ1 = lat1 * Math.PI / 180;
    const φ2 = lat2 * Math.PI / 180;
    const Δφ = (lat2 - lat1) * Math.PI / 180;
    const Δλ = (lng2 - lng1) * Math.PI / 180;
    const a = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2;
    return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  },

  findCluster(lat, lng, maxM = 85) {
    let best = null;
    let bestD = maxM;
    for (const c of this.accidents?.clusters || []) {
      const d = this.haversineM(lat, lng, c.lat, c.lng);
      if (d < bestD) { bestD = d; best = c; }
    }
    return best;
  },

  attachToTurns(turns) {
    for (const t of turns) {
      t.accident = this.findCluster(t.lat, t.lng);
      if (t.accident) {
        const note = this.instructorNote(t.accident.id);
        if (note) t.accident = { ...t.accident, instructorNote: note };
      }
    }
  },

  routeAccidentScore(route, keyTurnFn) {
    const steps = route.legs?.[0]?.steps || [];
    let score = 0;
    const seen = new Set();
    for (const step of steps) {
      const arrow = keyTurnFn(step.maneuver);
      if (arrow.cls === 'straight') continue;
      const loc = step.maneuver.location;
      const c = this.findCluster(loc[1], loc[0]);
      if (c && !seen.has(c.id)) {
        seen.add(c.id);
        score += c.total * 3 + c.fatal * 15;
      }
    }
    return score;
  },

  accidentBadgeHtml(cluster) {
    if (!cluster) return '';
    const sev = cluster.fatal > 0 ? 'high' : cluster.total >= 3 ? 'mid' : 'low';
    return `<span class="acc-badge acc-${sev}">事故記録 ${cluster.total}件</span>`;
  },

  accidentDetailHtml(cluster) {
    if (!cluster) return '';
    let html = '';
    if (cluster.summary) {
      html += `<p class="acc-summary"><strong>この付近の傾向:</strong> ${cluster.summary}</p>`;
    }
    const types = cluster.typeCounts || {};
    if (Object.keys(types).length) {
      html += '<p class="acc-detail-line"><strong>事故の種類</strong> ' +
        Object.entries(types).map(([k, v]) => `${k} ${v}件`).join(' · ') + '</p>';
    }
    const roads = cluster.roadCounts || {};
    if (Object.keys(roads).length) {
      html += '<p class="acc-detail-line"><strong>道路</strong> ' +
        Object.entries(roads).map(([k, v]) => `${k} ${v}件`).join(' · ') + '</p>';
    }
    const parties = cluster.partyCounts || {};
    if (Object.keys(parties).length) {
      html += '<p class="acc-detail-line"><strong>当事者</strong> ' +
        Object.entries(parties).map(([k, v]) => `${k} ${v}件`).join(' · ') + '</p>';
    }
    return html;
  },

  accidentBlockHtml(cluster) {
    if (!cluster) return '';
    const hints = (cluster.hints || []).map(h => `<li>${h}</li>`).join('');
    const note = cluster.instructorNote
      ? `<p class="acc-instructor"><strong>指導員メモ:</strong> ${cluster.instructorNote}</p>` : '';
    return `<div class="acc-block">
      ${this.accidentBadgeHtml(cluster)}
      ${this.accidentDetailHtml(cluster)}
      <ul class="acc-hints">${hints}</ul>${note}</div>`;
  },

  renderPresets(containerId, onSelect) {
    const el = document.getElementById(containerId);
    if (!el || !this.pack?.presets?.length) return;
    el.innerHTML = '';
    this.pack.presets.forEach(p => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'preset-btn';
      btn.textContent = p.label;
      btn.onclick = () => onSelect(p);
      el.appendChild(btn);
    });
  },

  applyPreset(p) {
    document.getElementById('startInput').value = p.start;
    document.getElementById('goalInput').value = p.goal;
    if (p.departTime) document.getElementById('departTime').value = p.departTime;
  },

  updateHeader() {
    if (!this.pack) return;
    const tag = document.querySelector('.tagline');
    if (tag) tag.textContent = `${this.pack.shortName || this.pack.name} 周辺 · 出発前予習 · 本番は Google マップ`;
    if (this.pack.center) map.setView([this.pack.center.lat, this.pack.center.lng], 14);
  },

  renderFooter() {
    const el = document.getElementById('legalFooter');
    if (!el) return;
    const period = this.accidents?.yearFrom && this.accidents?.yearTo
      ? `${this.accidents.yearFrom}〜${this.accidents.yearTo}年`
      : `${this.accidents?.year || '—'}年`;
    const gen = this.accidents?.generatedAt || '—';
    el.innerHTML = `
      <p><strong>データ出典:</strong> ${this.accidents?.source || '—'}
        (<a href="${this.accidents?.sourceUrl || '#'}" target="_blank" rel="noopener">警察庁</a> ${period}・教習エリア内 ${this.accidents?.totalAccidents ?? 0}件 / 集計日 ${gen})
        · <a href="accident-map.html">事故マップ（全画面）</a></p>
      <p>${this.accidents?.disclaimer || '過去の統計であり、現在の危険を保証しません。'}</p>
      <p>運転中のナビ・判断は Google マップ等の本番ナビに従ってください。SAFENAVI は出発前の予習用です。</p>`;
  },
};
