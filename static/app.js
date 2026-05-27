/**
 * SAMAEG-PLI - Frontend
 * Sistema de Alerta de Risco Geodinâmico Rodoviário
 *
 * - Auto-refresh do snapshot a cada 30s
 * - Mapa Leaflet (CARTO Light) com camadas: pontos, regiões, malha DER-SP, heatmap
 * - Filtros interativos da malha rodoviária
 */

const REFRESH_MS = 30_000;
const SP_BOUNDS = [[-25.5, -53.2], [-19.7, -44.0]];        // Estado inteiro
const LITORAL_BOUNDS = [[-25.0, -47.0], [-22.5, -44.3]];   // Litoral norte + Baixada Santista

const NIVEL_LABEL = ["Monitoramento", "Observação", "Atenção", "Alerta", "Alerta Máximo"];
const NIVEL_COLOR = ["#2aa358", "#f1c40f", "#f39c12", "#e74c3c", "#8e44ad"];
const NIVEL_DESC = [
  "Sem chuva relevante",
  "Chuva próxima ao limiar",
  "Vistorias preventivas",
  "Possíveis ocorrências",
  "Risco severo"
];

const state = {
  map: null,
  layers: { points: null, regions: null, heat: null, roads: null },
  pointMarkers: new Map(),
  pointData: new Map(),       // id -> dados completos do ponto (para heatmap)
  regionPolys: [],
  roadGeoJSON: null,
  roadFilters: {
    tipo_pista: "",
    regional: "",
    jurisdicao: "",
    rodovia: ""
  }
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  initMap();
  attachEvents();
  loadRoadNetwork();
  refresh();
  setInterval(refresh, REFRESH_MS);
}

// ============================================================================
// MAPA
// ============================================================================

function initMap() {
  state.map = L.map("map", {
    zoomControl: true,
    attributionControl: false,
  });
  state.map.fitBounds(SP_BOUNDS);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    maxZoom: 19,
    minZoom: 6,
    subdomains: "abcd",
  }).addTo(state.map);

  L.control.attribution({ position: "bottomright", prefix: false })
    .addAttribution("OSM | CARTO | INPE/MERGE | DER-SP")
    .addTo(state.map);

  state.layers.points = L.layerGroup().addTo(state.map);
  state.layers.regions = L.layerGroup().addTo(state.map);
  state.layers.roads = L.layerGroup().addTo(state.map);
}

// ============================================================================
// EVENTOS
// ============================================================================

function attachEvents() {
  document.getElementById("btn-refresh").addEventListener("click", async () => {
    const btn = document.getElementById("btn-refresh");
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = "Atualizando...";
    try {
      await fetch("/api/refresh", { method: "POST" });
      await refresh();
    } catch (e) {
      console.error(e);
    } finally {
      btn.textContent = original;
      btn.disabled = false;
    }
  });

  document.getElementById("btn-fit").addEventListener("click", () => {
    state.map.fitBounds(SP_BOUNDS);
  });

  document.getElementById("btn-fit-litoral").addEventListener("click", () => {
    state.map.fitBounds(LITORAL_BOUNDS);
  });

  document.getElementById("layer-points").addEventListener("change", (e) => {
    if (e.target.checked) state.map.addLayer(state.layers.points);
    else state.map.removeLayer(state.layers.points);
  });

  document.getElementById("layer-regions").addEventListener("change", (e) => {
    if (e.target.checked) state.map.addLayer(state.layers.regions);
    else state.map.removeLayer(state.layers.regions);
  });

  document.getElementById("layer-heatmap").addEventListener("change", (e) => {
    if (e.target.checked) addHeatmap();
    else removeHeatmap();
  });

  attachRoadFilterEvents();
  attachModalEvents();
}

// ============================================================================
// MODAIS (ajuda e glossário)
// ============================================================================

