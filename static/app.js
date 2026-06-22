/**
 * PLI-HazardTrack - Frontend
 * Sistema de monitoramento de riscos climáticos extremos em rodovias
 *
 * - Auto-refresh do snapshot a cada 30s
 * - Mapa Leaflet (CARTO Light) com camadas de risco e bases DER/IGC
 * - Filtros interativos por camada
 */

const REFRESH_MS = 30_000;
/** UAs prioritárias para ações e situação operacional (até N). */
const FOCAL_MAX = 4;
const SP_BOUNDS = [
  [-25.5, -53.2],
  [-19.7, -44.0],
]; // Estado inteiro
const LITORAL_BOUNDS = [
  [-25.0, -47.0],
  [-22.5, -44.3],
]; // Litoral norte + Baixada Santista

// Prefixo da app, injetado pelo template (vazio em raiz, "/hazardtrack" atras de Nginx em path)
const APP_BASE =
  typeof window !== "undefined" && window.APP_BASE ? window.APP_BASE : "";
const apiUrl = (path) => APP_BASE + path;

const NIVEL_LABEL = [
  "Monitoramento",
  "Observação",
  "Atenção",
  "Alerta",
  "Alerta Máximo",
];
const NIVEL_COLOR = ["#2aa358", "#f1c40f", "#f39c12", "#e74c3c", "#8e44ad"];
const NIVEL_DESC = [
  "Sem chuva relevante",
  "Chuva próxima ao limiar",
  "Vistorias preventivas",
  "Possíveis ocorrências",
  "Risco severo",
];
const HAZARD_ALERT_LABEL = {
  geo: "Movimentos de massa (risco geológico)",
  hidro: "Inundação (risco hidrológico)",
};

// ============================================================================
// REGISTRY DE CAMADAS DE HAZARD
// Cada camada tem paleta propria de 5 niveis (escuro = mais grave) e funcao
// que extrai o RD daquele hazard a partir de um ponto do snapshot.
// Para adicionar uma camada nova: registrar entrada aqui + tornar `available`.
// ============================================================================
const TRECHO_SELECT_PLACEHOLDER = "Selecione um valor";
const TRECHO_VALUE_PENDING = "Aguardando dados";

const HAZARDS = {
  encosta: {
    label: "Movimentos de massa",
    description:
      "Engloba escorregamento e queda de bloco. Pelo método em uso (REGEA-NIPPON 2021), são tratados na mesma envoltória crítica.",
    // Mesma escala dos pontos (niveis operacionais oficiais).
    palette: ["#2aa358", "#f1c40f", "#f39c12", "#e74c3c", "#8e44ad"],
    source: "REGEA-NIPPON 2021",
    available: true,
    rdFrom: (point) => (Number.isInteger(point?.rd) ? point.rd : null),
  },
  inundacao: {
    label: "Inundação",
    description:
      "Alagamento e enxurrada por chuva intensa de curto prazo (24h).",
    // Nivel 0 = mesmo verde dos pontos (Monitoramento). Niveis 1-3 sobem em azul,
    // nivel 4 vira magenta/violeta vivido para destaque maximo.
    palette: ["#2aa358", "#5fa8d3", "#1d6fb8", "#0a3d7a", "#d61f8d"],
    source: "REGEA-NIPPON 2021",
    available: true,
    rdFrom: (point) => (Number.isInteger(point?.rd) ? point.rd : null),
  },
};

// Estado das camadas de risco (UA geo/hidro). Recarrega sempre ligadas.
const HAZARD_STORAGE_KEY = "pli_hazardtrack.hazard_layers.v2";
const LEGEND_COLLAPSE_KEY = "pli_hazardtrack.legend_collapsed.v1";
const LAYER_PANEL_COLLAPSE_KEY = "pli_hazardtrack.layer_panel_collapsed.v1";
const MAP_LAYER_STORAGE_KEY = "pli_hazardtrack.map_layers.v2";
const PROGRESS_POLL_MS = 1500;

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
    localStorage.setItem(LEGEND_COLLAPSE_KEY, JSON.stringify(LEGEND_COLLAPSED));
  } catch {
    /* ignora */
  }
}

const LEGEND_COLLAPSED = _loadLegendCollapsed();

function _loadHazardState() {
  return Object.fromEntries(
    Object.entries(HAZARDS)
      .filter(([, h]) => h.available)
      .map(([k]) => [k, true]),
  );
}

function saveHazardState() {
  try {
    localStorage.setItem(HAZARD_STORAGE_KEY, JSON.stringify(HAZARD_STATE));
  } catch {
    /* storage cheio/bloqueado: ignora */
  }
}

const HAZARD_LAYER_KEY = { geo: "encosta", hidro: "inundacao" };

const MAP_LAYER_DEFAULTS = {
  regions: false,
  heatmap: false,
  roads: false,
  fireRisk: true,
  municipios: false,
  rc: false,
  uba: false,
  cgr: false,
};

function loadMapLayerState() {
  return { ...MAP_LAYER_DEFAULTS };
}

const MAP_LAYER_STATE = loadMapLayerState();

function saveMapLayerState() {
  try {
    localStorage.setItem(MAP_LAYER_STORAGE_KEY, JSON.stringify(MAP_LAYER_STATE));
  } catch {
    /* ignora */
  }
}

function snapshotPoints(snap) {
  const geo = snap?.points_geo || [];
  const hid = snap?.points_hidro || [];
  if (geo.length || hid.length) return { geo, hid };
  const legacy = snap?.points || [];
  return {
    geo: legacy.filter((p) => p.hazard === "geo" || p.RAHID == null),
    hid: legacy.filter((p) => p.hazard === "hidro" || p.RAGEO == null),
  };
}

// ============================================================================
// Helpers UA - leem ATRIBUTOS NATIVOS de uas_area_estudo nos pontos
// retornados por /api/snapshot (sem normalizacao intermediaria).
// ============================================================================
function uaKmMid(p) {
  if (p == null) return null;
  if (p.km_inicial != null && p.km_final != null) {
    return (Number(p.km_inicial) + Number(p.km_final)) / 2;
  }
  return null;
}
function uaLabel(p) {
  if (!p) return "—";
  const rod = p.sigla_rodovia || "UA";
  const ki = p.km_inicial, kf = p.km_final;
  if (ki != null && kf != null) {
    return `${rod} km ${formatTrechoKm(ki)}-${formatTrechoKm(kf)}`;
  }
  return rod;
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

function sortPointsByAlert(a, b) {
  const dr = (b.rd || 0) - (a.rd || 0);
  if (dr !== 0) return dr;
  return (b.ac96h_mm || 0) - (a.ac96h_mm || 0);
}

/** Pool de UAs conforme camada(s) ativa(s); une geo+hidro pelo pior RD. */
function activePointPool(snap) {
  const { geo, hid } = snapshotPoints(snap);
  const encostaOn = HAZARD_STATE.encosta;
  const inundacaoOn = HAZARD_STATE.inundacao;
  if (encostaOn && !inundacaoOn) {
    return geo.map((p) => ({ ...p }));
  }
  if (inundacaoOn && !encostaOn) {
    return hid.map((p) => ({ ...p }));
  }
  const byId = new Map();
  const pick = (existing, candidate, hazard) => {
    if (!existing) return { ...candidate, hazard };
    if (sortPointsByAlert(candidate, existing) < 0) {
      return { ...candidate, hazard };
    }
    return existing;
  };
  for (const p of geo) {
    byId.set(p.ua_id, pick(byId.get(p.ua_id), p, "geo"));
  }
  for (const p of hid) {
    byId.set(p.ua_id, pick(byId.get(p.ua_id), p, "hidro"));
  }
  return [...byId.values()];
}

/**
 * Conjunto focal único (1..FOCAL_MAX UAs) para todos os painéis de alerta.
 * Só inclui UAs com RD > 0; em operação normal retorna [].
 */
function resolveFocalPoints(snap) {
  const pool = activePointPool(snap);
  if (!pool.length) return [];
  const alerted = pool.filter((p) => (p.rd || 0) > 0);
  if (!alerted.length) return [];
  alerted.sort(sortPointsByAlert);
  return alerted.slice(0, FOCAL_MAX);
}

function levelsFromPoints(points) {
  const by = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0 };
  for (const p of points) {
    const rd = Math.min(4, Math.max(0, p.rd || 0));
    by[rd] = (by[rd] || 0) + 1;
  }
  return by;
}

function focalMaxRd(focal) {
  if (!focal?.length) return 0;
  return Math.max(...focal.map((p) => p.rd || 0));
}

function infoCardClassForRd(rd) {
  if (rd >= 3) return "info-card--critical";
  if (rd >= 2) return "info-card--warning";
  return "info-card--success";
}

function infoAccentForRd(rd) {
  if (rd >= 3) return "var(--info-critical)";
  if (rd >= 2) return "var(--info-warning)";
  return "var(--info-success)";
}

const TRECHO_SCALAR_NOTE =
  "Cada trecho monitorado corresponde a uma Unidade de Análise (UA). Os "
  + "indicadores referem-se aos valores calculados nessa UA (RA do polígono, "
  + "chuva no centróide, RD = RA × ICC).";

function formatTrechoKm(km) {
  if (km == null || km === "") return "—";
  const n = Number(km);
  if (!Number.isFinite(n)) return String(km);
  return n.toLocaleString("pt-BR", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

function resolvePanelUaId(snap) {
  if (state.uaPickerId) return state.uaPickerId;
  const focal = resolveFocalPoints(snap);
  if (state.trechoRegion) {
    const rid = Number(state.trechoRegion);
    const inReg = focal.filter((p) => uaRegionId(p) === rid);
    if (inReg.length) return inReg[0].ua_id;
    const { geo } = snapshotPoints(snap);
    const ranked = geo
      .filter((p) => uaRegionId(p) === rid)
      .sort((a, b) => (b.rd || 0) - (a.rd || 0));
    return ranked[0]?.ua_id || null;
  }
  return focal[0]?.ua_id || null;
}

function renderFocalBanner(focal) {
  const el = document.getElementById("focal-banner");
  if (!el) return;
  if (!focal?.length) {
    el.hidden = true;
    el.textContent = "";
    el.classList.remove(
      "info-card--critical",
      "info-card--success",
      "info-card--warning",
    );
    return;
  }
  el.hidden = false;
  const maxRd = focalMaxRd(focal);
  el.classList.remove(
    "info-card--critical",
    "info-card--success",
    "info-card--warning",
  );
  el.classList.add(
    infoCardClassForRd(maxRd),
  );
  const labels = focal.map((p) => escapeHtml(focalShortLabel(p))).join(" · ");
  const top = focalShortLabel(focal[0]);
  if (focal.length === 1) {
    el.innerHTML =
      "Ações e situação operacional referem-se ao trecho <b>" + labels
      + "</b>. Indicadores, previsão e sensibilidade empregam "
      + "<b>um trecho por vez</b> (priorização automática).";
  } else {
    el.innerHTML =
      "Ações e situação operacional consideram até <b>" + focal.length
      + " trechos</b> em alerta: " + labels + ". "
      + "Indicadores, previsão e sensibilidade adotam o de maior RD "
      + "(<b>" + escapeHtml(top) + "</b>) — selecione outro no seletor.";
  }
}

function formatRaValue(pt, channel) {
  if (!pt) return "—";
  const raw = channel === "geo" ? pt.RAGEO : pt.RAHID;
  if (raw == null || raw === "") return "SEM DADO";
  return String(raw);
}

function formatTrechoLabel(pt) {
  if (!pt) return "—";
  if (pt.km_inicial != null && pt.km_final != null) {
    return `km ${formatTrechoKm(pt.km_inicial)}-${formatTrechoKm(pt.km_final)}`;
  }
  return uaLabel(pt);
}

function resolveMaxAlertContext(snap, summary) {
  const pending = {
    hazardLabel: TRECHO_VALUE_PENDING,
    region: TRECHO_VALUE_PENDING,
    rodovia: TRECHO_VALUE_PENDING,
    trecho: TRECHO_VALUE_PENDING,
    raGeo: TRECHO_VALUE_PENDING,
    raHid: TRECHO_VALUE_PENDING,
    rdAlert: TRECHO_VALUE_PENDING,
    rdChannel: null,
  };
  if (!snap || !summary?.max_rd_point) return pending;

  const hazard = summary.max_rd_hazard === "hidro" ? "hidro" : "geo";
  const pair = getUaPair(snap, summary.max_rd_point);
  const alertPt = hazard === "hidro" ? pair.hid : pair.geo;
  const ref = pair.geo || pair.hid || alertPt;
  if (!ref) return pending;

  const rdAlert = alertPt?.rd ?? summary.max_rd ?? 0;
  return {
    hazardLabel: HAZARD_ALERT_LABEL[hazard] || HAZARD_ALERT_LABEL.geo,
    region: ref.regiao_nome || "—",
    rodovia: ref.sigla_rodovia || "—",
    trecho: formatTrechoLabel(ref),
    raGeo: formatRaValue(pair.geo, "geo"),
    raHid: formatRaValue(pair.hid, "hidro"),
    rdAlert,
    rdChannel: hazard,
  };
}

function renderMaxAlertPanel(snap, summary, level) {
  const hazardEl = document.getElementById("max-alert-hazard");
  const ctx = resolveMaxAlertContext(snap, summary);
  const pendingTrecho =
    !snap
    || summary?.data_status === "loading"
    || summary?.data_status === "no_data"
    || !summary?.max_rd_point;

  if (hazardEl) {
    hazardEl.textContent = pendingTrecho ? TRECHO_VALUE_PENDING : ctx.hazardLabel;
  }

  const fields = [
    ["max-alert-region", ctx.region],
    ["max-alert-road", ctx.rodovia],
    ["max-alert-segment", ctx.trecho],
    ["max-alert-ra-geo", ctx.raGeo],
    ["max-alert-ra-hid", ctx.raHid],
  ];
  for (const [id, value] of fields) {
    const el = document.getElementById(id);
    if (el) el.textContent = pendingTrecho ? TRECHO_VALUE_PENDING : value;
  }

  const rdEl = document.getElementById("max-alert-rd");
  if (rdEl) {
    if (pendingTrecho) {
      rdEl.textContent = TRECHO_VALUE_PENDING;
    } else {
      const rd = Math.min(4, Math.max(0, Number(ctx.rdAlert) || 0));
      const tag =
        ctx.rdChannel === "hidro"
          ? " · inundação"
          : ctx.rdChannel === "geo"
            ? " · encosta"
            : "";
      rdEl.textContent = `${rd} — ${NIVEL_LABEL[rd]}${tag}`;
    }
  }
}

function focalShortLabel(p) {
  return uaLabel(p);
}

function sidebarLevelCounts(summary, focal) {
  if (focal?.length) return levelsFromPoints(focal);
  return activeByLevel(summary);
}

function maxLevelFromCounts(by) {
  for (let i = 4; i >= 0; i--) {
    if ((by?.[i] || by?.[String(i)] || 0) > 0) return i;
  }
  return 0;
}

function pendingLevelCountsObj() {
  const o = {};
  for (let i = 0; i <= 4; i++) o[i] = TRECHO_VALUE_PENDING;
  return o;
}

function setLayerLevelCounts(prefix, by) {
  const pending =
    by?.[0] === TRECHO_VALUE_PENDING || by?.["0"] === TRECHO_VALUE_PENDING;
  for (let i = 0; i <= 4; i++) {
    const el = document.getElementById(`count-${prefix}-${i}`);
    if (!el) continue;
    const raw = by?.[i] ?? by?.[String(i)];
    if (pending || raw === TRECHO_VALUE_PENDING) {
      el.textContent = TRECHO_VALUE_PENDING;
    } else {
      el.textContent = String(raw ?? 0);
    }
  }
}

function initLevelMeters() {
  setLayerLevelCounts("geo", pendingLevelCountsObj());
  setLayerLevelCounts("hidro", pendingLevelCountsObj());
  syncMeterScaleColors();
}

function applySidebarLevelCounts(summary, focal) {
  const by = sidebarLevelCounts(summary, focal);
  const byGeo = summary.by_level_geo || {};
  const byHidro = summary.by_level_hidro || {};
  setLayerLevelCounts("geo", byGeo);
  setLayerLevelCounts("hidro", byHidro);
  const maxRd = focal?.length ? focalMaxRd(focal) : (summary.max_rd ?? 0);
  applyMeterHighlight({
    encosta: byGeo,
    inundacao: byHidro,
    combined: by,
    max: {
      encosta: maxLevelFromCounts(byGeo),
      inundacao: maxLevelFromCounts(byHidro),
      combined: maxRd,
    },
  });
}

function syncMeterScaleColors() {
  applyMeterHighlight({
    encosta: {},
    inundacao: {},
    max: { encosta: 0, inundacao: 0 },
  });
}

const HAZARD_STATE = _loadHazardState();

const state = {
  map: null,
  layers: {
    hazardZones: {},
    regions: null,
    heat: null,
    roads: null,
    fireRisk: null,
  },
  pointMarkers: new Map(),
  pointData: new Map(), // id -> dados completos do ponto (para heatmap)
  regionPolys: [],
  roadGeoJSON: null,
  fireRiskGeoJSON: {},
  fireRiskHorizon: "observado",
  roadFilters: {
    tipo_pista: "",
    regional: "",
    administra: "",
    rodovia: "",
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
    hazard: "encosta",
    savedHazardState: null,
  },
  historyMode: false,
  historyAtIso: null,
  focalPoints: [],
  uaPickerId: "",
  trechoRegion: "",
  trechoRoad: "",
  trechoApoioId: "",
  trechoFocus: { markerKeys: [], overlay: null, lastKey: "" },
  lastPopupLatLng: null,
  // Halo visual aplicado ao clicar numa UA (separado de trechoFocus,
  // que e disparado por seletores da sidebar). Persiste ate o usuario
  // clicar fora ou em outra UA.
  uaClickFocus: { markerKey: null, halo: null },
  forecastData: null,
};

document.addEventListener("DOMContentLoaded", init);

const SB_PANELS_OPEN_DEFAULT = new Set([
  "ppdc-max-panel",
  "fire-panel",
]);

function applyDefaultSidebarPanels() {
  document.querySelectorAll(".sb-panel").forEach((panel) => {
    const open = SB_PANELS_OPEN_DEFAULT.has(panel.id);
    const body = panel.querySelector(".sb-panel-body");
    const head = panel.querySelector(".sb-panel-head[data-sb-toggle]");
    panel.classList.toggle("is-open", open);
    if (body) body.hidden = !open;
    if (head) head.setAttribute("aria-expanded", open ? "true" : "false");
  });
}

function init() {
  applyDefaultSidebarPanels();
  initMap();
  attachEvents();
  initSidebarPanels();
  initSidebarJumps();
  initSidebarChrome();
  window.pliMapBridge = {
    onFiltersChanged() {
      renderRoadsOnMap();
      renderFireRiskLayer();
      if (state.lastSnapshot) renderPointsOnMap(state.lastSnapshot);
    },
    getLayerValues(layerId, fieldKey) {
      let rows = [];
      if (layerId === "roads") {
        rows = state.roadGeoJSON?.features?.map((f) => f.properties || {}) || [];
      } else if (layerId === "fireRisk") {
        rows = state.fireRiskGeoJSON[state.fireRiskHorizon]?.features
          ?.map((f) => f.properties || {}) || [];
      } else if (layerId === "encosta" || layerId === "inundacao") {
        const snap = state.lastSnapshot || {};
        const { geo, hid } = snapshotPoints(snap);
        rows = layerId === "inundacao" ? hid : geo;
      }

      const values = rows.map((row) => {
        if (fieldKey === "rd" && layerId !== "roads") {
          return HAZARDS[layerId]?.rdFrom(row);
        }
        return row?.[fieldKey];
      }).filter((v) => v !== null && v !== undefined && v !== "");

      return [...new Set(values.map((v) => String(fixText(v))))].sort(
        (a, b) => a.localeCompare(b, "pt-BR", { numeric: true }),
      );
    },
  };
  if (window.QueryFilter) window.QueryFilter.init();
  loadFireRiskSnapshot();
  renderHazardPanel();
  renderHazardLegend();
  initLegendToggles();
  loadRoadNetwork();
  renderStatusCard({ pending: true, timeLine: "—" });
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

  // Painel Camadas persistente sobre o mapa.
  installMapLayerControl();

  L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    {
      attribution: "&copy; OpenStreetMap &copy; CARTO",
      maxZoom: 19,
      minZoom: 6,
      subdomains: "abcd",
    },
  ).addTo(state.map);

  L.control
    .attribution({ position: "bottomright", prefix: false })
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
  state.layers.regions = L.layerGroup(); // criada vazia, ligada via toggle
  state.layers.roads = L.layerGroup().addTo(state.map);
  state.layers.fireRisk = L.layerGroup();
  // Camadas administrativas (criadas vazias; carregadas sob demanda no toggle)
  state.layers.municipios = L.layerGroup();
  state.layers.rc = L.layerGroup();
  state.layers.uba = L.layerGroup();
  state.layers.cgr = L.layerGroup();

  // Mascara visual: tudo fora do estado de SP fica esmaecido. Carregamento
  // assincrono - se falhar, o mapa funciona normal sem mascara.
  loadSpMask();

  // Click no mapa (fora de qualquer feature) limpa o halo de UA clicada.
  state.map.on("click", () => clearUaClickFocus());
}

/**
 * Carrega o contorno do estado e desenha um poligono mundial com furo
 * no formato de SP. Resultado: SP fica nitido, o restante levemente apagado.
 */
async function loadSpMask() {
  try {
    const gj = await (
      await fetch(apiUrl("/static/data/sp_state.geojson"))
    ).json();
    const feat = (gj.features || [])[0];
    if (!feat) return;

    // Coleta o(s) anel(eis) externo(s) do estado em formato lat/lon Leaflet.
    const collectRings = (geom) => {
      if (geom.type === "Polygon") return [geom.coordinates[0]];
      if (geom.type === "MultiPolygon")
        return geom.coordinates.map((p) => p[0]);
      return [];
    };
    const sp_rings_lonlat = collectRings(feat.geometry);
    const sp_rings_latlng = sp_rings_lonlat.map((ring) =>
      ring.map(([lon, lat]) => [lat, lon]),
    );

    // Anel externo "do mundo" (sentido horario) + aneis de SP como furos
    const world = [
      [-90, -180],
      [-90, 180],
      [90, 180],
      [90, -180],
    ];
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
    const lbl = btn.querySelector(".sb-tool-lbl");
    btn.disabled = true;
    const original = lbl ? lbl.textContent : btn.textContent;
    if (lbl) lbl.textContent = "…";
    else btn.textContent = "…";
    try {
      if (state.historyMode) await exitHistoryMode(false);
      await fetch(apiUrl("/api/refresh"), { method: "POST" });
      await refresh();
    } catch (e) {
      console.error(e);
    } finally {
      if (lbl) lbl.textContent = original;
      else btn.textContent = original;
      btn.disabled = false;
    }
  });

  document.getElementById("btn-fit").addEventListener("click", () => {
    state.map.fitBounds(SP_BOUNDS);
  });

  document.getElementById("btn-fit-litoral").addEventListener("click", () => {
    state.map.fitBounds(LITORAL_BOUNDS);
  });

  document.getElementById("btn-zoom-in")?.addEventListener("click", () => {
    state.map.zoomIn();
  });

  document.getElementById("btn-zoom-out")?.addEventListener("click", () => {
    state.map.zoomOut();
  });

  // ---- Linha do Tempo (animacao 96h) ----
  document
    .getElementById("btn-timeline-start")
    ?.addEventListener("click", startTimeline);
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

  // ---- Busca histórica (sidebar) ----
  document.getElementById("history-go")?.addEventListener("click", () => {
    runHistoricalConsultation();
  });
  document.getElementById("history-live")?.addEventListener("click", () => {
    exitHistoryMode(true);
  });

  document.getElementById("layer-regions").addEventListener("change", (e) => {
    MAP_LAYER_STATE.regions = e.target.checked;
    saveMapLayerState();
    if (e.target.checked) state.map.addLayer(state.layers.regions);
    else state.map.removeLayer(state.layers.regions);
  });

  document.getElementById("layer-heatmap").addEventListener("change", (e) => {
    MAP_LAYER_STATE.heatmap = e.target.checked;
    saveMapLayerState();
    if (e.target.checked) addHeatmap();
    else removeHeatmap();
  });

  document.getElementById("layer-roads")?.addEventListener("change", (e) => {
    MAP_LAYER_STATE.roads = e.target.checked;
    saveMapLayerState();
    if (e.target.checked) state.map.addLayer(state.layers.roads);
    else state.map.removeLayer(state.layers.roads);
  });

  document.getElementById("layer-fireRisk")?.addEventListener("change", async (e) => {
    MAP_LAYER_STATE.fireRisk = e.target.checked;
    saveMapLayerState();
    if (e.target.checked) {
      await loadFireRiskLayer();
      state.map.addLayer(state.layers.fireRisk);
    } else {
      state.map.removeLayer(state.layers.fireRisk);
    }
    syncInteractiveLayerOrder();
    renderHazardLegend();
  });

  document.getElementById("layer-fireRisk-horizon")?.addEventListener(
    "change",
    async (e) => {
      state.fireRiskHorizon = e.target.value || "observado";
      state.fireRiskGeoJSON[state.fireRiskHorizon] = null;
      if (MAP_LAYER_STATE.fireRisk) {
        await loadFireRiskLayer(state.fireRiskHorizon);
        renderHazardLegend();
      }
    },
  );

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".js-unified-layers");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const lat = Number(btn.dataset.lat);
    const lng = Number(btn.dataset.lng);
    const latlng = Number.isFinite(lat) && Number.isFinite(lng)
      ? L.latLng(lat, lng)
      : state.lastPopupLatLng;
    if (latlng) openUnifiedLayerPopup(latlng);
  });

  attachAdminLayerEvents();
  restoreMapLayerState();
  attachModalEvents();
  initTrechoPickers();
  initTrechoMetricCards();
  initLevelMeters();
}

