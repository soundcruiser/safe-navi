/** 教習エリア内の事故クラスタを Leaflet に表示 */
const AccidentMap = {
  map: null,
  layer: null,
  markers: [],

  init(leafletMap) {
    this.map = leafletMap;
    this.layer = L.layerGroup();
    return this;
  },

  yearLabel() {
    const a = School.accidents;
    if (!a) return '';
    if (a.yearFrom && a.yearTo && a.yearFrom !== a.yearTo) return `${a.yearFrom}〜${a.yearTo}年`;
    return `${a.yearTo || a.year || ''}年`;
  },

  radius(c) {
    return Math.min(20, Math.max(6, 4 + Math.sqrt(c.total) * 2));
  },

  color(c) {
    if (c.fatal > 0) return '#ef4444';
    if (c.total >= 5) return '#f97316';
    if (c.total >= 2) return '#f0a500';
    return '#eab308';
  },

  popupHtml(c) {
    const hints = (c.hints || []).slice(0, 5).map(h => `<li style="margin:4px 0 4px 1em">${h}</li>`).join('');
    const note = School.instructorNote(c.id);
    const detail = School.accidentDetailHtml(c).replace(/class="acc-/g, 'style="margin:6px 0;font-size:11px;" class="acc-');
    return `<div style="font-size:12px;line-height:1.5;max-width:280px">
      <strong>事故記録 ${c.total}件</strong>（負傷${c.injury || 0} / 死亡${c.fatal || 0}）<br>
      <span style="color:#888">${AccidentMap.yearLabel()}・約50m圏内・警察庁統計</span>
      ${detail}
      <ul style="margin:8px 0;padding:0">${hints}</ul>
      ${note ? `<p style="color:#a5b4fc"><strong>指導員:</strong> ${note}</p>` : ''}
    </div>`;
  },

  clear() {
    if (this.layer) this.layer.clearLayers();
    this.markers = [];
  },

  render(clusters, opts = {}) {
    if (!this.map || !clusters?.length) return;
    this.clear();
    clusters.forEach(c => {
      const m = L.circleMarker([c.lat, c.lng], {
        radius: this.radius(c),
        fillColor: this.color(c),
        color: '#fff',
        weight: 1.5,
        fillOpacity: 0.82,
      });
      m._clusterId = c.id;
      m._cluster = c;
      m.bindPopup(this.popupHtml(c), { maxWidth: 300 });
      m.addTo(this.layer);
      this.markers.push(m);
    });
    if (opts.bounds && School.pack?.bounds) {
      const b = School.pack.bounds;
      L.rectangle([[b.minLat, b.minLng], [b.maxLat, b.maxLng]], {
        color: '#6366f1', weight: 1, dashArray: '5 4', fillOpacity: 0.04,
      }).addTo(this.layer).bindTooltip('教習エリア（約5km）', { sticky: true });
    }
    if (School.pack?.center) {
      L.marker([School.pack.center.lat, School.pack.center.lng], {
        icon: L.divIcon({
          className: '',
          html: '<div style="background:#22c55e;color:#000;font-weight:700;font-size:10px;padding:4px 8px;border-radius:8px;border:2px solid #fff;white-space:nowrap">教習所</div>',
          iconAnchor: [40, 12],
        }),
      }).addTo(this.layer);
    }
  },

  highlightRoute(clusterIds) {
    const ids = clusterIds instanceof Set ? clusterIds : new Set(clusterIds || []);
    this.markers.forEach(m => {
      const on = ids.has(m._clusterId);
      m.setStyle({
        weight: on ? 3 : 1.5,
        fillOpacity: on ? 0.95 : 0.45,
        color: on ? '#a5b4fc' : '#fff',
      });
      if (on) m.bringToFront();
    });
  },

  setVisible(on) {
    if (!this.layer || !this.map) return;
    if (on) {
      if (!this.map.hasLayer(this.layer)) this.layer.addTo(this.map);
    } else if (this.map.hasLayer(this.layer)) {
      this.map.removeLayer(this.layer);
    }
  },

  fitToArea() {
    if (School.pack?.bounds) {
      const b = School.pack.bounds;
      this.map.fitBounds([[b.minLat, b.minLng], [b.maxLat, b.maxLng]], { padding: [24, 24] });
    }
  },
};
