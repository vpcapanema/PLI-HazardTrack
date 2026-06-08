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
    rdFrom: (point) => Number.isInteger(point?.rd_geo) ? point.rd_geo : null,
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
    rdFrom: (point) => Number.isInteger(point?.rd_hid) ? point.rd_hid : null,
  },
};

// Estado das camadas, persistido em localStorage (controle do usuario).
// Default: todas as disponiveis ligadas; o que o usuario alterar fica salvo.
const HAZARD_STORAGE_KEY = "pli_hazardtrack.hazard_layers.v1";

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
  }
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  initMap();
  attachEvents();
  renderHazardPanel();
  renderHazardLegend();
  loadRoadNetwork();
  refresh();
  setInterval(refresh, REFRESH_MS);
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
  // Durante a animacao temporal, o snapshot ao vivo nao recolore o mapa
  // (a Linha do Tempo controla as cores dos trechos).
  if (state.timeline.active) return;
  try {
    const res = await fetch(apiUrl("/api/snapshot"));
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
  tlEl("tl-status").textContent = "Baixando 96 h do MERGE/INPE...";
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
  const rd = frame.rd || {};
  for (const [id, markers] of state.pointMarkers) {
    const v = rd[id];
    const color = Number.isInteger(v)
      ? (NIVEL_COLOR[v] || "#64748b")
      : "#64748b";
    const arr = Array.isArray(markers) ? markers : [markers];
    arr.forEach((m) => m.setStyle({ color }));
  }
  const range = tlEl("tl-range");
  if (range) range.value = idx;
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
  const ts = snap.timestamp_utc ? new Date(snap.timestamp_utc) : null;
  const summary = snap.summary || {};
  const maxRd = summary.max_rd ?? 0;
  const status = summary.data_status || "ok";   // ok | degraded | no_data | mock | loading

  // ---- Primeiro ciclo ainda em andamento (servidor recem-bootado) ----
  if (status === "loading") {
    setStatus("Carregando primeira leitura do MERGE/INPE...", "warn");
    document.getElementById("status-time").textContent =
      "Pode levar até ~60 s no primeiro ciclo (Render free)";
    setBadge("badge-source", "MERGE / INPE", "loading");
    setBadge("badge-update", "carregando", "loading");
    // Mostra a malha em estilo "sem dado" para a interface nao ficar vazia
    // enquanto o primeiro update do MERGE termina.
    renderPointsOnMap(snap.points || []);
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
    setStatus("Sem dado real do MERGE/INPE neste ciclo", "alert");
    document.getElementById("status-time").textContent =
      ts ? "Última tentativa às " + formatTime(ts) : "—";
    setBadge("badge-source", "Sem dado", "no-data");
    setBadge("badge-update", ts ? formatTime(ts) : "—", "no-data");
    // Mostra os pontos da malha monitorada (estilo "sem dado") para deixar
    // claro que o monitoramento existe; chuva e RD vao zerados.
    renderPointsOnMap(snap.points || []);
    renderRegionsOnMap(snap.regions || []);
    renderRegions(snap.regions || []);
    if (state.roadGeoJSON) renderRoadsOnMap();
    stopDownloadPoll();
    renderWorstNoData(summary.message);
    renderRdBasisNote(summary, status);
    document.querySelectorAll(".meter-cell").forEach((c) => c.classList.remove("active"));
    for (let i = 0; i <= 4; i++) {
      const el = document.getElementById("count-" + i);
      if (el) el.textContent = "\u2014";
    }
    return;
  }

  // ---- Estado operacional normal ----
  stopDownloadPoll();
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

  // Atualiza coloracao da malha conforme o snapshot
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
    "badge-ok", "badge-degraded", "badge-no-data", "badge-mock", "badge-loading"
  );
  if (kind === "ok") el.classList.add("badge-ok");
  else if (kind === "degraded") el.classList.add("badge-degraded");
  else if (kind === "no-data" || kind === "no_data") el.classList.add("badge-no-data");
  else if (kind === "mock") el.classList.add("badge-mock");
  else if (kind === "loading") el.classList.add("badge-loading");
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

