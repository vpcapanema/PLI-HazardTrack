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

// Prefixo da app, injetado pelo template (vazio em raiz, "/hazardtrack" atras de Nginx em path)
const APP_BASE = (typeof window !== "undefined" && window.APP_BASE) ? window.APP_BASE : "";
const apiUrl = (path) => APP_BASE + path;

const NIVEL_LABEL = ["Monitoramento", "Observação", "Atenção", "Alerta", "Alerta Máximo"];
const NIVEL_COLOR = ["#2aa358", "#f1c40f", "#f39c12", "#e74c3c", "#8e44ad"];
const NIVEL_DESC = [
  "Sem chuva relevante",
  "Chuva próxima ao limiar",
  "Vistorias preventivas",
  "Possíveis ocorrências",
  "Risco severo"
];

// ============================================================================
// REGISTRY DE CAMADAS DE HAZARD
// Cada camada tem paleta propria de 5 niveis (escuro = mais grave) e funcao
// que extrai o RD daquele hazard a partir de um ponto do snapshot.
// Para adicionar uma camada nova: registrar entrada aqui + tornar `available`.
// ============================================================================
const HAZARDS = {
  encosta: {
    label: "Instabilidade de encosta",
    legendTitle: "Situação operacional dos trechos<br>rodoviários considerando: instabilidade de encosta",
    description: "Engloba escorregamento e queda de bloco. Pelo método em uso (REGEA-NIPPON 2021), são tratados na mesma envoltória crítica.",
    // Mesma escala dos pontos (niveis operacionais oficiais).
    palette: ["#2aa358", "#f1c40f", "#f39c12", "#e74c3c", "#8e44ad"],
    source: "REGEA-NIPPON 2021",
    available: true,
    rdFrom: (point) => Number.isInteger(point?.rd) ? point.rd : null,
  },
  inundacao: {
    label: "Inundação",
    legendTitle: "Situação operacional dos trechos<br>rodoviários considerando: inundação",
    description: "Alagamento e enxurrada por chuva intensa de curto prazo (24h).",
    // Nivel 0 = mesmo verde dos pontos (Monitoramento). Niveis 1-3 sobem em azul,
    // nivel 4 vira magenta/violeta vivido para destaque maximo.
    palette: ["#2aa358", "#5fa8d3", "#1d6fb8", "#0a3d7a", "#d61f8d"],
    source: "REGEA-NIPPON 2021",
    available: true,
    rdFrom: (point) => Number.isInteger(point?.rd) ? point.rd : null,
  },
};

// Estado das camadas, persistido em localStorage (controle do usuario).
// Default: todas as disponiveis ligadas; o que o usuario alterar fica salvo.
const HAZARD_STORAGE_KEY = "pli_hazardtrack.hazard_layers.v1";
const LEGEND_COLLAPSE_KEY = "pli_hazardtrack.legend_collapsed.v1";

function _loadLegendCollapsed() {
  try {
    const raw = localStorage.getItem(LEGEND_COLLAPSE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveLegendCollapsed() {
  try {
    localStorage.setItem(
      LEGEND_COLLAPSE_KEY,
      JSON.stringify(LEGEND_COLLAPSED)
    );
  } catch { /* ignora */ }
}

const LEGEND_COLLAPSED = _loadLegendCollapsed();

function _loadHazardState() {
  const defaults = Object.fromEntries(
    Object.entries(HAZARDS).filter(([, h]) => h.available).map(([k]) => [k, true])
  );
  try {
    const raw = localStorage.getItem(HAZARD_STORAGE_KEY);
    if (!raw) return defaults;
    const saved = JSON.parse(raw);
    // Mescla: chaves novas (versoes futuras) entram como default
    return { ...defaults, ...saved };
  } catch {
    return defaults;
  }
}

function saveHazardState() {
  try {
    localStorage.setItem(HAZARD_STORAGE_KEY, JSON.stringify(HAZARD_STATE));
  } catch { /* storage cheio/bloqueado: ignora */ }
}

const HAZARD_LAYER_KEY = { geo: "encosta", hidro: "inundacao" };

function snapshotPoints(snap) {
  const geo = snap?.points_geo || [];
  const hid = snap?.points_hidro || [];
  if (geo.length || hid.length) return { geo, hid };
  const legacy = snap?.points || [];
  return {
    geo: legacy.filter((p) => p.hazard === "geo" || p.ra_hid == null),
    hid: legacy.filter((p) => p.hazard === "hidro" || p.ra_geo == null),
  };
}

function activeByLevel(summary) {
  const encostaOn = HAZARD_STATE.encosta;
  const inundacaoOn = HAZARD_STATE.inundacao;
  if (encostaOn && !inundacaoOn) {
    return summary.by_level_geo || summary.by_level || {};
  }
  if (inundacaoOn && !encostaOn) {
    return summary.by_level_hidro || summary.by_level || {};
  }
  return summary.by_level || {};
}

const HAZARD_STATE = _loadHazardState();

const state = {
  map: null,
  layers: { hazardZones: {}, regions: null, heat: null, roads: null },
  pointMarkers: new Map(),
  pointData: new Map(),       // id -> dados completos do ponto (para heatmap)
  regionPolys: [],
  roadGeoJSON: null,
  roadFilters: {
    tipo_pista: "",
    regional: "",
    administra: "",
    rodovia: ""
  },
  // Animacao temporal (Linha do Tempo - Anexo C 3.4.2)
  timeline: {
    active: false,
    loading: false,
    playing: false,
    frames: [],
    idx: 0,
    step: 1,
    timer: null,
  },
  historyMode: false,
  historyAtIso: null,
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  initMap();
  attachEvents();
  renderHazardPanel();
  renderHazardLegend();
  initLegendToggles();
  loadRoadNetwork();
  refresh();
  setInterval(() => {
    if (!state.historyMode && !state.timeline.active) refresh();
  }, REFRESH_MS);
}

// ============================================================================
// MAPA
// ============================================================================

function initMap() {
  state.map = L.map("map", {
    zoomControl: false,
    attributionControl: false,
  });
  state.map.fitBounds(SP_BOUNDS);

  L.control.zoom({ position: "topright" }).addTo(state.map);

  // Painel de camadas DENTRO do mapa (filho de .leaflet-control-container)
  installMapLayerControl();

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    maxZoom: 19,
    minZoom: 6,
    subdomains: "abcd",
  }).addTo(state.map);

  L.control.attribution({ position: "bottomright", prefix: false })
    .addAttribution("OSM | CARTO | INPE/MERGE | DER-SP")
    .addTo(state.map);

  // Riscos Monitorados: cada hazard (encosta, inundacao) e uma camada propria
  // de zonas, colorida pelo seu RD em tempo real e ligada/desligada no painel.
  state.layers.hazardZones = {};
  Object.entries(HAZARDS).forEach(([key, h]) => {
    if (!h.available) return;
    const g = L.layerGroup();
    state.layers.hazardZones[key] = g;
    if (HAZARD_STATE[key]) g.addTo(state.map);
  });
  state.layers.regions = L.layerGroup();  // criada vazia, ligada via toggle
  state.layers.roads = L.layerGroup().addTo(state.map);
  // Camadas administrativas (criadas vazias; carregadas sob demanda no toggle)
  state.layers.municipios = L.layerGroup();
  state.layers.rc = L.layerGroup();
  state.layers.uba = L.layerGroup();
  state.layers.cgr = L.layerGroup();

  // Mascara visual: tudo fora do estado de SP fica esmaecido. Carregamento
  // assincrono - se falhar, o mapa funciona normal sem mascara.
  loadSpMask();
}

/**
 * Carrega o contorno do estado e desenha um poligono mundial com furo
 * no formato de SP. Resultado: SP fica nitido, o restante levemente apagado.
 */
async function loadSpMask() {
  try {
    const gj = await (await fetch(apiUrl("/static/data/sp_state.geojson"))).json();
    const feat = (gj.features || [])[0];
    if (!feat) return;

    // Coleta o(s) anel(eis) externo(s) do estado em formato lat/lon Leaflet.
    const collectRings = (geom) => {
      if (geom.type === "Polygon") return [geom.coordinates[0]];
      if (geom.type === "MultiPolygon") return geom.coordinates.map((p) => p[0]);
      return [];
    };
    const sp_rings_lonlat = collectRings(feat.geometry);
    const sp_rings_latlng = sp_rings_lonlat.map((ring) =>
      ring.map(([lon, lat]) => [lat, lon])
    );

    // Anel externo "do mundo" (sentido horario) + aneis de SP como furos
    const world = [[-90, -180], [-90, 180], [90, 180], [90, -180]];
    const polys = [world, ...sp_rings_latlng];

    const mask = L.polygon(polys, {
      color: "transparent",
      fillColor: "#0b1a2f",
      fillOpacity: 0.25,
      interactive: false,
      smoothFactor: 0.3,
    });
    mask.addTo(state.map);

    // Contorno fino do estado, ressaltando o limite. smoothFactor baixo para
    // o Leaflet nao re-simplificar a linha no render (mantem o tracado real).
    L.polygon(sp_rings_latlng, {
      color: "#1f2937",
      weight: 1.2,
      opacity: 0.55,
      fill: false,
      interactive: false,
      smoothFactor: 0.3,
    }).addTo(state.map);
  } catch (e) {
    console.warn("nao foi possivel carregar mascara de SP:", e);
  }
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
      if (state.historyMode) await exitHistoryMode(false);
      await fetch(apiUrl("/api/refresh"), { method: "POST" });
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

  // ---- Linha do Tempo (animacao 96h) ----
  document.getElementById("btn-timeline")?.addEventListener("click", openTimeline);
  document.getElementById("tl-close")?.addEventListener("click", closeTimeline);
  document.getElementById("tl-play")?.addEventListener("click", tlTogglePlay);
  document.getElementById("tl-prev")?.addEventListener("click", () => {
    tlPause();
    applyTimelineFrame(state.timeline.idx - state.timeline.step);
  });
  document.getElementById("tl-next")?.addEventListener("click", () => {
    tlPause();
    applyTimelineFrame(state.timeline.idx + state.timeline.step);
  });
  document.getElementById("tl-range")?.addEventListener("input", (e) => {
    tlPause();
    applyTimelineFrame(Number(e.target.value));
  });
  document.getElementById("tl-step")?.addEventListener("change", (e) => {
    state.timeline.step = Math.max(1, Number(e.target.value) || 1);
  });

  // ---- Consulta histórica (badge de data/hora) ----
  const badgeUpdate = document.getElementById("badge-update");
  const timePanel = document.getElementById("time-travel-panel");
  badgeUpdate?.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!timePanel) return;
    const open = timePanel.hidden;
    timePanel.hidden = !open;
    if (open) {
      const inp = document.getElementById("history-at");
      if (inp && !inp.value) {
        const d = new Date();
        d.setMinutes(0, 0, 0);
        inp.value = toDatetimeLocalValue(d);
        inp.max = toDatetimeLocalValue(new Date());
      }
      loadHistoryHints();
    }
  });
  document.getElementById("history-go")?.addEventListener("click", () => {
    runHistoricalConsultation();
  });
  document.getElementById("history-live")?.addEventListener("click", () => {
    exitHistoryMode(true);
  });
  document.addEventListener("click", (e) => {
    const wrap = document.getElementById("time-travel-wrap");
    if (!wrap || !timePanel || timePanel.hidden) return;
    if (!wrap.contains(e.target)) timePanel.hidden = true;
  });

  document.getElementById("layer-regions").addEventListener("change", (e) => {
    if (e.target.checked) state.map.addLayer(state.layers.regions);
    else state.map.removeLayer(state.layers.regions);
  });

  document.getElementById("layer-heatmap").addEventListener("change", (e) => {
    if (e.target.checked) addHeatmap();
    else removeHeatmap();
  });

  attachAdminLayerEvents();
  attachRoadFilterEvents();
  attachModalEvents();
}