function uaRegionId(p) {
  if (!p) return null;
  // Aceita tanto UA (regiao_id nativo) quanto malha DER (region_id normalizado)
  const v = p.regiao_id ?? p.region_id;
  return v != null ? Number(v) : null;
}

function trechoIndexByRoad(snap) {
  const { geo } = snapshotPoints(snap);
  const byRod = new Map();
  for (const p of geo) {
    const rod = p.sigla_rodovia || "—";
    if (!byRod.has(rod)) byRod.set(rod, []);
    byRod.get(rod).push(p);
  }
  for (const pts of byRod.values()) {
    pts.sort((a, b) => (uaKmMid(a) || 0) - (uaKmMid(b) || 0));
  }
  return byRod;
}

function monitoredMalhaRoads() {
  const s = new Set();
  for (const f of state.roadGeoJSON?.features || []) {
    if (f.properties?.monitored) s.add(f.properties.rodovia);
  }
  return s;
}

function malhaTrechosForRoad(road, regId) {
  const rid = regId ? Number(regId) : null;
  return (state.roadGeoJSON?.features || [])
    .filter((f) => {
      const p = f.properties || {};
      if (!p.monitored || p.rodovia !== road) return false;
      if (rid != null && Number(p.region_id) !== rid) return false;
      return true;
    })
    .map((f, i) => ({ i, p: f.properties || {} }))
    .sort((a, b) => (a.p.km_ini || 0) - (b.p.km_ini || 0));
}

function roadsInRegion(snap, regId) {
  const byRod = trechoIndexByRoad(snap);
  const rid = Number(regId);
  const uaRoads = [];
  for (const [road, pts] of byRod) {
    if (pts.some((p) => uaRegionId(p) === rid)) uaRoads.push(road);
  }
  uaRoads.sort((a, b) => a.localeCompare(b, "pt-BR"));
  const uaSet = new Set(uaRoads);
  const apoioRoads = [];
  for (const f of state.roadGeoJSON?.features || []) {
    const p = f.properties || {};
    if (!p.monitored || Number(p.region_id) !== rid) continue;
    if (!uaSet.has(p.rodovia)) apoioRoads.push(p.rodovia);
  }
  return {
    uaRoads,
    apoioRoads: [...new Set(apoioRoads)].sort((a, b) =>
      a.localeCompare(b, "pt-BR"),
    ),
  };
}

function filteredUaPoints(byRod, road, regId) {
  let pts = byRod.get(road) || [];
  if (regId) {
    const rid = Number(regId);
    pts = pts.filter((p) => uaRegionId(p) === rid);
  }
  return pts;
}

function trechoMalhaOptionsHtml(road, regId) {
  const segs = malhaTrechosForRoad(road, regId);
  if (!segs.length) {
    return `<option value="">Sem trechos na malha</option>`;
  }
  let html = `<option value="">${TRECHO_SELECT_PLACEHOLDER}</option>`;
  for (const { i, p } of segs) {
    html += `<option value="apoio:${i}">km ${formatTrechoKm(p.km_ini)} – ${
      formatTrechoKm(p.km_fim)
    } · sem indicadores RD</option>`;
  }
  return html;
}

function trechoKmOptionsHtml(byRod, road, regId) {
  const pts = filteredUaPoints(byRod, road, regId);
  if (!pts.length) {
    return '<option value="">Sem trechos nesta rodovia</option>';
  }
  let html = `<option value="">${TRECHO_SELECT_PLACEHOLDER}</option>`;
  for (const p of pts) {
    const rdTag = (p.rd || 0) > 0 ? ` · RD ${p.rd}` : "";
    html += `<option value="${escapeHtml(String(p.ua_id))}">km ${
      formatTrechoKm(p.km_inicial)
    }-${formatTrechoKm(p.km_final)}${rdTag}</option>`;
  }
  return html;
}

function syncTrechoRegionValue(regId) {
  document.querySelectorAll(".js-trecho-region").forEach((sel) => {
    sel.value = regId;
  });
}

function syncTrechoRoadValue(road) {
  document.querySelectorAll(".js-trecho-road").forEach((sel) => {
    sel.value = road;
  });
}

function syncTrechoKmValue(uaId) {
  document.querySelectorAll(".js-trecho-km").forEach((sel) => {
    sel.value = uaId;
  });
}

function syncTrechoKmOptions(snap) {
  const byRod = trechoIndexByRoad(snap);
  const road = state.trechoRoad;
  const regId = state.trechoRegion || "";
  document.querySelectorAll(".js-trecho-km").forEach((sel) => {
    if (!road) {
      sel.innerHTML =
        `<option value="">${TRECHO_SELECT_PLACEHOLDER}</option>`;
      sel.disabled = true;
      sel.value = "";
      return;
    }
    sel.disabled = false;
    const uaPts = filteredUaPoints(byRod, road, regId);
    if (uaPts.length) {
      sel.innerHTML = trechoKmOptionsHtml(byRod, road, regId);
      if (state.uaPickerId) sel.value = state.uaPickerId;
      else sel.value = "";
      return;
    }
    sel.innerHTML = trechoMalhaOptionsHtml(road, regId);
    if (state.trechoApoioId) sel.value = state.trechoApoioId;
    else sel.value = "";
  });
}

function buildRegionOptionsHtml(snap) {
  const regions = (snap?.regions || []).slice().sort(
    (a, b) => (a.regiao_id ?? a.id) - (b.regiao_id ?? b.id),
  );
  let html = `<option value="">${TRECHO_SELECT_PLACEHOLDER}</option>`;
  for (const r of regions) {
    const rid = r.regiao_id ?? r.id;
    const nome = r.regiao_nome ?? r.nome ?? "—";
    html += `<option value="${rid}">${rid} · ${escapeHtml(nome)}</option>`;
  }
  return html;
}

function buildTrechoRoadOptionsHtml(byRod, regId) {
  let uaRoads;
  let apoioRoads;
  if (regId) {
    const scoped = roadsInRegion(state.lastSnapshot, regId);
    uaRoads = scoped.uaRoads;
    apoioRoads = scoped.apoioRoads;
  } else {
    uaRoads = [...byRod.keys()].sort((a, b) => a.localeCompare(b, "pt-BR"));
    const malhaRoads = [...monitoredMalhaRoads()].sort((a, b) =>
      a.localeCompare(b, "pt-BR"),
    );
    apoioRoads = malhaRoads.filter((r) => !byRod.has(r));
  }
  let html = `<option value="">${TRECHO_SELECT_PLACEHOLDER}</option>`;
  if (uaRoads.length) {
    html += '<optgroup label="Com indicadores RD (809 UAs)">';
    for (const r of uaRoads) {
      html += `<option value="${escapeHtml(r)}">${escapeHtml(r)}</option>`;
    }
    html += "</optgroup>";
  }
  if (apoioRoads.length) {
    html += '<optgroup label="Malha de apoio (sem UA / sem RA oficial)">';
    for (const r of apoioRoads) {
      html += `<option value="${escapeHtml(r)}">${escapeHtml(r)}</option>`;
    }
    html += "</optgroup>";
  }
  return html;
}

function rebuildTrechoPickers(snap) {
  const byRod = trechoIndexByRoad(snap);
  const regId = state.trechoRegion || "";
  const regionHtml = buildRegionOptionsHtml(snap);
  const roadHtml = buildTrechoRoadOptionsHtml(byRod, regId);
  const scoped = regId ? roadsInRegion(snap, regId) : null;
  const scopedRoads = scoped
    ? new Set([...scoped.uaRoads, ...scoped.apoioRoads])
    : new Set([...byRod.keys(), ...monitoredMalhaRoads()]);

  if (state.uaPickerId) {
    const pair = getUaPair(snap, state.uaPickerId);
    const ref = pair.geo || pair.hid;
    if (ref?.sigla_rodovia) {
      state.trechoRoad = ref.sigla_rodovia;
      state.trechoApoioId = "";
    }
    const rid = uaRegionId(ref);
    if (rid != null) state.trechoRegion = String(rid);
  }

  document.querySelectorAll(".js-trecho-region").forEach((sel) => {
    sel.innerHTML = regionHtml;
    sel.value = state.trechoRegion || "";
  });

  document.querySelectorAll(".js-trecho-road").forEach((sel) => {
    sel.innerHTML = roadHtml;
    if (state.trechoRoad && scopedRoads.has(state.trechoRoad)) {
      sel.value = state.trechoRoad;
    } else if (!state.uaPickerId && !state.trechoApoioId) {
      sel.value = "";
      state.trechoRoad = "";
    }
  });

  syncTrechoKmOptions(snap);
  if (state.uaPickerId && filteredUaPoints(
    byRod, state.trechoRoad, regId,
  ).some((p) => String(p.ua_id) === state.uaPickerId)) {
    syncTrechoKmValue(state.uaPickerId);
  } else if (state.trechoApoioId) {
    syncTrechoKmValue(state.trechoApoioId);
  } else if (!state.uaPickerId) {
    syncTrechoKmValue("");
  }
}

function initTrechoPickers() {
  document.querySelectorAll(".js-trecho-region").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      state.trechoRegion = e.target.value || "";
      state.trechoRoad = "";
      state.uaPickerId = "";
      state.trechoApoioId = "";
      syncTrechoRegionValue(state.trechoRegion);
      syncTrechoRoadValue("");
      if (state.lastSnapshot) {
        const byRod = trechoIndexByRoad(state.lastSnapshot);
        const roadHtml = buildTrechoRoadOptionsHtml(byRod, state.trechoRegion);
        document.querySelectorAll(".js-trecho-road").forEach((rsel) => {
          rsel.innerHTML = roadHtml;
          rsel.value = "";
        });
        syncTrechoKmOptions(state.lastSnapshot);
      }
      handleTrechoSelection("");
    });
  });
  document.querySelectorAll(".js-trecho-road").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      state.trechoRoad = e.target.value || "";
      state.uaPickerId = "";
      state.trechoApoioId = "";
      syncTrechoRoadValue(state.trechoRoad);
      if (state.lastSnapshot) {
        syncTrechoKmOptions(state.lastSnapshot);
      }
      handleTrechoSelection("");
    });
  });
  document.querySelectorAll(".js-trecho-km").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      handleTrechoSelection(e.target.value || "");
    });
  });
}

