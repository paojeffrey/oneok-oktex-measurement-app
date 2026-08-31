/* OkTex Pipeline Measurement App — React (via CDN + htm, no build step). */
const { useState, useEffect, useRef, useCallback } = React;
const html = htm.bind(React.createElement);

const TYPE_COLOR = { RECEIPT: "#1a9f6b", DELIVERY: "#2563eb", BIDIRECTIONAL: "#e08a1e" };
const TYPE_CLASS = { RECEIPT: "r", DELIVERY: "d", BIDIRECTIONAL: "i" };
const TYPE_LABEL = { RECEIPT: "Receipt", DELIVERY: "Delivery", BIDIRECTIONAL: "Bi-Directional" };

const fmt = (n) => (n == null ? "—" : Math.round(n).toLocaleString("en-US"));
const fmtSigned = (n) => (n == null ? "—" : (n >= 0 ? "+" : "") + Math.round(n).toLocaleString("en-US"));

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

/* ---------- KPI cards ---------- */
function Kpis({ kpis }) {
  if (!kpis) return null;
  const bal = kpis.imbalance_dth;
  return html`
    <div class="kpis">
      <div class="kpi"><div class="label">Total Receipts</div>
        <div class="val">${fmt(kpis.total_receipts_dth)}<span class="unit">Dth</span></div></div>
      <div class="kpi"><div class="label">Total Deliveries</div>
        <div class="val">${fmt(kpis.total_deliveries_dth)}<span class="unit">Dth</span></div></div>
      <div class="kpi ${bal >= 0 ? "pos" : "neg"}"><div class="label">System Imbalance</div>
        <div class="val">${fmtSigned(bal)}<span class="unit">Dth</span></div></div>
      <div class="kpi"><div class="label">Imbalance</div>
        <div class="val">${kpis.imbalance_pct > 0 ? "+" : ""}${kpis.imbalance_pct}<span class="unit">%</span></div></div>
      <div class="kpi"><div class="label">Active Meters</div>
        <div class="val">${kpis.active_meters}</div></div>
    </div>`;
}

/* ---------- Leaflet map ---------- */
function PipelineMap({ route, meters, onSelect }) {
  const elRef = useRef(null);
  const mapRef = useRef(null);
  const layerRef = useRef(null);

  useEffect(() => {
    if (mapRef.current || !elRef.current) return;
    const map = L.map(elRef.current, { zoomControl: true, scrollWheelZoom: true });
    // OpenStreetMap standard tiles — keyless, no API-key watermark.
    L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      { attribution: '&copy; OpenStreetMap contributors', subdomains: "abc", maxZoom: 19 }
    ).addTo(map);
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);
  }, []);

  useEffect(() => {
    const map = mapRef.current, layer = layerRef.current;
    if (!map || !layer || !meters.length) return;
    layer.clearLayers();

    // Pipeline polylines — one per named route segment (so disjoint
    // segments of the real system are not joined by false connectors).
    if (route && route.length) {
      const bySeg = {};
      route.forEach((p) => { (bySeg[p.segment_name] = bySeg[p.segment_name] || []).push(p); });
      Object.values(bySeg).forEach((seg) => {
        const pts = seg.sort((a, b) => a.seq - b.seq).map((p) => [p.latitude, p.longitude]);
        L.polyline(pts, { color: "#d1352b", weight: 3.5, opacity: 0.9 }).addTo(layer);
      });
    }

    // Meter markers sized by measured quantity
    const maxActual = Math.max(...meters.map((m) => m.actual_dth || 0), 1);
    meters.forEach((m) => {
      const r = 6 + 12 * Math.sqrt((m.actual_dth || 0) / maxActual);
      const marker = L.circleMarker([m.latitude, m.longitude], {
        radius: r, color: "#fff", weight: 2,
        fillColor: TYPE_COLOR[m.meter_type] || "#888", fillOpacity: 0.92,
      }).addTo(layer);

      const vcls = (m.variance_pct >= 0) ? "var-pos" : "var-neg";
      marker.bindTooltip(`
        <div class="meter-pop">
          <div class="mp-name">${m.meter_name}</div>
          <div class="mp-type">${TYPE_LABEL[m.meter_type] || m.meter_type} · ${m.county}, ${m.state}</div>
          <table>
            <tr><td class="k">Scheduled</td><td class="v">${fmt(m.scheduled_dth)} Dth</td></tr>
            <tr><td class="k">Actual (measured)</td><td class="v">${fmt(m.actual_dth)} Dth</td></tr>
            <tr><td class="k">Variance</td><td class="v ${vcls}">${m.variance_pct > 0 ? "+" : ""}${m.variance_pct}%</td></tr>
            <tr><td class="k">Pressure</td><td class="v">${m.pressure_psig} psig</td></tr>
            <tr><td class="k">Capacity</td><td class="v">${fmt(m.capacity_dth)} Dth</td></tr>
          </table>
        </div>`, { sticky: true, direction: "top", opacity: 1, className: "okt-tip" });
      marker.on("click", () => onSelect && onSelect(m));
    });

    const bounds = L.latLngBounds(meters.map((m) => [m.latitude, m.longitude]));
    map.fitBounds(bounds.pad(0.18));
  }, [route, meters]);

  return html`<div id="map" ref=${elRef}></div>`;
}

