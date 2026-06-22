/**
 * PLI-HazardTrack — painel administrativo (dashboard multi-seção).
 */
(function () {
  "use strict";

  const PANEL_META = {
    visao: ["Visão geral", "Panorama dos dois módulos de monitoramento"],
    saude: ["Saúde dos sistemas", "Semáforos, pipelines e fontes de dados"],
    estatisticas: ["Estatísticas", "Distribuição atual dos níveis monitorados"],
    analytics: ["Analytics", "Tendências operacionais e desempenho"],
    relatorios: ["Relatórios", "Exportação inteligente para operação e auditoria"],
    sistema: ["Sistema técnico", "Runtime, dependências e diagnóstico completo"],
  };

  const RD_COLORS = ["#94a3b8", "#60a5fa", "#fbbf24", "#f97316", "#ef4444"];
  const RF_COLORS = {
    minimo: "#94a3b8",
    baixo: "#60a5fa",
    medio: "#fbbf24",
    alto: "#f97316",
    critico: "#ef4444",
    SEM_DADO: "#cbd5e1",
  };

  const REPORTS = [
    {
      id: "operacional",
      title: "Relatório operacional",
      desc: "HTML imprimível com KPIs, distribuição RD/RF e tops.",
      fmt: "HTML",
      icon: "📋",
    },
    {
      id: "overview",
      title: "Panorama JSON",
      desc: "Resumo estruturado para integração ou auditoria.",
      fmt: "JSON",
      icon: "{ }",
    },
    {
      id: "geodinamico",
      title: "Top UAs geodinâmicas",
      desc: "CSV das UAs com maior RD (encosta + inundação).",
      fmt: "CSV",
      icon: "⛰",
    },
    {
      id: "fogo",
      title: "Top trechos — fogo",
      desc: "CSV dos trechos com maior RF observado.",
      fmt: "CSV",
      icon: "🔥",
    },
  ];

  let dashboard = null;
  let diagnostics = null;

  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => showPanel(btn.dataset.panel));
  });
  document.getElementById("btn-refresh").addEventListener("click", refresh);
  document.getElementById("sidebar-toggle").addEventListener("click", () => {
    document.getElementById("admin-sidebar").classList.toggle("open");
  });

  const hash = location.hash.replace("#", "");
  if (hash && PANEL_META[hash]) showPanel(hash);
  else showPanel("visao");

  setInterval(refresh, 60_000);
  refresh();

  function showPanel(id) {
    document.querySelectorAll(".nav-item").forEach((b) => {
      b.classList.toggle("active", b.dataset.panel === id);
    });
    document.querySelectorAll(".panel").forEach((p) => {
      p.classList.toggle("active", p.id === "panel-" + id);
    });
    const meta = PANEL_META[id] || ["Admin", ""];
    document.getElementById("panel-title").textContent = meta[0];
    document.getElementById("panel-subtitle").textContent = meta[1];
    location.hash = id;
    document.getElementById("admin-sidebar").classList.remove("open");
  }

  async function refresh() {
    try {
      const [dashRes, diagRes] = await Promise.all([
        fetch("/admin/api/dashboard", { credentials: "same-origin" }),
        fetch("/admin/api/diagnostics", { credentials: "same-origin" }),
      ]);
      if (dashRes.status === 401) {
        window.location = "/admin/login";
        return;
      }
      dashboard = await dashRes.json();
      if (diagRes.ok) diagnostics = await diagRes.json();
      renderAll();
    } catch (e) {
      console.warn("admin refresh:", e);
    }
  }

  function renderAll() {
    if (!dashboard) return;
    document.getElementById("updated-at").textContent =
      "Atualizado " +
      new Date(dashboard.generated_at).toLocaleString("pt-BR");
    renderOverview();
    renderHealth();
    renderStats();
    renderAnalytics();
    renderReports();
    renderSystem();
  }

  // ---- helpers ---------------------------------------------------------
  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }
  function fmtTime(iso) {
    return iso ? new Date(iso).toLocaleString("pt-BR") : "—";
  }
  function fmtSec(s) {
    if (s == null) return "—";
    if (s < 60) return s.toFixed(1) + " s";
    return (s / 60).toFixed(1) + " min";
  }
  function lightDot(state) {
    return `<span class="light-dot light-${state || "warn"}"></span>`;
  }
  function kvGrid(rows) {
    const g = el("div", "kv-grid");
    for (const [k, v] of rows) {
      const row = el("div", "kv");
      row.appendChild(el("span", "kv-k", esc(k)));
      row.appendChild(el("span", "kv-v", esc(v)));
      g.appendChild(row);
    }
    return g;
  }
  function barChart(items, colors) {
    const total = items.reduce((s, i) => s + i.value, 0) || 1;
    const wrap = el("div", "bar-chart");
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      const pct = Math.round((100 * it.value) / total);
      const row = el("div", "bar-row");
      row.innerHTML =
        `<span class="bar-label">${esc(it.label)}</span>` +
        `<div class="bar-track"><i style="width:${pct}%;background:${colors[i] || "#3ec26e"}"></i></div>` +
        `<span class="bar-val">${it.value} <small>(${pct}%)</small></span>`;
      wrap.appendChild(row);
    }
    return wrap;
  }

  // ---- visão geral -----------------------------------------------------
  function renderOverview() {
    const ov = dashboard.overview;
    const geo = dashboard.stats.geodinamico;
    const fire = dashboard.stats.risco_fogo;
    const kpi = document.getElementById("kpi-overview");
    kpi.innerHTML = "";
    const cards = [
      ["RD máximo", ov.geodinamico.max_rd + " · " + ov.geodinamico.max_rd_label, "geo"],
      ["UAs monitoradas", ov.geodinamico.uas_monitoradas, "geo"],
      ["Alertas RD (3+4)", ov.geodinamico.alertas_rd, "geo warn"],
      ["Trechos fogo", ov.risco_fogo.total_trechos, "fire"],
      ["RF alto/crítico", ov.risco_fogo.alertas_rf, "fire warn"],
      ["Ref. fogo", ov.risco_fogo.data_referencia || "—", "fire"],
    ];
    for (const [label, val, mod] of cards) {
      const c = el("div", "kpi-card " + mod);
      c.innerHTML = `<small>${esc(label)}</small><strong>${esc(val)}</strong>`;
      kpi.appendChild(c);
    }

    document.getElementById("visao-geo").innerHTML = "";
    document.getElementById("visao-geo").appendChild(
      kvGrid([
        ["Status", geo.data_status || "—"],
        ["Última atualização", fmtTime(geo.last_update)],
        ["Fonte chuva", geo.data_source || "—"],
        ["Faltando 24h", geo.missing_24h ?? "—"],
        ["Cobertura", geo.uas_geo + " encosta · " + geo.uas_hidro + " inundação"],
      ])
    );
    const rdItems = Object.entries(geo.by_level_label || {}).map(([k, v]) => ({
      label: k,
      value: Number(v),
    }));
    document.getElementById("visao-geo").appendChild(barChart(rdItems, RD_COLORS));

    document.getElementById("visao-fire").innerHTML = "";
    document.getElementById("visao-fire").appendChild(
      kvGrid([
        ["Status", dashboard.health.risco_fogo.status],
        ["Data referência", fire.data_referencia || "—"],
        ["Metodologia", fire.modulo ? "INPE-RF-v11" : "—"],
        ["Horizontes", (fire.horizontes || []).join(", ") || "—"],
      ])
    );
    const rfItems = Object.entries(fire.classes_label || {}).map(([k, v]) => ({
      label: k,
      value: Number(v),
    }));
    document.getElementById("visao-fire").appendChild(
      barChart(
        rfItems,
        rfItems.map((i) => RF_COLORS[i.label.toLowerCase()] || "#3ec26e")
      )
    );
  }

  // ---- saúde -----------------------------------------------------------
  function renderHealth() {
    renderHealthBlock("health-geo", dashboard.health.geodinamico, "geo");
    renderHealthBlock("health-fire", dashboard.health.risco_fogo, "fire");

    const tbody = document.querySelector("#cycle-history tbody");
    tbody.innerHTML = "";
    const rows = dashboard.analytics.recent_cycles || [];
    if (!rows.length) {
      tbody.innerHTML =
        '<tr><td colspan="6" class="empty">Sem ciclos registrados.</td></tr>';
      return;
    }
    for (const h of rows) {
      const tr = document.createElement("tr");
      tr.className = h.outcome === "ok" ? "row-ok" : "row-fail";
      tr.innerHTML =
        `<td>${esc(h.started_at)}</td>` +
        `<td>${fmtSec(h.duration_s)}</td>` +
        `<td>${esc(h.outcome)} · ${esc(h.data_status || "")}</td>` +
        `<td>${esc(h.max_rd ?? "—")}</td>` +
        `<td>${esc(h.files_ok ?? "—")}</td>` +
        `<td><code>${esc(h.error || "")}</code></td>`;
      tbody.appendChild(tr);
    }
  }

  function renderHealthBlock(rootId, block, kind) {
    const root = document.getElementById(rootId);
    root.innerHTML = "";
    const lights = el("div", "lights");
    const labels =
      kind === "geo"
        ? {
            dados: "Dados MERGE",
            scheduler: "Scheduler 10 min",
            eccodes: "Decodificador GRIB",
            erros: "Erros recentes",
          }
        : {
            produto: "Produto RF",
            auto_runner: "Runner automático",
            inpe_poll: "INPE (arquivo novo?)",
            pipeline_lock: "Lock pipeline",
          };
    for (const [k, v] of Object.entries(block.lights || {})) {
      const tile = el("div", "light-tile");
      tile.innerHTML =
        lightDot(v) +
        `<div class="light-label"><b>${esc(labels[k] || k)}</b></div>`;
      lights.appendChild(tile);
    }
    root.appendChild(lights);

    if (kind === "geo") {
      root.appendChild(
        kvGrid([
          ["Status", block.status],
          ["Ciclos OK", block.scheduler.cycle_success + " / " + block.scheduler.cycle_count],
          ["Última duração", fmtSec(block.scheduler.last_duration_s)],
          ["Files OK", block.data_quality.files_ok ?? "—"],
          ["Faltando 24h", block.data_quality.missing_24h ?? "—"],
        ])
      );
      if (block.scheduler.last_error) {
        root.appendChild(
          el(
            "div",
            "alert alert-error",
            `<b>Último erro</b><br><code>${esc(block.scheduler.last_error)}</code>`
          )
        );
      }
    } else {
      const ar = block.auto_runner || {};
      const inpe = block.inpe || {};
      root.appendChild(
        kvGrid([
          ["Status", block.status],
          ["Polling", ar.enabled ? "a cada " + ar.poll_min + " min" : "desligado"],
          ["Último arquivo INPE", ar.last_file || "—"],
          ["Última execução", fmtTime(ar.last_run)],
          ["Arquivo mais recente (INPE)", inpe.latest_file || "—"],
          ["Atualização pendente", inpe.pending_update ? "sim" : "não"],
        ])
      );
    }
  }

  // ---- estatísticas ----------------------------------------------------
  function renderStats() {
    const geo = dashboard.stats.geodinamico;
    const fire = dashboard.stats.risco_fogo;

    const rdItems = Object.entries(geo.by_level_label || {}).map(([k, v]) => ({
      label: k,
      value: Number(v),
    }));
    document.getElementById("stats-rd-bars").innerHTML = "";
    document.getElementById("stats-rd-bars").appendChild(
      barChart(rdItems, RD_COLORS)
    );

    const rfItems = Object.entries(fire.classes_label || {}).map(([k, v]) => ({
      label: k,
      value: Number(v),
    }));
    document.getElementById("stats-rf-bars").innerHTML = "";
    document.getElementById("stats-rf-bars").appendChild(
      barChart(
        rfItems,
        rfItems.map((i) => {
          const key = Object.keys(fire.classes_label).find(
            (k) => fire.classes_label[k] === i.label
          );
          return RF_COLORS[key] || "#3ec26e";
        })
      )
    );

    renderRegionTable("stats-region-geo", geo.by_region_geo);
    renderRegionTable("stats-region-fire", fire.by_regional, true);
    renderTopTable("stats-top-geo", geo.top_uas_geo, [
      "ua_id",
      "sigla_rodovia",
      "rd",
      "nivel",
      "ac96h_mm",
    ]);
    renderTopTable("stats-top-fire", fire.top_trechos, [
      "rodovia",
      "km_ini",
      "rf_valor",
      "rf_classe",
      "municipio",
    ]);
  }

  function renderRegionTable(id, data, isFire) {
    const root = document.getElementById(id);
    root.innerHTML = "";
    if (!data || !Object.keys(data).length) {
      root.innerHTML = '<p class="empty">Sem dados.</p>';
      return;
    }
    const t = el("table", "small-table");
    t.innerHTML = "<thead><tr><th>Região</th><th>Detalhe</th></tr></thead>";
    const tb = el("tbody");
    for (const [region, counts] of Object.entries(data)) {
      const tr = document.createElement("tr");
      const detail = Object.entries(counts)
        .map(([k, v]) => `${k}: ${v}`)
        .join(" · ");
      tr.innerHTML = `<td>${esc(region)}</td><td>${esc(detail)}</td>`;
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    root.appendChild(t);
  }

  function renderTopTable(id, rows, cols) {
    const root = document.getElementById(id);
    root.innerHTML = "";
    if (!rows || !rows.length) {
      root.innerHTML = '<p class="empty">Sem registros elevados no momento.</p>';
      return;
    }
    const t = el("table", "small-table");
    t.innerHTML =
      "<thead><tr>" +
      cols.map((c) => `<th>${esc(c)}</th>`).join("") +
      "</tr></thead>";
    const tb = el("tbody");
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = cols.map((c) => `<td>${esc(r[c])}</td>`).join("");
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    root.appendChild(t);
  }

  // ---- analytics -------------------------------------------------------
  function renderAnalytics() {
    const ana = dashboard.analytics;
    const kpi = document.getElementById("kpi-analytics");
    kpi.innerHTML = "";
    const cards = [
      ["Taxa sucesso ciclos", ana.cycle_success_rate_pct + "%"],
      ["Uptime processo", fmtSec(ana.uptime_s)],
      ["Ciclos no histórico", (ana.rd_trend || []).length],
    ];
    for (const [label, val] of cards) {
      const c = el("div", "kpi-card");
      c.innerHTML = `<small>${esc(label)}</small><strong>${esc(val)}</strong>`;
      kpi.appendChild(c);
    }
    renderSparkline("chart-rd-trend", ana.rd_trend, "max_rd", RD_COLORS[4]);
    renderSparkline(
      "chart-duration",
      ana.duration_trend,
      "duration_s",
      "#003b5a"
    );
  }

  function renderSparkline(id, points, field, color) {
    const root = document.getElementById(id);
    root.innerHTML = "";
    if (!points || !points.length) {
      root.innerHTML = '<p class="empty">Histórico insuficiente.</p>';
      return;
    }
    const vals = points.map((p) => Number(p[field]) || 0);
    const max = Math.max(...vals, 1);
    const wrap = el("div", "sparkline");
    points.forEach((p, i) => {
      const h = Math.max(4, Math.round((vals[i] / max) * 100));
      const bar = el("div", "spark-bar");
      bar.style.height = h + "px";
      bar.style.background = color;
      bar.title = fmtTime(p.at) + ": " + vals[i];
      wrap.appendChild(bar);
    });
    root.appendChild(wrap);
    const labels = el("div", "spark-labels");
    labels.innerHTML =
      `<span>${fmtTime(points[0].at)}</span>` +
      `<span>${fmtTime(points[points.length - 1].at)}</span>`;
    root.appendChild(labels);
  }

  // ---- relatórios ------------------------------------------------------
  function renderReports() {
    const grid = document.getElementById("report-cards");
    grid.innerHTML = "";
    for (const r of REPORTS) {
      const card = el("article", "report-card");
      card.innerHTML =
        `<div class="report-icon">${r.icon}</div>` +
        `<h3>${esc(r.title)}</h3>` +
        `<p>${esc(r.desc)}</p>` +
        `<span class="report-fmt">${esc(r.fmt)}</span>` +
        `<a class="btn-primary report-dl" href="/admin/api/reports/export?type=${r.id}">Baixar</a>`;
      grid.appendChild(card);
    }

    const prev = document.getElementById("report-preview");
    const geo = dashboard.stats.geodinamico;
    const fire = dashboard.stats.risco_fogo;
    prev.innerHTML = "";
    prev.appendChild(
      kvGrid([
        ["Snapshot gerado", fmtTime(dashboard.generated_at)],
        ["RD máx atual", geo.max_rd + " (" + (geo.max_rd_name || "—") + ")"],
        ["UAs alerta 3+4", geo.alert_count],
        ["Trechos RF alto/crit", fire.alertas_rf],
        ["Top UA encosta", (geo.top_uas_geo[0] || {}).ua_id || "—"],
        ["Top trecho fogo", (fire.top_trechos[0] || {}).rodovia || "—"],
      ])
    );
  }

  // ---- sistema técnico -------------------------------------------------
  function renderSystem() {
    const root = document.getElementById("system-diag");
    root.innerHTML = "";
    if (!diagnostics) {
      root.innerHTML = '<p class="empty">Diagnóstico técnico indisponível.</p>';
      return;
    }
    const p = diagnostics.platform || {};
    root.appendChild(
      kvGrid([
        ["Python", (p.python || {}).version],
        ["Hostname", (p.system || {}).hostname],
        ["Memória RSS", ((p.process || {}).memory_rss_mb || "—") + " MB"],
        ["eccodes", (p.dependencies || {}).eccodes_lib_loaded ? "OK" : "FAIL"],
        ["Uptime", fmtSec((p.process || {}).uptime_s)],
      ])
    );
    const auth = diagnostics.auth_backend || {};
    root.appendChild(
      el("div", "subcard mt",
        `<div class="subcard-head">${lightDot((auth.health || {}).ok ? "ok" : "warn")}<b>Autenticação</b></div>` +
          kvGrid([
            ["Provider", auth.provider || "—"],
            ["Modo", auth.mode || "—"],
            ["Configurado", auth.configured ? "sim" : "não"],
          ]).outerHTML
      )
    );
    document.getElementById("raw-diagnostics").textContent = JSON.stringify(
      diagnostics,
      null,
      2
    );
  }
})();