// Progresso do primeiro ciclo. Fase "download": janela rotativa de 5 GRIBs,
// cada um com barra propria (passo de 1%) e contagem geral X/Y. Fase
// "processing": lista de etapas com mensagens amistosas ate o snapshot ser
// publicado e renderizado.
const VISIBLE_DL = 5;
const _dl = {
  poll: null, anim: null, data: null, pct: {},
  mode: null, procStart: null, doneAt: null, refreshed: false,
};

function stopDownloadPoll() {
  if (_dl.poll) { clearInterval(_dl.poll); _dl.poll = null; }
  if (_dl.anim) { clearInterval(_dl.anim); _dl.anim = null; }
  _dl.data = null;
  _dl.pct = {};
  _dl.mode = null;
  _dl.procStart = null;
  _dl.doneAt = null;
  _dl.refreshed = false;
}

function startDownloadPoll() {
  if (_dl.poll) return;
  _dl.mode = "download";
  buildDownloadCard();
  const poll = async () => {
    try {
      const r = await fetch(apiUrl("/api/progress"));
      _dl.data = await r.json();
    } catch { /* ignora erro de rede transitorio */ }
  };
  poll();
  _dl.poll = setInterval(poll, 800);
  _dl.anim = setInterval(renderDownloadFrame, 40);
}

function buildDownloadCard() {
  const card = document.getElementById("worst-card");
  if (!card) return;
  card.classList.add("empty");
  let rows = "";
  for (let s = 0; s < VISIBLE_DL; s++) {
    rows += `
      <li class="dl-row" data-slot="${s}">
        <div class="dl-name">&nbsp;</div>
        <div class="dl-line">
          <div class="dl-bar"><div class="dl-bar-fill"></div></div>
          <span class="dl-pct">0%</span>
        </div>
      </li>`;
  }
  card.innerHTML = `
    <div class="worst-empty loading dl-box">
      <div class="loading-title">
        <span class="loading-spinner" aria-hidden="true"></span>
        Buscando dados do MERGE/INPE
      </div>
      <ul class="dl-list">${rows}</ul>
      <div class="dl-overall">
        <div class="dl-overall-top">
          <span>Baixados</span>
          <span class="dl-overall-pct">0 / 0</span>
        </div>
        <div class="dl-bar dl-bar-lg">
          <div class="dl-bar-fill dl-overall-fill"></div>
        </div>
      </div>
    </div>`;
}

function renderDownloadFrame() {
  const card = document.getElementById("worst-card");
  const d = _dl.data;
  if (!card || !d) return;
  const mode = d.active
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
  const list = card.querySelector(".dl-list");
  if (!list) return;  // card foi substituido por outro estado
  const files = Array.isArray(d.files) ? d.files : [];
  const total = d.total || files.length || 96;
  const done = d.done || 0;
  // Mostra apenas os arquivos que ainda estao baixando: ao concluir, o
  // arquivo sai da lista e o proximo entra no lugar.
  const visible = files
    .filter((f) => f.status === "pending")
    .slice(0, VISIBLE_DL);
  list.querySelectorAll(".dl-row").forEach((row, s) => {
    const f = visible[s];
    const nameEl = row.querySelector(".dl-name");
    const fill = row.querySelector(".dl-bar-fill");
    const pctEl = row.querySelector(".dl-pct");
    if (!f) {
      row.classList.add("dl-hide");
      nameEl.textContent = "";
      fill.style.width = "0";
      pctEl.textContent = "";
      return;
    }
    row.classList.remove("dl-hide");
    nameEl.textContent = f.name;
    // Anima a barra do arquivo em passos de 1% (ate ~95%); ao concluir, o
    // arquivo deixa a lista. _dl.pct e indexado por f.h (estavel).
    let cur = _dl.pct[f.h] || 0;
    if (cur < 95) cur = Math.min(95, cur + 1);
    _dl.pct[f.h] = cur;
    fill.style.width = cur + "%";
    pctEl.textContent = Math.round(cur) + "%";
  });
  // Progresso geral: numero de baixados / total (sem porcentagem).
  const ofill = card.querySelector(".dl-overall-fill");
  const ocount = card.querySelector(".dl-overall-pct");
  if (ofill) ofill.style.width = (total ? (done / total) * 100 : 0) + "%";
  if (ocount) ocount.textContent = `${done} / ${total}`;
}