/**
 * Cria um L.Control com o painel "Camadas do mapa" - vira filho do
 * .leaflet-control-container (dentro do conteiner do Leaflet, canto sup-esq).
 */
function installMapLayerControl() {
  const Ctrl = L.Control.extend({
    options: { position: "topleft" },
    onAdd() {
      const wrap = L.DomUtil.create("div", "map-layer-control leaflet-bar");
      wrap.id = "map-layer-control";
      wrap.innerHTML = `
        <div class="map-layer-control-head">
          <span class="map-layer-control-title">Camadas do mapa</span>
          <button type="button" class="map-layer-control-toggle"
                  id="map-layer-control-toggle" aria-label="Recolher/expandir">▾</button>
        </div>
        <div class="map-layer-control-body">
          <div class="ck-group-title">Riscos Monitorados</div>
          <div id="hazard-toggles"></div>

          <div class="ck-group-title">Outras camadas</div>
          <label class="ck"><input type="checkbox" id="layer-regions"> Limites das regiões</label>
          <label class="ck"><input type="checkbox" id="layer-heatmap"> Mapa de calor de risco</label>
          <label class="ck"><input type="checkbox" id="layer-roads" checked> Malha rodoviária estadual (DER)</label>

          <div class="ck-group-title">Limites administrativos</div>
          <label class="ck"><input type="checkbox" id="layer-municipios"> Municípios (IGC 2021)</label>
          <label class="ck"><input type="checkbox" id="layer-rc"> Residências de Conserva (DER)</label>
          <label class="ck"><input type="checkbox" id="layer-uba"> Unidades Básicas de Atendimento (DER)</label>
          <label class="ck"><input type="checkbox" id="layer-cgr"> Coordenadorias Gerais Regionais (DER)</label>
        </div>
      `;

      // Bloqueia eventos de mapa (evita pan/zoom ao interagir com o painel)
      L.DomEvent.disableClickPropagation(wrap);
      L.DomEvent.disableScrollPropagation(wrap);

      // Toggle recolher/expandir
      const btn = wrap.querySelector("#map-layer-control-toggle");
      btn.addEventListener("click", () => wrap.classList.toggle("collapsed"));

      return wrap;
    },
  });
  new Ctrl().addTo(state.map);
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
  if (state.timeline.active) return;
  try {
    const url = state.historyMode && state.historyAtIso
      ? apiUrl("/api/snapshot?at=" + encodeURIComponent(state.historyAtIso))
      : apiUrl("/api/snapshot");
    const res = await fetch(url);
    const snap = await res.json();
    renderSnapshot(snap);
    // Coerencia logica: os paineis dependentes (Acoes, Previsao) so podem
    // concluir depois que o Monitoramento (estado geral da malha) terminar
    // de processar e renderizar os dados do ciclo.
    const st = (snap.summary && snap.summary.data_status) || "ok";
    if (st === "loading") {
      renderActionsWaiting();
      renderForecastWaiting();
    } else if (st === "no_data") {
      renderActionsNoData();
      renderForecastNoData();
    } else {
      loadActions();
      loadForecast();
    }
  } catch (e) {
    console.error("Erro ao atualizar snapshot:", e);
    setStatus("Erro de conexão com o servidor", "alert");
  }
}

// ============================================================================
// LINHA DO TEMPO (animacao 96h dos poligonos de alerta - Anexo C, 3.4.2)
// ============================================================================

function tlActiveChannelMessage() {
  const enc = HAZARD_STATE.encosta;
  const hid = HAZARD_STATE.inundacao;
  if (enc && hid) {
    return (
      "Camadas ativas: encosta (RD geológico, paleta verde→roxo) e " +
      "inundação (RD hidrológico, paleta verde→azul→magenta). " +
      "Cada UA usa a cor do seu canal."
    );
  }
  if (enc) {
    return "Camada ativa: Instabilidade de encosta — níveis de RD geológico (geo).";
  }
  if (hid) {
    return "Camada ativa: Inundação — níveis de RD hidrológico (24 h).";
  }
  return "Nenhuma camada ligada — marque Encosta ou Inundação no painel lateral.";
}

function updateTimelineChannelHint() {
  const el = tlEl("tl-channel");
  if (el) el.textContent = tlActiveChannelMessage();
}

function toDatetimeLocalValue(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return (
    d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
    "T" + pad(d.getHours()) + ":" + pad(d.getMinutes())
  );
}

let historyHintsLoaded = false;

async function loadHistoryHints() {
  const box = document.getElementById("history-hints");
  if (!box) return;
  if (historyHintsLoaded) return;
  try {
    const res = await fetch(apiUrl("/api/history-hints"));
    const data = await res.json();
    renderHistoryHints(data.events || [], data.disclaimer || "");
    historyHintsLoaded = true;
  } catch (e) {
    console.warn("history hints", e);
    box.innerHTML =
      "<span class=\"history-hints-loading\">Sugestões indisponíveis.</span>";
  }
}

function renderHistoryHints(events, disclaimer) {
  const box = document.getElementById("history-hints");
  if (!box) return;
  if (!events.length) {
    box.innerHTML =
      "<span class=\"history-hints-loading\">Nenhum evento cadastrado.</span>";
    return;
  }
  box.innerHTML = "";
  events.forEach((ev) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "history-hint-btn";
    const note = [ev.note, ev.source].filter(Boolean).join(" — ");
    btn.title = note;
    const lvl = ev.max_level ?? 0;
    const color = NIVEL_COLOR[lvl] || "#64748b";
    btn.innerHTML =
      "<span class=\"history-hint-level\" style=\"background:" + color +
      "\"></span><span class=\"history-hint-text\"><strong>" +
      escapeHtml(ev.label) + "</strong><small>" +
      escapeHtml(ev.level_label || "") + " · " +
      escapeHtml(ev.region || "") + "</small></span>";
    btn.addEventListener("click", () => {
      const inp = document.getElementById("history-at");
      if (inp && ev.at_utc) {
        inp.value = toDatetimeLocalValue(new Date(ev.at_utc));
      }
      runHistoricalConsultation();
    });
    box.appendChild(btn);
  });
  if (disclaimer) {
    const foot = document.createElement("p");
    foot.className = "time-travel-hints-help";
    foot.style.marginTop = "0.25rem";
    foot.textContent = disclaimer;
    box.appendChild(foot);
  }
}

async function runHistoricalConsultation() {
  const inp = document.getElementById("history-at");
  const panel = document.getElementById("time-travel-panel");
  if (!inp?.value) return;
  const atIso = new Date(inp.value).toISOString();
  state.historyMode = true;
  state.historyAtIso = atIso;
  if (panel) panel.hidden = true;
  closeTimeline();
  setBadge("badge-update", "Consultando…", "loading");
  setStatus("Consultando chuva MERGE/INPE na data selecionada…", "warn");
  document.getElementById("status-time").textContent =
    "Pode levar alguns minutos (96 GRIBs da época)";
  startDownloadPoll();
  setMapHistoryBanner("Carregando chuva MERGE/INPE da época…", true);
  try {
    const res = await fetch(
      apiUrl("/api/snapshot?at=" + encodeURIComponent(atIso))
    );
    const snap = await res.json();
    renderSnapshot(snap);
    loadActions();
    loadForecast();
  } catch (e) {
    console.error(e);
    setStatus("Erro na consulta histórica", "alert");
  }
}

async function exitHistoryMode(refreshLive) {
  state.historyMode = false;
  state.historyAtIso = null;
  const panel = document.getElementById("time-travel-panel");
  if (panel) panel.hidden = true;
  if (refreshLive) {
    setBadge("badge-update", "Ao vivo…", "loading");
    setMapHistoryBanner(null);
    try {
      await fetch(apiUrl("/api/refresh"), { method: "POST" });
    } catch { /* ignora */ }
    await refresh();
  }
}

function tlEl(id) {
  return document.getElementById(id);
}

