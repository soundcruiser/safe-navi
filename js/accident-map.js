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
    return Math.min(22, Math.max(9, 5 + Math.sqrt(c.total) * 2));
  },

  color(c) {
    if (c.fatal > 0) return '#ef4444';
    if (c.total >= 5) return '#f97316';
    if (c.total >= 2) return '#f0a500';
    return '#eab308';
  },

  popupHtml(c) {
    if (!c) return '<p>データがありません</p>';
    const hints = (c.hints || []).slice(0, 5).map(h => `<li>${h}</li>`).join('');
    const note = School.instructorNote(c.id);
    const detail = School.accidentDetailHtml(c);
    return `<div class="acc-popup-inner">
      <strong>事故記録 ${c.total}件</strong>（負傷${c.injury || 0} / 死亡${c.fatal || 0}）<br>
      <span class="acc-popup-meta">${AccidentMap.yearLabel()}・約50m圏内・警察庁統計</span>
      ${detail}
      <ul class="acc-popup-hints">${hints}</ul>
      ${note ? `<p class="acc-instructor"><strong>指導員:</strong> ${note}</p>` : ''}
    </div>`;
  },

  ensurePane() {
    if (!this.map.getPane('accidentPane')) {
      const pane = this.map.createPane('accidentPane');
      pane.style.zIndex = 650;
    }
  },

  bindMarkerPopup(m, cluster) {
    m.bindPopup(() => this.popupHtml(cluster), {
      maxWidth: 320,
      minWidth: 200,
      className: 'acc-popup',
      autoPan: true,
      closeButton: true,
    });
    m.on('click', () => {
      m.openPopup();
    });
  },

  clear() {
    if (this.layer) this.layer.clearLayers();
    this.markers = [];
  },

  render(clusters, opts = {}) {
    if (!this.map || !clusters?.length) return;
    this.ensurePane();
    this.clear();
    clusters.forEach(c => {
      const m = L.circleMarker([c.lat, c.lng], {
        pane: 'accidentPane',
        radius: this.radius(c),
        fillColor: this.color(c),
        color: '#fff',
        weight: 1.5,
        fillOpacity: 0.82,
        interactive: true,
        bubblingMouseEvents: false,
      });
      m._clusterId = c.id;
      m._cluster = c;
      this.bindMarkerPopup(m, c);
      m.addTo(this.layer);
      this.markers.push(m);
    });
    if (this.map.hasLayer(this.layer)) {
      this.layer.bringToFront();
    }
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
      this.layer.bringToFront();
    } else if (this.map.hasLayer(this.layer)) {
      this.map.removeLayer(this.layer);
    }
  },

  bringAboveRoute() {
    if (this.layer && this.map?.hasLayer(this.layer)) {
      this.layer.bringToFront();
    }
  },

  fitToArea() {
    if (School.pack?.bounds) {
      const b = School.pack.bounds;
      this.map.fitBounds([[b.minLat, b.minLng], [b.maxLat, b.maxLng]], { padding: [24, 24] });
    }
  },
};