function attachModalEvents() {
  const openModal = (id) => {
    const m = document.getElementById(id);
    if (m) {
      m.hidden = false;
      document.body.style.overflow = "hidden";
    }
  };
  const closeAll = () => {
    document.querySelectorAll(".modal-backdrop").forEach((el) => (el.hidden = true));
    document.body.style.overflow = "";
  };

  document.getElementById("link-help")?.addEventListener("click", (e) => {
    e.preventDefault();
    openModal("modal-help");
  });
  document.getElementById("link-glossary")?.addEventListener("click", (e) => {
    e.preventDefault();
    openModal("modal-glossary");
  });

  // Fechar pelo X
  document.querySelectorAll("[data-close-modal]").forEach((btn) => {
    btn.addEventListener("click", closeAll);
  });

  // Fechar clicando fora
  document.querySelectorAll(".modal-backdrop").forEach((bd) => {
    bd.addEventListener("click", (e) => {
      if (e.target === bd) closeAll();
    });
  });

  // Fechar com Esc
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAll();
  });
}

// ============================================================================
// REFRESH GERAL
// ============================================================================

async function refresh() {
  try {
    const res = await fetch("/api/snapshot");
    const snap = await res.json();
    renderSnapshot(snap);
  } catch (e) {
    console.error("Erro ao atualizar snapshot:", e);
    setStatus("Erro de conexão com o servidor", "alert");
  }
}

function renderSnapshot(snap) {
  const ts = snap.timestamp_utc ? new Date(snap.timestamp_utc) : null;
  const summary = snap.summary || {};
  const maxRd = summary.max_rd ?? 0;
  const status = summary.data_status || "ok";   // ok | degraded | no_data | mock

  // ---- Estado de DADOS (precede o estado operacional) ----
  if (status === "no_data") {
    setStatus("Sem dado real do MERGE/INPE neste ciclo", "alert");
    document.getElementById("status-time").textContent =
      ts ? "Última tentativa às " + formatTime(ts) : "—";
    setBadge("badge-source", "Sem dado", "no-data");
    setBadge("badge-update", ts ? formatTime(ts) : "—", "no-data");
    // Limpa pontos no mapa para nao mostrar leitura "fantasma"
    renderPointsOnMap([]);
    renderRegionsOnMap(snap.regions || []);
    renderRegions(snap.regions || []);
    renderWorstNoData(summary.message);
    document.querySelectorAll(".meter-cell").forEach((c) => c.classList.remove("active"));
    for (let i = 0; i <= 4; i++) {
      const el = document.getElementById("count-" + i);
      if (el) el.textContent = "—";
    }
    return;
  }

  // ---- Estado operacional normal ----
  const statusClasses = ["", "warn", "warn", "alert", "max"];
  const statusSuffix = status === "degraded"
    ? ` · dado parcial (${summary.missing_24h}h faltando em 24h)`
    : status === "mock"
      ? " · MODO DEV (mock)"
      : "";
  setStatus(
    `${NIVEL_LABEL[maxRd]} — estado geral da malha${statusSuffix}`,
    statusClasses[Math.min(4, maxRd)]
  );
  if (ts) {
    document.getElementById("status-time").textContent = "Atualizado às " + formatTime(ts);
  }

  // Badges da topbar
  setBadge(
    "badge-source",
    status === "mock" ? "MOCK (dev)" : "MERGE / INPE",
    status === "ok" ? "ok" : status
  );
  setBadge("badge-update", ts ? formatTime(ts) : "—", status === "ok" ? "ok" : status);

  // Distribuição por nível
  const by = summary.by_level || {};
  for (let i = 0; i <= 4; i++) {
    const el = document.getElementById("count-" + i);
    if (el) el.textContent = by[i] || 0;
  }
  document.querySelectorAll(".meter-cell").forEach((c) => c.classList.remove("active"));
  const activeCell = document.querySelector(`.meter-cell[data-rd="${maxRd}"]`);
  if (activeCell) activeCell.classList.add("active");

  // Trecho mais crítico
  renderWorst(snap);

  // Regiões
  renderRegions(snap.regions || []);

  // Mapa
  renderRegionsOnMap(snap.regions || []);
  renderPointsOnMap(snap.points || []);

  // Heatmap (se ativo, atualiza)
  if (document.getElementById("layer-heatmap").checked) {
    removeHeatmap();
    addHeatmap();
  }
}