async function openTimeline() {
  const panel = tlEl("timeline");
  if (!panel) return;
  panel.hidden = false;
  if (state.timeline.frames.length) {
    state.timeline.active = true;
    applyTimelineFrame(state.timeline.idx);
    return;
  }
  state.timeline.loading = true;
  updateTimelineChannelHint();
  tlEl("tl-status").textContent = "Montando animação a partir do cache MERGE…";
  tlEl("tl-play").disabled = true;
  try {
    const res = await fetch(apiUrl("/api/timeline"));
    const data = await res.json();
    if (!data.available || !Array.isArray(data.frames) || !data.frames.length) {
      tlEl("tl-status").textContent =
        data.reason || "Sem dados para a animação.";
      return;
    }
    state.timeline.frames = data.frames;
    state.timeline.idx = data.frames.length - 1;   // comeca no "agora"
    state.timeline.active = true;
    const range = tlEl("tl-range");
    range.min = 0;
    range.max = data.frames.length - 1;
    range.value = state.timeline.idx;
    range.disabled = false;
    tlEl("tl-status").textContent = "";
    updateTimelineChannelHint();
    applyTimelineFrame(state.timeline.idx);
  } catch (e) {
    console.error("Erro na linha do tempo:", e);
    tlEl("tl-status").textContent = "Erro ao carregar a animação.";
  } finally {
    state.timeline.loading = false;
    tlEl("tl-play").disabled = false;
  }
}

function closeTimeline() {
  tlPause();
  state.timeline.active = false;
  const panel = tlEl("timeline");
  if (panel) panel.hidden = true;
  refresh();   // restaura as cores ao vivo
}

function applyTimelineFrame(idx) {
  const frames = state.timeline.frames;
  if (!frames.length) return;
  idx = Math.max(0, Math.min(frames.length - 1, idx));
  state.timeline.idx = idx;
  const frame = frames[idx];
  for (const [markerKey, markers] of state.pointMarkers) {
    const hazardKey = markerKey.includes(":")
      ? markerKey.split(":")[1]
      : "encosta";
    const uaId = markerKey.includes(":")
      ? markerKey.split(":")[0]
      : markerKey;
    const rdMap = hazardKey === "inundacao"
      ? (frame.rd_hidro || frame.rd || {})
      : (frame.rd_geo || frame.rd || {});
    const v = rdMap[uaId];
    const palette = HAZARDS[hazardKey]?.palette || NIVEL_COLOR;
    const color = Number.isInteger(v)
      ? (palette[v] || "#64748b")
      : "#64748b";
    const arr = Array.isArray(markers) ? markers : [markers];
    arr.forEach((m) => m.setStyle({ color, fillColor: color }));
  }
  const range = tlEl("tl-range");
  if (range) range.value = idx;
  updateTimelineChannelHint();
  const t = frame.ts ? new Date(frame.ts) : null;
  tlEl("tl-time").textContent = t
    ? t.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit",
        hour: "2-digit", minute: "2-digit" })
    : "—";
}

function tlPlay() {
  if (!state.timeline.frames.length) return;
  state.timeline.playing = true;
  tlEl("tl-play").textContent = "⏸";
  // Se estiver no fim, reinicia do comeco
  if (state.timeline.idx >= state.timeline.frames.length - 1) {
    applyTimelineFrame(0);
  }
  state.timeline.timer = setInterval(() => {
    const next = state.timeline.idx + state.timeline.step;
    if (next >= state.timeline.frames.length) {
      applyTimelineFrame(state.timeline.frames.length - 1);
      tlPause();
      return;
    }
    applyTimelineFrame(next);
  }, 600);
}

function tlPause() {
  state.timeline.playing = false;
  const btn = tlEl("tl-play");
  if (btn) btn.textContent = "▶";
  if (state.timeline.timer) {
    clearInterval(state.timeline.timer);
    state.timeline.timer = null;
  }
}

function tlTogglePlay() {
  if (state.timeline.playing) tlPause();
  else tlPlay();
}

function renderSnapshot(snap) {
  state.lastSnapshot = snap;
  const ts = snap.timestamp_utc ? new Date(snap.timestamp_utc) : null;
  const summary = snap.summary || {};
  const maxRd = summary.max_rd ?? 0;
  const status = summary.data_status || "ok";   // ok | degraded | no_data | mock | loading
  const isHistorical = !!summary.historical;

  if (!isHistorical) {
    setMapHistoryBanner(null);
  }

  // ---- Consulta histórica (badge seletor de data) ----
  if (isHistorical) {
    const consulted = summary.consulted_at || snap.timestamp_utc;
    const tConsult = consulted ? new Date(consulted) : null;
    updateMapHistoryBanner(summary, snap);
    setBadge(
      "badge-update",
      tConsult ? "Histórico " + formatTime(tConsult) : "Histórico",
      "historical"
    );
    if (summary.data_status === "no_data") {
      renderSnapshotNoData(snap, summary, tConsult);
      return;
    }
    setStatus(
      `Consulta histórica — ${NIVEL_LABEL[maxRd]} na data escolhida`,
      maxRd >= 3 ? "alert" : maxRd >= 2 ? "warn" : ""
    );
    document.getElementById("status-time").textContent =
      (summary.rd_basis || "Chuva observada MERGE") +
      (summary.merge_target_hour
        ? " · hora MERGE " + formatTime(new Date(summary.merge_target_hour))
        : "");
    setBadge("badge-source", "MERGE / INPE (hist.)", "degraded");
    stopDownloadPoll();
    renderPointsOnMap(snap);
    renderRegionsOnMap(snap.regions || []);
    renderRegions(snap.regions || []);
    if (state.roadGeoJSON) renderRoadsOnMap();
    renderWorst(snap);
    const by = activeByLevel(summary);
    for (let i = 0; i <= 4; i++) {
      const el = document.getElementById("count-" + i);
      if (el) el.textContent = by[i] || 0;
    }
    applyMeterHighlight(summary, maxRd);
    renderRdBasisNote(summary, status);
    return;
  }

  // ---- Primeiro ciclo ainda em andamento (servidor recem-bootado) ----
  if (status === "loading") {
    setStatus("Preparando monitoramento — baixando chuva do INPE", "warn");
    document.getElementById("status-time").textContent =
      "Primeira carga: últimas 96 horas (costuma levar de 3 a 8 min)";
    setBadge("badge-source", "MERGE / INPE", "loading");
    setBadge("badge-update", "carregando", "loading");
    // Mostra a malha em estilo "sem dado" para a interface nao ficar vazia
    // enquanto o primeiro update do MERGE termina.
    renderPointsOnMap(snap);
    renderRegionsOnMap(snap.regions || []);
    renderRegions(snap.regions || []);
    if (state.roadGeoJSON) renderRoadsOnMap();
    startDownloadPoll();
    renderRdBasisNote(summary, status);
    document.querySelectorAll(".meter-cell").forEach((c) => c.classList.remove("active"));
    // Distribuicao ainda nao processada: nao exibir como "concluido".
    for (let i = 0; i <= 4; i++) {
      const el = document.getElementById("count-" + i);
      if (el) el.textContent = "\u2014";
    }
    return;
  }

  // ---- Estado de DADOS (precede o estado operacional) ----
  if (status === "no_data") {
    fetch(apiUrl("/api/progress"))
      .then((r) => r.json())
      .then((prog) => {
        if (isIngestProgressBusy(prog)) {
          renderSnapshot({
            ...snap,
            summary: { ...summary, data_status: "loading" },
          });
        } else {
          renderSnapshotNoData(snap, summary, ts);
        }
      })
      .catch(() => renderSnapshotNoData(snap, summary, ts));
    return;
  }

  // ---- Estado operacional normal ----
  stopDownloadPoll();
  const statusClasses = ["", "warn", "warn", "alert", "max"];
  const statusSuffix = status === "degraded"
    ? ` · leitura incompleta (${summary.missing_24h}h faltando em 24h)`
    : status === "mock"
      ? " · modo de teste (dados simulados)"
      : "";
  setStatus(
    `${NIVEL_LABEL[maxRd]} — situação geral na área monitorada${statusSuffix}`,
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

  // Distribuição por nível (camada(s) ativa(s))
  const by = activeByLevel(summary);
  for (let i = 0; i <= 4; i++) {
    const el = document.getElementById("count-" + i);
    if (el) el.textContent = by[i] || 0;
  }
  applyMeterHighlight(summary, maxRd);

  // Trecho mais crítico
  renderWorst(snap);

  // Regiões
  renderRegions(snap.regions || []);

  // Mapa
  renderRegionsOnMap(snap.regions || []);
  renderPointsOnMap(snap);

  // Malha DER: apoio cartográfico (sem tradução de alerta)
  if (state.roadGeoJSON) renderRoadsOnMap();

  // Heatmap (se ativo, atualiza)
  if (document.getElementById("layer-heatmap").checked) {
    removeHeatmap();
    addHeatmap();
  }

  renderRdBasisNote(summary, status);
}

function setBadge(id, text, kind) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.classList.remove(
    "badge-ok", "badge-degraded", "badge-no-data", "badge-mock",
    "badge-loading", "badge-historical"
  );
  if (kind === "ok") el.classList.add("badge-ok");
  else if (kind === "degraded") el.classList.add("badge-degraded");
  else if (kind === "no-data" || kind === "no_data") el.classList.add("badge-no-data");
  else if (kind === "mock") el.classList.add("badge-mock");
  else if (kind === "loading") el.classList.add("badge-loading");
  else if (kind === "historical") el.classList.add("badge-historical");
}

function isIngestProgressBusy(prog) {
  if (!prog) return false;
  if (prog.active || prog.refreshing) return true;
  if (prog.phase === "processing") return true;
  const cached = prog.hours_cached_ok ?? 0;
  const minOk = prog.min_ok_hours ?? 24;
  if (!prog.ingest_ready && cached < minOk) return true;
  const total = prog.total || 0;
  const done = prog.done || 0;
  return total > 0 && done < total;
}