function buildProcessingCard(d) {
  const card = document.getElementById("worst-card");
  if (!card) return;
  card.classList.add("empty");
  const stages = Array.isArray(d.stages) ? d.stages : [];
  const rows = stages.map((st) => `
      <li class="pr-row" data-key="${st.key}">
        <span class="pr-ic"></span>
        <span class="pr-label">${escapeHtml(st.label)}</span>
      </li>`).join("");
  card.innerHTML = `
    <div class="worst-empty loading dl-box">
      <div class="loading-title">
        <span class="loading-spinner" aria-hidden="true"></span>
        Processando os dados
      </div>
      <ul class="pr-list">${rows}</ul>
    </div>`;
}

function renderProcessing(d) {
  const card = document.getElementById("worst-card");
  const ul = card.querySelector(".pr-list");
  if (!ul) return;
  const rows = ul.querySelectorAll(".pr-row");
  const n = rows.length;
  if (!n) return;
  if (_dl.procStart == null) _dl.procStart = performance.now();
  const dwell = 650;  // ms minimos por etapa, leitura confortavel
  const elapsed = performance.now() - _dl.procStart;
  // O download ja terminou (indice 0); revelamos as etapas seguintes no tempo.
  let active = 1 + Math.floor(elapsed / dwell);
  const reachedEnd = active >= n - 1;
  if (active > n - 1) active = n - 1;
  const finished = d.phase === "done";
  rows.forEach((row, i) => {
    let st;
    if (i < active) st = "done";
    else if (i === active) st = (reachedEnd && finished) ? "done" : "active";
    else st = "pending";
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
  // Conclui: backend publicou (done) e ja revelamos todas as etapas.
  if (reachedEnd && finished) {
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
    ${renderWorstSparkline(worst.history || [])}
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
  const groups = state.layers.hazardZones || {};
  Object.values(groups).forEach((g) => g.clearLayers());
  state.pointMarkers.clear();
  state.pointData.clear();

  points.forEach((p) => {
    state.pointData.set(p.id, p);
    if (!Array.isArray(p.geometry) || p.geometry.length < 2) return;

    const isNoData = p.source === "NO_DATA";
    // A zona aparece nas camadas de Riscos Monitorados (encosta/inundacao),
    // colorida pelo RD daquele hazard em tempo real. O popup e o mesmo.
    const lines = [];
    Object.entries(HAZARDS).forEach(([key, h]) => {
      if (!h.available) return;
      const g = groups[key];
      if (!g) return;
      const rd = isNoData ? null : h.rdFrom(p);
      const color = (rd == null) ? "#64748b" : (h.palette[rd] || "#64748b");
      const pl = L.polyline(p.geometry, {
        color,
        weight: 5,
        opacity: 0.9,
      }).bindPopup(buildPopup(p));
      pl.addTo(g);
      lines.push(pl);
    });
    state.pointMarkers.set(p.id, lines);
  });
}

function raSourceLabel(src) {
  if (!src) return "";
  if (src.indexOf("tabela") >= 0) return "tabela oficial (Tab. 3.3.3.1-3/-4)";
  if (src.indexOf("figura") >= 0) return "digitalizado da Fig. 3.3.3";
  return src;
}

function buildPopup(p) {
  const isNoData = p.source === "NO_DATA";
  if (isNoData) {
    return `
      <div class="popup-content">
        <h4>${escapeHtml(p.nome)}</h4>
        <div class="popup-rod">${escapeHtml(p.rodovia)}${p.km != null ? " · km " + p.km : ""}</div>
        <div class="popup-rod">Região: ${escapeHtml(p.region_name || "—")}</div>
        <div class="popup-level" style="background:#64748b;color:#fff">
          Sem dado disponível
        </div>
        <div class="popup-source">Fonte MERGE/INPE indisponível neste ciclo.</div>
      </div>
    `;
  }
  const levelTextColor = p.rd === 1 ? "#0f172a" : "#ffffff";
  return `
    <div class="popup-content">
      <h4>${escapeHtml(p.nome)}</h4>
      <div class="popup-rod">${escapeHtml(p.rodovia)}${p.km != null ? " · km " + p.km : ""}</div>
      <div class="popup-rod">Região: ${escapeHtml(p.region_name || "—")}</div>
      <table>
        <tr><td>Janela 24h (hidro)</td><td>${p.ac24h_mm} mm</td></tr>
        ${p.fonte_chuva === "WRF" ? `<tr><td style="padding-left:10px;color:#555">= 18h obs + 6h prev</td><td style="color:#555">${p.ac18h_obs_mm} + ${p.prev6h_mm}</td></tr>` : ""}
        <tr><td>Acum. 96h (geo)</td><td>${p.ac96h_mm} mm</td></tr>
        ${p.fonte_chuva === "WRF" ? `<tr><td style="padding-left:10px;color:#555">= 72h obs + 24h prev</td><td style="color:#555">${p.ac72h_obs_mm} + ${p.prev24h_mm}</td></tr>` : ""}
        <tr><td>Intensidade (obs)</td><td>${p.intensity_mmh} mm/h</td></tr>
        <tr><td>CPC</td><td>${p.cpc !== null ? p.cpc : "—"}</td></tr>
        <tr><td>Risco analisado</td><td>${p.ra !== null && p.ra !== undefined ? 'RA' + p.ra : 'SEM DADO'}</td></tr>
        <tr><td>RA geológico</td><td>${p.ra_geo != null ? 'RA' + p.ra_geo : '—'}</td></tr>
        <tr><td>RA hidrológico</td><td>${p.ra_hid != null ? 'RA' + p.ra_hid : '—'}</td></tr>
        <tr><td>ICC geológico</td><td>${p.icc_geo}</td></tr>
        <tr><td>ICC hidrológico</td><td>${p.icc_hid}</td></tr>
      </table>
      ${p.ra_source ? `<div class="popup-source">RA: ${escapeHtml(raSourceLabel(p.ra_source))}</div>` : ""}
      ${p.fonte_chuva === "OBS_ONLY" ? `<div class="popup-source" style="color:#b45309">⚠ Previsão WRF indisponível — RD com chuva observada apenas (pode subestimar).</div>` : ""}
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

// Cor neutra para trechos fora da cobertura ou monitorados sem dado.
// Tom azul-acinzentado solido: aparece bem sobre o basemap claro mas nao
// compete visualmente com as paletas das camadas classificadas.
const ROAD_UNMONITORED_STYLE = { color: "#5b6b7d", weight: 1.8, opacity: 0.8 };
const ROAD_NO_DATA_STYLE     = { color: "#5b6b7d", weight: 2.2, opacity: 0.9, dashArray: "5,4" };

// Pesos por nivel - quanto mais grave, mais grossa a linha (escala aumentada)
const ROAD_WEIGHTS = [4.0, 4.5, 5.0, 5.5, 6.0];

// Para cada region_id, qual o RD maximo de cada hazard ativo no ciclo atual
// roadRegionMaxRd: Map<region_id, { encosta: rd|null, inundacao: rd|null }>
let roadRegionMaxRd = new Map();

function recomputeRoadRegionRd() {
  roadRegionMaxRd = new Map();
  const activeKeys = Object.entries(HAZARD_STATE)
    .filter(([k, on]) => on && HAZARDS[k]?.available)
    .map(([k]) => k);
  if (activeKeys.length === 0) return;

  for (const p of state.pointData.values()) {
    if (p.region_id == null) continue;
    if (p.source === "NO_DATA") continue;
    const key = Number(p.region_id);
    let bucket = roadRegionMaxRd.get(key);
    if (!bucket) {
      bucket = {};
      for (const k of activeKeys) bucket[k] = null;
      roadRegionMaxRd.set(key, bucket);
    }
    for (const k of activeKeys) {
      const rd = HAZARDS[k].rdFrom(p);
      if (rd == null) continue;
      if (bucket[k] == null || rd > bucket[k]) bucket[k] = rd;
    }
  }
}

/**
 * Para um trecho da malha, decide cor/estilo:
 *  - fora da cobertura  -> cinza
 *  - sem hazard ativo   -> cinza (mostra que existe vigilancia mas nada selecionado)
 *  - sem dado calculado -> cinza tracejado
 *  - tem dado           -> paleta da camada com maior RD (alerta mais grave)
 */
function styleForRoadFeature(props) {
  if (!props?.monitored || props.region_id == null) return ROAD_UNMONITORED_STYLE;
  const bucket = roadRegionMaxRd.get(Number(props.region_id));
  if (!bucket) return ROAD_NO_DATA_STYLE;

  // camada vencedora = maior RD entre as ativas
  let bestKey = null;
  let bestRd = -1;
  for (const [k, rd] of Object.entries(bucket)) {
    if (rd == null) continue;
    if (rd > bestRd) { bestRd = rd; bestKey = k; }
  }
  if (bestKey == null) return ROAD_NO_DATA_STYLE;

  const palette = HAZARDS[bestKey].palette;
  return {
    color: palette[bestRd] || palette[0],
    weight: ROAD_WEIGHTS[bestRd] || 3,
    opacity: 0.95,
    _hazard: bestKey,   // metadata interna, ignorada pelo Leaflet
    _rd: bestRd,
  };
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
  recomputeRoadRegionRd();

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
      const winnerKey = baseStyle._hazard || null;
      const winnerRd  = baseStyle._rd ?? null;
      const tipTitle = p.monitored
        ? `<b>${escapeHtml(p.rodovia || "?")}</b> · ${escapeHtml(p.region_name || "")}<br>` +
          (winnerKey != null
            ? `${escapeHtml(HAZARDS[winnerKey].label)}: <b>${escapeHtml(NIVEL_LABEL[winnerRd])}</b>`
            : "Sem dado") +
          ` · km ${p.km_ini}–${p.km_fim}`
        : `<b>${escapeHtml(p.rodovia || "?")}</b><br>` +
          `Fora da cobertura · km ${p.km_ini}–${p.km_fim}`;
      layer.bindTooltip(tipTitle, { sticky: true, direction: "top" });
      layer.bindPopup(buildRoadPopup(p));
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
        `<b>${monitoredShown}</b> trechos cobertos pelo sistema`;
    } else {
      el.innerHTML =
        `Filtro ativo: <b>${shown.toLocaleString("pt-BR")}</b> de ${total.toLocaleString("pt-BR")} trechos<br>` +
        `Extensão filtrada: <b>${Math.round(km).toLocaleString("pt-BR")}</b> km · ` +
        `<b>${monitoredShown}</b> cobertos`;
    }
  }
}

function buildRoadPopup(p) {
  const denom = p.denominacao ? `<small>${escapeHtml(p.denominacao)}</small>` : "";
  let monitoringBlock;
  if (p.monitored) {
    const bucket = roadRegionMaxRd.get(Number(p.region_id));
    const rows = Object.entries(HAZARDS)
      .filter(([k, h]) => h.available && HAZARD_STATE[k])
      .map(([k, h]) => {
        const rd = bucket?.[k];
        const palette = h.palette;
        const swatch = rd != null ? palette[rd] : "#94a3b8";
        const txt = rd != null ? `${rd} · ${escapeHtml(NIVEL_LABEL[rd])}` : "sem dado";
        return `
          <div class="popup-monitor-row">
            <span class="popup-monitor-label">${escapeHtml(h.label)}</span>
            <span class="rd-pill" style="background:${swatch};color:${rd >= 2 ? "#fff" : "#1f2937"}">${txt}</span>
          </div>`;
      }).join("");

    const activeNote = rows.length === 0
      ? `<div class="popup-monitor-off">Nenhuma camada ativa no painel.</div>`
      : "";

    monitoringBlock = `
      <div class="popup-monitor">
        <div class="popup-monitor-row">
          <span class="popup-monitor-label">Região</span>
          <b>${escapeHtml(p.region_name || "—")}</b>
        </div>
        ${rows}
        ${activeNote}
      </div>
    `;
  } else {
    monitoringBlock = `
      <div class="popup-monitor popup-monitor-off">
        <b>Trecho fora da cobertura atual.</b><br>
        O método em uso (REGEA-NIPPON 2021) só calibra envoltórias críticas
        para 4 regiões do litoral. Sem alertas calculados aqui.
      </div>
    `;
  }
  return `
    <div class="popup-content">
      <h4>${escapeHtml(p.rodovia || "?")} ${denom}</h4>
      <div class="popup-rod">${escapeHtml(p.municipio || "")} · ${escapeHtml(p.regional || "")}</div>
      ${monitoringBlock}
      <table>
        <tr><td>Quilômetro inicial</td><td>${p.km_ini ?? "—"}</td></tr>
        <tr><td>Quilômetro final</td><td>${p.km_fim ?? "—"}</td></tr>
        <tr><td>Extensão</td><td>${p.extensao ? p.extensao.toFixed(2) + " km" : "—"}</td></tr>
        <tr><td>Tipo de via</td><td>${escapeHtml(p.tipo || "—")}</td></tr>
        <tr><td>Tipo de pista</td><td>${escapeHtml(p.tipo_pista || "—")}</td></tr>
        <tr><td>Administração</td><td>${escapeHtml(p.administra || "—")}</td></tr>
        <tr><td>Residência DER</td><td>${escapeHtml(p.residencia || "—")}</td></tr>
      </table>
    </div>
  `;
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
      renderRoadsOnMap();
      renderHazardLegend();
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

  const blocks = activeEntries.map(([, h]) => `
    <div class="legend-block">
      <div class="legend-title">${h.legendTitle || escapeHtml(h.label)}</div>
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
  `).join("");

  root.innerHTML = blocks;
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

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}


// ============================================================================
// ACOES OPERACIONAIS (PPDC)
// ============================================================================
async function loadActions() {
  try {
    const res = await fetch(apiUrl("/api/actions"));
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
      + 'Aguardando o Monitoramento processar os dados da malha\u2026</div>';
  }
}

function renderActionsNoData() {
  const c = document.getElementById("actions-content");
  if (c) {
    c.innerHTML = '<div class="actions-empty">'
      + 'Sem dado neste ciclo \u2014 ações indisponíveis.</div>';
  }
}

function renderActions(data) {
  const container = document.getElementById("actions-content");
  if (!container) return;

  const nivel = data.max_nivel || "Monitoramento";
  const cor = data.max_cor || "#22c55e";
  const rd = data.max_rd ?? 0;
  const url = apiUrl("/acoes");

  if (data.acoes_necessarias) {
    // Alertas demandam acao: botao piscante que abre a pagina detalhada.
    const partes = [];
    if (data.total_critico) {
      partes.push(`${data.total_critico} em Alerta`);
    }
    if (data.total_atencao) {
      partes.push(`${data.total_atencao} em Atenção`);
    }
    const sub = partes.length
      ? partes.join(" · ")
      : "Ação preventiva requerida";
    container.innerHTML = `
      <a class="acoes-btn blink" href="${url}" target="_blank"
         rel="noopener" style="--acao-cor:${cor};">
        <span class="acoes-btn-dot"></span>
        <span class="acoes-btn-main">
          <b>Ações necessárias</b>
          <small>Nível ${rd} — ${nivel}</small>
        </span>
      </a>
      <div class="acoes-sub">${sub}. Toque para abrir o plano de
        contingência detalhado.</div>`;
  } else {
    // Operacao normal: estado calmo, sem piscar, com link de referencia.
    container.innerHTML = `
      <div class="acoes-calm">
        <span class="acoes-calm-dot"></span>
        <div>
          <b>Operação normal</b>
          <small>Monitoramento de rotina — nenhuma ação
            extraordinária.</small>
        </div>
      </div>
      <a class="acoes-btn-secondary" href="${url}" target="_blank"
         rel="noopener">Ver protocolo de contingência</a>`;
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
  let html = `<strong>Base do RD:</strong> ${escapeHtml(basis || "—")}`;
  if (forecastOk === false) {
    html += (
      "<br><small>Previsão WRF indisponível — RD calculado apenas com "
      + "chuva observada (pode subestimar).</small>"
    );
  } else if (summary.forecast_count != null) {
    html += (
      `<br><small>WRF aplicado em ${summary.forecast_count} `
      + `zona(s) neste ciclo.</small>`
    );
  }
  el.innerHTML = html;
}

function renderForecastWaiting() {
  const c = document.getElementById("forecast-content");
  if (c) {
    c.innerHTML = '<div class="forecast-empty waiting">'
      + 'Aguardando a leitura do MERGE/INPE concluir\u2026</div>';
  }
}

function renderForecastNoData() {
  const c = document.getElementById("forecast-content");
  if (c) {
    c.innerHTML = '<div class="forecast-empty">'
      + 'Sem dado neste ciclo \u2014 previsão indisponível.</div>';
  }
}

function renderForecast(data) {
  const container = document.getElementById("forecast-content");
  if (!container) return;

  const forecast = data.forecast || [];
  const comDados = forecast.filter((f) => f.ac24h_forecast_mm !== undefined);
  if (comDados.length === 0) {
    container.innerHTML = `<div class="forecast-empty">Previsão WRF indisponível</div>`;
    return;
  }

  const maxGeo = Math.max(...comDados.map((f) => f.ac24h_forecast_mm));
  const maxPonto = comDados.find((f) => f.ac24h_forecast_mm === maxGeo);
  const maxHidro = Math.max(
    ...comDados.map((f) => f.ac6h_forecast_mm ?? 0)
  );

  let html = `<div style="font-size: .9em; line-height: 1.4;">`;
  html += (
    `<div style="margin-bottom: 6px; font-size: .8em; color: #555;">`
    + `${escapeHtml(data.source || "WRF horário CPTEC/INPE")}</div>`
  );
  html += (
    `<div style="margin-bottom: 4px;">`
    + `<strong>Maior prev. geo (+24h):</strong> ${maxGeo.toFixed(1)} mm</div>`
  );
  html += (
    `<div style="margin-bottom: 4px;">`
    + `<strong>Maior prev. hidro (+6h):</strong> ${maxHidro.toFixed(1)} mm</div>`
  );
  html += (
    `<div style="font-size: .85em; color: #666; margin-bottom: 8px;">`
    + `${escapeHtml(maxPonto?.nome || "")}</div>`
  );

  html += (
    `<div style="max-height: 120px; overflow-y: auto; `
    + `border-top: 1px solid #eee; padding-top: 6px;">`
  );
  for (const f of comDados.slice(0, 5)) {
    const vals = `${f.ac24h_forecast_mm.toFixed(1)} (+24h)`;
    const hidro = f.ac6h_forecast_mm != null
      ? ` · ${f.ac6h_forecast_mm.toFixed(1)} (+6h)`
      : "";
    html += (
      `<div style="display:flex; justify-content:space-between; `
      + `font-size: .85em; padding: 2px 0; gap: 8px;">`
      + `<span>${escapeHtml(f.nome)}</span>`
      + `<span><b>${vals}${hidro} mm</b></span>`
      + `</div>`
    );
  }
  if (comDados.length > 5) {
    html += (
      `<div style="font-size: .8em; color: #999; text-align: center;">`
      + `+${comDados.length - 5} zonas</div>`
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
    <div style="margin-top:10px; padding-top:8px; border-top:1px solid #eee;">
      <div style="font-size:.75em; color:#666; margin-bottom:4px;">Evolução do Risco (últimos ${vals.length} ciclos)</div>
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
