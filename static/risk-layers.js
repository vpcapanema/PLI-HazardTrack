/**
 * Nomenclatura oficial das tres camadas de risco + aliases amistosos.
 * label = termo tecnico (RD geo/hidro, RF fogo); alias = rotulo operacional.
 */
(function (root) {
  "use strict";

  const GROUP = "Riscos associados a eventos climáticos extremos";

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

  root.PLI_RISK_LAYERS = { GROUP, LAYERS, byId, display, tooltip };
})(typeof window !== "undefined" ? window : globalThis);