function renderSnapshotNoData(snap, summary, ts) {
  setStatus("Dados de chuva indisponíveis neste momento", "alert");
  document.getElementById("status-time").textContent =
    ts ? "Última tentativa às " + formatTime(ts) : "—";
  setBadge("badge-source", "Sem dado", "no-data");
  setBadge("badge-update", ts ? formatTime(ts) : "—", "no-data");
  renderPointsOnMap(snap);
  renderRegionsOnMap(snap.regions || []);
  renderRegions(snap.regions || []);
  if (state.roadGeoJSON) renderRoadsOnMap();
  stopDownloadPoll();
  renderWorstNoData(summary.message);
  renderRdBasisNote(summary, "no_data");
  document.querySelectorAll(".meter-cell").forEach((c) => {
    c.classList.remove("active", "meter-cell--blink");
  });
  for (let i = 0; i <= 4; i++) {
    const el = document.getElementById("count-" + i);
    if (el) el.textContent = "\u2014";
  }
}

function renderWorstNoData(message) {
  const card = document.getElementById("worst-card");
  card.classList.add("empty");
  card.classList.remove("worst-card--blink");
  card.innerHTML = `
    <div class="worst-empty no-data">
      <div class="no-data-title">Chuva indisponível</div>
      <div class="no-data-msg">${escapeHtml(
        message || (
          "Não foi possível obter a chuva medida pelo INPE agora. "
          + "Nova tentativa automática em até 10 min."
        )
      )}</div>
    </div>
  `;
}

// Progresso do primeiro ciclo: lista rolavel de arquivos (ativos +
// concluidos), cada um com barra real vinda do servidor, mais total X/Y.
const _dl = {
  poll: null, data: null,
  mode: null, procStart: null, doneAt: null, refreshed: false,
};

function stopDownloadPoll() {
  if (_dl.poll) { clearInterval(_dl.poll); _dl.poll = null; }
  _dl.data = null;
  _dl.mode = null;
  _dl.procStart = null;
  _dl.doneAt = null;
  _dl.refreshed = false;
}

function formatBytes(n) {
  const v = Number(n) || 0;
  if (v >= 1e6) return (v / 1e6).toFixed(1) + " MB";
  if (v >= 1e3) return (v / 1e3).toFixed(0) + " KB";
  return v + " B";
}

/** Rotulo da barra por fase do pipeline (download / decode / ok). */
function fileProgressLabel(f) {
  if (f.status === "ok") return { pct: 100, text: "Concluído" };
  if (f.status === "fail") return { pct: 0, text: "Falha" };
  if (f.status === "decoding") {
    return { pct: null, text: "Interpretando", indeterminate: true };
  }
  if (f.status === "pending") {
    return { pct: 0, text: "Aguardando" };
  }
  const pct = Number(f.pct);
  if (Number.isFinite(pct) && pct > 0) {
    return { pct, text: "Baixando " + Math.round(pct) + "%" };
  }
  if (f.bytes_done > 0) {
    return {
      pct: null,
      text: "Baixando " + formatBytes(f.bytes_done),
      indeterminate: true,
    };
  }
  return { pct: 0, text: "Iniciando..." };
}

function dlPanelTitle(d) {
  if (!d) return "Baixando chuva medida (INPE)";
  if (d.phase === "processing") return "Calculando níveis de alerta";
  if (d.batch_kind === "incremental") {
    return "Atualizando horas recentes";
  }
  const cached = d.hours_cached_ok ?? 0;
  const minOk = d.min_ok_hours ?? 24;
  if (cached < minOk) {
    return "Montando histórico de chuva";
  }
  if (cached < (d.hours_back ?? 96)) {
    return "Completando histórico horário";
  }
  return "Baixando chuva medida (INPE)";
}

function dlPanelSubtitle(d) {
  if (!d) {
    return "Fonte oficial INPE/MERGE — leituras horárias de precipitação.";
  }
  if (d.phase === "processing") {
    return "Chuva já carregada; aplicando sensibilidade regional e níveis PPDC.";
  }
  if (d.batch_kind === "incremental") {
    return "O INPE republicou as horas mais recentes; só elas são revisadas.";
  }
  const cached = d.hours_cached_ok ?? 0;
  const back = d.hours_back ?? 96;
  const minOk = d.min_ok_hours ?? 24;
  if (cached < minOk) {
    return (
      `Carregando ${back} horas para calcular os alertas. ` +
      `Mínimo para operar: ${minOk} horas válidas.`
    );
  }
  return "Download do INPE e leitura dos arquivos em segundo plano.";
}

function dlBatchHintText(d) {
  const total = d.total || 0;
  const workers = d.workers ?? 12;
  const decWorkers = d.decode_workers ?? 6;
  if (d.batch_kind === "incremental" && total > 0) {
    return (
      `Republicação INPE: ${total} hora(s) recente(s) em atualização.`
    );
  }
  if (total > 0 && (d.hours_cached_ok ?? 0) < (d.min_ok_hours ?? 24)) {
    return (
      `Primeira carga: ${total} arquivos horários · ` +
      `${workers} downloads e ${decWorkers} leituras em paralelo. ` +
      "Tempo típico: 3 a 8 min."
    );
  }
  if (total > 0) {
    return `${workers} downloads e ${decWorkers} leituras em paralelo.`;
  }
  return "";
}

/** Barra unica: horas em memoria (carga inicial) ou lote incremental. */
function dlMainProgress(d) {
  const cacheBack = d.hours_back || 96;
  const cacheOk = d.hours_cached_ok ?? 0;
  const cacheDisplay = d.cache_hours_display ?? cacheOk;
  const minOk = d.min_ok_hours ?? 24;
  const batchTotal = d.total || 0;
  const batchDone = d.done || 0;
  const batchDisp = d.batch_done_display ?? batchDone;
  const batchBusy = batchTotal > 0 && (
    d.active || batchDisp < batchTotal || batchDone < batchTotal
  );
  const isIncremental = d.batch_kind === "incremental";

  if (isIncremental && batchBusy) {
    const batchPct = Number.isFinite(d.batch_pct)
      ? d.batch_pct
      : (batchTotal ? (batchDisp / batchTotal) * 100 : 0);
    const doneTxt = batchDisp < batchTotal && batchDisp % 1
      ? batchDisp.toFixed(1)
      : String(Math.round(batchDisp));
    return {
      label: "Atualizando horas recentes",
      pct: batchPct,
      count: `${doneTxt} / ${batchTotal} arquivo(s)`,
    };
  }

  const cachePct = Number.isFinite(d.cache_pct)
    ? d.cache_pct
    : (cacheBack ? Math.min(100, (cacheOk / cacheBack) * 100) : 0);
  const disp = Number.isFinite(cacheDisplay)
    ? Math.round(cacheDisplay * 10) / 10
    : cacheOk;
  let count = `${disp} de ${cacheBack} horas prontas`;
  const faltaMin = Math.max(0, minOk - cacheOk);
  if (faltaMin > 0 && cacheOk < minOk) {
    count += ` · faltam ${faltaMin} h para exibir alertas no mapa`;
  }
  return {
    label: cacheOk < minOk ? "Montando histórico de chuva" : "Histórico em memória",
    pct: cachePct,
    count,
  };
}

function dlActivityHint(d) {
  const dlN = d.downloading ?? 0;
  const decN = d.decoding ?? 0;
  const pending = d.queued ?? 0;
  const failN = d.fail ?? 0;
  const parts = [];
  if (dlN > 0) parts.push(`${dlN} baixando do INPE`);
  if (decN > 0) parts.push(`${decN} lendo arquivos`);
  if (pending > 0) parts.push(`${pending} na fila`);
  if (failN > 0) {
    parts.push(`${failN} falha(s) — nova tentativa automática`);
  }
  if (!parts.length) {
    const ok = d.hours_cached_ok ?? 0;
    const back = d.hours_back ?? 96;
    if (ok < back) return "Preparando próximas horas...";
    return "Aguardando próxima etapa...";
  }
  return "Agora: " + parts.join(" · ");
}

function dlProcessingTitle(d) {
  if (d?.phase === "done") return "Painel atualizado";
  const stage = d?.stage;
  if (stage === "risk") return "Calculando alerta por trecho monitorado";
  if (stage === "forecast") return "Incorporando previsão de chuva";
  if (stage === "publish") return "Atualizando o mapa";
  if (stage === "aggregate") return "Organizando chuva já medida";
  return "Finalizando cálculo";
}

function dlProcessingSubtitle(d) {
  if (d?.phase === "done") {
    return "Dados prontos — o mapa será atualizado em instantes.";
  }
  return "A chuva do INPE já foi carregada; as etapas abaixo rodam em sequência.";
}

function startDownloadPoll() {
  if (_dl.poll) return;
  _dl.mode = "download";
  buildDownloadCard();
  const poll = async () => {
    try {
      const r = await fetch(apiUrl("/api/progress"));
      _dl.data = await r.json();
      renderDownloadFrame();
    } catch { /* ignora erro de rede transitorio */ }
  };
  poll();
  _dl.poll = setInterval(poll, 250);
}

function buildDownloadCard() {
  const card = document.getElementById("worst-card");
  if (!card) return;
  card.classList.add("empty");
  card.classList.remove("worst-card--busy");
  card.innerHTML = `
    <div class="worst-empty loading dl-box">
      <div class="loading-title">
        <span class="loading-spinner" aria-hidden="true"></span>
        <span class="dl-title-text">Baixando chuva medida (INPE)</span>
      </div>
      <p class="dl-subtitle">Fonte oficial INPE/MERGE — leituras horárias de precipitação.</p>
      <div class="dl-cache">
        <div class="dl-overall-top">
          <span class="dl-progress-label">Montando histórico de chuva</span>
          <span class="dl-cache-pct">0 / 96 horas</span>
        </div>
        <div class="dl-bar dl-bar-lg dl-bar-cache">
          <div class="dl-bar-fill dl-cache-fill"></div>
        </div>
      </div>
      <div class="dl-batch-hint"></div>
      <ul class="dl-list" aria-label="Arquivos em andamento"></ul>
      <div class="dl-list-hint"></div>
    </div>`;
}

/** Arquivos visiveis (servidor envia subconjunto ativo + recentes). */
function listDownloadFiles(d) {
  return Array.isArray(d.files) ? d.files : [];
}