function handleTrechoSelection(value) {
  if (value && String(value).startsWith("apoio:")) {
    state.uaPickerId = "";
    state.trechoApoioId = value;
    syncTrechoKmValue(value);
    if (!state.lastSnapshot) return;
    renderWorst(state.lastSnapshot, state.focalPoints);
    renderRegions(state.lastSnapshot.regions || [], state.lastSnapshot);
    if (state.forecastData) {
      renderForecast(state.forecastData, state.lastSnapshot);
    }
    updateTrechoMapFocus(state.lastSnapshot, { zoom: true });
    return;
  }
  state.trechoApoioId = "";
  state.uaPickerId = value || "";
  syncTrechoKmValue(state.uaPickerId);
  if (state.uaPickerId && state.lastSnapshot) {
    const pair = getUaPair(state.lastSnapshot, state.uaPickerId);
    const ref = pair.geo || pair.hid;
    if (ref?.sigla_rodovia) {
      state.trechoRoad = ref.sigla_rodovia;
      syncTrechoRoadValue(state.trechoRoad);
      const rid = uaRegionId(ref);
      if (rid != null) {
        state.trechoRegion = String(rid);
        syncTrechoRegionValue(state.trechoRegion);
      }
      syncTrechoKmOptions(state.lastSnapshot);
      syncTrechoKmValue(state.uaPickerId);
    }
  }
  if (!state.lastSnapshot) return;
  renderWorst(state.lastSnapshot, state.focalPoints);
  renderRegions(state.lastSnapshot.regions || [], state.lastSnapshot);
  if (state.forecastData) {
    renderForecast(state.forecastData, state.lastSnapshot);
  }
  updateTrechoMapFocus(state.lastSnapshot, { zoom: true });
}

async function restoreMapLayerState() {
  Object.entries(MAP_LAYER_STATE).forEach(([key, checked]) => {
    const cb = document.getElementById(`layer-${key}`);
    if (cb) cb.checked = !!checked;
  });

  if (MAP_LAYER_STATE.regions) {
    state.map.addLayer(state.layers.regions);
  } else {
    state.map.removeLayer(state.layers.regions);
  }

  if (MAP_LAYER_STATE.roads) {
    state.map.addLayer(state.layers.roads);
  } else {
    state.map.removeLayer(state.layers.roads);
  }

  if (MAP_LAYER_STATE.fireRisk) {
    await loadFireRiskLayer(state.fireRiskHorizon);
    state.map.addLayer(state.layers.fireRisk);
  } else {
    state.map.removeLayer(state.layers.fireRisk);
  }
  syncInteractiveLayerOrder();
  renderHazardLegend();

  if (MAP_LAYER_STATE.heatmap) addHeatmap();
  else removeHeatmap();

  await Promise.all(
    Object.keys(ADMIN_LAYERS).map(async (key) => {
      if (!MAP_LAYER_STATE[key]) return;
      await loadAdminLayer(key);
      state.map.addLayer(state.layers[key]);
    }),
  );
}

/**
 * Acordeão dos painéis da sidebar (seções Monitoramento / Mapa).
 */
function initSidebarPanels() {
  document.querySelectorAll("[data-sb-toggle]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      if (e.target.closest(".sb-tip")) return;
      const panel = btn.closest(".sb-panel");
      const body = panel?.querySelector(".sb-panel-body");
      if (!panel || !body) return;
      const open = panel.classList.toggle("is-open");
      body.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      if (open && panel.id === "history-search-panel") {
        ensureHistorySearchReady();
      }
    });
  });
}

function ensureHistorySearchReady() {
  const inp = document.getElementById("history-at");
  if (inp) {
    if (!inp.value) {
      const d = new Date();
      d.setMinutes(0, 0, 0);
      inp.value = toDatetimeLocalValue(d);
    }
    inp.max = toDatetimeLocalValue(new Date());
  }
  const hints = document.getElementById("history-hints");
  if (hints?.querySelector(".history-hints-loading")) {
    loadHistoryHints();
  }
}

/** Abre painel da sidebar e rola até o alvo (links do bloco de boas-vindas). */
function initSidebarJumps() {
  const openPanel = (targetId) => {
    const el = document.getElementById(targetId);
    if (!el) return;
    const panel = el.closest(".sb-panel");
    if (panel) {
      panel.classList.add("is-open");
      const body = panel.querySelector(".sb-panel-body");
      const head = panel.querySelector(".sb-panel-head");
      if (body) body.hidden = false;
      if (head) head.setAttribute("aria-expanded", "true");
      if (panel.id === "history-search-panel") {
        ensureHistorySearchReady();
      }
    }
    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  document.querySelectorAll("[data-sb-jump]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const id = btn.getAttribute("data-sb-jump");
      if (id) openPanel(id);
    });
  });
}

const SB_WIDTH_MIN = 300;
const SB_WIDTH_MAX = 900;
const SB_WIDTH_DEFAULT = 450;
const SB_LS_WIDTH = "pli.sidebar.width";

/** Redimensionar (arrastar) e recolher/expandir a sidebar. */
function initSidebarChrome() {
  const shell = document.getElementById("sidebar-shell");
  const handle = document.getElementById("sb-resize-handle");
  const toggle = document.getElementById("sb-toggle");
  if (!shell || !handle || !toggle) return;

  const clampWidth = (px) =>
    Math.min(SB_WIDTH_MAX, Math.max(SB_WIDTH_MIN, Math.round(px)));

  let stored = parseInt(localStorage.getItem(SB_LS_WIDTH), 10);
  if (!Number.isFinite(stored)) stored = SB_WIDTH_DEFAULT;
  let sidebarWidth = clampWidth(stored);

  const applyWidth = (px) => {
    sidebarWidth = clampWidth(px);
    shell.style.setProperty("--sidebar-width", `${sidebarWidth}px`);
    shell.dataset.width = String(sidebarWidth);
    localStorage.setItem(SB_LS_WIDTH, String(sidebarWidth));
    syncAppHeaderHeights();
  };

  const notifyMapResize = () => {
    if (!state.map) return;
    window.requestAnimationFrame(() => state.map.invalidateSize());
    setTimeout(() => state.map.invalidateSize(), 240);
  };

  const syncAppHeaderHeights = () => {
    const sidebarHeader = document.querySelector(".sidebar-header");
    const topbar = document.querySelector(".topbar");
    if (!sidebarHeader || !topbar) return;
    sidebarHeader.style.minHeight = "";
    topbar.style.minHeight = "";
    const h = Math.max(sidebarHeader.offsetHeight, topbar.offsetHeight);
    const px = `${h}px`;
    sidebarHeader.style.minHeight = px;
    topbar.style.minHeight = px;
    document.documentElement.style.setProperty("--app-header-height", px);
    document.documentElement.style.setProperty("--topbar-height", px);
  };
  syncAppHeaderHeights();
  requestAnimationFrame(() => {
    syncAppHeaderHeights();
    requestAnimationFrame(syncAppHeaderHeights);
  });
  window.addEventListener("resize", syncAppHeaderHeights);
  if (typeof ResizeObserver !== "undefined") {
    const headerRo = new ResizeObserver(() => syncAppHeaderHeights());
    const sidebarHeader = document.querySelector(".sidebar-header");
    const topbar = document.querySelector(".topbar");
    if (sidebarHeader) headerRo.observe(sidebarHeader);
    if (topbar) headerRo.observe(topbar);
    headerRo.observe(shell);
  }

  const setCollapsed = (collapsed) => {
    shell.classList.toggle("is-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    const label = collapsed ? "Expandir painel" : "Recolher painel";
    toggle.title = label;
    toggle.setAttribute("aria-label", label);
    notifyMapResize();
    syncAppHeaderHeights();
  };

  applyWidth(sidebarWidth);
  setCollapsed(false);

  toggle.addEventListener("click", () => {
    setCollapsed(!shell.classList.contains("is-collapsed"));
  });

  let dragging = false;
  let dragStartX = 0;
  let dragStartW = 0;

  const onPointerMove = (e) => {
    if (!dragging) return;
    const next = clampWidth(dragStartW + (e.clientX - dragStartX));
    applyWidth(next);
    notifyMapResize();
  };

  const stopDrag = () => {
    if (!dragging) return;
    dragging = false;
    shell.classList.remove("is-resizing");
    document.body.classList.remove("sb-resizing");
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", stopDrag);
    window.removeEventListener("pointercancel", stopDrag);
    notifyMapResize();
  };

  handle.addEventListener("pointerdown", (e) => {
    if (shell.classList.contains("is-collapsed")) return;
    e.preventDefault();
    dragging = true;
    dragStartX = e.clientX;
    dragStartW = sidebarWidth;
    shell.classList.add("is-resizing");
    document.body.classList.add("sb-resizing");
    handle.setPointerCapture(e.pointerId);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopDrag);
    window.addEventListener("pointercancel", stopDrag);
  });
}

/** Camadas: markup persistente em index.html; IDs preservados para eventos. */
function installMapLayerControl() {
  const panel = document.getElementById("map-layer-control");
  const toggle = panel?.querySelector(".map-layer-control-toggle");
  if (!panel || !toggle) return;

  let collapsed = false;
  try {
    collapsed = localStorage.getItem(LAYER_PANEL_COLLAPSE_KEY) === "1";
  } catch {
    /* ignora */
  }

  const applyCollapsed = (isCollapsed) => {
    panel.classList.toggle("collapsed", isCollapsed);
    toggle.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    toggle.setAttribute(
      "aria-label",
      isCollapsed
        ? "Expandir painel de camadas"
        : "Recolher painel de camadas",
    );
    toggle.title = isCollapsed ? "Expandir" : "Recolher";
    toggle.textContent = isCollapsed ? "\u25B8" : "\u25C2";
  };

  applyCollapsed(collapsed);

  toggle.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    collapsed = !panel.classList.contains("collapsed");
    applyCollapsed(collapsed);
    try {
      localStorage.setItem(LAYER_PANEL_COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignora */
    }
  });
}

// ============================================================================
// MODAIS (ajuda e glossário)
// ============================================================================

function fillApiModalUrls() {
  const paths = {
    "api-url-live": "/api/public/ua-layers?hazard=geo",
    "api-url-all": "/api/public/ua-layers",
    "api-url-geo": "/api/public/ua-layers?hazard=geo",
    "api-url-hidro": "/api/public/ua-layers?hazard=hidro",
    "api-url-alerts": "/api/public/ua-layers?min_rd=3",
  };
  const origin = window.location.origin || "";
  Object.entries(paths).forEach(([id, path]) => {
    const el = document.getElementById(id);
    if (el) el.textContent = origin + apiUrl(path);
  });
  const ex = document.getElementById("api-fetch-example");
  if (ex) {
    const sample = origin + apiUrl("/api/public/ua-layers?hazard=geo");
    ex.textContent =
      `const res = await fetch("${sample}");\n` +
      "const geojson = await res.json();\n" +
      "console.log(geojson.metadata.timestamp_utc, geojson.features.length);";
  }
}

