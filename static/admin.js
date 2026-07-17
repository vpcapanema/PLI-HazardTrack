/**
 * PLI-HazardTrack — painel administrativo (dashboard multi-seção).
 */
(function () {
  "use strict";

  const PANEL_META = {
    visao: ["Visão geral", "Panorama dos dois módulos de monitoramento"],
    saude: ["Saúde dos sistemas", "Semáforos, pipelines e fontes de dados"],
    controles: [
      "Controles de alerta",
      "Ligar ou desligar cada sistema (default: ligado)",
    ],
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

  const RD_LABELS = {
    0: "Monitoramento",
    1: "Observação",
    2: "Atenção",
    3: "Alerta",
    4: "Alerta Máximo",
  };

  const RF_LABELS = {
    minimo: "Mínimo",
    baixo: "Baixo",
    medio: "Médio",
    alto: "Alto",
    critico: "Crítico",
    SEM_DADO: "Sem dado",
  };

  const COL_LABELS = {
    ua_id: "UA",
    sigla_rodovia: "Rodovia",
    rd: "RD",
    nivel: "Nível",
    ac96h_mm: "Chuva 96h (mm)",
    rodovia: "Rodovia",
    km_ini: "Km inicial",
    km_fim: "Km final",
    rf_valor: "RF",
    rf_classe: "Classe",
    municipio: "Município",
  };

  const STATUS_LABELS = {
    ok: "OK",
    degraded: "Degradado",
    loading: "Carregando",
    no_data: "Sem dado",
    warn: "Atenção",
    fail: "Falha",
    fresh: "Atualizado",
    skip: "Ignorado",
    busy: "Ocupado",
    error: "Erro",
    disabled: "Desligado",
    unknown: "Desconhecido",
  };

  const TZ_BR = "America/Sao_Paulo";

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
  document
    .getElementById("btn-refresh-geo")
    ?.addEventListener("click", () => forceRefresh("geo"));
  document
    .getElementById("btn-refresh-fire")
    ?.addEventListener("click", () => forceRefresh("fire"));
  document.getElementById("sidebar-toggle").addEventListener("click", () => {
    document.getElementById("admin-sidebar").classList.toggle("open");
  });

  const hash = location.hash.replace("#", "");
  if (hash && PANEL_META[hash]) showPanel(hash);
  else showPanel("visao");

  setInterval(refresh, 60_000);
  refresh();

  const REFRESH_META = {
    geo: {
      btn: "btn-refresh-geo",
      msg: "refresh-geo-msg",
      label: "Atualizar agora",
      doneMsg: "Leitura MERGE/INPE atualizada e RD recalculado.",
    },
    fire: {
      btn: "btn-refresh-fire",
      msg: "refresh-fire-msg",
      label: "Atualizar agora",
      doneMsg: "Risco de fogo recalculado com o arquivo mais atual do INPE.",
    },
  };

  async function forceRefresh(system) {
    const meta = REFRESH_META[system];
    if (!meta) return;
    const btn = document.getElementById(meta.btn);
    const msg = document.getElementById(meta.msg);
    const lbl = btn?.querySelector(".brn-lbl");
    if (btn) btn.disabled = true;
    if (lbl) lbl.textContent = "Atualizando…";
    showRefreshMsg(msg, "Atualização em andamento — puxando dados da fonte…",
      "info");
    try {
      const res = await fetch(`/admin/api/refresh/${system}`, {
        method: "POST",
        credentials: "same-origin",
      });
      if (res.status === 401) {
        window.location = "/admin/login";
        return;
      }
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        showRefreshMsg(msg, body.error || "Falha ao iniciar atualização.",
          "error");
        resetRefreshBtn(btn, lbl, meta.label);
        return;
      }
      pollRefresh(system, meta, btn, lbl, msg);
    } catch (e) {
      console.warn("force refresh:", e);
      showRefreshMsg(msg, "Erro de rede ao iniciar atualização.", "error");
      resetRefreshBtn(btn, lbl, meta.label);
    }
  }

  async function pollRefresh(system, meta, btn, lbl, msg, attempt) {
    attempt = attempt || 0;
    if (attempt > 120) {
      showRefreshMsg(msg, "Ainda processando em segundo plano…", "info");
      resetRefreshBtn(btn, lbl, meta.label);
      return;
    }
    try {
      const res = await fetch("/admin/api/refresh/status", {
        credentials: "same-origin",
      });
      const st = (await res.json())[system] || {};
      if (st.running) {
        setTimeout(
          () => pollRefresh(system, meta, btn, lbl, msg, attempt + 1),
          3000,
        );
        return;
      }
      const last = st.last || {};
      if (last.outcome && last.outcome !== "error" &&
          last.outcome !== "no_source") {
        showRefreshMsg(
          msg,
          `${meta.doneMsg} (${last.elapsed_s ?? "?"}s)`,
          "ok",
        );
        await refresh();
      } else if (last.outcome === "no_source") {
        showRefreshMsg(msg, "Sem arquivo novo na fonte agora.", "info");
      } else {
        showRefreshMsg(
          msg,
          "Falha na atualização: " + (last.error || "erro desconhecido"),
          "error",
        );
      }
    } catch (e) {
      console.warn("poll refresh:", e);
    } finally {
      resetRefreshBtn(btn, lbl, meta.label);
    }
  }

  function resetRefreshBtn(btn, lbl, label) {
    if (btn) btn.disabled = false;
    if (lbl) lbl.textContent = label;
  }

  function showRefreshMsg(el, text, kind) {
    if (!el) return;
    el.hidden = false;
    el.className = "refresh-msg refresh-msg--" + (kind || "info");
    el.textContent = text;
  }

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
      (dashboard.generated_at_fmt || fmtDateTime(dashboard.generated_at));
    renderOverview();
    renderHealth();
    renderControls();
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
  function fmtDateTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const parts = new Intl.DateTimeFormat("pt-BR", {
      timeZone: TZ_BR,
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).formatToParts(d);
    const get = (t) => parts.find((p) => p.type === t)?.value || "";
    return (
      get("day") + "/" + get("month") + "/" + get("year") + " " +
      get("hour") + ":" + get("minute") + ":" + get("second")
    );
  }

  function fmtDate(value) {
    if (!value) return "—";
    const text = String(value);
    const m = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return m[3] + "/" + m[2] + "/" + m[1];
    return fmtDateTime(value).slice(0, 10);
  }

  function fmtTime(iso) {
    return fmtDateTime(iso);
  }

  function fmtStatus(code) {
    if (code == null || code === "") return "—";
    const key = String(code).toLowerCase();
    return STATUS_LABELS[key] || String(code);
  }

  function rfColorKey(labelOrKey) {
    const raw = String(labelOrKey || "").toLowerCase();
    if (raw === "sem dado" || raw === "sem_dado") return "SEM_DADO";
    const byLabel = Object.entries(RF_LABELS).find(
      ([, lbl]) => lbl.toLowerCase() === raw,
    );
    if (byLabel) return byLabel[0];
    return raw.replace(/\s+/g, "_");
  }

  function fmtRfClass(cls) {
    if (!cls) return "—";
    return RF_LABELS[String(cls)] || String(cls);
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
      ["Ref. fogo", ov.risco_fogo.data_referencia_fmt || fmtDate(ov.risco_fogo.data_referencia) || "—", "fire"],
    ];
    for (const [label, val, mod] of cards) {
      const c = el("div", "kpi-card " + mod);
      c.innerHTML = `<small>${esc(label)}</small><strong>${esc(val)}</strong>`;
      kpi.appendChild(c);
    }

    document.getElementById("visao-geo").innerHTML = "";
    document.getElementById("visao-geo").appendChild(
      kvGrid([
        ["Status", fmtStatus(geo.data_status)],
        ["Última atualização", geo.last_update_fmt || fmtDateTime(geo.last_update)],
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
        ["Status", fmtStatus(dashboard.health.risco_fogo.status)],
        ["Data referência", fire.data_referencia_fmt || fmtDate(fire.data_referencia)],
        ["Metodologia", fire.metodologia || dashboard.health.risco_fogo.metodologia || "—"],
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
        rfItems.map((i) => RF_COLORS[rfColorKey(i.label)] || "#3ec26e")
      )
    );
  }

  // ---- saúde -----------------------------------------------------------
  function renderHealth() {
    renderHealthBlock("health-geo", dashboard.health.geodinamico, "geo");
    renderHealthBlock("health-fire", dashboard.health.risco_fogo, "fire");
    renderExecControl("exec-geo", dashboard.health.geodinamico);
    renderExecControl("exec-fire", dashboard.health.risco_fogo);

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
        `<td>${esc(h.started_at_fmt || fmtDateTime(h.started_at))}</td>` +
        `<td>${fmtSec(h.duration_s)}</td>` +
        `<td>${esc(fmtStatus(h.outcome))} · ${esc(fmtStatus(h.data_status || ""))}</td>` +
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
          ["Status", fmtStatus(block.status)],
          ["Ciclos OK", block.scheduler.cycle_success + " / " + block.scheduler.cycle_count],
          ["Última duração", fmtSec(block.scheduler.last_duration_s)],
          ["Files OK", block.data_quality.files_ok ?? "—"],
          ["Faltando 24h", block.data_quality.missing_24h ?? "—"],
        ])
      );
      renderGaugeCorrection(root, block.gauge_correction);
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
          ["Status", fmtStatus(block.status)],
          ["Polling", ar.enabled ? "a cada " + ar.poll_min + " min" : "desligado"],
          ["Último arquivo INPE", ar.last_file || "—"],
          ["Última execução", ar.last_run_fmt || fmtDateTime(ar.last_run)],
          ["Arquivo mais recente (INPE)", inpe.latest_file || "—"],
          ["Atualização pendente", inpe.pending_update ? "sim" : "não"],
        ])
      );
    }
  }

  function renderGaugeCorrection(root, gc) {
    if (!gc) return;
    const card = el("div", "kv-section");
    let head = "<b>Correção por solo (DAEE/CEMADEN)</b>";
    if (!gc.enabled) {
      card.innerHTML = head + '<div class="muted">desativada</div>';
      root.appendChild(card);
      return;
    }
    const rows = [
      ["Fonte", gc.source || "—"],
      ["Estado", gc.applied ? "aplicada" : (gc.error ? "indisponível" : "sem ancoragem")],
      ["Janela de ancoragem", (gc.anchor_hours ?? "—") + " h"],
      ["Raio de influência", (gc.radius_km ?? "—") + " km"],
      ["Estações recentes", gc.stations_recent ?? "—"],
      ["UAs ancoradas", (gc.points_corrected ?? 0) + " / " + (gc.points_total ?? 0)],
      ["Overrides por consenso seco", gc.points_ground_override ?? 0],
      ["Fator médio", gc.mean_factor ?? "—"],
      ["Maior redução", gc.max_downscale != null ? "×" + gc.max_downscale : "—"],
      ["Maior aumento", gc.max_upscale != null ? "×" + gc.max_upscale : "—"],
    ];
    if (gc.error) rows.push(["Erro", gc.error]);
    card.innerHTML = head;
    card.appendChild(kvGrid(rows));
    const note = el(
      "div",
      "muted",
      "Ancoragem multiplicativa do satélite MERGE/IMERG às medições de " +
        "pluviômetros por IDW (p=2); fator da janela de 24 h aplicado a " +
        "todas as janelas. Consenso redundante de solo seco invalida " +
        "picos extremos incompatíveis do satélite."
    );
    card.appendChild(note);
    root.appendChild(card);
  }

  function renderExecControl(rootId, block) {
    const root = document.getElementById(rootId);
    if (!root || !block?.execution) return;
    const ex = block.execution;
    root.innerHTML = "";
    root.appendChild(buildToggleCard(ex));
  }

  function buildToggleCard(ex) {
    const wrap = el("div", "toggle-card");
    const head = el("div", "toggle-head");
    head.innerHTML =
      `<div><strong>Execução contínua</strong>` +
      `<div class="toggle-sub">${esc(ex.label || "")}</div></div>`;
    const btn = el("button", "toggle-btn" + (ex.enabled ? " on" : " off"));
    btn.type = "button";
    btn.dataset.system = ex.system_key;
    btn.setAttribute("aria-pressed", ex.enabled ? "true" : "false");
    btn.innerHTML =
      `<span class="toggle-track"><i></i></span>` +
      `<span class="toggle-label">${ex.enabled ? "LIGADO" : "DESLIGADO"}</span>`;
    btn.addEventListener("click", () => setAlertSystem(ex.system_key, !ex.enabled, btn));
    head.appendChild(btn);
    wrap.appendChild(head);
    return wrap;
  }

  async function setAlertSystem(system, enabled, btn) {
    if (btn) btn.disabled = true;
    try {
      const res = await fetch("/admin/api/alert-controls", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system, enabled }),
      });
      if (res.status === 401) {
        window.location = "/admin/login";
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.error || "Falha ao alterar controle");
        return;
      }
      await refresh();
    } catch (e) {
      console.warn("alert control:", e);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function renderControls() {
    const geoRoot = document.getElementById("control-geo");
    const fireRoot = document.getElementById("control-fire");
    if (!geoRoot || !fireRoot) return;
    const geo = dashboard.health.geodinamico;
    const fire = dashboard.health.risco_fogo;
    geoRoot.innerHTML = "";
    fireRoot.innerHTML = "";
    geoRoot.appendChild(buildToggleCard(geo.execution));
    geoRoot.appendChild(
      kvGrid([
        ["Status dados", fmtStatus(geo.status)],
        ["Ingest pronto", geo.merge_ingest?.ready ? "sim" : "não"],
        ["Horas em cache", geo.merge_ingest?.hours_cached_ok ?? "—"],
        ["Intervalo ingest", (geo.merge_ingest?.ingest_interval_s || "—") + " s"],
        ["Scheduler RD", "a cada 10 min"],
      ])
    );
    const ar = fire.auto_runner || {};
    const inpe = fire.inpe || {};
    fireRoot.appendChild(buildToggleCard(fire.execution));
    fireRoot.appendChild(
      kvGrid([
        ["Resolucao INPE", fire.execution?.inpe_resolution || "diaria"],
        ["Polling", "a cada " + (ar.poll_min || "—") + " min"],
        ["Arquivo INPE", inpe.latest_file || "—"],
        ["Produto local", fire.data_referencia_fmt || fmtDate(fire.data_referencia)],
        ["Atualização pendente", inpe.pending_update ? "sim" : "não"],
        ["Última execução", ar.last_run_fmt || fmtDateTime(ar.last_run)],
      ])
    );
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
        rfItems.map((i) => RF_COLORS[rfColorKey(i.label)] || "#3ec26e")
      )
    );

    renderRegionTable("stats-region-geo", geo.by_region_geo_label || geo.by_region_geo);
    renderRegionTable("stats-region-fire", fire.by_regional_label || fire.by_regional, true);
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
        .map(([k, v]) => {
          const lbl = isFire
            ? (RF_LABELS[rfColorKey(k)] || k)
            : (RD_LABELS[Number(k)] || k);
          return `${lbl}: ${v}`;
        })
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
      cols.map((c) => `<th>${esc(COL_LABELS[c] || c)}</th>`).join("") +
      "</tr></thead>";
    const tb = el("tbody");
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = cols.map((c) => {
        let val = r[c];
        if (c === "rf_classe") val = fmtRfClass(val);
        if (c === "ac96h_mm" && val != null) val = Number(val).toFixed(1);
        if (c === "rf_valor" && val != null) val = Number(val).toFixed(3);
        return `<td>${esc(val)}</td>`;
      }).join("");
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
      bar.title = (p.at_fmt || fmtDateTime(p.at)) + ": " + vals[i];
      wrap.appendChild(bar);
    });
    root.appendChild(wrap);
    const labels = el("div", "spark-labels");
    const p0 = points[0];
    const pN = points[points.length - 1];
    labels.innerHTML =
      `<span>${p0.at_fmt || fmtDateTime(p0.at)}</span>` +
      `<span>${pN.at_fmt || fmtDateTime(pN.at)}</span>`;
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
        ["Snapshot gerado", dashboard.generated_at_fmt || fmtDateTime(dashboard.generated_at)],
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
    const ov = diagnostics.overview || {};
    const pipe = diagnostics.pipeline || {};
    const sched = pipe.scheduler || {};
    const ingestSt = pipe.merge_ingest || {};

    root.appendChild(
      kvGrid([
        ["Gerado em", diagnostics.generated_at_fmt || fmtDateTime(diagnostics.generated_at)],
        ["Python", (p.python || {}).version],
        ["Hostname", (p.system || {}).hostname],
        ["Memória RSS", ((p.process || {}).memory_rss_mb || "—") + " MB"],
        ["eccodes", (p.dependencies || {}).eccodes_lib_loaded ? "OK" : "FALHA"],
        ["Uptime", fmtSec((p.process || {}).uptime_s)],
      ])
    );

    const lights = el("div", "lights mt");
    const lightLabels = {
      data: "Dados MERGE/RD",
      scheduler: "Scheduler",
      eccodes: "Decodificador GRIB",
      errors: "Erros recentes",
    };
    for (const [k, v] of Object.entries(ov.lights || {})) {
      const tile = el("div", "light-tile");
      tile.innerHTML =
        lightDot(v) +
        `<div class="light-label"><b>${esc(lightLabels[k] || k)}</b></div>`;
      lights.appendChild(tile);
    }
    root.appendChild(lights);

    root.appendChild(
      el("h3", "subhead", "Pipeline geodinâmico")
    );
    root.appendChild(
      kvGrid([
        ["Status dados", fmtStatus(ov.data_status)],
        ["Última atualização", ov.last_update_fmt || fmtDateTime(ov.last_update)],
        ["Pontos carregados", ov.points_loaded ?? "—"],
        ["Ciclos OK", (sched.cycle_success ?? "—") + " / " + (sched.cycle_count ?? "—")],
        ["Último ciclo", sched.last_started_at ? fmtDateTime(sched.last_started_at) : "—"],
        ["Duração último ciclo", fmtSec(sched.last_duration_s)],
        ["Ingest pronto", ingestSt.ready ? "sim" : "não"],
        ["Horas em cache", ingestSt.hours_cached_ok ?? "—"],
        ["Último refresh ingest", ingestSt.last_refresh_at ? fmtDateTime(ingestSt.last_refresh_at) : "—"],
      ])
    );

    const ext = diagnostics.external_sources || {};
    if (Object.keys(ext).length) {
      root.appendChild(el("h3", "subhead", "Fontes externas"));
      const t = el("table", "small-table");
      t.innerHTML =
        "<thead><tr><th>Fonte</th><th>Status</th><th>Tempo</th></tr></thead>";
      const tb = el("tbody");
      for (const src of Object.values(ext)) {
        const reach = src.reachability || {};
        const tr = document.createElement("tr");
        tr.innerHTML =
          `<td>${esc(src.name || "—")}</td>` +
          `<td>${reach.ok ? "OK" : "FALHA"}${reach.status ? " (" + reach.status + ")" : ""}</td>` +
          `<td>${reach.elapsed_ms != null ? reach.elapsed_ms + " ms" : "—"}</td>`;
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      root.appendChild(t);
    }

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

    const meth = diagnostics.methodology || {};
    if (meth.ra_mode) {
      root.appendChild(
        el("div", "subcard mt",
          `<div class="subcard-head"><b>Metodologia RD</b></div>` +
            kvGrid([
              ["Modo RA", meth.ra_mode],
              ["Pontos monitorados", meth.points_total ?? "—"],
              ["Regiões", (meth.regions || []).length],
            ]).outerHTML
        )
      );
    }

    document.getElementById("raw-diagnostics").textContent = JSON.stringify(
      diagnostics,
      null,
      2
    );
  }
})();
