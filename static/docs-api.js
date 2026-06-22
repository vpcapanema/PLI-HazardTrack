/**
 * Preenche URLs, simbologia e exemplo de fetch na pagina /docs/api.
 */
(function () {
  "use strict";

  function apiUrl(path) {
    const base = window.APP_BASE || "";
    if (!path.startsWith("/")) path = "/" + path;
    return base + path;
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function legendHeadHtml(alias, subtitle) {
    return (
      `<div class="legend-title">`
      + `<span class="legend-title-risk">${escapeHtml(alias)}</span>`
      + `<span class="legend-title-sub">${escapeHtml(subtitle)}</span>`
      + `</div>`
    );
  }

  function legendRowsHtml(palette, labels, weights, ndLabel) {
    const rows = palette.map((color, i) => {
      const w = weights[i] != null ? weights[i] : 4;
      const lbl = labels[i] != null ? labels[i] : String(i);
      return (
        `<div class="legend-item">`
        + `<span class="line" style="border-top:${w}px solid ${color}"></span>`
        + `${escapeHtml(lbl)}`
        + `</div>`
      );
    }).join("");
    const nd = ndLabel
      ? `<div class="legend-item">`
        + `<span class="line line-rd-nd"></span>${escapeHtml(ndLabel)}`
        + `</div>`
      : "";
    return rows + nd;
  }

  function renderLegendPreview() {
    const root = document.getElementById("api-legend-preview");
    const cfg = window.PLI_RISK_LAYERS;
    if (!root || !cfg) return;

    const fireMain = cfg.FIRE_CLASSES.filter((c) => c.id !== "SEM_DADO");
    const entries = [
      {
        key: "geo",
        alias: cfg.LAYERS.geo.alias,
        subtitle: `${cfg.LAYERS.geo.label} · níveis operacionais`,
        palette: cfg.PALETTES.geo,
        labels: cfg.RD_LEVELS.map((l) => l.label),
        weights: cfg.STROKE_WEIGHTS,
        ndLabel: "Monitorado · sem dado",
      },
      {
        key: "hidro",
        alias: cfg.LAYERS.hidro.alias,
        subtitle: `${cfg.LAYERS.hidro.label} · níveis operacionais`,
        palette: cfg.PALETTES.hidro,
        labels: cfg.RD_LEVELS.map((l) => l.label),
        weights: cfg.STROKE_WEIGHTS,
        ndLabel: "Monitorado · sem dado",
      },
      {
        key: "fire",
        alias: cfg.LAYERS.fire.alias,
        subtitle: `${cfg.LAYERS.fire.label} · observado`,
        palette: fireMain.map((c) => c.color),
        labels: fireMain.map((c) => c.label),
        weights: cfg.STROKE_WEIGHTS.slice(0, fireMain.length),
        ndLabel: "Sem dado",
      },
    ];

    root.innerHTML = entries.map((e) => (
      `<div class="legend-block" data-legend-key="${e.key}">`
      + `<div class="legend-head">${legendHeadHtml(e.alias, e.subtitle)}</div>`
      + `<div class="legend-body"><div class="legend-rows">`
      + legendRowsHtml(e.palette, e.labels, e.weights, e.ndLabel)
      + `</div></div></div>`
    )).join("");
  }

  function swatchHtml(color) {
    return (
      `<span class="docs-symb-swatch" style="background:${color}" `
      + `aria-hidden="true"></span><code>${color}</code>`
    );
  }

  function renderRdSymbology(tableId, paletteKey) {
    const cfg = window.PLI_RISK_LAYERS;
    const table = document.getElementById(tableId);
    if (!table || !cfg) return;
    const palette = cfg.PALETTES[paletteKey] || [];
    const weights = cfg.STROKE_WEIGHTS || [];
    const rows = cfg.RD_LEVELS.map((lvl) => {
      const color = palette[lvl.rd] || "#64748b";
      const weight = weights[lvl.rd] != null ? `${weights[lvl.rd]} px` : "—";
      return (
        "<tr>"
        + `<td><code>${lvl.rd}</code></td>`
        + `<td>${lvl.label}</td>`
        + `<td class="docs-symb-color">${swatchHtml(color)}</td>`
        + `<td>${weight}</td>`
        + `<td>${lvl.desc}</td>`
        + "</tr>"
      );
    }).join("");
    const sem = cfg.SEM_DADO_UA;
    table.innerHTML = (
      "<thead><tr>"
      + "<th>RD</th><th>Nível PPDC</th><th>Cor (hex)</th>"
      + "<th>Espessura</th><th>Significado operacional</th>"
      + "</tr></thead><tbody>"
      + rows
      + "<tr>"
      + "<td>—</td><td>" + sem.label + "</td>"
      + `<td class="docs-symb-color">${swatchHtml(sem.color)}</td>`
      + "<td>3 px</td>"
      + "<td>UA sem RD (RA ausente ou monitoramento indisponível)</td>"
      + "</tr></tbody>"
    );
  }

  function renderFireSymbology() {
    const cfg = window.PLI_RISK_LAYERS;
    const table = document.getElementById("api-symb-fire");
    if (!table || !cfg) return;
    const rows = cfg.FIRE_CLASSES.map((cls) => (
      "<tr>"
      + `<td><code>${cls.id}</code></td>`
      + `<td>${cls.label}</td>`
      + `<td class="docs-symb-color">${swatchHtml(cls.color)}</td>`
      + `<td>${cls.id === "SEM_DADO" ? "Trecho sem produto RF" : "Condição ambiental favorável à ignição/propagação"}</td>`
      + "</tr>"
    )).join("");
    table.innerHTML = (
      "<thead><tr>"
      + "<th><code>rf_classe</code></th><th>Rótulo</th>"
      + "<th>Cor (hex)</th><th>Leitura</th>"
      + "</tr></thead><tbody>" + rows + "</tbody>"
    );
  }

  const paths = {
    "api-url-catalog": "/api/public",
    "api-url-live": "/api/public/ua-layers?hazard=geo",
    "api-url-all": "/api/public/ua-layers",
    "api-url-geo": "/api/public/ua-layers?hazard=geo",
    "api-url-hidro": "/api/public/ua-layers?hazard=hidro",
    "api-url-alerts": "/api/public/ua-layers?min_rd=3",
    "api-url-fire-layers": "/api/public/fire-risk/layers?horizonte=observado",
    "api-url-fire-layers-ref":
      "/api/public/fire-risk/layers?horizonte=observado",
    "api-url-fire-snapshot": "/api/public/fire-risk/snapshot",
  };

  const origin = window.location.origin || "";
  Object.entries(paths).forEach(([id, path]) => {
    const el = document.getElementById(id);
    if (el) el.textContent = origin + apiUrl(path);
  });

  renderRdSymbology("api-symb-geo", "geo");
  renderRdSymbology("api-symb-hidro", "hidro");
  renderFireSymbology();
  renderLegendPreview();

  const ex = document.getElementById("api-fetch-example");
  const key = window.PLI_PUBLIC_API_KEY || "";
  if (ex) {
    const authHdr = key
      ? '  headers: { "X-API-Key": "<sua-chave>" },\n'
      : "";
    const geo = origin + apiUrl("/api/public/ua-layers?hazard=geo");
    const hidro = origin + apiUrl("/api/public/ua-layers?hazard=hidro");
    const fogo = origin + apiUrl(
      "/api/public/fire-risk/layers?horizonte=observado",
    );
    ex.textContent =
      `const opts = {${authHdr ? `\n${authHdr}` : ""}};\n\n` +
      `// Risco geologico (movimentos de massa)\n` +
      `const geo = await (await fetch("${geo}", opts)).json();\n\n` +
      `// Risco hidrologico (inundacao)\n` +
      `const hidro = await (await fetch("${hidro}", opts)).json();\n\n` +
      `// Risco de fogo (incendios · INPE)\n` +
      `const fogo = await (await fetch("${fogo}", opts)).json();`;
  }
})();