function attachModalEvents() {
  const openModal = (id) => {
    const m = document.getElementById(id);
    if (m) {
      if (id === "modal-api") fillApiModalUrls();
      m.hidden = false;
      document.body.style.overflow = "hidden";
    }
  };
  const closeAll = () => {
    document
      .querySelectorAll(".modal-backdrop")
      .forEach((el) => (el.hidden = true));
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
  document.getElementById("link-api")?.addEventListener("click", (e) => {
    e.preventDefault();
    openModal("modal-api");
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
    const url =
      state.historyMode && state.historyAtIso
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
  const hazardKey = state.timeline.hazard || "encosta";
  const h = HAZARDS[hazardKey];
  if (!state.timeline.active) {
    return "Escolha o tipo de risco na seção Evolução 96 h e confirme com OK.";
  }
  if (hazardKey === "encosta") {
    return (
      `Animação: ${h?.label || "Encosta"} — níveis de RD geológico ` +
      "(paleta verde→roxo)."
    );
  }
  return (
    `Animação: ${h?.label || "Inundação"} — níveis de RD hidrológico ` +
    "(paleta verde→azul→magenta)."
  );
}

function setHazardTogglesDisabled(disabled) {
  document
    .querySelectorAll('#hazard-toggles input[type="checkbox"]')
    .forEach((cb) => {
      cb.disabled = disabled;
    });
}

function prepareTimelineLayers(hazardKey) {
  Object.entries(HAZARDS).forEach(([k, h]) => {
    if (!h.available) return;
    const on = k === hazardKey;
    HAZARD_STATE[k] = on;
    const g = state.layers.hazardZones?.[k];
    if (g) {
      if (on) g.addTo(state.map);
      else state.map.removeLayer(g);
    }
  });
  renderHazardLegend();
  updateTimelineChannelHint();
  setHazardTogglesDisabled(true);
}

function restoreTimelineLayers() {
  const saved = state.timeline.savedHazardState;
  if (!saved) return;
  Object.assign(HAZARD_STATE, saved);
  state.timeline.savedHazardState = null;
  Object.entries(HAZARDS).forEach(([k, h]) => {
    if (!h.available) return;
    const g = state.layers.hazardZones?.[k];
    if (g) {
      if (HAZARD_STATE[k]) g.addTo(state.map);
      else state.map.removeLayer(g);
    }
  });
  renderHazardPanel();
  renderHazardLegend();
  setHazardTogglesDisabled(false);
}

async function startTimeline() {
  const sel = document.getElementById("timeline-hazard");
  const hazard = sel?.value === "inundacao" ? "inundacao" : "encosta";
  state.timeline.hazard = hazard;
  const panel = tlEl("timeline");
  if (state.timeline.active && state.timeline.frames.length) {
    if (panel) panel.hidden = false;
    if (!state.timeline.savedHazardState) {
      state.timeline.savedHazardState = { ...HAZARD_STATE };
    }
    prepareTimelineLayers(hazard);
    applyTimelineFrame(state.timeline.idx);
    return;
  }
  await openTimeline();
}

function updateTimelineChannelHint() {
  const el = tlEl("tl-channel");
  if (el) el.textContent = tlActiveChannelMessage();
}

function toDatetimeLocalValue(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return (
    d.getFullYear() +
    "-" +
    pad(d.getMonth() + 1) +
    "-" +
    pad(d.getDate()) +
    "T" +
    pad(d.getHours()) +
    ":" +
    pad(d.getMinutes())
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
      '<span class="history-hints-loading">Sugestões indisponíveis.</span>';
  }
}

function renderHistoryHints(events, disclaimer) {
  const box = document.getElementById("history-hints");
  if (!box) return;
  if (!events.length) {
    box.innerHTML =
      '<span class="history-hints-loading">Nenhum evento cadastrado.</span>';
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
      '<span class="history-hint-level" style="background:' +
      color +
      '"></span><span class="history-hint-text"><strong>' +
      escapeHtml(ev.label) +
      "</strong><small>" +
      escapeHtml(ev.level_label || "") +
      " · " +
      escapeHtml(ev.region || "") +
      "</small></span>";
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
    foot.className = "history-search-hint";
    foot.style.marginTop = "0.25rem";
    foot.textContent = disclaimer;
    box.appendChild(foot);
  }
}

async function runHistoricalConsultation() {
  const inp = document.getElementById("history-at");
  if (!inp?.value) return;
  const atIso = new Date(inp.value).toISOString();
  state.historyMode = true;
  state.historyAtIso = atIso;
  closeTimeline();
  setBadge("badge-update", "Consultando…", "loading");
  renderStatusCard({
    headline: "Consultando histórico…",
    detail:
      '<span class="status-detail-item">Reconstituindo RD com chuva '
      + "observada da data escolhida</span>",
    timeLine: "Aguarde a resposta do servidor · pode levar alguns minutos",
    levelVisible: false,
    dotClass: "warn",
    pending: true,
    snap: state.lastSnapshot,
    summary: state.lastSnapshot?.summary || null,
  });
  startDownloadPoll();
  setMapHistoryBanner("Carregando chuva MERGE/INPE da época…", true);
  try {
    const res = await fetch(
      apiUrl("/api/snapshot?at=" + encodeURIComponent(atIso)),
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
  if (refreshLive) {
    setBadge("badge-update", "Ao vivo…", "loading");
    setMapHistoryBanner(null);
    try {
      await fetch(apiUrl("/api/refresh"), { method: "POST" });
    } catch {
      /* ignora */
    }
    await refresh();
  }
}

function tlEl(id) {
  return document.getElementById(id);
}

async function openTimeline() {
  const panel = tlEl("timeline");
  if (!panel) return;
  if (!state.timeline.savedHazardState) {
    state.timeline.savedHazardState = { ...HAZARD_STATE };
  }
  prepareTimelineLayers(state.timeline.hazard);
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
  const startBtn = document.getElementById("btn-timeline-start");
  if (startBtn) startBtn.disabled = true;
  try {
    const res = await fetch(apiUrl("/api/timeline"));
    const data = await res.json();
    if (!data.available || !Array.isArray(data.frames) || !data.frames.length) {
      tlEl("tl-status").textContent =
        data.reason || "Sem dados para a animação.";
      restoreTimelineLayers();
      return;
    }
    state.timeline.frames = data.frames;
    state.timeline.idx = data.frames.length - 1; // comeca no "agora"
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
    restoreTimelineLayers();
  } finally {
    state.timeline.loading = false;
    tlEl("tl-play").disabled = false;
    if (startBtn) startBtn.disabled = false;
  }
}

function closeTimeline() {
  tlPause();
  state.timeline.active = false;
  const panel = tlEl("timeline");
  if (panel) panel.hidden = true;
  restoreTimelineLayers();
  refresh(); // restaura as cores ao vivo
}

function applyTimelineFrame(idx) {
  const frames = state.timeline.frames;
  if (!frames.length) return;
  idx = Math.max(0, Math.min(frames.length - 1, idx));
  state.timeline.idx = idx;
  const frame = frames[idx];
  const hazardKey = state.timeline.hazard || "encosta";
  const rdMap =
    hazardKey === "inundacao"
      ? frame.rd_hidro || frame.rd || {}
      : frame.rd_geo || frame.rd || {};
  const palette = HAZARDS[hazardKey]?.palette || NIVEL_COLOR;
  for (const [markerKey, markers] of state.pointMarkers) {
    const parts = markerKey.split(":");
    const mkHazard = parts[1] || "encosta";
    if (mkHazard !== hazardKey) continue;
    const uaId = parts[0];
    const v = rdMap[uaId];
    const color = Number.isInteger(v) ? palette[v] || "#64748b" : "#64748b";
    const arr = Array.isArray(markers) ? markers : [markers];
    arr.forEach((m) => m.setStyle({ color, fillColor: color }));
  }
  const range = tlEl("tl-range");
  if (range) range.value = idx;
  updateTimelineChannelHint();
  const t = frame.ts ? new Date(frame.ts) : null;
  tlEl("tl-time").textContent = t
    ? t.toLocaleString("pt-BR", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
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
  rebuildTrechoPickers(snap);
  const ts = snap.timestamp_utc ? new Date(snap.timestamp_utc) : null;
  const summary = snap.summary || {};
  const maxRd = summary.max_rd ?? 0;
  const status = summary.data_status || "ok"; // ok | degraded | no_data | mock | loading
  const isHistorical = !!summary.historical;
  const focal =
    status === "ok" || status === "degraded" || status === "mock"
      ? resolveFocalPoints(snap)
      : isHistorical && status !== "no_data"
        ? resolveFocalPoints(snap)
        : [];
  state.focalPoints = focal;
  renderFocalBanner(focal);

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
      "historical",
    );
    if (summary.data_status === "no_data") {
      renderSnapshotNoData(snap, summary, tConsult);
      return;
    }
    renderStatusCard({
      auxLine: "Consulta histórica",
      detail: statusDetailHtml(summary, focal),
      timeLine: statusTimeLine(summary, tConsult, "historical"),
      level: maxRd,
      snap,
      summary,
    });
    setBadge("badge-source", "MERGE / INPE (hist.)", "degraded");
    stopDownloadPoll();
    renderPointsOnMap(snap);
    renderRegionsOnMap(snap.regions || []);
    renderRegions(snap.regions || [], snap);
    if (state.roadGeoJSON) renderRoadsOnMap();
    renderWorst(snap, focal);
    applySidebarLevelCounts(summary, focal);
    renderRdBasisNote(summary, status);
    return;
  }

  // ---- Primeiro ciclo ainda em andamento (servidor recem-bootado) ----
  if (status === "loading") {
    state.focalPoints = [];
    renderFocalBanner([]);
    renderStatusCard({
      auxLine: "Preparando monitoramento",
      detail:
        '<span class="status-detail-item">Baixando série horária MERGE/INPE '
        + "(últimas 96 h)</span>"
        + '<span class="status-detail-item">809 UAs aguardando primeira '
        + "leitura de chuva</span>",
      timeLine:
        "Primeira carga: costuma levar de 3 a 8 min · progresso no cartão "
        + "abaixo",
      dotClass: "warn",
      snap,
      summary,
      pending: true,
    });
    setBadge("badge-source", "MERGE / INPE", "loading");
    setBadge("badge-update", "carregando", "loading");
    // Mostra a malha em estilo "sem dado" para a interface nao ficar vazia
    // enquanto o primeiro update do MERGE termina.
    renderPointsOnMap(snap);
    renderRegionsOnMap(snap.regions || []);
    renderRegions(snap.regions || [], snap);
    if (state.roadGeoJSON) renderRoadsOnMap();
    startDownloadPoll();
    renderRdBasisNote(summary, status);
    document
      .querySelectorAll(".meter-cell")
      .forEach((c) => c.classList.remove("active"));
    setLayerLevelCounts("geo", pendingLevelCountsObj());
    setLayerLevelCounts("hidro", pendingLevelCountsObj());
    syncMeterScaleColors();
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
  const statusSuffix =
    status === "degraded"
      ? " (leitura incompleta)"
      : status === "mock"
        ? " (teste)"
        : "";
  renderStatusCard({
    auxLine: statusSuffix ? `Situação geral${statusSuffix}` : "",
    detail: statusDetailHtml(summary, focal),
    timeLine: statusTimeLine(summary, ts, status),
    level: maxRd,
    snap,
    summary,
  });

  // Badges da topbar
  setBadge(
    "badge-source",
    status === "mock" ? "MOCK (dev)" : "MERGE / INPE",
    status === "ok" ? "ok" : status,
  );
  setBadge(
    "badge-update",
    ts ? formatTime(ts) : "—",
    status === "ok" ? "ok" : status,
  );

  // Trecho mais crítico / UAs em foco
  renderWorst(snap, focal);

  // Distribuição por nível (focal se houver alerta; senão malha inteira)
  applySidebarLevelCounts(summary, focal);

  // Regiões
  renderRegions(snap.regions || [], snap);

  // Mapa
  renderRegionsOnMap(snap.regions || []);
  renderPointsOnMap(snap);

  // Malha Rodoviaria Estadual: apoio cartografico (sem traducao de alerta)
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
    "badge-ok",
    "badge-degraded",
    "badge-no-data",
    "badge-mock",
    "badge-loading",
    "badge-historical",
  );
  if (kind === "ok") el.classList.add("badge-ok");
  else if (kind === "degraded") el.classList.add("badge-degraded");
  else if (kind === "no-data" || kind === "no_data")
    el.classList.add("badge-no-data");
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
  state.focalPoints = [];
  renderFocalBanner([]);
  renderStatusCard({
    headline: "Dados de chuva indisponíveis",
    detail:
      '<span class="status-detail-item">MERGE/INPE sem leitura utilizável '
      + "no momento</span>"
      + '<span class="status-detail-item">O mapa permanece visível, mas RD '
      + "não pode ser calculado</span>",
    timeLine: statusTimeLine(summary, ts, "no_data"),
    level: 0,
    dotClass: "alert",
    levelVisible: false,
    snap,
    summary,
  });
  setBadge("badge-update", ts ? formatTime(ts) : "—", "no-data");
  renderPointsOnMap(snap);
  renderRegionsOnMap(snap.regions || []);
  renderRegions(snap.regions || [], snap);
  if (state.roadGeoJSON) renderRoadsOnMap();
  stopDownloadPoll();
  renderWorstNoData(summary.message);
  renderRdBasisNote(summary, "no_data");
  document.querySelectorAll(".meter-cell").forEach((c) => {
    c.classList.remove("active", "meter-cell--blink");
  });
  setLayerLevelCounts("geo", pendingLevelCountsObj());
  setLayerLevelCounts("hidro", pendingLevelCountsObj());
  syncMeterScaleColors();
}

function renderWorstNoData(message) {
  const card = document.getElementById("worst-card");
  if (!card) return;
  const msg =
    message ||
    "Não foi possível obter a chuva medida pelo INPE agora. "
    + "Nova tentativa automática em até 10 min.";
  resetTrechoMetricCard(card, {
    noteHtml:
      `<strong>Chuva indisponível.</strong> ${escapeHtml(msg)}`,
  });
}

// Progresso do primeiro ciclo: lista rolavel de arquivos (ativos +
// concluidos), cada um com barra real vinda do servidor, mais total X/Y.
const _dl = {
  poll: null,
  es: null,
  esRetry: null,
  esFailures: 0,
  data: null,
  mode: null,
  procStart: null,
  doneAt: null,
  refreshed: false,
};

function stopDownloadPoll() {
  if (_dl.poll) {
    clearInterval(_dl.poll);
    _dl.poll = null;
  }
  if (_dl.es) {
    try {
      _dl.es.close();
    } catch (e) {
      /* noop */
    }
    _dl.es = null;
  }
  if (_dl.esRetry) {
    clearTimeout(_dl.esRetry);
    _dl.esRetry = null;
  }
  _dl.data = null;
  _dl.mode = null;
  _dl.procStart = null;
  _dl.doneAt = null;
  _dl.refreshed = false;
  _dl.esFailures = 0;
  const el = document.getElementById("ingest-progress");
  if (el) {
    el.hidden = true;
    el.innerHTML = "";
  }
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
    return `Republicação INPE: ${total} hora(s) recente(s) em atualização.`;
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
  const batchBusy =
    batchTotal > 0 &&
    (d.active || batchDisp < batchTotal || batchDone < batchTotal);
  const isIncremental = d.batch_kind === "incremental";

  if (isIncremental && batchBusy) {
    const batchPct = Number.isFinite(d.batch_pct)
      ? d.batch_pct
      : batchTotal
        ? (batchDisp / batchTotal) * 100
        : 0;
    const doneTxt =
      batchDisp < batchTotal && batchDisp % 1
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
    : cacheBack
      ? Math.min(100, (cacheOk / cacheBack) * 100)
      : 0;
  const disp = Number.isFinite(cacheDisplay)
    ? Math.round(cacheDisplay * 10) / 10
    : cacheOk;
  let count = `${disp} de ${cacheBack} horas prontas`;
  const faltaMin = Math.max(0, minOk - cacheOk);
  if (faltaMin > 0 && cacheOk < minOk) {
    count += ` · faltam ${faltaMin} h para exibir alertas no mapa`;
  }
  return {
    label:
      cacheOk < minOk ? "Montando histórico de chuva" : "Histórico em memória",
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
  if (_dl.poll || _dl.es) return;
  _dl.mode = "download";
  buildDownloadCard();
  // Tenta SSE primeiro (push, ~0 req/s em idle). Fallback automatico
  // para polling tradicional se EventSource indisponivel ou se houver
  // varias falhas de conexao em sequencia.
  if (typeof EventSource !== "undefined") {
    _startProgressSSE();
  } else {
    _startProgressPolling();
  }
}

function _startProgressSSE() {
  // Snapshot inicial via GET (UI ja preenchida antes do 1o push).
  fetch(apiUrl("/api/progress"))
    .then((r) => r.json())
    .then((d) => {
      _dl.data = d;
      renderDownloadFrame();
    })
    .catch(() => {});
  try {
    const es = new EventSource(apiUrl("/api/progress/stream"));
    _dl.es = es;
    _dl.esFailures = 0;
    es.onmessage = (ev) => {
      _dl.esFailures = 0;
      try {
        _dl.data = JSON.parse(ev.data);
        renderDownloadFrame();
      } catch {
        /* payload malformado: ignora */
      }
    };
    es.onerror = () => {
      _dl.esFailures = (_dl.esFailures || 0) + 1;
      // 3 falhas seguidas: desiste do SSE e cai para polling.
      // EventSource ja reconecta sozinho entre erros isolados.
      if (_dl.esFailures >= 3) {
        try {
          es.close();
        } catch (e) {
          /* noop */
        }
        _dl.es = null;
        _startProgressPolling();
      }
    };
  } catch (e) {
    _startProgressPolling();
  }
}

function _startProgressPolling() {
  if (_dl.poll) return;
  const poll = async () => {
    try {
      const r = await fetch(apiUrl("/api/progress"));
      _dl.data = await r.json();
      renderDownloadFrame();
    } catch {
      /* ignora erro de rede transitorio */
    }
  };
  poll();
  _dl.poll = setInterval(poll, PROGRESS_POLL_MS);
}

function buildDownloadCard() {
  const el = document.getElementById("ingest-progress");
  if (!el) return;
  el.hidden = false;
  el.innerHTML = `
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
  const el = document.getElementById("ingest-progress");
  const d = _dl.data;
  if (!el || !d) return;
  const ingestBusy = isIngestProgressBusy(d);
  const batchBusy = d.total > 0 && d.done < d.total;
  const mode =
    (d.phase === "ingest" && (d.active || batchBusy)) ||
    (ingestBusy && d.phase !== "processing" && d.phase !== "done")
      ? "download"
      : d.phase === "processing" || d.phase === "done"
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
  const el = document.getElementById("ingest-progress");
  const list = el?.querySelector(".dl-list");
  const hint = el?.querySelector(".dl-list-hint");
  const batchHint = el?.querySelector(".dl-batch-hint");
  const subtitleEl = el?.querySelector(".dl-subtitle");
  const titleEl = el?.querySelector(".dl-title-text");
  if (!list) return;
  const files = listDownloadFiles(d);

  if (titleEl) titleEl.textContent = dlPanelTitle(d);
  if (subtitleEl) subtitleEl.textContent = dlPanelSubtitle(d);
  if (batchHint) batchHint.textContent = dlBatchHintText(d);
  if (hint) hint.textContent = dlActivityHint(d);

  const main = dlMainProgress(d);
  const cacheFill = el.querySelector(".dl-cache-fill");
  const cacheCount = el.querySelector(".dl-cache-pct");
  const progressLabel = el.querySelector(".dl-progress-label");
  if (progressLabel) progressLabel.textContent = main.label;
  if (cacheFill) cacheFill.style.width = main.pct + "%";
  if (cacheCount) cacheCount.textContent = main.count;

  const prevKeys = list.dataset.keys || "";
  const nextKeys = files.map((f) => `${f.h}:${f.status}`).join(",");
  if (prevKeys !== nextKeys) {
    list.dataset.keys = nextKeys;
    if (!files.length) {
      list.innerHTML = `<li class="dl-row dl-empty">Conectando ao servidor de chuva do INPE...</li>`;
    } else {
      list.innerHTML = files
        .map(
          (f) => `
      <li class="dl-row ${rowStatusClass(f)}" data-h="${f.h}">
        <div class="dl-name">${escapeHtml(f.name)}</div>
        <div class="dl-line">
          <div class="dl-bar"><div class="dl-bar-fill"></div></div>
          <span class="dl-pct">0%</span>
        </div>
      </li>`,
        )
        .join("");
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
  const el = document.getElementById("ingest-progress");
  if (!el) return;
  const stages = Array.isArray(d.stages) ? d.stages : [];
  const rows = stages
    .map(
      (st) => `
      <li class="pr-card pr-pending" data-key="${escapeHtml(st.key)}">
        <span class="pr-ic" aria-hidden="true"></span>
        <span class="pr-label">${escapeHtml(st.label)}</span>
      </li>`,
    )
    .join("");
  el.hidden = false;
  el.innerHTML = `
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
  const el = document.getElementById("ingest-progress");
  const ul = el?.querySelector(".pr-list");
  const procTitle = el?.querySelector(".dl-proc-title");
  const procSub = el?.querySelector(".dl-proc-subtitle");
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
  renderStatusCard({
    headline: text,
    dotClass: cls || "",
    levelVisible: false,
    snap: state.lastSnapshot,
    summary: state.lastSnapshot?.summary || null,
  });
}

function statusDotClass(level) {
  if (level >= 4) return "max";
  if (level >= 3) return "alert";
  if (level >= 2) return "warn";
  return "";
}

function statusDetailHtml(summary, focal) {
  if (!summary) return "";
  const items = [];
  const totalGeo = summary.total_geo ?? 0;
  const totalHid = summary.total_hidro ?? 0;
  items.push(`${totalGeo} UAs encosta · ${totalHid} inundação`);

  const byGeo = summary.by_level_geo || {};
  const byHid = summary.by_level_hidro || {};
  const alertCount = (by) =>
    (by[2] || 0) + (by[3] || 0) + (by[4] || 0);
  const alertGeo = alertCount(byGeo);
  const alertHid = alertCount(byHid);
  const focalN = focal?.length || 0;

  if (focalN) {
    items.push(
      `<b>${focalN}</b> trecho${focalN > 1 ? "s" : ""} em destaque `
      + "(Atenção ou acima)",
    );
  } else if ((summary.max_rd || 0) === 0) {
    items.push("Nenhum trecho acima de Monitoramento");
  }

  if (alertGeo || alertHid) {
    items.push(
      `Em Atenção/alerta: ${alertGeo} encosta · ${alertHid} inundação`,
    );
  }

  return items
    .map((t) => `<span class="status-detail-item">${t}</span>`)
    .join("");
}

function statusTimeLine(summary, ts, status) {
  const parts = [];
  if (status === "mock") {
    parts.push("Modo de teste (dados simulados)");
  } else if (status === "degraded") {
    const miss = summary?.missing_24h;
    parts.push(
      miss != null
        ? `Leitura parcial (${miss} h faltando em 24 h)`
        : "Leitura parcial",
    );
  } else if (status === "historical") {
    parts.push(summary?.rd_basis || "Chuva observada MERGE/INPE (histórico)");
  } else if (status === "loading") {
    parts.push("Primeira carga MERGE/INPE em andamento");
  } else if (status === "no_data") {
    parts.push("Sem leitura de chuva disponível");
  } else {
    parts.push(summary?.rd_basis || "Chuva observada MERGE/INPE");
  }
  if (ts) {
    const label = status === "historical" ? "consulta" : "atualizado";
    parts.push(`${label} às ${formatTime(ts)}`);
  }
  if (summary?.merge_target_hour && status !== "loading") {
    parts.push(
      "hora MERGE " + formatTime(new Date(summary.merge_target_hour)),
    );
  }
  return parts.join(" · ");
}

function isPpdcDataPending(summary, opts = {}) {
  if (opts.pending === true) return true;
  const st = summary?.data_status;
  return st === "loading" || st === undefined;
}

function applyPpdcStatusPending(badgeEl, nameEl, displayEl, card) {
  if (badgeEl) {
    badgeEl.textContent = "—";
    badgeEl.style.background = "rgba(255, 255, 255, 0.12)";
    badgeEl.style.color = "var(--sidebar-muted)";
    badgeEl.hidden = false;
  }
  if (nameEl) nameEl.textContent = TRECHO_VALUE_PENDING;
  if (displayEl) {
    displayEl.classList.add("ppdc-status-display--pending");
    displayEl.style.background = "rgba(255, 255, 255, 0.08)";
    displayEl.style.color = "var(--sidebar-muted)";
    displayEl.removeAttribute("data-rd-level");
  }
  if (card) {
    card.style.borderLeftColor = "rgba(255, 255, 255, 0.12)";
    card.removeAttribute("data-rd-level");
  }
}

function renderStatusCard(opts = {}) {
  const {
    headline = "—",
    detail = "",
    timeLine = "",
    level = 0,
    dotClass = "",
    levelVisible = true,
    snap = null,
    summary = null,
    auxLine = "",
    pending = false,
  } = opts;
  const lineEl = document.getElementById("status-line");
  const detailEl = document.getElementById("status-detail");
  const timeEl = document.getElementById("status-time");
  const badgeEl = document.getElementById("status-level-badge");
  const nameEl = document.getElementById("status-level-name");
  const displayEl = document.getElementById("ppdc-status-display");
  const dot = document.getElementById("status-dot");
  const card = document.getElementById("status-card");

  if (lineEl) {
    if (auxLine) {
      lineEl.textContent = auxLine;
      lineEl.hidden = false;
    } else {
      lineEl.textContent = headline;
      lineEl.hidden = !headline || headline === "—";
    }
  }
  if (detailEl) {
    detailEl.innerHTML = detail;
    detailEl.hidden = !detail;
  }
  if (timeEl) timeEl.textContent = timeLine || "—";

  if (isPpdcDataPending(summary, { pending })) {
    applyPpdcStatusPending(badgeEl, nameEl, displayEl, card);
    if (dot) dot.hidden = true;
    renderMaxAlertPanel(snap, summary, null);
    return;
  }

  const lvl = Math.min(4, Math.max(0, Number(level) || 0));
  const color = NIVEL_COLOR[lvl];
  displayEl?.classList.remove("ppdc-status-display--pending");
  if (badgeEl) {
    badgeEl.textContent = String(lvl);
    badgeEl.style.background = color;
    badgeEl.style.color = lvl === 1 ? "#0f172a" : "#fff";
    badgeEl.hidden = !levelVisible;
  }
  if (nameEl) {
    nameEl.textContent = levelVisible ? NIVEL_LABEL[lvl] : headline;
  }
  if (displayEl && levelVisible) {
    displayEl.style.background = color;
    displayEl.style.color = lvl === 1 ? "#0f172a" : "#fff";
    displayEl.dataset.rdLevel = String(lvl);
  } else if (displayEl && !levelVisible) {
    displayEl.classList.add("ppdc-status-display--pending");
    displayEl.style.background = "rgba(255, 255, 255, 0.08)";
    displayEl.style.color = "var(--sidebar-muted)";
  }
  if (dot) {
    dot.hidden = true;
    dot.classList.remove("warn", "alert", "max");
    const cls = dotClass || statusDotClass(lvl);
    if (cls) dot.classList.add(cls);
  }
  if (card) {
    card.style.borderLeftColor = levelVisible ? color : "";
    card.dataset.rdLevel = String(lvl);
  }

  renderMaxAlertPanel(snap, summary, levelVisible ? lvl : null);
}

// ============================================================================
// CARDS DE MÉTRICAS POR TRECHO (estrutura persistente no HTML)
// ============================================================================

function setCardBind(card, key, text, { html = false, hide = false } = {}) {
  const el = card?.querySelector(`[data-bind="${key}"]`);
  if (!el) return;
  if (hide) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  if (html) el.innerHTML = text;
  else el.textContent = text;
}

function setCardStat(card, channel, key, value, suffix = "") {
  const el = card?.querySelector(
    `[data-channel="${channel}"][data-stat="${key}"] b`,
  );
  if (!el) return;
  el.textContent =
    value != null && value !== "" && value !== undefined
      ? `${value}${suffix}`
      : TRECHO_VALUE_PENDING;
}

function setCardLevel(card, bindKey, rd) {
  const el = card?.querySelector(`[data-bind="${bindKey}"]`);
  if (!el) return;
  if (rd == null || rd === undefined) {
    el.textContent = TRECHO_VALUE_PENDING;
    el.style.background = "#64748b";
    el.style.color = "#fff";
    el.classList.remove("worst-level--blink");
    return;
  }
  el.textContent = `RD ${rd} — ${NIVEL_LABEL[rd]}`;
  el.style.background = NIVEL_COLOR[rd];
  el.style.color = rd === 1 ? "#0f172a" : "#ffffff";
  el.classList.toggle("worst-level--blink", shouldBlinkAlert(rd));
}

function initTrechoMetricCards() {
  for (const id of ["worst-card", "forecast-card", "region-card"]) {
    const card = document.getElementById(id);
    if (!card) continue;
    card.classList.remove("empty", "worst-card--busy");
  }
}

function pendingAllCardStats(card, channel) {
  card?.querySelectorAll(
    `[data-channel="${channel}"] [data-stat] b`,
  ).forEach((el) => {
    el.textContent = TRECHO_VALUE_PENDING;
  });
}

function applyTrechoCardChrome(card, maxRd) {
  if (!card) return;
  card.classList.remove(
    "empty",
    "worst-card--busy",
    "info-card--critical",
    "info-card--success",
    "info-card--warning",
    "worst-card--blink",
  );
  if (maxRd != null && maxRd !== undefined && maxRd > 0) {
    card.classList.add(infoCardClassForRd(maxRd));
    if (shouldBlinkAlert(maxRd)) card.classList.add("worst-card--blink");
    card.style.borderLeftColor = infoAccentForRd(maxRd);
  } else {
    card.style.borderLeftColor = "rgba(255, 255, 255, 0.1)";
  }
}

function resetTrechoMetricCard(card, { note, noteHtml } = {}) {
  if (!card) return;
  applyTrechoCardChrome(card, null);
  setCardBind(card, "name", TRECHO_VALUE_PENDING);
  setCardBind(card, "subtitle", TRECHO_VALUE_PENDING);
  if (noteHtml != null) {
    setCardBind(card, "note", noteHtml, { html: true });
  } else if (note != null) {
    setCardBind(card, "note", note);
  }
  pendingAllCardStats(card, "encosta");
  pendingAllCardStats(card, "inundacao");
  setCardLevel(card, "encosta-level", null);
  setCardLevel(card, "hidro-level", null);
  const dual = card.querySelector(".worst-dual");
  if (dual) dual.hidden = false;
  const sparkWrap = card.querySelector('[data-bind="sparkline"]');
  if (sparkWrap) {
    sparkWrap.innerHTML = "";
    sparkWrap.hidden = true;
  }
  setCardBind(card, "footer", "", { hide: true });
}

function setCardStatLabel(card, channel, key, label) {
  const el = card?.querySelector(
    `[data-channel="${channel}"][data-stat="${key}"] span`,
  );
  if (el && label) el.textContent = label;
}

function fillIndicatorsChannel(card, channel, pt, isGeo) {
  const bind = channel === "encosta" ? "encosta" : "hidro";
  if (!pt) {
    pendingAllCardStats(card, channel);
    setCardLevel(card, `${bind}-level`, null);
    return;
  }
  setCardLevel(card, `${bind}-level`, pt.rd);
  const ra = isGeo ? pt.RAGEO : pt.RAHID;
  const icc = isGeo ? pt.icc_geo : pt.icc_hid;
  setCardStat(card, channel, "ra", ra != null ? ra : null);
  setCardStat(card, channel, "icc", icc != null ? icc : null);
  setCardStat(card, channel, "chuva24", pt.ac24h_mm, " mm");
  setCardStat(card, channel, "ac96", pt.ac96h_mm, " mm");
  setCardStat(card, channel, "intensity", pt.intensity_mmh, " mm/h");
  if (isGeo) {
    setCardStat(
      card,
      channel,
      "cpc",
      pt.cpc != null && pt.cpc !== undefined ? pt.cpc : null,
    );
  }
}

function fillIndicatorsCard(geo, hid) {
  const card = document.getElementById("worst-card");
  if (!card) return;
  const ref = geo || hid;
  if (!ref) {
    resetTrechoMetricCard(card, { note: "Trecho não encontrado." });
    return;
  }
  const maxRd = Math.max(geo?.rd || 0, hid?.rd || 0);
  applyTrechoCardChrome(card, maxRd);
  setCardBind(card, "name", uaLabel(ref) || ref.ua_id);
  setCardBind(
    card,
    "subtitle",
    `${ref.sigla_rodovia || "—"} · ${formatTrechoLabel(ref)} · ${
      ref.regiao_nome || "—"
    }`,
  );
  setCardBind(card, "note", TRECHO_SCALAR_NOTE, { html: true });
  fillIndicatorsChannel(card, "encosta", geo, true);
  fillIndicatorsChannel(card, "inundacao", hid, false);
  const sparkWrap = card.querySelector('[data-bind="sparkline"]');
  if (sparkWrap) {
    const spark =
      geo && (geo.history || []).length >= 2
        ? renderWorstSparkline(geo.history || [])
        : "";
    if (spark) {
      sparkWrap.innerHTML = spark;
      sparkWrap.hidden = false;
    } else {
      sparkWrap.innerHTML = "";
      sparkWrap.hidden = true;
    }
  }
  setCardBind(card, "footer", TRECHO_VALUE_PENDING, { hide: true });
}

function fillApoioIndicatorsCard() {
  const card = document.getElementById("worst-card");
  if (!card) return;
  const road = state.trechoRoad || TRECHO_VALUE_PENDING;
  let segLabel = "";
  const segs = malhaTrechosForRoad(state.trechoRoad, state.trechoRegion);
  if (state.trechoApoioId?.startsWith("apoio:")) {
    const idx = Number(state.trechoApoioId.split(":")[1]);
    const seg = segs[idx];
    if (seg) {
      segLabel =
        `km ${formatTrechoKm(seg.p.km_ini)} – ${formatTrechoKm(seg.p.km_fim)}`;
    }
  }
  applyTrechoCardChrome(card, 0);
  setCardBind(card, "name", road);
  setCardBind(
    card,
    "subtitle",
    segLabel ? `Trecho ${segLabel}` : "Malha de apoio",
  );
  setCardBind(
    card,
    "note",
    "Esta rodovia integra a <strong>malha cartográfica de apoio</strong> "
    + "(área das quatro regiões), sem UA nem RA oficial. Indicadores de RD "
    + "disponíveis apenas em <strong>SP-055</strong> e <strong>SP-098</strong>.",
    { html: true },
  );
  fillIndicatorsChannel(card, "encosta", null, true);
  fillIndicatorsChannel(card, "inundacao", null, false);
  const sparkWrap = card.querySelector('[data-bind="sparkline"]');
  if (sparkWrap) sparkWrap.hidden = true;
  setCardBind(card, "footer", TRECHO_VALUE_PENDING, { hide: true });
}

function fillForecastCard(data, snap) {
  const card = document.getElementById("forecast-card");
  if (!card) return;

  if (state.trechoApoioId || isTrechoApoioRoad(snap)) {
    resetTrechoMetricCard(card, {
      note:
        "Previsão restrita às rodovias SP-055 e SP-098 (com UA). "
        + "Esta via constitui malha cartográfica de apoio.",
    });
    return;
  }

  const targetIds = resolveForecastTargetIds(snap);
  if (!targetIds.length) {
    resetTrechoMetricCard(card, {
      note:
        "Selecione região, rodovia e trecho — ou aguarde trecho em alerta.",
    });
    return;
  }

  const order = new Map(targetIds.map((id, i) => [id, i]));
  const comDados = (data?.forecast || [])
    .filter((f) => order.has(f.ua_id))
    .sort((a, b) => order.get(a.ua_id) - order.get(b.ua_id));
  const f = comDados[0];
  const hasGeo = f?.ac24h_forecast_mm != null;
  const hasHid = f?.ac6h_forecast_mm != null;

  if (!f || (!hasGeo && !hasHid)) {
    resetTrechoMetricCard(card, {
      note:
        "Previsão indisponível para "
        + (state.uaPickerId ? "o trecho selecionado" : "o trecho em alerta")
        + ".",
    });
    return;
  }

  const pair = snap ? getUaPair(snap, f.ua_id) : { geo: null, hid: null };
  const ref = pair.geo || pair.hid || f;
  const modeLabel = state.uaPickerId
    ? "Trecho selecionado"
    : "Trecho em alerta";

  applyTrechoCardChrome(card, 0);
  setCardBind(card, "name", uaLabel(ref) || ref.ua_id);
  setCardBind(
    card,
    "subtitle",
    `${ref.sigla_rodovia || "—"} · ${formatTrechoLabel(ref)} · ${
      ref.regiao_nome || "—"
    }`,
  );
  setCardBind(
    card,
    "note",
    "Previsão do modelo WRF (CPTEC/INPE) na UA do trecho "
    + "(+24 h canal geológico; +6 h canal hidrológico).",
  );
  pendingAllCardStats(card, "encosta");
  pendingAllCardStats(card, "inundacao");
  setCardLevel(card, "encosta-level", null);
  setCardLevel(card, "hidro-level", null);
  if (hasGeo) {
    setCardStat(
      card,
      "encosta",
      "fc24",
      f.ac24h_forecast_mm.toFixed(1),
      " mm",
    );
  }
  if (hasHid) {
    setCardStat(
      card,
      "inundacao",
      "fc6",
      f.ac6h_forecast_mm.toFixed(1),
      " mm",
    );
  }
  setCardBind(
    card,
    "footer",
    `${data?.source || "Previsão horária CPTEC/INPE"} · ${modeLabel}`,
  );
}

function fillRegionCard(regions, snap) {
  const card = document.getElementById("region-card");
  if (!card) return;

  if (state.trechoApoioId || isTrechoApoioRoad(snap)) {
    resetTrechoMetricCard(card, {
      note:
        "Sensibilidade K restrita a trechos-UA em SP-055 e SP-098. "
        + "Esta via constitui malha cartográfica de apoio.",
    });
    return;
  }

  const hlIds = snap ? resolveRegionHighlightIds(snap) : [];
  const activeId = hlIds[0];
  const activeReg = (regions || []).find(
    (r) => (r.regiao_id ?? r.id) === activeId,
  );
  const activeRegName = activeReg?.regiao_nome ?? activeReg?.nome;
  const ctx = snap ? resolveUaPickerContext(snap) : null;

  if (!activeReg && !ctx) {
    resetTrechoMetricCard(card, {
      note:
        "Selecione região, rodovia e trecho — ou aguarde trecho em alerta.",
    });
    return;
  }

  applyTrechoCardChrome(card, 0);
  const ref = ctx || {};
  setCardBind(
    card, "name", uaLabel(ref) || ref.ua_id || activeRegName || "—",
  );
  const subParts = [
    ref.sigla_rodovia ? escapeHtml(ref.sigla_rodovia) : null,
    ref.km_inicial != null
      ? `km ${formatTrechoKm(ref.km_inicial)}-${formatTrechoKm(ref.km_final)}`
      : null,
    ref.regiao_nome
      ? escapeHtml(ref.regiao_nome)
      : activeRegName
        ? escapeHtml(activeRegName)
        : null,
  ].filter(Boolean);
  setCardBind(card, "subtitle", subParts.join(" · ") || "—", { html: true });
  setCardBind(
    card,
    "note",
    "Sensibilidade K: valores menores indicam maior resposta da região "
    + "à precipitação acumulada (envoltória crítica).",
  );
  pendingAllCardStats(card, "encosta");
  setCardLevel(card, "encosta-level", null);
  if (activeReg) {
    setCardStat(card, "encosta", "k_geo", activeReg.k_geo);
    setCardStat(card, "encosta", "reg_id", activeReg.regiao_id ?? activeReg.id);
    setCardStat(card, "encosta", "reg_nome", activeRegName);
  }
  setCardBind(card, "footer", TRECHO_VALUE_PENDING, { hide: true });
}

// ============================================================================
// TRECHO MAIS CRÍTICO
// ============================================================================

function getUaPair(snap, id) {
  const { geo, hid } = snapshotPoints(snap);
  return {
    geo: geo.find((p) => p.ua_id === id) || null,
    hid: hid.find((p) => p.ua_id === id) || null,
  };
}

function resolveUaPickerContext(snap) {
  const id = resolvePanelUaId(snap);
  if (!id) return null;
  const pair = getUaPair(snap, id);
  return pair.geo || pair.hid;
}

function resolveRegionHighlightIds(snap) {
  if (state.trechoRegion) return [Number(state.trechoRegion)];
  const id = resolvePanelUaId(snap);
  if (!id) return [];
  const pair = getUaPair(snap, id);
  const ref = pair.geo || pair.hid;
  const rid = uaRegionId(ref);
  return rid != null ? [rid] : [];
}

function resolveForecastTargetIds(snap) {
  const id = resolvePanelUaId(snap);
  return id ? [id] : [];
}

function renderWorstUaPair(geo, hid) {
  fillIndicatorsCard(geo, hid);
}

function isTrechoApoioRoad(snap) {
  if (!state.trechoRoad || !snap) return false;
  const byRod = trechoIndexByRoad(snap);
  const regId = state.trechoRegion || "";
  return !filteredUaPoints(byRod, state.trechoRoad, regId).length;
}

function renderTrechoApoioCard() {
  fillApoioIndicatorsCard();
}

function renderWorst(snap, focal) {
  const card = document.getElementById("worst-card");
  if (!card) return;
  const status = (snap?.summary || {}).data_status;
  if (status === "loading") return;

  if (state.trechoApoioId || isTrechoApoioRoad(snap)) {
    renderTrechoApoioCard();
    return;
  }

  const panelId = resolvePanelUaId(snap);
  if (panelId) {
    const pair = getUaPair(snap, panelId);
    renderWorstUaPair(pair.geo, pair.hid);
    return;
  }

  const points = focal ?? resolveFocalPoints(snap);
  if (!points.length) {
    if (status === "no_data") return;
    resetTrechoMetricCard(card, {
      note: "Nenhum trecho acima de Monitoramento.",
    });
    return;
  }

  const pair = getUaPair(snap, points[0].ua_id);
  renderWorstUaPair(pair.geo, pair.hid);
}

function renderWorstPointBody(worst, withSparkline) {
  const levelTextColor = worst.rd === 1 ? "#0f172a" : "#ffffff";
  const levelBlink = shouldBlinkAlert(worst.rd) ? " worst-level--blink" : "";
  const wrapCls =
    withSparkline && (worst.history || []).length >= 2
      ? "worst-card"
      : "worst-card-item";
  const infoCls = " " + infoCardClassForRd(worst.rd);
  const blinkCls =
    shouldBlinkAlert(worst.rd) && !withSparkline ? " worst-card--blink" : "";
  const hazardTag =
    worst.hazard === "hidro"
      ? " · inundação"
      : worst.hazard === "geo"
        ? " · encosta"
        : "";
  return `
    <div class="${wrapCls}${infoCls}${blinkCls}" style="border-left-color:${infoAccentForRd(worst.rd)}">
      <div class="worst-name">${escapeHtml(uaLabel(worst))}</div>
      <div class="worst-rod">${escapeHtml(worst.sigla_rodovia || "")} · ${escapeHtml(formatTrechoLabel(worst))} · ${escapeHtml(worst.regiao_nome || "—")}${hazardTag}</div>
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
        <div class="worst-stat" title="Coeficiente de Precipitação Crítica (CPC)">
          <span>CPC</span><b>${worst.cpc !== null && worst.cpc !== undefined ? worst.cpc : "—"}</b>
        </div>
      </div>
      ${withSparkline ? renderWorstSparkline(worst.history || []) : ""}
    </div>`;
}

// ============================================================================
// REGIÕES (sidebar e mapa)
// ============================================================================

function renderRegions(regions, snap) {
  fillRegionCard(regions, snap);
}

function regionTooltipHtml(r) {
  const rid = r.regiao_id ?? r.id;
  const nome = r.regiao_nome ?? r.nome ?? "—";
  const rod = r.sigla_rodovia ?? r.rodovia ?? "—";
  const km = (r.km_inicial != null && r.km_final != null)
    ? `km ${formatTrechoKm(r.km_inicial)}–${formatTrechoKm(r.km_final)}`
    : null;
  const extKm = r.extensao_oficial_km != null
    ? `${Number(r.extensao_oficial_km).toFixed(1)} km (cadastral)`
    : null;
  const areaKm2 = r.area_km2 != null
    ? `${Number(r.area_km2).toFixed(1)} km²`
    : null;
  const municipios = r.municipios
    ? String(r.municipios).split(/;|,/).map((s) => s.trim()).filter(Boolean)
    : [];
  const residencias = r.residencias_dr
    ? String(r.residencias_dr).split(/;|,/).map((s) => s.trim()).filter(Boolean)
    : [];
  const conserva = r.conservado_por || null;
  const kGeo = r.k_geo != null ? r.k_geo : "—";

  const subParts = [escapeHtml(rod), km, extKm].filter(Boolean);
  const lines = [
    `<b>Região ${escapeHtml(String(rid))} · ${escapeHtml(nome)}</b>`,
    subParts.length ? `<small>${subParts.join(" · ")}</small>` : null,
    areaKm2 ? `<small>Área monitorada: ${areaKm2}</small>` : null,
    municipios.length
      ? `<small>Municípios: ${escapeHtml(municipios.join(", "))}</small>`
      : null,
    residencias.length
      ? `<small>Residências DR: ${escapeHtml(residencias.join(", "))}</small>`
      : null,
    conserva
      ? `<small>Conservado por: ${escapeHtml(conserva)}</small>`
      : null,
    `<small>Sensibilidade K: <b>${escapeHtml(String(kGeo))}`
      + `</b> (menor = reage mais cedo)</small>`,
  ].filter(Boolean);
  return lines.join("<br>");
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
    }).bindTooltip(regionTooltipHtml(r), { sticky: true });
    poly._pliLayerKind = "regions";
    poly._pliLayerProps = r;
    poly.on("click", (e) => {
      setPopupClickLatLng(e);
      L.DomEvent.stopPropagation(e);
    });
    poly.addTo(state.layers.regions);
    state.regionPolys.push(poly);
  });
}

// ============================================================================
// PONTOS DE MONITORAMENTO
// ============================================================================

function boundsFromGeometry(geometry) {
  if (!Array.isArray(geometry) || !geometry.length) return null;
  const b = L.latLngBounds([]);
  for (const pt of geometry) {
    if (!Array.isArray(pt) || pt.length < 2) continue;
    b.extend([pt[0], pt[1]]);
  }
  return b.isValid() ? b : null;
}

function boundsFromGeoJsonGeometry(geom) {
  if (!geom?.coordinates) return null;
  const b = L.latLngBounds([]);
  const extendCoords = (coords) => {
    if (typeof coords[0] === "number") {
      b.extend([coords[1], coords[0]]);
      return;
    }
    coords.forEach(extendCoords);
  };
  extendCoords(geom.coordinates);
  return b.isValid() ? b : null;
}

function restoreTrechoMarkerStyle(markerKey) {
  const p = state.pointData.get(markerKey);
  const markers = state.pointMarkers.get(markerKey);
  if (!p || !markers) return;
  const hazardKey = markerKey.split(":")[1] || "encosta";
  const h = HAZARDS[hazardKey];
  const isNoData = p.source === "NO_DATA";
  const isPoly = p.geometry_type === "polygon" && p.geometry?.length >= 3;
  const rd = isNoData ? null : h?.rdFrom(p);
  const color = rd == null ? "#64748b" : h.palette[rd] || "#64748b";
  const blinkCls = shouldBlinkAlert(rd) ? " ua-alert-blink" : "";
  const style = {
    color,
    weight: isPoly ? 2 : 5,
    opacity: 0.9,
    fillColor: color,
    fillOpacity: isPoly ? 0.55 : 0,
    className: (isPoly ? "ua-polygon" : "ua-polyline") + blinkCls,
  };
  markers.forEach((m) => m.setStyle(style));
}

function clearTrechoMapFocus() {
  if (state.trechoFocus.overlay) {
    state.map.removeLayer(state.trechoFocus.overlay);
    state.trechoFocus.overlay = null;
  }
  for (const key of state.trechoFocus.markerKeys) {
    restoreTrechoMarkerStyle(key);
  }
  state.trechoFocus.markerKeys = [];
}

function clearUaClickFocus() {
  if (state.uaClickFocus?.halo && state.map) {
    state.map.removeLayer(state.uaClickFocus.halo);
  }
  state.uaClickFocus = { markerKey: null, halo: null };
}

function applyUaClickFocus(markerKey) {
  clearUaClickFocus();
  const p = state.pointData.get(markerKey);
  if (!p || !Array.isArray(p.geometry) || p.geometry.length < 2) return;
  if (!state.map) return;
  const isPoly = p.geometry_type === "polygon" && p.geometry.length >= 3;
  const baseOpts = {
    color: "#22d3ee",
    interactive: false,
    className: "ua-click-halo",
  };
  const halo = isPoly
    ? L.polygon(p.geometry, {
        ...baseOpts,
        weight: 9,
        opacity: 0.55,
        fillColor: "#22d3ee",
        fillOpacity: 0,
      })
    : L.polyline(p.geometry, {
        ...baseOpts,
        weight: 14,
        opacity: 0.45,
      });
  halo.addTo(state.map);
  halo.bringToBack();
  state.uaClickFocus = { markerKey, halo };
}

function applyTrechoUaFocus(uaId, { zoom = true } = {}) {
  const bounds = L.latLngBounds([]);
  ["encosta", "inundacao"].forEach((hazardKey) => {
    const markerKey = `${uaId}:${hazardKey}`;
    const markers = state.pointMarkers.get(markerKey);
    const p = state.pointData.get(markerKey);
    if (!markers?.length || !p) return;
    const h = HAZARDS[hazardKey];
    const isNoData = p.source === "NO_DATA";
    const isPoly = p.geometry_type === "polygon" && p.geometry?.length >= 3;
    const rd = isNoData ? null : h?.rdFrom(p);
    const color = rd == null ? "#64748b" : h.palette[rd] || "#64748b";
    const blinkCls = shouldBlinkAlert(rd) ? " ua-alert-blink" : "";
    markers.forEach((m) => {
      m.setStyle({
        color: "#fde047",
        weight: isPoly ? 4 : 7,
        opacity: 1,
        fillColor: color,
        fillOpacity: isPoly ? 0.8 : 0,
        className:
          (isPoly ? "ua-polygon ua-trecho-focus" : "ua-polyline ua-trecho-focus")
          + blinkCls,
      });
      m.bringToFront?.();
    });
    state.trechoFocus.markerKeys.push(markerKey);
    const gb = boundsFromGeometry(p.geometry);
    if (gb) bounds.extend(gb);
  });
  if (zoom && bounds.isValid()) {
    state.map.fitBounds(bounds.pad(0.4), { maxZoom: 14, animate: true });
  }
}

function applyTrechoApoioFocus({ zoom = true } = {}) {
  if (!state.trechoApoioId?.startsWith("apoio:")) return;
  const idx = Number(state.trechoApoioId.split(":")[1]);
  const segs = malhaTrechosForRoad(state.trechoRoad, state.trechoRegion);
  const seg = segs[idx];
  if (!seg) return;
  const feat = (state.roadGeoJSON?.features || []).find((f) => {
    const fp = f.properties || {};
    return fp.monitored
      && fp.rodovia === seg.p.rodovia
      && fp.km_ini === seg.p.km_ini
      && fp.km_fim === seg.p.km_fim;
  });
  if (!feat) return;
  state.trechoFocus.overlay = L.geoJSON(feat, {
    style: {
      color: "#fde047",
      weight: 7,
      opacity: 1,
    },
  }).addTo(state.map);
  const gb = boundsFromGeoJsonGeometry(feat.geometry);
  if (zoom && gb) {
    state.map.fitBounds(gb.pad(0.35), { maxZoom: 14, animate: true });
  }
}

function trechoFocusKey(snap) {
  if (state.trechoApoioId?.startsWith("apoio:")) return state.trechoApoioId;
  if (snap && state.trechoRoad && isTrechoApoioRoad(snap)) return "";
  const uaId = state.uaPickerId || resolvePanelUaId(snap);
  return uaId ? `ua:${uaId}` : "";
}

function updateTrechoMapFocus(snap, { zoom } = {}) {
  if (!state.map || state.timeline.active) return;
  const key = trechoFocusKey(snap);
  const shouldZoom = zoom ?? key !== state.trechoFocus.lastKey;
  clearTrechoMapFocus();
  if (!key) {
    state.trechoFocus.lastKey = "";
    return;
  }
  state.trechoFocus.lastKey = key;
  if (key.startsWith("apoio:")) {
    applyTrechoApoioFocus({ zoom: shouldZoom });
    return;
  }
  applyTrechoUaFocus(key.slice(3), { zoom: shouldZoom });
}

function renderPointsOnMap(snap) {
  const groups = state.layers.hazardZones || {};
  Object.values(groups).forEach((g) => g.clearLayers());
  state.pointMarkers.clear();
  state.pointData.clear();
  // Halo de clique fica orfao se a UA foi removida; limpa por seguranca
  clearUaClickFocus();

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
      if (window.QueryFilter && !QueryFilter.matchUa(hazardKey, p)) return;
      const markerKey = `${p.ua_id}:${hazardKey}`;
      state.pointData.set(markerKey, p);
      if (!Array.isArray(p.geometry) || p.geometry.length < 2) return;

      const isNoData = p.source === "NO_DATA";
      const isPoly = p.geometry_type === "polygon" && p.geometry.length >= 3;
      const rd = isNoData ? null : h.rdFrom(p);
      const color = rd == null ? "#64748b" : h.palette[rd] || "#64748b";
      const blinkCls = shouldBlinkAlert(rd) ? " ua-alert-blink" : "";
      const pathClass = (isPoly ? "ua-polygon" : "ua-polyline") + blinkCls;
      const style = {
        color,
        weight: isPoly ? 2 : 5,
        opacity: 0.9,
        fillColor: color,
        fillOpacity: isPoly ? 0.55 : 0,
        className: pathClass,
      };
      const layer = isPoly
        ? L.polygon(p.geometry, style).bindPopup(buildPopup(p, hazardKey), {
            className: "ua-popup-wrap",
            maxWidth: 360,
            minWidth: 280,
          })
        : L.polyline(p.geometry, style).bindPopup(buildPopup(p, hazardKey), {
            className: "ua-popup-wrap",
            maxWidth: 360,
            minWidth: 280,
          });
      // Click destaca o vetor da UA com um halo (separado do focus
      // disparado por seletor da sidebar - aquele e amarelo no proprio
      // stroke; este e um halo ciano por baixo, mantendo a cor da RD).
      layer.on("click", (e) => {
        setPopupClickLatLng(e);
        L.DomEvent.stopPropagation(e);
        applyUaClickFocus(markerKey);
      });
      layer._pliLayerKind = hazardKey;
      layer._pliLayerProps = p;
      layer.addTo(g);
      state.pointMarkers.set(markerKey, [layer]);
    });
  });
  syncInteractiveLayerOrder();
  updateTrechoMapFocus(snap);
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