/* ---------- AI insights ---------- */
function Insights({ flowDate }) {
  const [text, setText] = useState("");
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);

  const run = useCallback(async () => {
    setLoading(true); setText(""); setMeta(null);
    try {
      const d = await api("/api/insights", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gas_day: flowDate }),
      });
      setText(d.summary);
      setMeta(d.model_used ? "Generated by Claude via Databricks Model Serving" : "Computed fallback (model unavailable)");
    } catch (e) {
      setText("Unable to generate insights right now.");
    } finally { setLoading(false); }
  }, [flowDate]);

  useEffect(() => { run(); }, [run]);

  return html`
    <div class="card side-card">
      <div class="card-hd">
        <h2>AI Operations Insight</h2>
        <button class="btn" disabled=${loading} onClick=${run}>${loading ? "Analyzing…" : "Refresh"}</button>
      </div>
      <div class="ai-body ${loading ? "loading" : ""}">${loading ? "Analyzing today's flows…" : text}</div>
      ${meta && html`<div class="ai-meta">${meta}</div>`}
    </div>`;
}

/* ---------- Trend chart ---------- */
function TrendChart({ trend }) {
  const ref = useRef(null);
  const chartRef = useRef(null);
  useEffect(() => {
    if (!ref.current || !trend.length) return;
    if (chartRef.current) chartRef.current.destroy();
    chartRef.current = new Chart(ref.current, {
      type: "line",
      data: {
        labels: trend.map((t) => t.gas_day.slice(5)),
        datasets: [
          { label: "Receipts", data: trend.map((t) => t.receipts_dth),
            borderColor: "#1a9f6b", backgroundColor: "rgba(26,159,107,.08)", fill: true, tension: .3, pointRadius: 0, borderWidth: 2 },
          { label: "Deliveries + Bi-Directional", data: trend.map((t) => t.deliveries_dth),
            borderColor: "#2563eb", backgroundColor: "rgba(37,99,235,.06)", fill: true, tension: .3, pointRadius: 0, borderWidth: 2 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } } },
        scales: {
          x: { ticks: { maxTicksLimit: 10, font: { size: 10 } }, grid: { display: false } },
          y: { ticks: { callback: (v) => (v / 1000) + "k", font: { size: 10 } }, title: { display: true, text: "Dth", font: { size: 10 } } },
        },
      },
    });
  }, [trend]);
  return html`<div class="chart-wrap"><canvas ref=${ref}></canvas></div>`;
}

/* ---------- Meter table ---------- */
function MeterTable({ meters, onSelect }) {
  return html`
    <div class="tbl-wrap">
      <table class="data">
        <thead><tr>
          <th>Meter</th><th>Type</th><th>Location</th>
          <th class="num">Scheduled</th><th class="num">Actual</th><th class="num">Var %</th>
        </tr></thead>
        <tbody>
          ${meters.map((m) => html`
            <tr key=${m.meter_id} onClick=${() => onSelect && onSelect(m)}>
              <td><strong>${m.meter_id}</strong> ${m.meter_name}</td>
              <td><span class="pill ${TYPE_CLASS[m.meter_type]}">${m.meter_type}</span></td>
              <td>${m.county}, ${m.state}</td>
              <td class="num">${fmt(m.scheduled_dth)}</td>
              <td class="num"><strong>${fmt(m.actual_dth)}</strong></td>
              <td class="num" style=${{ color: m.variance_pct >= 0 ? "#0f7a52" : "#d64545" }}>
                ${m.variance_pct > 0 ? "+" : ""}${m.variance_pct}%</td>
            </tr>`)}
        </tbody>
      </table>
    </div>`;
}

