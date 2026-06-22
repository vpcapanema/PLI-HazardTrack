/**
 * Nomenclatura oficial das tres camadas de risco + aliases amistosos.
 * label = termo tecnico (RD geo/hidro, RF fogo); alias = rotulo operacional.
 */
(function (root) {
  "use strict";

  const GROUP = "Riscos associados a eventos climáticos extremos";

  /** Niveis PPDC compartilhados por RD geo e RD hidro (campo rd / nivel). */
  const RD_LEVELS = [
    { rd: 0, label: "Monitoramento", desc: "Sem chuva relevante" },
    { rd: 1, label: "Observação", desc: "Chuva próxima ao limiar" },
    { rd: 2, label: "Atenção", desc: "Vistorias preventivas" },
    { rd: 3, label: "Alerta", desc: "Possíveis ocorrências" },
    { rd: 4, label: "Alerta Máximo", desc: "Risco severo" },
  ];

  /** Cores por nivel RD — espelham o mapa web (static/app.js). */
  const PALETTES = {
    geo: ["#2aa358", "#f1c40f", "#f39c12", "#e74c3c", "#8e44ad"],
    hidro: ["#2aa358", "#5fa8d3", "#1d6fb8", "#0a3d7a", "#d61f8d"],
  };

  /** Espessura da linha (px) por nivel RD no mapa web. */
  const STROKE_WEIGHTS = [4.0, 4.5, 5.0, 5.5, 6.0];

  /** UA sem RD calculado ou monitoramento indisponivel. */
  const SEM_DADO_UA = { color: "#64748b", label: "Sem dado / indisponível" };

  /** Classes RF INPE (campo rf_classe) — ordem crescente de severidade. */
  const FIRE_CLASSES = [
    { id: "minimo", label: "Mínimo", color: "#2aa358" },
    { id: "baixo", label: "Baixo", color: "#a3d977" },
    { id: "medio", label: "Médio", color: "#f1c40f" },
    { id: "alto", label: "Alto", color: "#e67e22" },
    { id: "critico", label: "Crítico", color: "#7f1d1d" },
    { id: "SEM_DADO", label: "Sem dado", color: "#94a3b8" },
  ];

  const LAYERS = {
    geo: {
      id: "encosta",
      label: "Risco geológico",
      alias: "Risco a movimentos de massa",
      index: "RD",
    },
    hidro: {
      id: "inundacao",
      label: "Risco hidrológico",
      alias: "Risco a inundação",
      index: "RD",
    },
    fire: {
      id: "fireRisk",
      label: "Risco de fogo",
      alias: "Risco a incêndios",
      index: "RF",
      source: "INPE",
    },
  };

  function byId(layerId) {
    return Object.values(LAYERS).find((entry) => entry.id === layerId) || null;
  }

  function display(entry) {
    return entry ? entry.alias : "";
  }

  function tooltip(entry) {
    if (!entry) return "";
    const src = entry.source ? ` · ${entry.source}` : "";
    return `${entry.label}${src} (${entry.index})`;
  }

  root.PLI_RISK_LAYERS = {
    GROUP,
    LAYERS,
    RD_LEVELS,
    PALETTES,
    STROKE_WEIGHTS,
    SEM_DADO_UA,
    FIRE_CLASSES,
    byId,
    display,
    tooltip,
  };
})(typeof window !== "undefined" ? window : globalThis);