function formatKmiKmf(kmIni, kmFim) {
  const a = kmIni != null && kmIni !== "" ? formatKm(kmIni) : "—";
  const b = kmFim != null && kmFim !== "" ? formatKm(kmFim) : "—";
  return `${a} - ${b}`;
}

function formatCodeName(code, name, sep = " - ") {
  const c = fixText(code);
  const n = fixText(name);
  if (c && n && c !== n) return `${escapeHtml(c)}${sep}${escapeHtml(n)}`;
  return escapeHtml(c || n || "—");
}

function hexToRgba(hex, alpha) {
  const raw = String(hex || "").replace("#", "");
  if (raw.length !== 6) return `rgba(100, 116, 139, ${alpha})`;
  const r = parseInt(raw.slice(0, 2), 16);
  const g = parseInt(raw.slice(2, 4), 16);
  const b = parseInt(raw.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function popupRiskStyle(color) {
  const c = color || "#64748b";
  return `--popup-risk-color:${c};--popup-risk-bg:${hexToRgba(c, 0.10)};`;
}

function unifiedLayersButtonHtml() {
  return `
    <button type="button" class="ua-popup-all-layers js-unified-layers"
            title="Mostrar informações de todas as camadas"
            aria-label="Mostrar informações de todas as camadas">
      <span aria-hidden="true">▣</span>
      <span>Mostrar informações de todas as camadas</span>
    </button>`;
}

function flattenLatLngLines(latlngs) {
  if (!Array.isArray(latlngs) || !latlngs.length) return [];
  if (latlngs[0]?.lat != null) return [latlngs];
  return latlngs.flatMap((part) => flattenLatLngLines(part));
}

function pointInRing(latlng, ring) {
  let inside = false;
  const x = latlng.lng;
  const y = latlng.lat;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i].lng;
    const yi = ring[i].lat;
    const xj = ring[j].lng;
    const yj = ring[j].lat;
    const intersect = ((yi > y) !== (yj > y))
      && (x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-12) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function distanceToSegmentPx(p, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (dx === 0 && dy === 0) return p.distanceTo(a);
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (
    dx * dx + dy * dy
  )));
  return p.distanceTo(L.point(a.x + t * dx, a.y + t * dy));
}