function rowStatusClass(f) {
  if (f.status === "ok") return "dl-ok";
  if (f.status === "fail") return "dl-fail";
  if (f.status === "decoding") return "dl-decoding";
  if (f.status === "downloading") return "dl-active";
  if (f.status === "pending") return "dl-pending";
  return "";
}

function renderDownloadFrame() {
  const card = document.getElementById("worst-card");
  const d = _dl.data;
  if (!card || !d) return;
  const ingestBusy = isIngestProgressBusy(d);
  const batchBusy = d.total > 0 && d.done < d.total;
  const mode = (d.phase === "ingest" && (d.active || batchBusy))
    || (ingestBusy && d.phase !== "processing" && d.phase !== "done")
    ? "download"
    : (d.phase === "processing" || d.phase === "done")
      ? "processing"
      : _dl.mode;
  if (mode !== _dl.mode) {
    _dl.mode = mode;
    _dl.procStart = null;
    _dl.doneAt = null;
    if (mode === "download") buildDownloadCard();
    else if (mode === "processing") buildProcessingCard(d);
  }
  if (mode === "download") renderDownloadList(d);
  else if (mode === "processing") renderProcessing(d);
}

function renderDownloadList(d) {
  const card = document.getElementById("worst-card");
  const list = card?.querySelector(".dl-list");
  const hint = card?.querySelector(".dl-list-hint");
  const batchHint = card?.querySelector(".dl-batch-hint");
  const subtitleEl = card?.querySelector(".dl-subtitle");
  const titleEl = card?.querySelector(".dl-title-text");
  if (!list) return;
  const files = listDownloadFiles(d);

  if (titleEl) titleEl.textContent = dlPanelTitle(d);
  if (subtitleEl) subtitleEl.textContent = dlPanelSubtitle(d);
  if (batchHint) batchHint.textContent = dlBatchHintText(d);
  if (hint) hint.textContent = dlActivityHint(d);

  const main = dlMainProgress(d);
  const cacheFill = card.querySelector(".dl-cache-fill");
  const cacheCount = card.querySelector(".dl-cache-pct");
  const progressLabel = card.querySelector(".dl-progress-label");
  if (progressLabel) progressLabel.textContent = main.label;
  if (cacheFill) cacheFill.style.width = main.pct + "%";
  if (cacheCount) cacheCount.textContent = main.count;

  const prevKeys = list.dataset.keys || "";
  const nextKeys = files.map((f) => `${f.h}:${f.status}`).join(",");
  if (prevKeys !== nextKeys) {
    list.dataset.keys = nextKeys;
    if (!files.length) {
      list.innerHTML =
        `<li class="dl-row dl-empty">Conectando ao servidor de chuva do INPE...</li>`;
    } else {
      list.innerHTML = files.map((f) => `
      <li class="dl-row ${rowStatusClass(f)}" data-h="${f.h}">
        <div class="dl-name">${escapeHtml(f.name)}</div>
        <div class="dl-line">
          <div class="dl-bar"><div class="dl-bar-fill"></div></div>
          <span class="dl-pct">0%</span>
        </div>
      </li>`).join("");
    }
  }

  files.forEach((f) => {
    const row = list.querySelector(`.dl-row[data-h="${f.h}"]`);
    if (!row) return;
    row.className = "dl-row " + rowStatusClass(f);
    const fill = row.querySelector(".dl-bar-fill");
    const pctEl = row.querySelector(".dl-pct");
    const prog = fileProgressLabel(f);
    fill.classList.remove("dl-bar-indeterminate");
    if (prog.indeterminate) {
      fill.classList.add("dl-bar-indeterminate");
      fill.style.width = prog.pct != null ? prog.pct + "%" : "";
    } else if (prog.pct != null) {
      fill.style.width = prog.pct + "%";
    } else {
      fill.style.width = "0%";
    }
    pctEl.textContent = prog.text;
  });
}

function buildProcessingCard(d) {
  const card = document.getElementById("worst-card");
  if (!card) return;
  card.classList.add("empty", "worst-card--busy");
  const stages = Array.isArray(d.stages) ? d.stages : [];
  const rows = stages.map((st) => `
      <li class="pr-card pr-pending" data-key="${escapeHtml(st.key)}">
        <span class="pr-ic" aria-hidden="true"></span>
        <span class="pr-label">${escapeHtml(st.label)}</span>
      </li>`).join("");
  card.innerHTML = `
    <div class="worst-empty loading dl-box dl-box--processing">
      <div class="loading-title">
        <span class="loading-spinner" aria-hidden="true"></span>
        <span class="dl-proc-title">Finalizando cálculo</span>
      </div>
      <p class="dl-subtitle dl-proc-subtitle"></p>
      <ul class="pr-list">${rows}</ul>
    </div>`;
}

function renderProcessing(d) {
  const card = document.getElementById("worst-card");
  const ul = card?.querySelector(".pr-list");
  const procTitle = card?.querySelector(".dl-proc-title");
  const procSub = card?.querySelector(".dl-proc-subtitle");
  if (procTitle) procTitle.textContent = dlProcessingTitle(d);
  if (procSub) procSub.textContent = dlProcessingSubtitle(d);
  if (!ul) return;
  const stages = Array.isArray(d.stages) ? d.stages : [];
  ul.querySelectorAll(".pr-card").forEach((row) => {
    const key = row.dataset.key;
    const stage = stages.find((s) => s.key === key);
    if (!stage) return;
    const st = stage.status;
    row.classList.remove("pr-done", "pr-active", "pr-pending");
    row.classList.add("pr-" + st);
    const ic = row.querySelector(".pr-ic");
    if (st === "done") {
      ic.textContent = "\u2713";
    } else if (st === "active") {
      ic.innerHTML = '<span class="loading-spinner pr-spin"></span>';
    } else {
      ic.textContent = "";
    }
  });
  if (d.phase === "done") {
    if (_dl.doneAt == null) _dl.doneAt = performance.now();
    if (!_dl.refreshed && performance.now() - _dl.doneAt > 600) {
      _dl.refreshed = true;
      refresh();
    }
  }
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
  const hazard = summary.max_rd_hazard;
  const { geo, hid } = snapshotPoints(snap);
  const pool = [...geo, ...hid];
  const worst = id
    ? pool.find((p) => p.id === id && (!hazard || p.hazard === hazard))
      || pool.find((p) => p.id === id)
    : null;

  if (!worst) {
    card.classList.add("empty");
    card.innerHTML = '<div class="worst-empty">Aguardando a primeira leitura de chuva…</div>';
    return;
  }

  card.classList.remove("empty", "worst-card--blink");
  card.style.borderLeftColor = NIVEL_COLOR[worst.rd];

  const levelTextColor = worst.rd === 1 ? "#0f172a" : "#ffffff";
  const levelBlink = shouldBlinkAlert(worst.rd) ? " worst-level--blink" : "";

  card.innerHTML = `
    <div class="worst-name">${escapeHtml(worst.nome)}</div>
    <div class="worst-rod">${escapeHtml(worst.rodovia)} · km ${worst.km} · ${escapeHtml(worst.region_name || "—")}</div>
    <span class="worst-level${levelBlink}" style="background:${NIVEL_COLOR[worst.rd]};color:${levelTextColor}">
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
      <div class="worst-stat" title="Quanto a chuva observada já se aproxima do limite desta região">
        <span>Proximidade do limite</span><b>${worst.cpc !== null ? worst.cpc : "—"}</b>
      </div>
    </div>
    ${renderWorstSparkline(worst.history || [])}
  `;
  if (shouldBlinkAlert(worst.rd)) {
    card.classList.add("worst-card--blink");
  }
}

// ============================================================================
// REGIÕES (sidebar e mapa)
// ============================================================================