/* ---------- App shell ---------- */
function App() {
  const [route, setRoute] = useState([]);
  const [dates, setDates] = useState([]);
  const [flowDate, setFlowDate] = useState(null);
  const [data, setData] = useState(null);
  const [trend, setTrend] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [r, dts, tr] = await Promise.all([api("/api/route"), api("/api/dates"), api("/api/trend")]);
        setRoute(r.route); setTrend(tr.trend);
        setDates(dts.dates); setFlowDate(dts.dates[0]);
      } catch (e) { setErr(String(e)); }
    })();
  }, []);

  useEffect(() => {
    if (!flowDate) return;
    (async () => {
      try { setData(await api(`/api/measurements?gas_day=${flowDate}`)); }
      catch (e) { setErr(String(e)); }
    })();
  }, [flowDate]);

  const meters = data ? data.meters : [];

  return html`
    <header class="hdr">
      <div class="brand">
        <img class="logo-img" src="/static/okt-logo.svg" alt="OkTex" />
        <div>
          <h1>OkTex Pipeline — Daily Measurements</h1>
          <div class="sub">Meter-level scheduled &amp; measured quantities · West Texas (El Paso) → Oklahoma</div>
        </div>
      </div>
      <div class="controls">
        <span class="badge-synth">Synthetic demo data</span>
        <div>
          <label>Gas Day</label>
          <select value=${flowDate || ""} onChange=${(e) => setFlowDate(e.target.value)}>
            ${dates.map((d) => html`<option key=${d} value=${d}>${d}</option>`)}
          </select>
        </div>
      </div>
    </header>

    <div class="wrap">
      ${err && html`<div class="kpi neg" style=${{ marginBottom: 14 }}>Error loading data: ${err}</div>`}
      <${Kpis} kpis=${data && data.kpis} />

      <div class="grid">
        <div class="card">
          <div class="card-hd"><h2>Pipeline Map</h2><span class="hint">Hover a meter for daily quantities · marker size ∝ measured Dth</span></div>
          <${PipelineMap} route=${route} meters=${meters} />
          <div class="legend">
            <span class="item"><span class="seg-line"></span>OkTex Pipeline</span>
            <span class="item"><span class="dot r"></span>Receipt</span>
            <span class="item"><span class="dot d"></span>Delivery</span>
            <span class="item"><span class="dot i"></span>Bi-Directional</span>
          </div>
        </div>
        <div class="side">
          <${Insights} flowDate=${flowDate} />
          <div class="card">
            <div class="card-hd"><h2>About</h2></div>
            <div class="ai-body">Daily throughput for ${data ? data.meters.length : "—"} OkTex meter stations
            across West Texas and Oklahoma, read live from <strong>Lakebase Postgres</strong>. Meter names, types,
            and locations are from the public OKT system map; all quantities are synthetic.</div>
          </div>
        </div>
      </div>

      <div class="bottom">
        <div class="card">
          <div class="card-hd"><h2>System Throughput Trend</h2><span class="hint">Receipts vs deliveries · full history</span></div>
          <${TrendChart} trend=${trend} />
        </div>
        <div class="card">
          <div class="card-hd"><h2>Meter Measurements — ${flowDate || ""}</h2><span class="hint">Ranked by measured Dth</span></div>
          <${MeterTable} meters=${meters} />
        </div>
      </div>

      <div class="foot">
        OkTex Pipeline Company, L.L.C. (TSP 80-002-2246) · Demo built on Databricks (Unity Catalog + Lakebase + Apps + Foundation Models).<br/>
        Meter names, types, and locations are from the public OKT System Overview Map. All measurement quantities are synthetic. No ONEOK or customer operational data is used.
      </div>
    </div>`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