function setBadge(id, text, kind) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.classList.remove("badge-ok", "badge-degraded", "badge-no-data", "badge-mock");
  if (kind === "ok") el.classList.add("badge-ok");
  else if (kind === "degraded") el.classList.add("badge-degraded");
  else if (kind === "no-data" || kind === "no_data") el.classList.add("badge-no-data");
  else if (kind === "mock") el.classList.add("badge-mock");
}

function renderWorstNoData(message) {
  const card = document.getElementById("worst-card");
  card.classList.add("empty");
  card.innerHTML = `
    <div class="worst-empty no-data">
      <div class="no-data-title">Sem dado disponível</div>
      <div class="no-data-msg">${escapeHtml(
        message || "MERGE/INPE indisponível neste ciclo. Tentando novamente em 10 min."
      )}</div>
    </div>
  `;
}

function setStatus(text, cls) {
  document.getElementById("status-line").textContent = text;
  const dot = document.getElementById("status-dot");
  dot.classList.remove("warn", "alert", "max");
  if (cls) dot.classList.add(cls);
}

// ============================================================================
// TRECHO MAIS CRÍTICO
// ============================================================================

function renderWorst(snap) {
  const card = document.getElementById("worst-card");
  const summary = snap.summary || {};
  const id = summary.max_rd_point;
  const points = snap.points || [];
  const worst = id ? points.find((p) => p.id === id) : null;

  if (!worst) {
    card.classList.add("empty");
    card.innerHTML = '<div class="worst-empty">Aguardando primeira leitura...</div>';
    return;
  }

  card.classList.remove("empty");
  card.style.borderLeftColor = NIVEL_COLOR[worst.rd];

  const levelTextColor = worst.rd === 1 ? "#0f172a" : "#ffffff";

  card.innerHTML = `
    <div class="worst-name">${escapeHtml(worst.nome)}</div>
    <div class="worst-rod">${escapeHtml(worst.rodovia)} · km ${worst.km} · ${escapeHtml(worst.region_name || "—")}</div>
    <span class="worst-level" style="background:${NIVEL_COLOR[worst.rd]};color:${levelTextColor}">
      Nível ${worst.rd} — ${NIVEL_LABEL[worst.rd]}
    </span>
    <div class="worst-stats">
      <div class="worst-stat" title="Chuva acumulada nas últimas 24 horas">
        <span>Chuva 24h</span><b>${worst.ac24h_mm} mm</b>
      </div>
      <div class="worst-stat" title="Chuva acumulada nas últimas 96 horas">
        <span>Acum. 96h</span><b>${worst.ac96h_mm} mm</b>
      </div>
      <div class="worst-stat" title="Intensidade horária na última leitura">
        <span>Intensidade</span><b>${worst.intensity_mmh} mm/h</b>
      </div>
      <div class="worst-stat" title="Coeficiente de Precipitação Crítica: razão entre chuva observada e a envoltória da região">
        <span>CPC</span><b>${worst.cpc !== null ? worst.cpc : "—"}</b>
      </div>
    </div>
  `;
}

// ============================================================================
// REGIÕES (sidebar e mapa)
// ============================================================================

function renderRegions(regions) {
  const list = document.getElementById("region-list");
  list.innerHTML = regions
    .map((r) => `
      <div class="region-row" title="Sensibilidade da região (parâmetro K). Quanto menor, mais sensível">
        <div class="region-info">
          <b>${r.id}. ${escapeHtml(r.nome)}</b>
          <small>${escapeHtml(r.rodovia || "")}</small>
        </div>
        <div class="region-k">
          <span>Sensibilidade</span>
          <code>K = ${r.k_geo}</code>
        </div>
      </div>
    `)
    .join("");
}