function distanceToLatLngLinePx(latlng, line) {
  const p = state.map.latLngToLayerPoint(latlng);
  let best = Infinity;
  for (let i = 1; i < line.length; i++) {
    const a = state.map.latLngToLayerPoint(line[i - 1]);
    const b = state.map.latLngToLayerPoint(line[i]);
    best = Math.min(best, distanceToSegmentPx(p, a, b));
  }
  return best;
}

function layerContainsLatLng(layer, latlng, tolerancePx = 10) {
  if (!layer || !latlng) return false;
  if (layer.getBounds && !layer.getBounds().pad(0.01).contains(latlng)) {
    return false;
  }
  if (!layer.getLatLngs) return false;
  const lines = flattenLatLngLines(layer.getLatLngs());
  if (layer instanceof L.Polygon) {
    return lines.some((ring) => pointInRing(latlng, ring));
  }
  return lines.some((line) => distanceToLatLngLinePx(latlng, line) <= tolerancePx);
}

function setPopupClickLatLng(e) {
  if (e?.latlng) state.lastPopupLatLng = e.latlng;
}

function raClassLabel(hazardKey, p) {
  const isGeo = hazardKey === "encosta" || p.hazard === "geo";
  const ra = isGeo ? p.RAGEO : p.RAHID;
  const kind = isGeo ? "geológico" : "hidrológico";
  if (ra === null || ra === undefined) {
    return `RA ${kind} = sem dado`;
  }
  return `RA ${kind} = ${ra}`;
}

function popupHeaderHtml(p, hazardKey) {
  const title = hazardKey === "inundacao"
    ? "Risco de Inundação"
    : "Risco de Movimentos de Massa";
  return `
    <header class="ua-popup-header">
      <div class="ua-popup-risk">${escapeHtml(title)}</div>
    </header>`;
}

function popupRainRows(p, hazardKey) {
  const isGeo = hazardKey === "encosta" || p.hazard === "geo";
  if (isGeo) {
    const prev = p.prev24h_mm;
    const obs = p.ac72h_obs_mm ?? p.ac72h_mm;
    return `
      <tr><th>Chuva prevista próximas 24 horas</th><td>${formatNum(prev)} mm</td></tr>
      <tr><th>Chuva acumulada nas últimas 72 horas</th><td>${formatNum(obs)} mm</td></tr>
      <tr>
        <th><span class="coef-label">Coeficiente de Precipitação Crítica (CPC)</span></th>
        <td>${formatNum(obs)} mm obs. + ${formatNum(prev)} mm prev. = ${formatNum(p.ac96h_mm)} mm</td>
      </tr>`;
  }
  const prev = p.prev6h_mm;
  const obs = p.ac18h_obs_mm ?? p.ac18h_mm;
  return `
    <tr><th>Chuva prevista próximas 6 horas</th><td>${formatNum(prev)} mm</td></tr>
    <tr><th>Chuva acumulada nas últimas 18 horas</th><td>${formatNum(obs)} mm</td></tr>
    <tr>
      <th><span class="coef-label">Índice de Correlação com Chuvas hidrológico (ICCHID)</span></th>
      <td>${formatNum(obs)} mm obs. + ${formatNum(prev)} mm prev. = ${formatNum(p.ac24h_mm)} mm</td>
    </tr>`;
}

function formatUbaDisplay(p) {
  const code = fixText(p.uba_codigo);
  const nome = fixText(p.uba_nome);
  return formatCodeName(code, nome);
}

function popupDerSection(p) {
  const rod = fixText(p.sigla_rodovia || p.rodovia || "—");
  const trecho = formatKmiKmf(p.km_inicial ?? p.km_ini, p.km_final ?? p.km_fim);
  const regional = fixText(p.regional);
  const dr = fixText(p.residencia_dr);
  const regionalDisplay = formatCodeName(dr, regional);
  const residenciaDisplay = formatCodeName(dr, regional);
  const uba = formatUbaDisplay(p);
  const municipio = fixText(p.municipio);
  const jurisdicao = fixText(p.jurisdicao);
  const conserv = fixText(p.conservado_por);
  const conservDisplay = formatCodeName(conserv, p.uba_nome || regional);
  return `
    <table class="modal-table ua-popup-table">
      <tr><th>Rodovia</th><td><b>${escapeHtml(rod)}</b></td></tr>
      <tr><th>Trecho (kmi - kmf)</th><td>${escapeHtml(trecho)}</td></tr>
      <tr>
        <th>Sede Regional DER</th>
        <td><b>${regionalDisplay}</b></td>
      </tr>
      <tr>
        <th>Residência DER</th>
        <td><b>${residenciaDisplay}</b></td>
      </tr>
      <tr>
        <th>UBA (atendimento)</th>
        <td><b>${uba}</b></td>
      </tr>
      <tr><th>Município</th><td>${escapeHtml(municipio || "—")}</td></tr>
      <tr><th>Jurisdição</th><td>${escapeHtml(jurisdicao || "—")}</td></tr>
      <tr><th>Conservado por</th><td>${conservDisplay}</td></tr>
    </table>`;
}