function renderRegions(regions) {
  const list = document.getElementById("region-list");
  list.innerHTML = regions
    .map((r) => `
      <div class="region-row" title="Quanto menor o valor, menos chuva costuma bastar para subir o alerta">
        <div class="region-info">
          <b>${r.id}. ${escapeHtml(r.nome)}</b>
          <small>${escapeHtml(r.rodovia || "")}</small>
        </div>
        <div class="region-k">
          <span>Sensibilidade</span>
          <code>${r.k_geo}</code>
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
      `Região ${r.id}: ${r.nome} (${r.rodovia})<br><small>Sensibilidade: ${r.k_geo} (menor = reage mais cedo)</small>`,
      { sticky: true }
    );
    poly.addTo(state.layers.regions);
    state.regionPolys.push(poly);
  });
}

// ============================================================================
// PONTOS DE MONITORAMENTO
// ============================================================================

function renderPointsOnMap(snap) {
  const groups = state.layers.hazardZones || {};
  Object.values(groups).forEach((g) => g.clearLayers());
  state.pointMarkers.clear();
  state.pointData.clear();

  const { geo, hid } = snapshotPoints(snap || {});
  const layers = [
    ["encosta", geo],
    ["inundacao", hid],
  ];

  layers.forEach(([hazardKey, points]) => {
    const h = HAZARDS[hazardKey];
    const g = groups[hazardKey];
    if (!h?.available || !g) return;

    points.forEach((p) => {
      const markerKey = `${p.id}:${hazardKey}`;
      state.pointData.set(markerKey, p);
      if (!Array.isArray(p.geometry) || p.geometry.length < 2) return;

      const isNoData = p.source === "NO_DATA";
      const isPoly = p.geometry_type === "polygon" && p.geometry.length >= 3;
      const rd = isNoData ? null : h.rdFrom(p);
      const color = (rd == null) ? "#64748b" : (h.palette[rd] || "#64748b");
      const blinkCls = shouldBlinkAlert(rd) ? " ua-alert-blink" : "";
      const pathClass = (isPoly ? "ua-polygon" : "ua-polyline") + blinkCls;
      const style = {
        color, weight: isPoly ? 2 : 5, opacity: 0.9,
        fillColor: color, fillOpacity: isPoly ? 0.55 : 0,
        className: pathClass,
      };
      const layer = isPoly
        ? L.polygon(p.geometry, style).bindPopup(
          buildPopup(p, hazardKey),
          { className: "ua-popup-wrap", maxWidth: 360, minWidth: 280 }
        )
        : L.polyline(p.geometry, style).bindPopup(
          buildPopup(p, hazardKey),
          { className: "ua-popup-wrap", maxWidth: 360, minWidth: 280 }
        );
      layer.addTo(g);
      state.pointMarkers.set(markerKey, [layer]);
    });
  });
}

function fixText(str) {
  if (str == null || str === undefined) return "";
  const s = String(str);
  if (!/Ã|â€|\uFFFD/.test(s)) return s;
  try {
    return decodeURIComponent(escape(s));
  } catch {
    return s;
  }
}

/** Número com vírgula decimal (padrão BR) para popups e tooltips. */
function formatNum(value, decimals = 1) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  if (decimals == null) {
    return String(n).replace(".", ",");
  }
  return n.toFixed(decimals).replace(".", ",");
}

function formatKm(km) {
  return formatNum(km, 1);
}

function formatKmRange(kmIni, kmFim) {
  const a = kmIni != null && kmIni !== "" ? formatKm(kmIni) : "—";
  const b = kmFim != null && kmFim !== "" ? formatKm(kmFim) : "—";
  return `km ${a}–${b}`;
}

function raClassLabel(hazardKey, p) {
  const isGeo = hazardKey === "encosta" || p.hazard === "geo";
  const ra = isGeo ? (p.ra_geo ?? p.ra) : (p.ra_hid ?? p.ra);
  const kind = isGeo ? "geológico" : "hidrológico";
  if (ra === null || ra === undefined) {
    return `RA ${kind} = sem dado`;
  }
  return `RA ${kind} = ${ra}`;
}

function popupHeaderHtml(p, hazardKey) {
  const regionName = escapeHtml(fixText(p.region_name || "—"));
  const channelLabel = escapeHtml(
    fixText(HAZARDS[hazardKey]?.label || hazardKey || "")
  );
  const rod = fixText(p.rodovia || "");
  const trecho = rod && p.km != null && p.km !== ""
    ? `${escapeHtml(rod)} km ${formatKm(p.km)}`
    : (rod ? escapeHtml(rod) : "—");
  const raLine = escapeHtml(raClassLabel(hazardKey, p));
  return `
    <header class="ua-popup-header">
      <div class="ua-popup-region">Região: ${regionName}</div>
      <div class="ua-popup-risk">${channelLabel}</div>
      <div class="ua-popup-meta-row">
        <span class="ua-popup-trecho">${trecho}</span>
        <span class="ua-popup-ra">${raLine}</span>
      </div>
    </header>`;
}

function popupRainRows(p, hazardKey) {
  const isGeo = hazardKey === "encosta" || p.hazard === "geo";
  if (isGeo) {
    let rows = `<tr><th>Acum. 96h (geo)</th><td>${formatNum(p.ac96h_mm)} mm</td></tr>`;
    if (p.fonte_chuva === "WRF") {
      rows += `<tr><th>Composição</th><td>${formatNum(p.ac72h_obs_mm)} mm obs. + ${formatNum(p.prev24h_mm)} mm prev.</td></tr>`;
    }
    return rows;
  }
  let rows = `<tr><th>Janela 24h (hidro)</th><td>${formatNum(p.ac24h_mm)} mm</td></tr>`;
  if (p.fonte_chuva === "WRF") {
    rows += `<tr><th>Composição</th><td>${formatNum(p.ac18h_obs_mm)} mm obs. + ${formatNum(p.prev6h_mm)} mm prev.</td></tr>`;
  }
  return rows;
}

function formatUbaDisplay(p) {
  const code = fixText(p.uba_codigo || p.uba);
  const nome = fixText(p.uba_nome);
  if (code && nome && code !== nome) {
    return `${escapeHtml(code)} — ${escapeHtml(nome)}`;
  }
  return escapeHtml(code || nome || "—");
}

function popupDerSection(p) {
  const cgr = fixText(p.regional_cgr || p.regional);
  const rc = fixText(p.residencia_conserva || p.rc);
  const uba = formatUbaDisplay(p);
  const missing = !cgr && !rc && uba === "—";
  if (missing) {
    return `
      <p class="ua-popup-note">
        Unidades DER (CGR, UBA e Residência de Conserva) não identificadas
        automaticamente para o trecho desta UA.
      </p>`;
  }
  return `
    <table class="modal-table ua-popup-table">
      <tr>
        <th>CGR (Coord. Geral Regional)</th>
        <td><b>${escapeHtml(cgr || "—")}</b></td>
      </tr>
      <tr>
        <th>UBA (atendimento)</th>
        <td><b>${uba}</b></td>
      </tr>
      <tr>
        <th>Residência de Conserva</th>
        <td>${escapeHtml(rc || "—")}</td>
      </tr>
      ${p.municipio ? `<tr><th>Município</th><td>${escapeHtml(fixText(p.municipio))}</td></tr>` : ""}
    </table>`;
}

function buildPopup(p, hazardKey) {
  const isNoData = p.source === "NO_DATA";
  const header = popupHeaderHtml(p, hazardKey);

  if (isNoData) {
    return `
      <div class="ua-popup">
        ${header}
        <div class="ua-popup-body">
          <h3 class="ua-popup-section">Unidades DER do trecho</h3>
          ${popupDerSection(p)}
          <div class="ua-popup-level ua-popup-level--nd">Sem dado disponível</div>
          <p class="ua-popup-foot">Fonte MERGE/INPE indisponível neste ciclo.</p>
        </div>
      </div>`;
  }

  const levelTextColor = p.rd === 1 ? "#0f172a" : "#ffffff";
  const palette = HAZARDS[hazardKey]?.palette || NIVEL_COLOR;
  const isGeo = hazardKey === "encosta" || p.hazard === "geo";
  const iccRow = isGeo
    ? `<tr><th>ICC geológico</th><td>${formatNum(p.icc_geo, 0)}</td></tr>`
    : `<tr><th>ICC hidrológico</th><td>${formatNum(p.icc_hid, 0)}</td></tr>`;
  const warnWrf = p.fonte_chuva === "OBS_ONLY"
    ? `<p class="ua-popup-note">Previsão WRF indisponível — cálculo usa só chuva observada (pode subestimar).</p>`
    : "";

  return `
    <div class="ua-popup">
      ${header}
      <div class="ua-popup-body">
        <h3 class="ua-popup-section">Unidades DER do trecho</h3>
        ${popupDerSection(p)}
        <h3 class="ua-popup-section">Chuva e risco</h3>
        <table class="modal-table ua-popup-table">
          ${popupRainRows(p, hazardKey)}
          <tr><th>Intensidade (obs.)</th><td>${formatNum(p.intensity_mmh)} mm/h</td></tr>
          <tr><th>CPC</th><td>${p.cpc !== null ? formatNum(p.cpc) : "—"}</td></tr>
          ${iccRow}
        </table>
        ${warnWrf}
        <div class="ua-popup-level"
             style="background:${palette[p.rd]};color:${levelTextColor}">
          Nível ${p.rd} — ${NIVEL_LABEL[p.rd]}
        </div>
      </div>
    </div>`;
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

// Cor neutra para trechos fora da cobertura ou monitorados sem dado.
// Tom azul-acinzentado solido: aparece bem sobre o basemap claro mas nao
// compete visualmente com as paletas das camadas classificadas.
const ROAD_UNMONITORED_STYLE = { color: "#5b6b7d", weight: 1.8, opacity: 0.8 };
const ROAD_SUPPORT_STYLE = { color: "#94a3b8", weight: 2, opacity: 0.75 };

// Pesos por nivel — legenda das UAs (malha DER nao usa mais escala RD)
const ROAD_WEIGHTS = [4.0, 4.5, 5.0, 5.5, 6.0];

/**
 * Malha DER: referencia cartografica neutra. Alertas visuais ficam nas UAs.
 */
function styleForRoadFeature(props) {
  if (!props?.monitored) return ROAD_UNMONITORED_STYLE;
  return ROAD_SUPPORT_STYLE;
}

async function loadRoadNetwork() {
  const setSummary = (msg) => {
    const el = document.getElementById("road-stats-summary");
    if (el) el.textContent = msg;
  };

  try {
    const stats = normalizeRoadStats(
      await (await fetch(apiUrl("/api/road-stats"))).json()
    );
    populateFilterDropdowns(stats);

    setSummary("Carregando malha rodoviária...");
    const gj = await (await fetch(apiUrl("/api/road-network"))).json();
    state.roadGeoJSON = normalizeRoadGeoJSON(gj);
    renderRoadsOnMap();
  } catch (e) {
    console.error("Erro ao carregar malha:", e);
    setSummary("Erro ao carregar a malha");
  }
}

// ============================================================================
// LIMITES ADMINISTRATIVOS (municipios, RC, UBA, CGR)
// ============================================================================

const ADMIN_LAYERS = {
  municipios: {
    file: "/static/data/municipios.geojson",
    style: { color: "#475569", weight: 0.5, opacity: 0.45, fill: false, interactive: false },
  },
  rc: {
    file: "/static/data/rc_poligonos.geojson",
    style: { color: "#7c3aed", weight: 1.2, opacity: 0.7, fillColor: "#7c3aed", fillOpacity: 0.04, interactive: false },
  },
  uba: {
    file: "/static/data/uba_poligonos.geojson",
    style: { color: "#0d9488", weight: 1.4, opacity: 0.8, fill: false, interactive: false },
  },
  cgr: {
    file: "/static/data/cgr_poligonos.geojson",
    style: { color: "#b45309", weight: 1.8, opacity: 0.85, fill: false, interactive: false },
  },
};

const adminLoaded = new Set();

async function loadAdminLayer(key) {
  if (adminLoaded.has(key)) return;
  const cfg = ADMIN_LAYERS[key];
  if (!cfg) return;
  try {
    const gj = await (await fetch(apiUrl(cfg.file))).json();
    L.geoJSON(gj, { style: cfg.style }).addTo(state.layers[key]);
    adminLoaded.add(key);
  } catch (e) {
    console.warn(`falha ao carregar camada ${key}:`, e);
  }
}

function attachAdminLayerEvents() {
  Object.keys(ADMIN_LAYERS).forEach((key) => {
    const cb = document.getElementById(`layer-${key}`);
    if (!cb) return;
    cb.addEventListener("change", async (e) => {
      if (e.target.checked) {
        await loadAdminLayer(key);
        state.map.addLayer(state.layers[key]);
      } else {
        state.map.removeLayer(state.layers[key]);
      }
    });
  });
}

function normalizeRoadProperties(props) {
  if (!props) return {};
  return {
    ...props,
    rodovia: props.rodovia ?? props.Rodovia ?? "",
    tipo_pista: props.tipo_pista ?? props.TipoPista ?? "",
    regional: props.regional ?? props.CodRegiona ?? "",
    administra: props.administra ?? props.Administra ?? "",
    extensao: Number(props.extensao ?? props.Extensao ?? 0),
    km_ini: props.km_ini ?? props.KmInicial,
    km_fim: props.km_fim ?? props.KmFinal,
    municipio: props.municipio ?? props.Municipio ?? "",
    denominacao: props.denominacao ?? props.Denominaca ?? "",
    monitored: Boolean(props.monitored),
    region_id: props.region_id ?? null,
    region_name: props.region_name ?? null,
    hazards: props.hazards ?? [],
  };
}

function normalizeRoadGeoJSON(gj) {
  if (!gj?.features) return gj;
  return {
    ...gj,
    features: gj.features.map((f) => ({
      ...f,
      properties: normalizeRoadProperties(f.properties),
    })),
  };
}

function normalizeRoadStats(stats) {
  if (!stats || typeof stats !== "object") {
    return {
      total_trechos: 0,
      extensao_total_km: 0,
      rodovias_unicas: 0,
      tipos_pista: [],
      regionais: [],
      administra: [],
    };
  }
  const total = stats.total_trechos ?? stats.total_features ?? 0;
  const rodovias = stats.rodovias_unicas
    ?? (Array.isArray(stats.rodovias) ? stats.rodovias.length : 0);
  return {
    total_trechos: total,
    extensao_total_km: Number(stats.extensao_total_km ?? 0),
    rodovias_unicas: rodovias,
    tipos_pista: stats.tipos_pista ?? stats.tipo_pista ?? [],
    regionais: stats.regionais ?? stats.regional ?? [],
    administra: stats.administra ?? [],
  };
}

function populateFilterDropdowns(stats) {
  const s = normalizeRoadStats(stats);
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
  fillSelect("filter-tipo-pista", s.tipos_pista);
  fillSelect("filter-regional", s.regionais);
  fillSelect("filter-administra", s.administra);
}

function updateStatsSummary(stats) {
  const el = document.getElementById("road-stats-summary");
  if (!el) return;
  const s = normalizeRoadStats(stats);
  const fmt = (n) => Number(n || 0).toLocaleString("pt-BR");
  el.innerHTML =
    `<b>${fmt(s.total_trechos)}</b> trechos<br>` +
    `<b>${fmt(Math.round(s.extensao_total_km))}</b> km de extensão total<br>` +
    `<b>${fmt(s.rodovias_unicas)}</b> rodovias distintas`;
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
      if (f.administra && p.administra !== f.administra) return false;
      if (f.rodovia) {
        const q = f.rodovia.toLowerCase();
        if (!(p.rodovia || "").toLowerCase().includes(q)) return false;
      }
      return true;
    })
  };

  const gj = L.geoJSON(filtered, {
    style: (feat) => styleForRoadFeature(feat.properties || {}),
    onEachFeature: (feat, layer) => {
      const p = feat.properties || {};
      const baseStyle = styleForRoadFeature(p);
      const tipTitle = p.monitored
        ? `<b>${escapeHtml(fixText(p.rodovia || "?"))}</b> · ${escapeHtml(fixText(p.region_name || ""))}<br>` +
          `Malha de apoio · ${formatKmRange(p.km_ini, p.km_fim)}`
        : `<b>${escapeHtml(fixText(p.rodovia || "?"))}</b><br>` +
          `Fora da cobertura · ${formatKmRange(p.km_ini, p.km_fim)}`;
      layer.bindTooltip(tipTitle, { sticky: true, direction: "top" });
      layer.on("mouseover", () =>
        layer.setStyle({ ...baseStyle, weight: (baseStyle.weight || 2) + 2, opacity: 1 })
      );
      layer.on("mouseout", () => layer.setStyle(baseStyle));
    }
  });
  gj.addTo(state.layers.roads);

  // Atualiza contagem
  const el = document.getElementById("road-stats-summary");
  if (el && state.roadGeoJSON) {
    const total = state.roadGeoJSON.features.length;
    const shown = filtered.features.length;
    const km = filtered.features.reduce((s, ft) => s + (ft.properties?.extensao || 0), 0);
    const monitoredShown = filtered.features.filter((ft) => ft.properties?.monitored).length;
    if (shown === total) {
      el.innerHTML =
        `<b>${total.toLocaleString("pt-BR")}</b> trechos · <b>${Math.round(km).toLocaleString("pt-BR")}</b> km<br>` +
        `<b>${monitoredShown}</b> trechos com monitoramento ativo`;
    } else {
      el.innerHTML =
        `Filtro ativo: <b>${shown.toLocaleString("pt-BR")}</b> de ${total.toLocaleString("pt-BR")} trechos<br>` +
        `Extensão filtrada: <b>${Math.round(km).toLocaleString("pt-BR")}</b> km · ` +
        `<b>${monitoredShown}</b> cobertos`;
    }
  }
}

// ============================================================================
// PAINEL DE CAMADAS DE HAZARD + LEGENDA DINAMICA
// ============================================================================

/** Toggles das camadas de hazard, no mesmo estilo das outras camadas do mapa. */
function renderHazardPanel() {
  const root = document.getElementById("hazard-toggles");
  if (!root) return;
  const items = Object.entries(HAZARDS)
    .filter(([, h]) => h.available)
    .map(([key, h]) => {
      const checked = HAZARD_STATE[key] ? "checked" : "";
      return `
        <label class="ck">
          <input type="checkbox" id="hazard-${escapeHtml(key)}"
                 name="hazard-${escapeHtml(key)}"
                 data-hazard="${escapeHtml(key)}" ${checked}>
          ${escapeHtml(h.label)}
        </label>
      `;
    }).join("");
  // Sempre mostra a secao; sem camadas disponiveis, exibe uma linha vazia.
  root.innerHTML = items
    || '<div class="ck ck-empty">Nenhuma camada disponível</div>';

  root.querySelectorAll('input[type="checkbox"][data-hazard]').forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const k = e.target.getAttribute("data-hazard");
      HAZARD_STATE[k] = e.target.checked;
      saveHazardState();
      const g = state.layers.hazardZones?.[k];
      if (g) {
        if (e.target.checked) g.addTo(state.map);
        else state.map.removeLayer(g);
      }
      renderHazardLegend();
      updateTimelineChannelHint();
      if (state.timeline.active) {
        applyTimelineFrame(state.timeline.idx);
      }
      const snap = state.lastSnapshot;
      if (snap) {
        const by = activeByLevel(snap.summary || {});
        for (let i = 0; i <= 4; i++) {
          const el = document.getElementById("count-" + i);
          if (el) el.textContent = by[i] || 0;
        }
      }
    });
  });
}

/** Legenda dinamica no canto do mapa: so mostra paletas das camadas ativas. */
function renderHazardLegend() {
  const root = document.getElementById("hazard-legend");
  if (!root) return;

  const activeEntries = Object.entries(HAZARDS)
    .filter(([k, h]) => h.available && HAZARD_STATE[k]);

  if (activeEntries.length === 0) {
    root.innerHTML = "";
    return;
  }

  const blocks = activeEntries.map(([key, h]) => {
    const collapsed = !!LEGEND_COLLAPSED[key];
    const toggleChar = collapsed ? "\u25B8" : "\u25C2";
    return `
    <div class="legend-block${collapsed ? " collapsed" : ""}"
         data-legend-key="${key}">
      <div class="legend-head">
        <div class="legend-title">${h.legendTitle || escapeHtml(h.label)}</div>
        <button type="button" class="legend-toggle"
                aria-expanded="${collapsed ? "false" : "true"}"
                aria-label="${collapsed ? "Expandir legenda" : "Recolher legenda"}"
                title="${collapsed ? "Expandir" : "Recolher"}">${toggleChar}</button>
      </div>
      <div class="legend-body">
        <div class="legend-rows">
          ${h.palette.map((c, i) => `
            <div class="legend-item">
              <span class="line" style="border-top:${ROAD_WEIGHTS[i]}px solid ${c}"></span>
              ${i} — ${escapeHtml(NIVEL_LABEL[i])}
            </div>
          `).join("")}
          <div class="legend-item"><span class="line line-rd-nd"></span>Monitorado · sem dado</div>
          <div class="legend-item"><span class="line line-out"></span>Fora da área de monitoramento</div>
        </div>
      </div>
    </div>`;
  }).join("");

  root.innerHTML = blocks;
}

function initLegendToggles() {
  const root = document.getElementById("hazard-legend");
  if (!root || root.dataset.toggleBound) return;
  root.dataset.toggleBound = "1";
  root.addEventListener("click", (e) => {
    const btn = e.target.closest(".legend-toggle");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const block = btn.closest(".legend-block");
    if (!block) return;
    const key = block.dataset.legendKey;
    const collapsed = block.classList.toggle("collapsed");
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    btn.setAttribute(
      "aria-label",
      collapsed ? "Expandir legenda" : "Recolher legenda"
    );
    btn.title = collapsed ? "Expandir" : "Recolher";
    btn.textContent = collapsed ? "\u25B8" : "\u25C2";
    if (key) {
      LEGEND_COLLAPSED[key] = collapsed;
      saveLegendCollapsed();
    }
  });
}

function attachRoadFilterEvents() {
  const handler = () => {
    state.roadFilters = {
      tipo_pista: document.getElementById("filter-tipo-pista").value,
      regional: document.getElementById("filter-regional").value,
      administra: document.getElementById("filter-administra").value,
      rodovia: document.getElementById("filter-rodovia").value.trim()
    };
    renderRoadsOnMap();
  };
  ["filter-tipo-pista", "filter-regional", "filter-administra"].forEach((id) => {
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
    document.getElementById("filter-administra").value = "";
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

function formatHistoryBannerDate(d) {
  return d.toLocaleString("pt-BR", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function setMapHistoryBanner(text, loading) {
  const banner = document.getElementById("map-history-banner");
  const dateEl = document.getElementById("map-history-date");
  if (!banner || !dateEl) return;
  if (!text) {
    banner.hidden = true;
    banner.classList.remove("is-loading");
    dateEl.textContent = "—";
    return;
  }
  banner.hidden = false;
  banner.classList.toggle("is-loading", !!loading);
  dateEl.textContent = text;
}

function updateMapHistoryBanner(summary, snap) {
  if (!summary?.historical) {
    setMapHistoryBanner(null);
    return;
  }
  const raw = summary.consulted_at || snap?.timestamp_utc || state.historyAtIso;
  const d = raw ? new Date(raw) : null;
  setMapHistoryBanner(
    d ? formatHistoryBannerDate(d) : "Data não informada",
    false
  );
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}


function shouldBlinkAlert(rd) {
  return rd >= 3;
}

function applyMeterHighlight(summary, maxRd) {
  const by = activeByLevel(summary);
  document.querySelectorAll(".meter-cell").forEach((c) => {
    c.classList.remove("active", "meter-cell--blink");
    const rd = Number(c.dataset.rd);
    if (rd === maxRd) c.classList.add("active");
    if (shouldBlinkAlert(rd) && (by[rd] || 0) > 0) {
      c.classList.add("meter-cell--blink");
    }
  });
}

function actionsPageUrl() {
  if (state.historyMode && state.historyAtIso) {
    return apiUrl(
      "/acoes?at=" + encodeURIComponent(state.historyAtIso)
    );
  }
  return apiUrl("/acoes");
}

function actionsApiUrl() {
  if (state.historyMode && state.historyAtIso) {
    return apiUrl(
      "/api/actions?at=" + encodeURIComponent(state.historyAtIso)
    );
  }
  return apiUrl("/api/actions");
}

// ============================================================================
// ACOES OPERACIONAIS (PPDC)
// ============================================================================
async function loadActions() {
  try {
    const res = await fetch(actionsApiUrl());
    if (!res.ok) return;
    const data = await res.json();
    renderActions(data);
  } catch (e) {
    console.error("Erro ao carregar acoes:", e);
  }
}

function renderActionsWaiting() {
  const c = document.getElementById("actions-content");
  if (c) {
    c.innerHTML = '<div class="actions-empty waiting">'
      + 'Aguardando a primeira leitura de chuva para orientar ações\u2026</div>';
  }
}

function renderActionsNoData() {
  const c = document.getElementById("actions-content");
  if (c) {
    c.innerHTML = '<div class="actions-empty">'
      + 'Sem dados de chuva neste momento — ações indisponíveis.</div>';
  }
}

function renderActions(data) {
  const container = document.getElementById("actions-content");
  if (!container) return;

  const nivel = data.max_nivel || "Monitoramento";
  const cor = data.max_cor || "#22c55e";
  const rd = data.max_rd ?? 0;
  const url = actionsPageUrl();
  const blinkClass = shouldBlinkAlert(rd) ? " blink" : "";

  if (data.acoes_necessarias) {
    // Alertas demandam acao: botao piscante quando nivel >= 3.
    const partes = [];
    if (data.total_critico) {
      partes.push(`${data.total_critico} em Alerta`);
    }
    if (data.total_atencao) {
      partes.push(`${data.total_atencao} em Atenção`);
    }
    const sub = partes.length
      ? partes.join(" · ")
      : "Situação exige atenção preventiva";
    container.innerHTML = `
      <a class="acoes-btn${blinkClass}" href="${url}" target="_blank"
         rel="noopener" style="--acao-cor:${cor};">
        <span class="acoes-btn-dot"></span>
        <span class="acoes-btn-main">
          <b>Ações necessárias</b>
          <small>Nível ${rd} — ${nivel}</small>
        </span>
      </a>
      <div class="acoes-sub">${sub}. Abra o plano detalhado da Defesa Civil.</div>`;
  } else {
    // Operacao normal: estado calmo, sem piscar, com link de referencia.
    container.innerHTML = `
      <div class="acoes-calm">
        <span class="acoes-calm-dot"></span>
        <div>
          <b>Operação normal</b>
          <small>Chuva dentro da rotina — nenhuma ação
            extraordinária por enquanto.</small>
        </div>
      </div>
      <a class="acoes-btn-secondary" href="${url}" target="_blank"
         rel="noopener">Ver plano de contingência (PPDC)</a>`;
  }
}

// ============================================================================
// PREVISAO 24H
// ============================================================================
async function loadForecast() {
  try {
    const res = await fetch(apiUrl("/api/forecast"));
    if (!res.ok) return;
    const data = await res.json();
    renderForecast(data);
  } catch (e) {
    console.error("Erro ao carregar previsao:", e);
  }
}

function renderRdBasisNote(summary, dataStatus) {
  const el = document.getElementById("rd-basis-note");
  if (!el) return;
  if (dataStatus === "loading" || dataStatus === "no_data") {
    el.hidden = true;
    return;
  }
  const basis = summary.rd_basis;
  const forecastOk = summary.forecast_ok;
  if (!basis && forecastOk === undefined) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.className = forecastOk === false
    ? "rd-basis-note rd-basis-warn"
    : "rd-basis-note rd-basis-ok";
  let html = `<strong>Base do alerta:</strong> ${escapeHtml(basis || "—")}`;
  if (forecastOk === false) {
    html += (
      "<br><small>Previsão indisponível — cálculo usa só a chuva já medida "
      + "(pode demorar a refletir piora do tempo).</small>"
    );
  } else if (summary.forecast_count != null) {
    html += (
      `<br><small>Previsão aplicada em ${summary.forecast_count} `
      + `trecho(s) neste ciclo.</small>`
    );
  }
  el.innerHTML = html;
}

function renderForecastWaiting() {
  const c = document.getElementById("forecast-content");
  if (c) {
    c.innerHTML = '<div class="forecast-empty waiting">'
      + 'Aguardando a leitura de chuva concluir\u2026</div>';
  }
}

function renderForecastNoData() {
  const c = document.getElementById("forecast-content");
  if (c) {
    c.innerHTML = '<div class="forecast-empty">'
      + 'Sem dados de chuva — previsão indisponível.</div>';
  }
}

function renderForecast(data) {
  const container = document.getElementById("forecast-content");
  if (!container) return;

  const forecast = data.forecast || [];
  const comDados = forecast.filter((f) => f.ac24h_forecast_mm !== undefined);
  if (comDados.length === 0) {
    container.innerHTML = `<div class="forecast-empty">Previsão indisponível neste ciclo</div>`;
    return;
  }

  const maxGeo = Math.max(...comDados.map((f) => f.ac24h_forecast_mm));
  const maxPonto = comDados.find((f) => f.ac24h_forecast_mm === maxGeo);
  const maxHidro = Math.max(
    ...comDados.map((f) => f.ac6h_forecast_mm ?? 0)
  );

  let html = `<div class="forecast-panel">`;
  html += (
    `<div class="forecast-source">`
    + `${escapeHtml(data.source || "Previsão horária CPTEC/INPE")}</div>`
  );
  html += (
    `<div style="margin-bottom: 4px;">`
    + `<strong>Máxima em 24 h (deslizamentos):</strong> ${maxGeo.toFixed(1)} mm</div>`
  );
  html += (
    `<div style="margin-bottom: 4px;">`
    + `<strong>Máxima em 6 h (alagamentos):</strong> ${maxHidro.toFixed(1)} mm</div>`
  );
  html += (
    `<div class="forecast-meta">${escapeHtml(maxPonto?.nome || "")}</div>`
  );

  html += `<div class="forecast-list">`;
  for (const f of comDados.slice(0, 5)) {
    const vals = `${f.ac24h_forecast_mm.toFixed(1)} (+24h)`;
    const hidro = f.ac6h_forecast_mm != null
      ? ` · ${f.ac6h_forecast_mm.toFixed(1)} (+6h)`
      : "";
    html += (
      `<div class="forecast-row">`
      + `<span>${escapeHtml(f.nome)}</span>`
      + `<span><b>${vals}${hidro} mm</b></span>`
      + `</div>`
    );
  }
  if (comDados.length > 5) {
    html += (
      `<div class="forecast-more">`
      + `+${comDados.length - 5} trechos</div>`
    );
  }
  html += `</div></div>`;

  container.innerHTML = html;
}

function renderWorstSparkline(history) {
  if (!history || history.length < 2) return "";
  const vals = history.map(h => h.rd);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const w = 200;
  const h = 40;
  const step = w / (vals.length - 1);
  let path = "";
  vals.forEach((v, i) => {
    const x = i * step;
    const y = h - ((v - min) / range) * h;
    path += (i === 0 ? "M" : "L") + `${x},${y}`;
  });
  const color = NIVEL_COLOR[max] || "#999";
  return `
    <div class="worst-spark">
      <div class="worst-spark-label">Evolução do Risco (últimos ${vals.length} ciclos)</div>
      <svg width="${w}" height="${h}" style="overflow:visible">
        <path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        ${vals.map((v, i) => {
          const x = i * step;
          const y = h - ((v - min) / range) * h;
          return `<circle cx="${x}" cy="${y}" r="3" fill="${NIVEL_COLOR[v]}"/>`;
        }).join("")}
      </svg>
    </div>
  `;
}