function renderRegionsOnMap(regions) {
  state.layers.regions.clearLayers();
  state.regionPolys = [];

  const colors = ["#3ec26e", "#116593", "#1c3d59", "#003b5a"];

  regions.forEach((r, idx) => {
    if (!r.polygon || !r.polygon.length) return;
    const poly = L.polygon(r.polygon, {
      color: colors[idx % colors.length],
      weight: 2,
      opacity: 0.85,
      fillOpacity: 0.05,
      dashArray: "6,4",
    }).bindTooltip(
      `Região ${r.id}: ${r.nome} (${r.rodovia})<br><small>Sensibilidade K=${r.k_geo}</small>`,
      { sticky: true }
    );
    poly.addTo(state.layers.regions);
    state.regionPolys.push(poly);
  });
}

// ============================================================================
// PONTOS DE MONITORAMENTO
// ============================================================================

function renderPointsOnMap(points) {
  state.layers.points.clearLayers();
  state.pointMarkers.clear();
  state.pointData.clear();

  points.forEach((p) => {
    const icon = L.divIcon({
      className: "",
      html: `<div class="point-marker rd-${p.rd}">${p.rd}</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
      popupAnchor: [0, -14],
    });
    const m = L.marker([p.lat, p.lon], { icon }).bindPopup(buildPopup(p));
    m.addTo(state.layers.points);
    state.pointMarkers.set(p.id, m);
    state.pointData.set(p.id, p);
  });
}

function buildPopup(p) {
  const levelTextColor = p.rd === 1 ? "#0f172a" : "#ffffff";
  return `
    <div class="popup-content">
      <h4>${escapeHtml(p.nome)}</h4>
      <div class="popup-rod">${escapeHtml(p.rodovia)} · km ${p.km}</div>
      <div class="popup-rod">Região: ${escapeHtml(p.region_name || "—")}</div>
      <table>
        <tr><td>Chuva 24h</td><td>${p.ac24h_mm} mm</td></tr>
        <tr><td>Acum. 96h</td><td>${p.ac96h_mm} mm</td></tr>
        <tr><td>Intensidade</td><td>${p.intensity_mmh} mm/h</td></tr>
        <tr><td>CPC</td><td>${p.cpc !== null ? p.cpc : "—"}</td></tr>
        <tr><td>Risco analisado</td><td>RA${p.ra}</td></tr>
        <tr><td>ICC geológico</td><td>${p.icc_geo}</td></tr>
        <tr><td>ICC hidrológico</td><td>${p.icc_hid}</td></tr>
      </table>
      <div class="popup-level" style="background:${NIVEL_COLOR[p.rd]};color:${levelTextColor}">
        Nível ${p.rd} — ${NIVEL_LABEL[p.rd]}
      </div>
      <div class="popup-source">${escapeHtml(p.source || "")}</div>
    </div>
  `;
}

// ============================================================================
// MAPA DE CALOR
// ============================================================================

function addHeatmap() {
  if (!L.heatLayer) {
    console.warn("leaflet.heat não carregou");
    return;
  }
  const heatPoints = [];
  state.pointData.forEach((p) => {
    // Intensidade do heatmap baseada em RD + chuva acumulada
    // Mesmo com RD=0 mostramos algum sinal de chuva
    const rdComp = p.rd / 4.0;          // 0..1
    const rainComp = Math.min(p.ac96h_mm / 200.0, 1.0);  // 0..1
    const intensity = Math.max(0.15, rdComp, rainComp * 0.6);
    heatPoints.push([p.lat, p.lon, intensity]);
  });

  if (!heatPoints.length) return;

  state.layers.heat = L.heatLayer(heatPoints, {
    radius: 45,
    blur: 35,
    maxZoom: 12,
    max: 1.0,
    minOpacity: 0.4,
    gradient: {
      0.0: "#2aa358",
      0.25: "#f1c40f",
      0.5: "#f39c12",
      0.75: "#e74c3c",
      1.0: "#8e44ad",
    },
  });
  state.layers.heat.addTo(state.map);
}

function removeHeatmap() {
  if (state.layers.heat) {
    state.map.removeLayer(state.layers.heat);
    state.layers.heat = null;
  }
}

// ============================================================================
// MALHA RODOVIÁRIA DER-SP
// ============================================================================

const ROAD_STYLE = {
  DUP:  { color: "#1c3d59", weight: 2.5, opacity: 0.85 },                          // pista dupla — azul navy
  PAV:  { color: "#3ec26e", weight: 1.8, opacity: 0.75 },                          // pavimentada simples — verde
  IMP:  { color: "#94a3b8", weight: 1.5, opacity: 0.6, dashArray: "4,4" },         // em implantação
  PLAN: { color: "#cbd5e1", weight: 1.2, opacity: 0.5, dashArray: "2,6" },         // planejada
  default: { color: "#64748b", weight: 1.5, opacity: 0.7 }
};

async function loadRoadNetwork() {
  const setSummary = (msg) => {
    const el = document.getElementById("road-stats-summary");
    if (el) el.textContent = msg;
  };

  try {
    const stats = await (await fetch("/api/road-stats")).json();
    populateFilterDropdowns(stats);

    setSummary("Carregando malha rodoviária...");
    const gj = await (await fetch("/api/road-network")).json();
    state.roadGeoJSON = gj;
    renderRoadsOnMap();

    updateStatsSummary(stats);
  } catch (e) {
    console.error("Erro ao carregar malha:", e);
    setSummary("Erro ao carregar a malha");
  }
}

function populateFilterDropdowns(stats) {
  const fillSelect = (id, values) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    values.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      sel.appendChild(opt);
    });
  };
  fillSelect("filter-tipo-pista", stats.tipos_pista || []);
  fillSelect("filter-regional", stats.regionais || []);
  fillSelect("filter-jurisdicao", stats.jurisdicoes || []);
}

function updateStatsSummary(stats) {
  const el = document.getElementById("road-stats-summary");
  if (!el) return;
  el.innerHTML =
    `<b>${stats.total_trechos.toLocaleString("pt-BR")}</b> trechos<br>` +
    `<b>${Math.round(stats.extensao_total_km).toLocaleString("pt-BR")}</b> km de extensão total<br>` +
    `<b>${stats.rodovias_unicas}</b> rodovias distintas`;
}

function renderRoadsOnMap() {
  if (!state.roadGeoJSON) return;
  state.layers.roads.clearLayers();

  const f = state.roadFilters;
  const filtered = {
    type: "FeatureCollection",
    features: state.roadGeoJSON.features.filter((feat) => {
      const p = feat.properties || {};
      if (f.tipo_pista && p.tipo_pista !== f.tipo_pista) return false;
      if (f.regional && p.regional !== f.regional) return false;
      if (f.jurisdicao && p.jurisdicao !== f.jurisdicao) return false;
      if (f.rodovia) {
        const q = f.rodovia.toLowerCase();
        if (!(p.rodovia || "").toLowerCase().includes(q)) return false;
      }
      return true;
    })
  };

  const gj = L.geoJSON(filtered, {
    style: (feat) => {
      const tp = feat.properties?.tipo_pista || "default";
      return ROAD_STYLE[tp] || ROAD_STYLE.default;
    },
    onEachFeature: (feat, layer) => {
      const p = feat.properties || {};
      layer.bindTooltip(
        `<b>${escapeHtml(p.rodovia || "?")}</b> km ${p.km_ini}–${p.km_fim}<br>${escapeHtml(p.municipio || "")}`,
        { sticky: true, direction: "top" }
      );
      layer.bindPopup(buildRoadPopup(p));
      layer.on("mouseover", () => layer.setStyle({ weight: 5, opacity: 1 }));
      layer.on("mouseout", () => {
        const tp = p.tipo_pista || "default";
        layer.setStyle(ROAD_STYLE[tp] || ROAD_STYLE.default);
      });
    }
  });
  gj.addTo(state.layers.roads);

  // Atualiza contagem
  const el = document.getElementById("road-stats-summary");
  if (el && state.roadGeoJSON) {
    const total = state.roadGeoJSON.features.length;
    const shown = filtered.features.length;
    const km = filtered.features.reduce((s, ft) => s + (ft.properties?.extensao || 0), 0);
    if (shown === total) {
      el.innerHTML =
        `<b>${total.toLocaleString("pt-BR")}</b> trechos · <b>${Math.round(km).toLocaleString("pt-BR")}</b> km`;
    } else {
      el.innerHTML =
        `Filtro ativo: <b>${shown.toLocaleString("pt-BR")}</b> de ${total.toLocaleString("pt-BR")} trechos<br>` +
        `Extensão filtrada: <b>${Math.round(km).toLocaleString("pt-BR")}</b> km`;
    }
  }
}

function buildRoadPopup(p) {
  const denom = p.denominacao ? `<small>${escapeHtml(p.denominacao)}</small>` : "";
  return `
    <div class="popup-content">
      <h4>${escapeHtml(p.rodovia || "?")} ${denom}</h4>
      <div class="popup-rod">${escapeHtml(p.municipio || "")} · ${escapeHtml(p.regional || "")}</div>
      <table>
        <tr><td>Quilômetro inicial</td><td>${p.km_ini ?? "—"}</td></tr>
        <tr><td>Quilômetro final</td><td>${p.km_fim ?? "—"}</td></tr>
        <tr><td>Extensão</td><td>${p.extensao ? p.extensao.toFixed(2) + " km" : "—"}</td></tr>
        <tr><td>Tipo de via</td><td>${escapeHtml(p.tipo || "—")}</td></tr>
        <tr><td>Tipo de pista</td><td>${escapeHtml(p.tipo_pista || "—")}</td></tr>
        <tr><td>Jurisdição</td><td>${escapeHtml(p.jurisdicao || "—")}</td></tr>
        <tr><td>Administração</td><td>${escapeHtml(p.administra || "—")}</td></tr>
        <tr><td>Residência DER</td><td>${escapeHtml(p.residencia || "—")}</td></tr>
      </table>
    </div>
  `;
}

function attachRoadFilterEvents() {
  const handler = () => {
    state.roadFilters = {
      tipo_pista: document.getElementById("filter-tipo-pista").value,
      regional: document.getElementById("filter-regional").value,
      jurisdicao: document.getElementById("filter-jurisdicao").value,
      rodovia: document.getElementById("filter-rodovia").value.trim()
    };
    renderRoadsOnMap();
  };
  ["filter-tipo-pista", "filter-regional", "filter-jurisdicao"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", handler);
  });
  let timer;
  document.getElementById("filter-rodovia")?.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(handler, 250);
  });
  document.getElementById("btn-clear-filters")?.addEventListener("click", () => {
    document.getElementById("filter-tipo-pista").value = "";
    document.getElementById("filter-regional").value = "";
    document.getElementById("filter-jurisdicao").value = "";
    document.getElementById("filter-rodovia").value = "";
    handler();
  });
  document.getElementById("layer-roads")?.addEventListener("change", (e) => {
    if (e.target.checked) state.map.addLayer(state.layers.roads);
    else state.map.removeLayer(state.layers.roads);
  });
}

// ============================================================================
// UTILITÁRIOS
// ============================================================================

function formatTime(d) {
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}