function buildPopup(p, hazardKey, options = {}) {
  const includeUnifiedButton = options.includeUnifiedButton !== false;
  const isNoData = p.source === "NO_DATA";
  const header = popupHeaderHtml(p, hazardKey);

  if (isNoData) {
    const ndColor = "#64748b";
    return `
      <div class="ua-popup" style="${popupRiskStyle(ndColor)}">
        ${header}
        <div class="ua-popup-body">
          <div class="ua-popup-meta"><b>Classificação trecho</b></div>
          <div class="ua-popup-level ua-popup-level--nd">Sem dado disponível</div>
          <div class="ua-popup-meta"><b>Informações cadastrais:</b></div>
          ${popupDerSection(p)}
          <p class="ua-popup-foot">Fonte MERGE/INPE indisponível neste ciclo.</p>
          ${includeUnifiedButton ? unifiedLayersButtonHtml() : ""}
        </div>
      </div>`;
  }

  const levelTextColor = p.rd === 1 ? "#0f172a" : "#ffffff";
  const palette = HAZARDS[hazardKey]?.palette || NIVEL_COLOR;
  const isGeo = hazardKey === "encosta" || p.hazard === "geo";
  const iccRow = isGeo
    ? `<tr><th><span class="coef-label">Índice de Correlação com Chuvas geológico (ICCGEO)</span></th><td>${formatNum(p.icc_geo, 0)}</td></tr>`
    : `<tr><th><span class="coef-label">Índice de Correlação com Chuvas hidrológico (ICCHID)</span></th><td>${formatNum(p.icc_hid, 0)}</td></tr>`;
  const warnWrf =
    p.fonte_chuva === "OBS_ONLY"
      ? `<p class="ua-popup-note">Previsão WRF indisponível — cálculo usa só chuva observada (pode subestimar).</p>`
      : "";

  return `
    <div class="ua-popup" style="${popupRiskStyle(palette[p.rd])}">
      ${header}
      <div class="ua-popup-body">
        <div class="ua-popup-meta"><b>Classificação trecho</b></div>
        <div class="ua-popup-level"
             style="background:${palette[p.rd]};color:${levelTextColor}">
          Nível ${p.rd} — ${NIVEL_LABEL[p.rd]}
        </div>
        <div class="ua-popup-meta"><b>Informações cadastrais:</b></div>
        ${popupDerSection(p)}
        <div class="ua-popup-meta"><b>Informações do risco:</b></div>
        <table class="modal-table ua-popup-table">
          ${popupRainRows(p, hazardKey)}
          <tr><th>Intensidade observada</th><td>${formatNum(p.intensity_mmh)} mm/h</td></tr>
          <tr><th><span class="coef-label">Coeficiente de Precipitação Crítica (CPC)</span></th><td>${p.cpc !== null ? formatNum(p.cpc) : "—"}</td></tr>
          ${iccRow}
        </table>
        ${warnWrf}
        ${includeUnifiedButton ? unifiedLayersButtonHtml() : ""}
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
    const rdComp = p.rd / 4.0; // 0..1
    const rainComp = Math.min(p.ac96h_mm / 200.0, 1.0); // 0..1
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

// Pesos por nivel — legenda das UAs (malha rodoviaria nao usa mais escala RD)
const ROAD_WEIGHTS = [4.0, 4.5, 5.0, 5.5, 6.0];

/**
 * Malha Rodoviaria Estadual: referencia cartografica neutra.
 * Alertas visuais ficam nas UAs.
 */
function styleForRoadFeature(props) {
  if (!props?.monitored) return ROAD_UNMONITORED_STYLE;
  return ROAD_SUPPORT_STYLE;
}

async function loadRoadNetwork() {
  try {
    const stats = normalizeRoadStats(
      await (await fetch(apiUrl("/api/road-stats"))).json(),
    );
    populateFilterDropdowns(stats);

    const gj = await (await fetch(apiUrl("/api/road-network"))).json();
    state.roadGeoJSON = normalizeRoadGeoJSON(gj);
    renderRoadsOnMap();
    if (state.lastSnapshot) {
      rebuildTrechoPickers(state.lastSnapshot);
    }
  } catch (e) {
    console.error("Erro ao carregar malha:", e);
  }
}

// ============================================================================
// LIMITES ADMINISTRATIVOS (municipios, RC, UBA, CGR)
// ============================================================================

const ADMIN_LAYERS = {
  municipios: {
    file: "/static/data/municipios.geojson",
    style: {
      color: "#475569",
      weight: 0.5,
      opacity: 0.45,
      fill: false,
      interactive: false,
    },
  },
  rc: {
    file: "/static/data/rc_poligonos.geojson",
    style: {
      color: "#7c3aed",
      weight: 1.2,
      opacity: 0.7,
      fillColor: "#7c3aed",
      fillOpacity: 0.04,
      interactive: false,
    },
  },
  uba: {
    file: "/static/data/uba_poligonos.geojson",
    style: {
      color: "#0d9488",
      weight: 1.4,
      opacity: 0.8,
      fill: false,
      interactive: false,
    },
  },
  cgr: {
    file: "/static/data/cgr_poligonos.geojson",
    style: {
      color: "#b45309",
      weight: 1.8,
      opacity: 0.85,
      fill: false,
      interactive: false,
    },
  },
};

const adminLoaded = new Set();

async function loadAdminLayer(key) {
  if (adminLoaded.has(key)) return;
  const cfg = ADMIN_LAYERS[key];
  if (!cfg) return;
  try {
    const gj = await (await fetch(apiUrl(cfg.file))).json();
    L.geoJSON(gj, {
      style: cfg.style,
      onEachFeature: (feat, layer) => {
        layer._pliLayerKind = key;
        layer._pliLayerProps = feat.properties || {};
        layer.on("click", (e) => {
          setPopupClickLatLng(e);
          L.DomEvent.stopPropagation(e);
        });
      },
    }).addTo(state.layers[key]);
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
      MAP_LAYER_STATE[key] = e.target.checked;
      saveMapLayerState();
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
  const rodovias =
    stats.rodovias_unicas ??
    (Array.isArray(stats.rodovias) ? stats.rodovias.length : 0);
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
  if (window.QueryFilter) {
    QueryFilter.setRoadEnums(normalizeRoadStats(stats));
  }
}

function renderRoadsOnMap() {
  if (!state.roadGeoJSON) return;
  state.layers.roads.clearLayers();

  const useAdvanced = window.QueryFilter?.hasActiveRules?.();
  const filtered = {
    type: "FeatureCollection",
    features: state.roadGeoJSON.features.filter((feat) => {
      const p = feat.properties || {};
      if (useAdvanced) return QueryFilter.matchRoad(p);
      const f = state.roadFilters;
      if (f.tipo_pista && p.tipo_pista !== f.tipo_pista) return false;
      if (f.regional && p.regional !== f.regional) return false;
      if (f.administra && p.administra !== f.administra) return false;
      if (f.rodovia) {
        const q = f.rodovia.toLowerCase();
        if (!(p.rodovia || "").toLowerCase().includes(q)) return false;
      }
      return true;
    }),
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
      layer._pliLayerKind = "roads";
      layer._pliLayerProps = p;
      layer.on("click", (e) => {
        setPopupClickLatLng(e);
        L.DomEvent.stopPropagation(e);
      });
      layer.on("mouseover", () =>
        layer.setStyle({
          ...baseStyle,
          weight: (baseStyle.weight || 2) + 2,
          opacity: 1,
        }),
      );
      layer.on("mouseout", () => layer.setStyle(baseStyle));
    },
  });
  gj.addTo(state.layers.roads);
  syncInteractiveLayerOrder();
}

const FIRE_RISK_COLORS = {
  minimo: "#2aa358",
  baixo: "#a3d977",
  medio: "#f1c40f",
  alto: "#e67e22",
  critico: "#7f1d1d",
  SEM_DADO: "#94a3b8",
};
const FIRE_RISK_LABELS = {
  minimo: "Mínimo",
  baixo: "Baixo",
  medio: "Médio",
  alto: "Alto",
  critico: "Crítico",
  SEM_DADO: "Sem dado",
};
const FIRE_RISK_ORDER = ["minimo", "baixo", "medio", "alto", "critico"];

function fireRiskClassLabel(cls) {
  return FIRE_RISK_LABELS[cls] || fixText(cls || "Sem dado");
}

function fireRiskTextColor(cls) {
  return cls === "baixo" || cls === "medio" ? "#0f172a" : "#ffffff";
}

function formatRfScore(value) {
  const txt = formatNum(value, 2);
  return txt === "—" ? "—" : `${txt} de 1`;
}

function formatDateOnlyBR(value) {
  if (!value) return "—";
  const text = String(value);
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (match) return `${match[3]}/${match[2]}/${match[1]}`;
  const d = new Date(text);
  if (Number.isNaN(d.getTime())) return fixText(text);
  return d.toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  });
}

function styleForFireRiskFeature(props) {
  const cls = props?.rf_classe || "SEM_DADO";
  return {
    color: FIRE_RISK_COLORS[cls] || FIRE_RISK_COLORS.SEM_DADO,
    weight: cls === "critico" ? 4.5 : 3.2,
    opacity: cls === "SEM_DADO" ? 0.45 : 0.92,
  };
}

function fireRiskPopupHtml(props, options = {}) {
  const includeUnifiedButton = options.includeUnifiedButton !== false;
  const cls = props?.rf_classe || "SEM_DADO";
  const color = FIRE_RISK_COLORS[cls] || FIRE_RISK_COLORS.SEM_DADO;
  const label = fireRiskClassLabel(cls);
  const rod = fixText(props?.rodovia || props?.sigla_rodovia || "Trecho DER");
  const km = formatKmiKmf(
    props?.km_ini ?? props?.km_inicial,
    props?.km_fim ?? props?.km_final,
  );
  const sedeRegional = fixText(props?.sede_regional || props?.regional);
  const residencia = fixText(props?.residencia_dr || props?.residencia);
  const sedeRegionalDisplay = formatCodeName(residencia, sedeRegional);
  const residenciaDisplay = formatCodeName(residencia, sedeRegional);
  const uba = formatUbaDisplay(props);
  const municipio = fixText(props?.municipio);
  const jurisdicao = fixText(props?.jurisdicao);
  const conservado = fixText(props?.conservado_por || props?.conservado);
  const horizonte = fixText(props?.horizonte || state.fireRiskHorizon || "observado");
  const dataRef = formatDateOnlyBR(props?.data_referencia);
  const metodologia = fixText(props?.metodologia || "INPE-RF-v11");
  return `
    <div class="ua-popup ua-popup--fire" style="${popupRiskStyle(color)}">
      <header class="ua-popup-header">
        <div class="ua-popup-risk">
          Risco de Fogo por Trecho Rodoviário
        </div>
      </header>
      <div class="ua-popup-body">
        <div class="ua-popup-meta"><b>Classificação trecho</b></div>
        <div class="ua-popup-level"
             style="background:${color};color:${fireRiskTextColor(cls)}">
          ${escapeHtml(label)}
        </div>
        <div class="ua-popup-meta"><b>Informações cadastrais:</b></div>
        <table class="modal-table ua-popup-table">
          <tr><th>Rodovia</th><td><b>${escapeHtml(rod)}</b></td></tr>
          <tr><th>Trecho (kmi - kmf)</th><td>${escapeHtml(km)}</td></tr>
          <tr><th>Sede Regional DER</th><td>${sedeRegionalDisplay}</td></tr>
          <tr><th>Residência DER</th><td>${residenciaDisplay}</td></tr>
          <tr><th>UBA (atendimento)</th><td>${uba}</td></tr>
          <tr><th>Município</th><td>${escapeHtml(municipio || "—")}</td></tr>
          <tr><th>Jurisdição</th><td>${escapeHtml(jurisdicao || "—")}</td></tr>
          <tr><th>Conservado por</th><td>${formatCodeName(conservado, props?.uba_nome || sedeRegional)}</td></tr>
        </table>
        <div class="ua-popup-meta"><b>Informações do risco:</b></div>
        <table class="modal-table ua-popup-table">
          <tr><th>Risco medido</th><td>${formatRfScore(props?.rf_valor)}</td></tr>
          <tr><th>Horizonte</th><td>${escapeHtml(horizonte)}</td></tr>
          <tr><th>Data da geração do risco</th><td>${escapeHtml(dataRef)}</td></tr>
        </table>
        <p class="ua-popup-note">
          RF significa <b>Risco de Fogo</b>. A escala vai de 0 a 1:
          quanto mais perto de 1, maior a condição ambiental favorável
          à ignição e propagação do fogo na vegetação.
        </p>
        <p class="ua-popup-note">
          Produto oficial INPE, agregado ao trecho rodoviário. Resolução
          efetiva da fonte: ~10 km. Metodologia: ${escapeHtml(metodologia)}.
        </p>
        ${includeUnifiedButton ? unifiedLayersButtonHtml() : ""}
      </div>
    </div>`;
}

async function loadFireRiskLayer(horizonte = state.fireRiskHorizon) {
  const horizon = horizonte || "observado";
  state.fireRiskHorizon = horizon;
  if (state.fireRiskGeoJSON[horizon]) {
    renderFireRiskLayer();
    return;
  }
  try {
    const url = apiUrl(
      "/api/public/fire-risk/layers?horizonte=" +
      encodeURIComponent(horizon),
    );
    const gj = await (await fetch(url)).json();
    state.fireRiskGeoJSON[horizon] = gj;
    renderFireRiskLayer();
  } catch (e) {
    console.warn("falha ao carregar risco de queimadas:", e);
  }
}

const FIRE_SUMMARY_ORDER = [...FIRE_RISK_ORDER, "SEM_DADO"];

async function loadFireRiskSnapshot() {
  const box = document.getElementById("fire-summary");
  if (!box) return;
  // Fonte leve (~0,5 KB) com o mesmo resumo do snapshot. Cai para o
  // endpoint publico se o estatico nao estiver presente.
  const sources = [
    apiUrl("/static/data/queimadas/risco_trechos_der_stats.json"),
    apiUrl("/api/public/fire-risk/snapshot"),
  ];
  for (const url of sources) {
    try {
      const res = await fetch(url);
      if (!res.ok) continue;
      const snap = await res.json();
      if (snap && snap.total_trechos) {
        renderFireRiskSummary(snap);
        return;
      }
    } catch (e) {
      console.warn("panorama de risco de fogo:", url, e);
    }
  }
  box.innerHTML =
    '<p class="fire-summary-loading">Panorama indisponível no momento.</p>';
}

function renderFireRiskSummary(snap) {
  const box = document.getElementById("fire-summary");
  if (!box) return;
  const classes = (snap && snap.classes) || {};
  const total = Number(snap?.total_trechos) || 0;
  const semDado = Number(classes.SEM_DADO) || 0;
  const avaliados = Math.max(total - semDado, 0);
  if (!total) {
    box.innerHTML =
      '<p class="fire-summary-loading">Sem produto de fogo publicado.</p>';
    return;
  }
  const maxCount = FIRE_SUMMARY_ORDER.reduce(
    (m, cls) => Math.max(m, Number(classes[cls]) || 0),
    0,
  ) || 1;
  const rows = FIRE_SUMMARY_ORDER.map((cls) => {
    const count = Number(classes[cls]) || 0;
    const pct = total ? Math.round((count / total) * 100) : 0;
    const width = Math.round((count / maxCount) * 100);
    const color = FIRE_RISK_COLORS[cls] || FIRE_RISK_COLORS.SEM_DADO;
    return `
      <div class="fire-sum-row">
        <span class="fire-sum-label">
          <span class="fire-sum-dot" style="background:${color}"></span>
          ${escapeHtml(fireRiskClassLabel(cls))}
        </span>
        <span class="fire-sum-track">
          <span class="fire-sum-bar"
                style="width:${width}%;background:${color}"></span>
        </span>
        <span class="fire-sum-count">
          ${count.toLocaleString("pt-BR")}
          <small>${pct}%</small>
        </span>
      </div>`;
  }).join("");
  box.innerHTML = `
    <div class="fire-sum-head">
      <div class="fire-sum-stat">
        <span class="fire-sum-stat-num">${avaliados.toLocaleString("pt-BR")}</span>
        <span class="fire-sum-stat-lbl">trechos com risco</span>
      </div>
      <div class="fire-sum-stat">
        <span class="fire-sum-stat-num">${total.toLocaleString("pt-BR")}</span>
        <span class="fire-sum-stat-lbl">trechos no Estado</span>
      </div>
    </div>
    <div class="fire-sum-bars">${rows}</div>
    <p class="fire-sum-foot">
      Produto observado · referência ${escapeHtml(
        formatDateOnlyBR(snap?.data_referencia),
      )}
    </p>`;
}

function renderFireRiskLayer() {
  const gj = state.fireRiskGeoJSON[state.fireRiskHorizon];
  if (!gj || !state.layers.fireRisk) return;
  state.layers.fireRisk.clearLayers();
  L.geoJSON(gj, {
    filter: (feat) => (
      !window.QueryFilter
      || window.QueryFilter.matchFireRisk(feat.properties || {})
    ),
    style: (feat) => styleForFireRiskFeature(feat.properties || {}),
    onEachFeature: (feat, layer) => {
      const p = feat.properties || {};
      const baseStyle = styleForFireRiskFeature(p);
      layer.bindPopup(fireRiskPopupHtml(p), {
        className: "ua-popup-wrap",
        maxWidth: 360,
      });
      layer._pliLayerKind = "fireRisk";
      layer._pliLayerProps = p;
      layer.on("click", (e) => {
        setPopupClickLatLng(e);
        L.DomEvent.stopPropagation(e);
      });
      layer.on("mouseover", () =>
        layer.setStyle({
          ...baseStyle,
          weight: (baseStyle.weight || 3) + 2,
          opacity: 1,
        }),
      );
      layer.on("mouseout", () => layer.setStyle(baseStyle));
    },
  }).addTo(state.layers.fireRisk);
  syncInteractiveLayerOrder();
}

function bringGroupToFront(group) {
  group?.eachLayer?.((layer) => {
    if (layer.bringToFront) layer.bringToFront();
  });
}

function bringGroupToBack(group) {
  group?.eachLayer?.((layer) => {
    if (layer.bringToBack) layer.bringToBack();
  });
}

function syncInteractiveLayerOrder() {
  // Ordem do painel: encosta, inundação, Risco de Fogo, apoio.
  // Como `bringToFront` coloca por cima, aplicamos de baixo para cima.
  bringGroupToBack(state.layers.roads);
  bringGroupToBack(state.layers.fireRisk);
  bringGroupToFront(state.layers.fireRisk);
  bringGroupToFront(state.layers.hazardZones?.inundacao);
  bringGroupToFront(state.layers.hazardZones?.encosta);
}

function firstHitInGroup(group, latlng) {
  let hit = null;
  group?.eachLayer?.((layer) => {
    if (hit) return;
    if (layerContainsLatLng(layer, latlng)) {
      hit = layer;
      return;
    }
    if (layer.eachLayer) {
      hit = firstHitInGroup(layer, latlng);
    }
  });
  return hit;
}

function adminLayerTitle(key) {
  return {
    municipios: "Municípios (IGC, 2021)",
    rc: "Residência de Conserva - DER",
    uba: "Unidade Básica de Atendimento - DER",
    cgr: "Coordenadoria Geral Regional - DER",
  }[key] || key;
}

function simplePropsTable(props, keys) {
  const rows = keys
    .map(([key, label]) => {
      const value = props?.[key];
      if (value == null || value === "") return "";
      return `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(fixText(value))}</td></tr>`;
    })
    .filter(Boolean)
    .join("");
  return rows
    ? `<table class="modal-table ua-popup-table">${rows}</table>`
    : '<p class="ua-popup-note">Sem atributos disponíveis para esta camada.</p>';
}

function roadLayerInfoHtml(props) {
  return `
    <div class="ua-popup-meta"><b>Malha Rodoviária Estadual</b></div>
    ${simplePropsTable(props, [
      ["rodovia", "Rodovia"],
      ["km_ini", "Km inicial"],
      ["km_fim", "Km final"],
      ["municipio", "Município"],
      ["regional", "Regional DER"],
      ["administra", "Administração"],
      ["conservado", "Conservado por"],
      ["jurisdicao", "Jurisdição"],
    ])}`;
}

function regionLayerInfoHtml(props) {
  return `
    <div class="ua-popup-meta"><b>Região monitorada</b></div>
    ${simplePropsTable(props, [
      ["regiao_id", "Região"],
      ["regiao_nome", "Nome"],
      ["sigla_rodovia", "Rodovia"],
      ["km_inicial", "Km inicial"],
      ["km_final", "Km final"],
      ["municipios", "Municípios"],
      ["residencias_dr", "Residências DER"],
      ["k_geo", "Sensibilidade K"],
    ])}`;
}

function genericAdminInfoHtml(key, props) {
  return `
    <div class="ua-popup-meta"><b>${escapeHtml(adminLayerTitle(key))}</b></div>
    ${simplePropsTable(props, Object.keys(props || {})
      .filter((k) => k !== "geometry")
      .slice(0, 8)
      .map((k) => [k, k]))}`;
}

function collectLayerInfosAt(latlng) {
  const entries = [];
  for (const key of ["encosta", "inundacao"]) {
    if (!HAZARD_STATE[key]) continue;
    const layer = firstHitInGroup(state.layers.hazardZones?.[key], latlng);
    if (layer?._pliLayerProps) {
      entries.push({
        key,
        label: HAZARDS[key].label,
        html: buildPopup(layer._pliLayerProps, key, { includeUnifiedButton: false }),
      });
    }
  }
  if (MAP_LAYER_STATE.fireRisk) {
    const layer = firstHitInGroup(state.layers.fireRisk, latlng);
    if (layer?._pliLayerProps) {
      entries.push({
        key: "fireRisk",
        label: "Risco de Fogo (INPE)",
        html: fireRiskPopupHtml(
          layer._pliLayerProps,
          { includeUnifiedButton: false },
        ),
      });
    }
  }
  if (MAP_LAYER_STATE.regions) {
    const layer = firstHitInGroup(state.layers.regions, latlng);
    if (layer?._pliLayerProps) {
      entries.push({
        key: "regions",
        label: "Regiões monitoradas",
        html: regionLayerInfoHtml(layer._pliLayerProps),
      });
    }
  }
  if (MAP_LAYER_STATE.roads) {
    const layer = firstHitInGroup(state.layers.roads, latlng);
    if (layer?._pliLayerProps) {
      entries.push({
        key: "roads",
        label: "Malha Rodoviária Estadual",
        html: roadLayerInfoHtml(layer._pliLayerProps),
      });
    }
  }
  for (const key of ["municipios", "rc", "uba", "cgr"]) {
    if (!MAP_LAYER_STATE[key]) continue;
    const layer = firstHitInGroup(state.layers[key], latlng);
    if (layer?._pliLayerProps) {
      entries.push({
        key,
        label: adminLayerTitle(key),
        html: genericAdminInfoHtml(key, layer._pliLayerProps),
      });
    }
  }
  return entries;
}

function unifiedLayerPopupHtml(entries) {
  if (!entries.length) {
    return `
      <div class="ua-popup ua-popup--unified">
        <header class="ua-popup-header">
          <div class="ua-popup-risk">Informações das camadas ativas</div>
        </header>
        <div class="ua-popup-body">
          <p class="ua-popup-note">Nenhuma feição ativa encontrada neste ponto.</p>
        </div>
      </div>`;
  }
  return `
    <div class="ua-popup ua-popup--unified">
      <header class="ua-popup-header">
        <div class="ua-popup-risk">Informações das camadas ativas</div>
        <div class="ua-popup-region">Ordem igual ao painel de camadas</div>
      </header>
      <div class="ua-popup-body">
        ${entries.map((entry, idx) => `
          <div class="unified-popup-item" data-layer="${escapeHtml(entry.key)}">
            <div class="unified-popup-title">${idx + 1}. ${escapeHtml(entry.label)}</div>
            ${entry.html}
          </div>
        `).join("")}
      </div>
    </div>`;
}

function openUnifiedLayerPopup(latlng) {
  const entries = collectLayerInfosAt(latlng);
  L.popup({
    className: "ua-popup-wrap unified-popup-wrap",
    maxWidth: 420,
    minWidth: 320,
  })
    .setLatLng(latlng)
    .setContent(unifiedLayerPopupHtml(entries))
    .openOn(state.map);
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
    })
    .join("");
  // Sempre mostra a secao; sem camadas disponiveis, exibe uma linha vazia.
  root.innerHTML =
    items || '<div class="ck ck-empty">Nenhuma camada disponível</div>';

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
      syncInteractiveLayerOrder();
      renderHazardLegend();
      if (state.timeline.active) {
        prepareTimelineLayers(state.timeline.hazard);
        applyTimelineFrame(state.timeline.idx);
        return;
      }
      const snap = state.lastSnapshot;
      if (snap) {
        const focal = resolveFocalPoints(snap);
        state.focalPoints = focal;
        renderFocalBanner(focal);
        applySidebarLevelCounts(snap.summary || {}, focal);
        renderWorst(snap, focal);
        const st = (snap.summary && snap.summary.data_status) || "ok";
        if (st !== "loading" && st !== "no_data") {
          loadActions();
          loadForecast();
        }
      }
    });
  });
}

/** Cabeçalho compacto da legenda: tipo de risco + níveis operacionais. */
function legendHeadHtml(h) {
  const risk = escapeHtml(h.label || "—");
  const subtitle = escapeHtml(
    h.legendSubtitle || "Níveis operacionais de alerta",
  );
  return (
    `<div class="legend-title">`
    + `<span class="legend-title-risk">${risk}</span>`
    + `<span class="legend-title-sub">${subtitle}</span>`
    + `</div>`
  );
}

function fireRiskLegendEntry() {
  if (!MAP_LAYER_STATE.fireRisk) return null;
  return [
    "fireRisk",
    {
      label: "Risco de fogo (INPE)",
      legendSubtitle: `Risco de Fogo · ${state.fireRiskHorizon || "observado"}`,
      palette: FIRE_RISK_ORDER.map((cls) => FIRE_RISK_COLORS[cls]),
      labels: FIRE_RISK_ORDER.map((cls) => fireRiskClassLabel(cls)),
      ndLabel: "Sem dado",
      outLabel: null,
    },
  ];
}

function legendRowsHtml(h) {
  const labels = h.labels || NIVEL_LABEL;
  const rows = h.palette
    .map(
      (c, i) => `
    <div class="legend-item">
      <span class="line" style="border-top:${ROAD_WEIGHTS[i]}px solid ${c}"></span>
      ${h.labels ? escapeHtml(labels[i]) : `${i} — ${escapeHtml(labels[i])}`}
    </div>
  `,
    )
    .join("");
  const nd = h.ndLabel === null
    ? ""
    : `<div class="legend-item"><span class="line line-rd-nd"></span>${escapeHtml(h.ndLabel || "Monitorado · sem dado")}</div>`;
  const out = h.outLabel === null
    ? ""
    : `<div class="legend-item"><span class="line line-out"></span>${escapeHtml(h.outLabel || "Fora da área de monitoramento")}</div>`;
  return rows + nd + out;
}

/** Legenda dinamica no canto do mapa: so mostra paletas das camadas ativas. */
function renderHazardLegend() {
  const root = document.getElementById("hazard-legend");
  if (!root) return;

  const activeEntries = Object.entries(HAZARDS).filter(
    ([k, h]) => h.available && HAZARD_STATE[k],
  );
  const fireEntry = fireRiskLegendEntry();
  if (fireEntry) activeEntries.push(fireEntry);

  if (activeEntries.length === 0) {
    root.innerHTML = "";
    return;
  }

  const blocks = activeEntries
    .map(([key, h]) => {
      const collapsed = !!LEGEND_COLLAPSED[key];
      const toggleChar = collapsed ? "\u25B8" : "\u25C2";
      return `
    <div class="legend-block${collapsed ? " collapsed" : ""}"
         data-legend-key="${key}">
      <div class="legend-head">
        ${legendHeadHtml(h)}
        <button type="button" class="legend-toggle"
                aria-expanded="${collapsed ? "false" : "true"}"
                aria-label="${collapsed ? "Expandir legenda" : "Recolher legenda"}"
                title="${collapsed ? "Expandir" : "Recolher"}">${toggleChar}</button>
      </div>
      <div class="legend-body">
        <div class="legend-rows">
          ${legendRowsHtml(h)}
        </div>
      </div>
    </div>`;
    })
    .join("");

  root.innerHTML = blocks;
  scheduleLegendPanelLayout();
}

/** Igualar largura (maior linha entre os paineis) e altura (stretch). */
function syncLegendPanelLayout() {
  const root = document.getElementById("hazard-legend");
  if (!root) return;

  root.style.removeProperty("--legend-panel-w");
  const blocks = [...root.querySelectorAll(".legend-block:not(.collapsed)")];
  if (!blocks.length) return;

  blocks.forEach((block) => {
    block.style.width = "max-content";
  });

  const maxW = blocks.reduce(
    (max, block) => Math.max(max, Math.ceil(block.getBoundingClientRect().width)),
    0,
  );
  blocks.forEach((block) => {
    block.style.width = "";
  });

  if (maxW > 0) {
    root.style.setProperty("--legend-panel-w", `${maxW}px`);
  }
}

function scheduleLegendPanelLayout() {
  requestAnimationFrame(() => {
    requestAnimationFrame(syncLegendPanelLayout);
  });
}

function initLegendPanelLayout() {
  if (window.__pliLegendLayoutBound) return;
  window.__pliLegendLayoutBound = true;
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(scheduleLegendPanelLayout, 120);
  });
}

function initLegendToggles() {
  initLegendPanelLayout();
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
      collapsed ? "Expandir legenda" : "Recolher legenda",
    );
    btn.title = collapsed ? "Expandir" : "Recolher";
    btn.textContent = collapsed ? "\u25B8" : "\u25C2";
    if (key) {
      LEGEND_COLLAPSED[key] = collapsed;
      saveLegendCollapsed();
    }
    scheduleLegendPanelLayout();
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
    false,
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

function applyMeterHighlight(levelState) {
  document.querySelectorAll(".meter-cell").forEach((c) => {
    c.classList.remove("active", "meter-cell--blink");
    const rd = Number(c.dataset.rd);
    const hazard = c.dataset.hazard;
    const h = HAZARDS[hazard];
    const by = levelState?.[hazard] || levelState?.combined || {};
    const maxRd = levelState?.max?.[hazard] ?? levelState?.max?.combined ?? 0;
    const count = by?.[rd] ?? by?.[String(rd)] ?? 0;
    const color = h?.palette?.[rd] || NIVEL_COLOR[rd] || "#64748b";
    c.style.setProperty("--meter-color", color);
    if (rd === maxRd && count > 0) c.classList.add("active");
    if (shouldBlinkAlert(rd) && count > 0) {
      c.classList.add("meter-cell--blink");
    }
  });
}

function focalizeActions(data, focal) {
  if (!focal?.length) {
    return {
      ...data,
      max_rd: 0,
      max_nivel: NIVEL_LABEL[0],
      max_cor: NIVEL_COLOR[0],
      acoes_necessarias: false,
      total_critico: 0,
      total_atencao: 0,
    };
  }
  const max_rd = focalMaxRd(focal);
  return {
    ...data,
    max_rd,
    max_nivel: NIVEL_LABEL[max_rd],
    max_cor: NIVEL_COLOR[max_rd],
    acoes_necessarias: max_rd >= 1,
    total_critico: focal.filter((p) => p.rd >= 3).length,
    total_atencao: focal.filter((p) => p.rd === 2).length,
  };
}

function actionsPageUrl() {
  if (state.historyMode && state.historyAtIso) {
    return apiUrl("/acoes?at=" + encodeURIComponent(state.historyAtIso));
  }
  return apiUrl("/acoes");
}

function actionsApiUrl() {
  if (state.historyMode && state.historyAtIso) {
    return apiUrl("/api/actions?at=" + encodeURIComponent(state.historyAtIso));
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
    c.innerHTML =
      '<div class="actions-empty waiting">' +
      "Aguardando a primeira leitura de chuva para orientar ações\u2026</div>";
  }
}

function renderActionsNoData() {
  const c = document.getElementById("actions-content");
  if (c) {
    c.innerHTML =
      '<div class="actions-empty">' +
      "Sem dados de chuva neste momento — ações indisponíveis.</div>";
  }
}

function renderActions(data) {
  const container = document.getElementById("actions-content");
  if (!container) return;

  const scoped = focalizeActions(data, state.focalPoints);
  const nivel = scoped.max_nivel || "Monitoramento";
  const cor = scoped.max_cor || "#22c55e";
  const rd = scoped.max_rd ?? 0;
  const url = actionsPageUrl();
  const blinkClass = shouldBlinkAlert(rd) ? " blink" : "";

  if (scoped.acoes_necessarias) {
    const partes = [];
    if (scoped.total_critico) {
      partes.push(`${scoped.total_critico} em Alerta`);
    }
    if (scoped.total_atencao) {
      partes.push(`${scoped.total_atencao} em Atenção`);
    }
    const sub = partes.length
      ? partes.join(" · ")
      : "Situação exige atenção preventiva";
    const foco =
      state.focalPoints?.length === 1
        ? " (UA em foco)"
        : state.focalPoints?.length > 1
          ? ` (${state.focalPoints.length} UAs em foco)`
          : "";
    container.innerHTML = `
      <a class="acoes-btn${blinkClass}" href="${url}" target="_blank"
         rel="noopener" style="--acao-cor:${cor};">
        <span class="acoes-btn-dot"></span>
        <span class="acoes-btn-main">
          <b>Ações necessárias</b>
          <small>Nível ${rd} — ${nivel}${foco}</small>
        </span>
      </a>
      <div class="acoes-sub">${sub}. Consulte o plano detalhado da Defesa Civil.</div>`;
  } else {
    // Operacao normal: informa sem criar outro card de status.
    container.innerHTML = `
      <div class="actions-empty actions-empty--normal">
        Operação normal — nenhuma ação extraordinária por enquanto.
      </div>`;
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
    state.forecastData = data;
    renderForecast(data, state.lastSnapshot);
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
  el.className =
    forecastOk === false
      ? "rd-basis-note rd-basis-warn"
      : "rd-basis-note rd-basis-ok";
  let html = `<strong>Base do alerta:</strong> ${escapeHtml(basis || "—")}`;
  if (forecastOk === false) {
    html +=
      "<br><small>Previsão indisponível — cálculo usa só a chuva já medida " +
      "(pode demorar a refletir piora do tempo).</small>";
  } else if (summary.forecast_count != null && state.uaPickerId) {
    html +=
      "<br><small>Previsão exibida para o trecho selecionado.</small>";
  } else if (summary.forecast_count != null && state.focalPoints?.length) {
    html +=
      "<br><small>Previsão destacada para o trecho com maior RD "
      + "(seleção automática de trecho prioritário).</small>";
  } else if (summary.forecast_count != null) {
    html +=
      `<br><small>Previsão aplicada em ${summary.forecast_count} ` +
      `trecho(s) neste ciclo.</small>`;
  }
  el.innerHTML = html;
}

function renderForecastWaiting() {
  resetTrechoMetricCard(document.getElementById("forecast-card"), {
    note: "Aguardando a leitura de chuva concluir…",
  });
}

function renderForecastNoData() {
  resetTrechoMetricCard(document.getElementById("forecast-card"), {
    note: "Sem dados de chuva — previsão indisponível.",
  });
}

function renderForecast(data, snap) {
  fillForecastCard(data, snap);
}

function renderWorstSparkline(history) {
  if (!history || history.length < 2) return "";
  const vals = history.map((h) => h.rd);
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
        ${vals
          .map((v, i) => {
            const x = i * step;
            const y = h - ((v - min) / range) * h;
            return `<circle cx="${x}" cy="${y}" r="3" fill="${NIVEL_COLOR[v]}"/>`;
          })
          .join("")}
      </svg>
    </div>
  `;
}
