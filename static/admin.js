/**
 * PLI-HazardTrack — painel administrativo (dashboard multi-seção).
 *
 * Gráficos em SVG puro (sem dependências), renderizados na largura real
 * do card e refeitos ao trocar de seção ou redimensionar a janela.
 */
(function () {
  "use strict";

  function appPath(path) {
    const prefix = window.__BASE_PATH__ || "";
    if (!prefix || path.startsWith(prefix + "/")) return path;
    return prefix + path;
  }

  const PANEL_META = {
    visao: ["Visão geral", "Panorama dos dois módulos de monitoramento"],
    saude: ["Saúde dos sistemas", "Semáforos, pipelines e fontes de dados"],
    controles: [
      "Controles de alerta",
      "Ligar ou desligar cada sistema (default: ligado)",
    ],
    estatisticas: ["Estatísticas", "Distribuição atual dos níveis monitorados"],
    analytics: ["Analytics", "Evolução do risco, chuva e qualidade do dado"],
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
  const RF_ORDER = ["minimo", "baixo", "medio", "alto", "critico", "SEM_DADO"];
  const REGION_COLORS = ["#003b5a", "#2aa358", "#f97316", "#8b5cf6", "#0ea5e9", "#b45309"];
  const NAVY = "#003b5a";
  const GREEN = "#2aa358";
  const INK3 = "#94a3b8";

  const RD_LABELS = {
    0: "Monitoramento",
    1: "Observação",
    2: "Atenção",
    3: "Alerta",
    4: "Alerta Máximo",
  };
  const RD_SHORT = ["N0", "N1", "N2", "N3", "N4"];
  const RD_AXIS = ["Monit.", "Observ.", "Atenção", "Alerta", "Máximo"];

  const RF_LABELS = {
    minimo: "Mínimo",
    baixo: "Baixo",
    medio: "Médio",
    alto: "Alto",
    critico: "Crítico",
    SEM_DADO: "Sem dado",
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
    skipped: "Ignorado",
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
  let analyticsHours = 24;
  let activePanel = "visao";

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
  document.querySelectorAll("#analytics-range button").forEach((b) => {
    b.addEventListener("click", () => setAnalyticsRange(Number(b.dataset.hours)));
  });

  try {
    const saved = Number(localStorage.getItem("pli_admin_hours"));
    if ([6, 24, 72, 168].includes(saved)) analyticsHours = saved;
  } catch (e) { /* storage indisponível */ }
  syncRangeButtons();

  const hash = location.hash.replace("#", "");
  if (hash && PANEL_META[hash]) showPanel(hash);
  else showPanel("visao");

  setInterval(refresh, 60_000);
  refresh();

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => renderPanel(activePanel), 150);
  });

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
      const res = await fetch(appPath(`/admin/api/refresh/${system}`), {
        method: "POST",
        credentials: "same-origin",
      });
      if (res.status === 401) {
        window.location = appPath("/admin/login");
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
      const res = await fetch(appPath("/admin/api/refresh/status"), {
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
    activePanel = id;
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
    // Gráficos medem a largura do card: refaz ao exibir a seção.
    renderPanel(id);
  }

  function renderPanel(id) {
    if (!dashboard) return;
    if (id === "estatisticas") renderStats();
    else if (id === "analytics") renderAnalytics();
    else if (id === "visao") renderOverview();
  }

  async function refresh() {
    try {
      const [dashRes, diagRes] = await Promise.all([
        fetch(appPath(`/admin/api/dashboard?hours=${analyticsHours}`), {
          credentials: "same-origin",
        }),
        fetch(appPath("/admin/api/diagnostics"), { credentials: "same-origin" }),
      ]);
      if (dashRes.status === 401) {
        window.location = appPath("/admin/login");
        return;
      }
      dashboard = await dashRes.json();
      if (diagRes.ok) diagnostics = await diagRes.json();
      renderAll();
    } catch (e) {
      console.warn("admin refresh:", e);
    }
  }

  async function setAnalyticsRange(hours) {
    if (!hours || hours === analyticsHours) return;
    analyticsHours = hours;
    try { localStorage.setItem("pli_admin_hours", String(hours)); } catch (e) { /* noop */ }
    syncRangeButtons();
    try {
      const res = await fetch(appPath(`/admin/api/analytics?hours=${hours}`), {
        credentials: "same-origin",
      });
      if (res.status === 401) {
        window.location = appPath("/admin/login");
        return;
      }
      if (!res.ok || !dashboard) return;
      dashboard.analytics = await res.json();
      renderAnalytics();
    } catch (e) {
      console.warn("analytics range:", e);
    }
  }

  function syncRangeButtons() {
    document.querySelectorAll("#analytics-range button").forEach((b) => {
      b.classList.toggle("active", Number(b.dataset.hours) === analyticsHours);
    });
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
  function dtParts(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
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
    return {
      day: get("day"), month: get("month"), year: get("year"),
      hour: get("hour") === "24" ? "00" : get("hour"),
      minute: get("minute"), second: get("second"),
    };
  }
  function fmtDateTime(iso) {
    if (!iso) return "—";
    const p = dtParts(iso);
    if (!p) return String(iso);
    return (
      p.day + "/" + p.month + "/" + p.year + " " +
      p.hour + ":" + p.minute + ":" + p.second
    );
  }
  function fmtShort(iso) {
    if (!iso) return "";
    const p = dtParts(iso);
    if (!p) return String(iso);
    return p.day + "/" + p.month + " " + p.hour + ":" + p.minute;
  }
  function fmtHour(iso) {
    if (!iso) return "";
    const p = dtParts(iso);
    if (!p) return String(iso);
    return p.hour + "h";
  }

  function fmtDate(value) {
    if (!value) return "—";
    const text = String(value);
    const m = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return m[3] + "/" + m[2] + "/" + m[1];
    return fmtDateTime(value).slice(0, 10);
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
    s = Number(s);
    if (s < 60) return s.toFixed(1) + " s";
    if (s < 3600) return (s / 60).toFixed(1) + " min";
    if (s < 86400) return (s / 3600).toFixed(1) + " h";
    return (s / 86400).toFixed(1) + " d";
  }
  function fmtNum(v, digits) {
    if (v == null || v === "" || Number.isNaN(Number(v))) return "—";
    return Number(v).toLocaleString("pt-BR", {
      minimumFractionDigits: digits ?? 0,
      maximumFractionDigits: digits ?? 0,
    });
  }
  function fmtKm(a, b) {
    if (a == null && b == null) return "—";
    const f = (v) => (v == null ? "?" : Number(v).toFixed(1));
    return f(a) + "–" + f(b);
  }
  function signed(v) {
    if (v == null) return "—";
    if (v > 0) return "+" + v;
    return String(v);
  }
  function lightDot(state) {
    return `<span class="light-dot light-${state || "warn"}"></span>`;
  }
  function kvGrid(rows, cols) {
    const g = el("div", "kv-grid" + (cols ? " kv-grid--" + cols : ""));
    for (const [k, v] of rows) {
      const row = el("div", "kv");
      row.appendChild(el("span", "kv-k", esc(k)));
      row.appendChild(el("span", "kv-v", esc(v)));
      g.appendChild(row);
    }
    return g;
  }
  function emptyMsg(root, text) {
    root.innerHTML = `<p class="empty">${esc(text)}</p>`;
  }
  function levelChip(n, count) {
    return `<span class="lvl-chip" style="--c:${RD_COLORS[n]}">${RD_SHORT[n]}<b>${count}</b></span>`;
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
        `<div class="bar-track"><i style="width:${pct}%;background:${colors[i] || GREEN}"></i></div>` +
        `<span class="bar-val">${fmtNum(it.value)} <small>(${pct}%)</small></span>`;
      wrap.appendChild(row);
    }
    return wrap;
  }

  // ---- SVG charts ------------------------------------------------------
  const SVG_NS = "http://www.w3.org/2000/svg";
  function svgEl(tag, attrs, text) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    return e;
  }
  function chartWidth(root, fallback) {
    const w = root.clientWidth || root.parentElement?.clientWidth || 0;
    return Math.max(280, w || fallback || 560);
  }
  function niceMax(v) {
    if (!(v > 0)) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const n = v / p;
    let m;
    if (n <= 1) m = 1;
    else if (n <= 2) m = 2;
    else if (n <= 2.5) m = 2.5;
    else if (n <= 5) m = 5;
    else m = 10;
    return m * p;
  }
  function fmtTick(v) {
    if (Math.abs(v) >= 1000) return (v / 1000).toFixed(1).replace(/\.0$/, "") + "k";
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(Math.abs(v) < 1 ? 2 : 1);
  }

  /**
   * Gráfico de linhas/áreas empilhadas.
   * opts: { labels[], series:[{name,color,values[],fill,dash,width}],
   *         stacked, yMax, yMin, height, unit, xTicks, hoverText(i) }
   */
  function lineChart(root, opts) {
    root.innerHTML = "";
    const W = chartWidth(root);
    const H = opts.height || 220;
    const padL = 40, padR = 12, padT = 10, padB = 26;
    const iw = W - padL - padR;
    const ih = H - padT - padB;
    const n = opts.labels.length;
    if (n < 2) {
      emptyMsg(root, opts.emptyText || "Histórico insuficiente.");
      return;
    }
    const svg = svgEl("svg", {
      class: "chart-svg", width: W, height: H,
      viewBox: `0 0 ${W} ${H}`, role: "img",
    });
    const series = opts.series;
    let stackTop = null;
    let yMax = opts.yMax;
    if (opts.stacked) {
      stackTop = new Array(n).fill(0);
      for (const s of series) {
        for (let i = 0; i < n; i++) stackTop[i] += Number(s.values[i]) || 0;
      }
      if (yMax == null) yMax = Math.max(...stackTop);
    } else if (yMax == null) {
      yMax = 0;
      for (const s of series) {
        for (const v of s.values) if (v != null && v > yMax) yMax = Number(v);
      }
    }
    const yMin = opts.yMin ?? 0;
    yMax = opts.exactMax ? yMax : niceMax(yMax || 1);
    if (yMax <= yMin) yMax = yMin + 1;
    const x = (i) => padL + (iw * i) / (n - 1);
    const y = (v) => padT + ih - ((Math.min(Math.max(v, yMin), yMax) - yMin) / (yMax - yMin)) * ih;

    // grade + eixo Y
    const ticks = 4;
    for (let t = 0; t <= ticks; t++) {
      const v = yMin + ((yMax - yMin) * t) / ticks;
      const yy = y(v);
      svg.appendChild(svgEl("line", {
        x1: padL, x2: W - padR, y1: yy, y2: yy, class: "grid-line",
      }));
      svg.appendChild(svgEl("text", {
        x: padL - 6, y: yy + 3.5, class: "axis-text", "text-anchor": "end",
      }, fmtTick(v)));
    }
    // eixo X: até 6 rótulos
    const xt = Math.min(opts.xTicks || 6, n);
    for (let t = 0; t < xt; t++) {
      const i = Math.round(((n - 1) * t) / (xt - 1 || 1));
      svg.appendChild(svgEl("text", {
        x: x(i), y: H - 8, class: "axis-text",
        "text-anchor": t === 0 ? "start" : (t === xt - 1 ? "end" : "middle"),
      }, opts.labels[i]));
    }

    // áreas empilhadas (de baixo para cima)
    if (opts.stacked) {
      const base = new Array(n).fill(0);
      for (const s of series) {
        const top = base.map((b, i) => b + (Number(s.values[i]) || 0));
        let d = "";
        for (let i = 0; i < n; i++) d += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(top[i]).toFixed(1);
        for (let i = n - 1; i >= 0; i--) d += "L" + x(i).toFixed(1) + " " + y(base[i]).toFixed(1);
        d += "Z";
        svg.appendChild(svgEl("path", { d, fill: s.color, "fill-opacity": 0.85 }));
        for (let i = 0; i < n; i++) base[i] = top[i];
      }
    } else {
      for (const s of series) {
        let d = "";
        let started = false;
        for (let i = 0; i < n; i++) {
          const v = s.values[i];
          if (v == null || Number.isNaN(Number(v))) { started = false; continue; }
          d += (started ? "L" : "M") + x(i).toFixed(1) + " " + y(Number(v)).toFixed(1);
          started = true;
        }
        if (s.fill) {
          let area = "";
          let first = null, last = null;
          for (let i = 0; i < n; i++) {
            const v = s.values[i];
            if (v == null) continue;
            if (first == null) first = i;
            last = i;
            area += (area ? "L" : "M") + x(i).toFixed(1) + " " + y(Number(v)).toFixed(1);
          }
          if (first != null) {
            area += `L${x(last).toFixed(1)} ${y(yMin).toFixed(1)}L${x(first).toFixed(1)} ${y(yMin).toFixed(1)}Z`;
            svg.appendChild(svgEl("path", { d: area, fill: s.color, "fill-opacity": 0.12 }));
          }
        }
        svg.appendChild(svgEl("path", {
          d, fill: "none", stroke: s.color, "stroke-width": s.width || 1.8,
          "stroke-dasharray": s.dash || "", "stroke-linejoin": "round",
        }));
      }
    }
    // marcas de referência horizontais (limiares)
    for (const ref of opts.refs || []) {
      const yy = y(ref.value);
      svg.appendChild(svgEl("line", {
        x1: padL, x2: W - padR, y1: yy, y2: yy, stroke: ref.color || INK3,
        "stroke-dasharray": "4 3", "stroke-width": 1,
      }));
      svg.appendChild(svgEl("text", {
        x: W - padR, y: yy - 3, class: "axis-text", "text-anchor": "end",
      }, ref.label));
    }
    // áreas de hover com tooltip nativo
    if (opts.hoverText) {
      const step = iw / (n - 1);
      for (let i = 0; i < n; i++) {
        const r = svgEl("rect", {
          x: x(i) - step / 2, y: padT, width: step, height: ih,
          fill: "transparent", class: "hover-col",
        });
        r.appendChild(svgEl("title", {}, opts.hoverText(i)));
        svg.appendChild(r);
      }
    }
    root.appendChild(svg);
    if (opts.legend !== false) root.appendChild(legend(series));
  }

  function legend(series) {
    const lg = el("div", "legend");
    for (const s of series) {
      if (s.legend === false) continue;
      lg.innerHTML += `<span class="legend-item"><i style="background:${s.color}"></i>${esc(s.name)}</span>`;
    }
    return lg;
  }

  /**
   * Barras verticais agrupadas/empilhadas.
   * opts: { groups:[{label, values:[..]}], series:[{name,color}], stacked,
   *         height, valueFmt }
   */
  function barsChart(root, opts) {
    root.innerHTML = "";
    const W = chartWidth(root);
    const H = opts.height || 220;
    const padL = 40, padR = 8, padT = 12, padB = 26;
    const iw = W - padL - padR;
    const ih = H - padT - padB;
    const groups = opts.groups;
    const ns = opts.series.length;
    if (!groups.length) {
      emptyMsg(root, opts.emptyText || "Sem dados.");
      return;
    }
    let yMax = 0;
    for (const g of groups) {
      if (opts.stacked) yMax = Math.max(yMax, g.values.reduce((a, b) => a + (Number(b) || 0), 0));
      else yMax = Math.max(yMax, ...g.values.map((v) => Number(v) || 0));
    }
    yMax = niceMax(yMax || 1);
    const svg = svgEl("svg", {
      class: "chart-svg", width: W, height: H, viewBox: `0 0 ${W} ${H}`,
    });
    const y = (v) => padT + ih - (v / yMax) * ih;
    for (let t = 0; t <= 4; t++) {
      const v = (yMax * t) / 4;
      svg.appendChild(svgEl("line", {
        x1: padL, x2: W - padR, y1: y(v), y2: y(v), class: "grid-line",
      }));
      svg.appendChild(svgEl("text", {
        x: padL - 6, y: y(v) + 3.5, class: "axis-text", "text-anchor": "end",
      }, fmtTick(v)));
    }
    const gw = iw / groups.length;
    const inner = gw * 0.72;
    const bw = opts.stacked ? inner : inner / ns;
    groups.forEach((g, gi) => {
      const gx = padL + gw * gi + (gw - inner) / 2;
      let stackBase = 0;
      g.values.forEach((v, si) => {
        v = Number(v) || 0;
        const s = opts.series[si];
        let x0, y0, h;
        if (opts.stacked) {
          x0 = gx;
          h = (v / yMax) * ih;
          y0 = y(stackBase + v);
          stackBase += v;
        } else {
          x0 = gx + bw * si;
          h = (v / yMax) * ih;
          y0 = y(v);
        }
        const rect = svgEl("rect", {
          x: x0.toFixed(1), y: y0.toFixed(1), width: Math.max(1, bw - 2).toFixed(1),
          height: Math.max(0, h).toFixed(1), fill: s.color, rx: 2,
        });
        rect.appendChild(svgEl("title", {}, `${g.label} · ${s.name}: ${opts.valueFmt ? opts.valueFmt(v) : fmtNum(v)}`));
        svg.appendChild(rect);
        if (!opts.stacked && opts.showValues && v > 0) {
          svg.appendChild(svgEl("text", {
            x: (x0 + bw / 2).toFixed(1), y: (y0 - 3).toFixed(1),
            class: "axis-text", "text-anchor": "middle",
          }, fmtTick(v)));
        }
      });
      if (opts.stacked && opts.showValues && stackBase > 0) {
        svg.appendChild(svgEl("text", {
          x: (gx + inner / 2).toFixed(1), y: (y(stackBase) - 3).toFixed(1),
          class: "axis-text", "text-anchor": "middle",
        }, fmtTick(stackBase)));
      }
      svg.appendChild(svgEl("text", {
        x: (gx + inner / 2).toFixed(1), y: H - 8, class: "axis-text", "text-anchor": "middle",
      }, g.label));
    });
    root.appendChild(svg);
    if (opts.legend !== false) root.appendChild(legend(opts.series));
  }

  function trailSvg(values) {
    const n = values.length;
    const W = 72, H = 18;
    if (!n) return "";
    const x = (i) => (n === 1 ? W / 2 : (W - 2) * (i / (n - 1)) + 1);
    const y = (v) => H - 2 - (v / 4) * (H - 4);
    let d = "";
    values.forEach((v, i) => { d += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); });
    const last = values[n - 1];
    return `<svg class="trail" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true">` +
      `<path d="${d}" fill="none" stroke="${RD_COLORS[last]}" stroke-width="1.6"/>` +
      `<circle cx="${x(n - 1).toFixed(1)}" cy="${y(last).toFixed(1)}" r="2" fill="${RD_COLORS[last]}"/></svg>`;
  }

  // ---- visão geral -----------------------------------------------------
  function renderOverview() {
    const ov = dashboard.overview;
    const geo = dashboard.stats.geodinamico;
    const fire = dashboard.stats.risco_fogo;
    const kpi = document.getElementById("kpi-overview");
    kpi.innerHTML = "";
    const cards = [
      ["RD máximo", ov.geodinamico.max_rd, RD_LABELS[ov.geodinamico.max_rd] || ov.geodinamico.max_rd_label, "geo"],
      ["UAs monitoradas", fmtNum(ov.geodinamico.uas_monitoradas), geo.uas_geo + " encosta · " + geo.uas_hidro + " inundação", "geo"],
      ["Alertas RD (3+4)", fmtNum(ov.geodinamico.alertas_rd), "unidades em Alerta ou Alerta Máximo", "geo warn"],
      ["Trechos fogo", fmtNum(ov.risco_fogo.total_trechos), "malha DER monitorada", "fire"],
      ["RF alto/crítico", fmtNum(ov.risco_fogo.alertas_rf), "trechos nas duas classes superiores", "fire warn"],
      ["Referência fogo", ov.risco_fogo.data_referencia_fmt || fmtDate(ov.risco_fogo.data_referencia) || "—", "arquivo observado INPE", "fire"],
    ];
    for (const [label, val, sub, mod] of cards) kpi.appendChild(kpiCard(label, val, sub, mod));

    const vg = document.getElementById("visao-geo");
    vg.innerHTML = "";
    vg.appendChild(
      kvGrid([
        ["Status", fmtStatus(geo.data_status)],
        ["Última atualização", geo.last_update_fmt || fmtDateTime(geo.last_update)],
        ["Fonte chuva", geo.data_source || "—"],
        ["Horas faltando (24 h)", geo.missing_24h ?? "—"],
      ], 2)
    );
    const lv = levelsArr(geo.by_level);
    const rdItems = [0, 1, 2, 3, 4].map((n) => ({
      label: RD_SHORT[n] + " " + RD_LABELS[n],
      value: lv[n],
    }));
    vg.appendChild(barChart(rdItems, RD_COLORS));

    const vf = document.getElementById("visao-fire");
    vf.innerHTML = "";
    vf.appendChild(
      kvGrid([
        ["Status", fmtStatus(dashboard.health.risco_fogo.status)],
        ["Data referência", fire.data_referencia_fmt || fmtDate(fire.data_referencia)],
        ["Metodologia", fire.metodologia || dashboard.health.risco_fogo.metodologia || "—"],
        ["Horizontes", (fire.horizontes || []).join(", ") || "—"],
      ], 2)
    );
    const rfItems = RF_ORDER
      .filter((k) => fire.classes && fire.classes[k] != null)
      .map((k) => ({ label: RF_LABELS[k], value: Number(fire.classes[k]) }));
    vf.appendChild(
      barChart(rfItems, rfItems.map((i) => RF_COLORS[rfColorKey(i.label)] || GREEN))
    );
  }

  function kpiCard(label, value, sub, mod) {
    const c = el("div", "kpi-card " + (mod || ""));
    c.innerHTML =
      `<small>${esc(label)}</small><strong>${esc(value)}</strong>` +
      `<span class="kpi-sub">${esc(sub || "")}</span>`;
    return c;
  }

  // ---- saúde -----------------------------------------------------------
  function renderHealth() {
    renderHealthBlock("health-geo", dashboard.health.geodinamico, "geo");
    renderHealthBlock("health-fire", dashboard.health.risco_fogo, "fire");
    renderExecControl("exec-geo", dashboard.health.geodinamico);
    renderExecControl("exec-fire", dashboard.health.risco_fogo);

    const tbody = document.querySelector("#cycle-history tbody");
    tbody.innerHTML = "";
    const ana = dashboard.analytics || {};
    const rows = ana.recent_cycles || [];
    const note = document.getElementById("cycle-history-note");
    if (note) {
      note.textContent = ana.ops?.persisted_total
        ? `${fmtNum(ana.ops.persisted_total)} ciclos persistidos em disco`
        : "";
    }
    if (!rows.length) {
      tbody.innerHTML =
        '<tr><td colspan="9" class="empty">Sem ciclos registrados.</td></tr>';
      return;
    }
    for (const h of rows) {
      const tr = document.createElement("tr");
      tr.className = h.outcome === "ok" ? "row-ok" : "row-fail";
      const lv = Array.isArray(h.by_level) ? h.by_level : null;
      const alerts = h.alert_count ?? (lv ? lv[3] + lv[4] : "—");
      tr.innerHTML =
        `<td>${esc(h.started_at_fmt || fmtDateTime(h.started_at))}</td>` +
        `<td>${fmtSec(h.duration_s)}</td>` +
        `<td class="outcome">${esc(fmtStatus(h.outcome))}</td>` +
        `<td>${esc(fmtStatus(h.data_status || ""))}</td>` +
        `<td class="num">${esc(h.max_rd ?? "—")}</td>` +
        `<td class="num">${esc(alerts)}</td>` +
        `<td class="num">${h.ac24h_max != null ? fmtNum(h.ac24h_max, 1) + " mm" : "—"}</td>` +
        `<td class="num">${esc(h.files_ok ?? "—")}</td>` +
        `<td>${h.error ? "<code>" + esc(h.error) + "</code>" : ""}</td>`;
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
    const order = Object.keys(labels).filter((k) => k in (block.lights || {}));
    for (const k of Object.keys(block.lights || {})) if (!order.includes(k)) order.push(k);
    for (const k of order) {
      const tile = el("div", "light-tile");
      tile.innerHTML =
        lightDot(block.lights[k]) +
        `<div class="light-label"><b>${esc(labels[k] || k)}</b></div>`;
      lights.appendChild(tile);
    }
    root.appendChild(lights);

    if (kind === "geo") {
      root.appendChild(
        kvGrid([
          ["Status", fmtStatus(block.status)],
          ["Ciclos OK (processo)", block.scheduler.cycle_success + " / " + block.scheduler.cycle_count],
          ["Última duração", fmtSec(block.scheduler.last_duration_s)],
          ["Horas válidas (96 h)", block.data_quality.files_ok ?? "—"],
          ["Faltando 24 h", block.data_quality.missing_24h ?? "—"],
          ["Faltando 96 h", block.data_quality.missing_96h ?? "—"],
        ], 2)
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
        ], 2)
      );
    }
  }

  function renderGaugeCorrection(root, gc) {
    if (!gc) return;
    const card = el("div", "kv-section");
    const head = "<b>Correção por solo (DAEE/CEMADEN)</b>";
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
      ["Overrides (consenso seco)", gc.points_ground_override ?? 0],
      ["Fator médio", gc.mean_factor ?? "—"],
      ["Maior redução", gc.max_downscale != null ? "×" + gc.max_downscale : "—"],
      ["Maior aumento", gc.max_upscale != null ? "×" + gc.max_upscale : "—"],
    ];
    if (gc.error) rows.push(["Erro", gc.error]);
    card.innerHTML = head;
    card.appendChild(kvGrid(rows, 2));
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
      const res = await fetch(appPath("/admin/api/alert-controls"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system, enabled }),
      });
      if (res.status === 401) {
        window.location = appPath("/admin/login");
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
        ["Último refresh ingest", geo.merge_ingest?.last_refresh_at ? fmtDateTime(geo.merge_ingest.last_refresh_at) : "—"],
      ], 2)
    );
    const ar = fire.auto_runner || {};
    const inpe = fire.inpe || {};
    fireRoot.appendChild(buildToggleCard(fire.execution));
    fireRoot.appendChild(
      kvGrid([
        ["Resolução INPE", fire.execution?.inpe_resolution || "diária"],
        ["Polling", "a cada " + (ar.poll_min || "—") + " min"],
        ["Arquivo INPE", inpe.latest_file || "—"],
        ["Produto local", fire.data_referencia_fmt || fmtDate(fire.data_referencia)],
        ["Atualização pendente", inpe.pending_update ? "sim" : "não"],
        ["Última execução", ar.last_run_fmt || fmtDateTime(ar.last_run)],
      ], 2)
    );
  }

  // ---- estatísticas ----------------------------------------------------
  function renderStats() {
    const geo = dashboard.stats.geodinamico;
    const fire = dashboard.stats.risco_fogo;
    const levelsGeo = levelsArr(geo.by_level_geo);
    const levelsHid = levelsArr(geo.by_level_hidro);

    document.getElementById("stats-rd-note").textContent =
      fmtNum(geo.uas_geo) + " + " + fmtNum(geo.uas_hidro) + " UAs · " +
      (geo.last_update_fmt || fmtDateTime(geo.last_update));
    barsChart(document.getElementById("stats-rd-bars"), {
      groups: [0, 1, 2, 3, 4].map((n) => ({
        label: RD_SHORT[n] + " " + RD_AXIS[n],
        values: [levelsGeo[n], levelsHid[n]],
      })),
      series: [
        { name: "Encosta (RDGEO)", color: NAVY },
        { name: "Inundação (RDHID)", color: GREEN },
      ],
      height: 220,
      showValues: true,
    });

    document.getElementById("stats-rf-note").textContent =
      fmtNum(fire.total_trechos) + " trechos · ref. " +
      (fire.data_referencia_fmt || fmtDate(fire.data_referencia));
    const classes = fire.classes || {};
    barsChart(document.getElementById("stats-rf-bars"), {
      groups: RF_ORDER.map((k) => ({
        label: RF_LABELS[k],
        values: [Number(classes[k] || 0)],
        color: RF_COLORS[k],
      })),
      series: [{ name: "Trechos (observado)", color: "#f97316" }],
      height: 220,
      showValues: true,
      legend: false,
    });
    // cor por classe (uma série): recolore as barras
    document.querySelectorAll("#stats-rf-bars rect").forEach((r, i) => {
      r.setAttribute("fill", RF_COLORS[RF_ORDER[i]] || "#f97316");
    });

    renderRegionLevelMatrix("stats-region-geo", geo.regional?.regions || []);
    renderFireRegionalMatrix("stats-region-fire", fire.by_regional || {});
    renderRegionRainTable("stats-region-rain", geo.regional?.regions || []);

    renderTopTable("stats-top-fire", fire.top_trechos, [
      ["rodovia", "Rodovia"],
      ["km", "Km"],
      ["municipio", "Município"],
      ["regional", "Regional"],
      ["rf_valor", "RF", "num"],
      ["rf_classe", "Classe"],
    ], 10);
    const uaCols = [
      ["ua_id", "UA"],
      ["sigla_rodovia", "Rodovia"],
      ["km", "Km"],
      ["rd", "RD", "num"],
      ["ac24h_mm", "24 h mm", "num"],
      ["ac96h_mm", "96 h mm", "num"],
      ["intensity_mmh", "I mm/h", "num"],
      ["cpc", "CPC", "num"],
    ];
    renderTopTable("stats-top-geo", geo.top_uas_geo, uaCols, 10);
    renderTopTable("stats-top-hidro", geo.top_uas_hidro, uaCols, 10);
  }

  function levelsArr(d) {
    if (Array.isArray(d)) return d.map((v) => Number(v) || 0);
    d = d || {};
    return [0, 1, 2, 3, 4].map((i) => Number(d[i] ?? d[String(i)] ?? 0));
  }

  function renderRegionLevelMatrix(id, regions) {
    const root = document.getElementById(id);
    root.innerHTML = "";
    if (!regions.length) return emptyMsg(root, "Sem regiões no snapshot.");
    const t = el("table", "matrix-table");
    t.innerHTML =
      "<thead><tr><th>Região</th><th>Canal</th><th class='num'>UAs</th>" +
      [0, 1, 2, 3, 4].map((n) => `<th class="num" style="--c:${RD_COLORS[n]}"><i class="sw"></i>${RD_SHORT[n]}</th>`).join("") +
      "</tr></thead>";
    const tb = el("tbody");
    for (const r of regions) {
      const name = `${esc(r.regiao_nome || "R" + r.regiao_id)}<small>${esc(r.sigla_rodovia || "")}</small>`;
      const rows = [
        ["Encosta", r.uas_geo, r.levels_geo],
        ["Inundação", r.uas_hidro, r.levels_hidro],
      ];
      rows.forEach(([canal, total, lv], i) => {
        const tr = document.createElement("tr");
        if (i === 0) tr.className = "group-start";
        tr.innerHTML =
          (i === 0 ? `<td rowspan="2" class="region-cell">${name}</td>` : "") +
          `<td>${canal}</td><td class="num">${fmtNum(total)}</td>` +
          (lv || [0, 0, 0, 0, 0]).map((v, n) =>
            `<td class="num lvl${v > 0 && n >= 2 ? " hot" : ""}" style="--c:${RD_COLORS[n]}">${v ? fmtNum(v) : "·"}</td>`
          ).join("");
        tb.appendChild(tr);
      });
    }
    t.appendChild(tb);
    root.appendChild(el("div", "table-wrap")).appendChild(t);
  }

  function renderFireRegionalMatrix(id, byRegional) {
    const root = document.getElementById(id);
    root.innerHTML = "";
    const entries = Object.entries(byRegional || {});
    if (!entries.length) return emptyMsg(root, "Sem dados.");
    const order = ["critico", "alto", "medio", "baixo", "minimo", "SEM_DADO"];
    entries.sort((a, b) =>
      (Number(b[1].critico || 0) + Number(b[1].alto || 0)) -
      (Number(a[1].critico || 0) + Number(a[1].alto || 0))
    );
    const t = el("table", "matrix-table");
    t.innerHTML =
      "<thead><tr><th>Regional</th><th class='num'>Trechos</th>" +
      order.map((k) => `<th class="num" style="--c:${RF_COLORS[k]}"><i class="sw"></i>${RF_LABELS[k]}</th>`).join("") +
      "</tr></thead>";
    const tb = el("tbody");
    for (const [reg, counts] of entries) {
      const total = Object.values(counts).reduce((a, b) => a + Number(b || 0), 0);
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td class="region-cell">${esc(reg)}</td><td class="num">${fmtNum(total)}</td>` +
        order.map((k) => {
          const v = Number(counts[k] || 0);
          const hot = v > 0 && (k === "critico" || k === "alto");
          return `<td class="num lvl${hot ? " hot" : ""}" style="--c:${RF_COLORS[k]}">${v ? fmtNum(v) : "·"}</td>`;
        }).join("");
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    root.appendChild(el("div", "table-wrap")).appendChild(t);
  }

  function renderRegionRainTable(id, regions) {
    const root = document.getElementById(id);
    root.innerHTML = "";
    if (!regions.length) return emptyMsg(root, "Sem regiões no snapshot.");
    const t = el("table", "matrix-table matrix-table--dense");
    t.innerHTML =
      "<thead><tr><th>Região</th>" +
      "<th class='num'>24h máx</th><th class='num'>24h p90</th><th class='num'>24h méd.</th>" +
      "<th class='num'>96h máx</th><th class='num'>I máx</th><th class='num'>CPC máx</th>" +
      "<th class='num'>Limiares 24h</th></tr></thead>";
    const tb = el("tbody");
    for (const r of regions) {
      const tr = document.createElement("tr");
      const br = (r.hid24h_breaks || []).join(" · ");
      tr.innerHTML =
        `<td class="region-cell">${esc(r.regiao_nome)}<small>${esc(r.sigla_rodovia || "")}</small></td>` +
        `<td class="num"><b>${fmtNum(r.ac24h_max, 1)}</b></td>` +
        `<td class="num">${fmtNum(r.ac24h_p90, 1)}</td>` +
        `<td class="num">${fmtNum(r.ac24h_mean, 1)}</td>` +
        `<td class="num">${fmtNum(r.ac96h_max, 1)}</td>` +
        `<td class="num">${fmtNum(r.intensity_max, 2)}</td>` +
        `<td class="num">${fmtNum(r.cpc_max, 2)}</td>` +
        `<td class="num muted">${esc(br || "—")}</td>`;
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    root.appendChild(el("div", "table-wrap")).appendChild(t);
    root.appendChild(el("p", "card-foot",
      "mm nas janelas usadas pelo RD (24 h hidrológica · 96 h geológica) · I = intensidade horária · CPC = coeficiente de precipitação crítica"));
  }

  function renderTopTable(id, rows, cols, limit) {
    const root = document.getElementById(id);
    root.innerHTML = "";
    if (!rows || !rows.length) {
      return emptyMsg(root, "Sem registros elevados no momento.");
    }
    const t = el("table", "small-table");
    t.innerHTML =
      "<thead><tr>" +
      cols.map(([, label, cls]) => `<th class="${cls || ""}">${esc(label)}</th>`).join("") +
      "</tr></thead>";
    const tb = el("tbody");
    for (const r of rows.slice(0, limit || rows.length)) {
      const tr = document.createElement("tr");
      tr.innerHTML = cols.map(([c, , cls]) => {
        let val = r[c];
        if (c === "km") val = fmtKm(r.km_inicial ?? r.km_ini, r.km_final ?? r.km_fim);
        else if (c === "rf_classe") return `<td><span class="cls-chip" style="--c:${RF_COLORS[val] || INK3}">${esc(fmtRfClass(val))}</span></td>`;
        else if (c === "rd") return `<td class="num"><span class="cls-chip" style="--c:${RD_COLORS[val] || INK3}">${esc(val)}</span></td>`;
        else if (c === "ac96h_mm" || c === "ac24h_mm") val = fmtNum(val, 1);
        else if (c === "intensity_mmh" || c === "cpc") val = fmtNum(val, 2);
        else if (c === "rf_valor") val = fmtNum(val, 3);
        return `<td class="${cls || ""}">${esc(val ?? "—")}</td>`;
      }).join("");
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    t.classList.add("small-table--dense");
    root.appendChild(el("div", "table-wrap")).appendChild(t);
  }

  // ---- analytics -------------------------------------------------------
  function renderAnalytics() {
    const ana = dashboard.analytics;
    if (!ana || !ana.headline) return;
    syncRangeButtons();
    document.getElementById("analytics-window-label").textContent =
      "Janela de análise · " + (ana.series?.count || 0) + " ciclos";
    renderAnalyticsKpis(ana);
    renderLevelsChart(ana);
    renderHourlyChart(ana);
    renderThresholds(ana);
    renderEscalation(ana);
    renderDistributions(ana);
    renderFireHorizons(ana);
    renderQualityChart(ana);
    renderOps(ana);
  }

  function renderAnalyticsKpis(ana) {
    const h = ana.headline;
    const esc_ = ana.escalation || {};
    const kpi = document.getElementById("kpi-analytics");
    kpi.innerHTML = "";
    const d1 = h.alert_delta_1h, d24 = h.alert_delta_24h;
    const deltaTxt =
      (d1 == null ? "Δ1h —" : "Δ1h " + signed(d1)) + " · " +
      (d24 == null ? "Δ24h —" : "Δ24h " + signed(d24));
    const compl = h.files_ok != null ? Math.round((100 * h.files_ok) / 96) + "%" : "—";
    const dataBad = h.data_status && h.data_status !== "ok";
    const cards = [
      ["UAs em alerta (3+4)", fmtNum(h.alert_count), deltaTxt, "geo" + (h.alert_count > 0 ? " warn" : "")],
      ["UAs em escalada (≈1 h)", esc_.available ? fmtNum(esc_.up_1h) : "—",
        esc_.available ? "↓ " + fmtNum(esc_.down_1h) + " em recuo · ≈4 h: ↑" + fmtNum(esc_.up_4h) + " ↓" + fmtNum(esc_.down_4h) : "sem histórico nesta execução",
        "geo" + (esc_.up_1h > 0 ? " warn" : "")],
      ["Chuva 24 h máxima", h.ac24h_max != null ? fmtNum(h.ac24h_max, 1) + " mm" : "—",
        h.ac96h_max != null ? "96 h máx " + fmtNum(h.ac96h_max, 1) + " mm" : "último ciclo", "rain"],
      ["Intensidade máxima", h.intensity_max != null ? fmtNum(h.intensity_max, 2) + " mm/h" : "—", "hora mais recente do MERGE", "rain"],
      ["Completude MERGE", compl, (h.files_ok ?? "—") + " / 96 h · faltando 24 h: " + (h.missing_24h ?? "—") + " · " + fmtStatus(h.data_status), "data" + (dataBad ? " warn" : "")],
      ["Fator correção solo", h.gauge_factor != null ? "×" + fmtNum(h.gauge_factor, 2) : "—",
        h.gauge_stations != null ? fmtNum(h.gauge_stations) + " estações recentes" : "sem ancoragem", "data"],
    ];
    for (const [label, val, sub, mod] of cards) kpi.appendChild(kpiCard(label, val, sub, mod));
  }

  function renderLevelsChart(ana) {
    const root = document.getElementById("chart-levels");
    const s = ana.series || {};
    const rows = s.rows || [];
    const note = document.getElementById("chart-levels-note");
    note.textContent = rows.length
      ? `${s.from_fmt} → ${s.to_fmt}`
      : "";
    if (rows.length < 2) return emptyMsg(root, "Ainda não há ciclos suficientes na janela (a série persiste em disco a cada ciclo de 10 min).");
    const labels = rows.map((r) => fmtShort(r.at));
    lineChart(root, {
      labels,
      stacked: true,
      height: 210,
      series: [4, 3, 2, 1, 0].map((n) => ({
        name: RD_SHORT[n] + " " + RD_LABELS[n],
        color: RD_COLORS[n],
        values: rows.map((r) => r.by_level[n]),
      })).reverse(),
      hoverText: (i) => {
        const r = rows[i];
        return fmtDateTime(r.at) + "\n" +
          [4, 3, 2, 1, 0].map((n) => RD_SHORT[n] + ": " + r.by_level[n]).join("  ") +
          "\nRD máx " + r.max_rd + " · chuva 24 h máx " + fmtNum(r.ac24h_max, 1) + " mm";
      },
    });
    const now = rows[rows.length - 1].by_level;
    const strip = el("div", "stat-strip stat-strip--5");
    strip.innerHTML = [0, 1, 2, 3, 4].map((n) =>
      `<span><i style="background:${RD_COLORS[n]}"></i>${RD_SHORT[n]} agora <b>${fmtNum(now[n])}</b></span>`
    ).join("");
    root.appendChild(strip);
  }

  function renderHourlyChart(ana) {
    const root = document.getElementById("chart-hourly");
    const h = ana.hourly || {};
    const note = document.getElementById("chart-hourly-note");
    if (!h.available) {
      note.textContent = "";
      return emptyMsg(root, h.reason || "Série horária indisponível.");
    }
    note.textContent = "média das UAs · MERGE bruto · até " + (h.target_fmt || "");
    const labels = h.hours.map((iso, i) => (i % 24 === 0 || i === h.hours.length - 1) ? fmtShort(iso) : fmtHour(iso));
    lineChart(root, {
      labels,
      height: 210,
      xTicks: 5,
      series: h.regions.map((r, i) => ({
        name: r.regiao_nome + (r.sigla_rodovia ? " · " + r.sigla_rodovia : ""),
        color: REGION_COLORS[i % REGION_COLORS.length],
        values: r.mean,
        width: 1.6,
      })),
      hoverText: (i) =>
        fmtDateTime(h.hours[i]) + "\n" +
        h.regions.map((r) => r.regiao_nome + ": " + fmtNum(r.mean[i], 2) + " mm/h (máx " + fmtNum(r.max[i], 2) + ")").join("\n"),
    });
    const strip = el("div", "stat-strip");
    strip.innerHTML = h.regions.map((r, i) =>
      `<span><i style="background:${REGION_COLORS[i % REGION_COLORS.length]}"></i>` +
      `${esc(r.regiao_nome)}: <b>${fmtNum(r.sum96_mean, 1)} mm</b> em 96 h · pico ${fmtNum(r.peak_mmh, 2)} mm/h</span>`
    ).join("");
    root.appendChild(strip);
  }

  function renderThresholds(ana) {
    const root = document.getElementById("chart-thresholds");
    root.innerHTML = "";
    const regions = ana.regional?.regions || [];
    if (!regions.length) return emptyMsg(root, "Sem regiões no snapshot.");
    const wrap = el("div", "thr-list");
    for (const r of regions) {
      const breaks = r.hid24h_breaks || [];
      const top = Math.max(breaks[breaks.length - 1] || 0, r.ac24h_max || 0) * 1.15 || 1;
      const val = r.ac24h_max || 0;
      const lvl = r.hid_level_by_rain ?? 0;
      const row = el("div", "thr-row");
      row.innerHTML =
        `<div class="thr-head"><b>${esc(r.regiao_nome)}</b><small>${esc(r.sigla_rodovia || "")}</small>` +
        `<span class="thr-val" style="--c:${RD_COLORS[Math.min(4, lvl)]}">${fmtNum(val, 1)} mm` +
        `<em>${r.hid_next_break != null ? "faltam " + fmtNum(r.hid_margin_mm, 1) + " mm para N" + (lvl + 1) : "acima do último limiar"}</em></span></div>` +
        `<div class="thr-track"><i class="thr-fill" style="width:${Math.min(100, (100 * val) / top).toFixed(1)}%;background:${RD_COLORS[Math.min(4, lvl)]}"></i>` +
        breaks.map((b, i) =>
          `<span class="thr-mark" style="left:${Math.min(100, (100 * b) / top).toFixed(1)}%;--c:${RD_COLORS[i + 1]}" title="Limiar N${i + 1}: ${b} mm"><b>${b}</b></span>`
        ).join("") +
        `</div>`;
      wrap.appendChild(row);
    }
    root.appendChild(wrap);
    root.appendChild(el("p", "card-foot",
      "Barra = maior acumulado 24 h entre as UAs da região (com correção por solo e composição WRF quando disponível). Marcas = limiares oficiais de ICC hidrológico (hid24h_breaks)."));
  }

  function renderEscalation(ana) {
    const root = document.getElementById("escalation");
    const e = ana.escalation || {};
    const note = document.getElementById("escalation-note");
    root.innerHTML = "";
    if (!e.available) {
      note.textContent = "";
      return emptyMsg(root, e.reason || "Sem histórico.");
    }
    note.textContent = `${e.cycles_tracked} ciclo(s) no histórico · ≈${(e.cycles_tracked * 10 / 60).toFixed(1)} h`;
    const strip = el("div", "stat-strip stat-strip--4");
    strip.innerHTML =
      `<span><i style="background:${RD_COLORS[3]}"></i>↑ 1 h <b>${fmtNum(e.up_1h)}</b></span>` +
      `<span><i style="background:${RD_COLORS[1]}"></i>↓ 1 h <b>${fmtNum(e.down_1h)}</b></span>` +
      `<span><i style="background:${RD_COLORS[4]}"></i>↑ 4 h <b>${fmtNum(e.up_4h)}</b></span>` +
      `<span><i style="background:${RD_COLORS[0]}"></i>↓ 4 h <b>${fmtNum(e.down_4h)}</b></span>`;
    root.appendChild(strip);
    const rising = e.rising || [];
    if (!rising.length) {
      root.appendChild(el("p", "empty", "Nenhuma UA subiu de nível na janela."));
    } else {
      const t = el("table", "small-table");
      t.innerHTML = "<thead><tr><th>UA</th><th>Rodovia · km</th><th>Canal</th><th class='num'>RD</th><th>Trajetória</th><th class='num'>24 h (mm)</th></tr></thead>";
      const tb = el("tbody");
      for (const r of rising) {
        const tr = document.createElement("tr");
        tr.innerHTML =
          `<td>${esc(r.ua_id)}</td>` +
          `<td>${esc(r.sigla_rodovia || "—")} ${esc(fmtKm(r.km_inicial, r.km_final))}</td>` +
          `<td>${r.hazard === "hidro" ? "Inundação" : "Encosta"}</td>` +
          `<td class="num"><span class="cls-chip" style="--c:${RD_COLORS[r.rd_prev]}">${r.rd_prev}</span> → <span class="cls-chip" style="--c:${RD_COLORS[r.rd_now]}">${r.rd_now}</span></td>` +
          `<td>${trailSvg(r.trail || [])}</td>` +
          `<td class="num">${fmtNum(r.ac24h_mm, 1)}</td>`;
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      root.appendChild(el("div", "table-wrap")).appendChild(t);
    }
    const steady = e.steady_alert || [];
    if (steady.length) {
      root.appendChild(el("h3", "subhead", "Em alerta sem mudança de nível (" + fmtNum(e.steady_alert_total) + ")"));
      const t = el("table", "small-table small-table--dense");
      t.innerHTML = "<thead><tr><th>UA</th><th>Rodovia · km</th><th>Canal</th><th class='num'>RD</th><th class='num'>24 h (mm)</th><th class='num'>96 h (mm)</th></tr></thead>";
      const tb = el("tbody");
      for (const r of steady) {
        const tr = document.createElement("tr");
        tr.innerHTML =
          `<td>${esc(r.ua_id)}</td>` +
          `<td>${esc(r.sigla_rodovia || "—")} ${esc(fmtKm(r.km_inicial, r.km_final))}</td>` +
          `<td>${r.hazard === "hidro" ? "Inundação" : "Encosta"}</td>` +
          `<td class="num"><span class="cls-chip" style="--c:${RD_COLORS[r.rd_now]}">${r.rd_now}</span></td>` +
          `<td class="num">${fmtNum(r.ac24h_mm, 1)}</td><td class="num">${fmtNum(r.ac96h_mm, 1)}</td>`;
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      root.appendChild(el("div", "table-wrap")).appendChild(t);
    }
    const falling = e.falling || [];
    if (falling.length) {
      root.appendChild(el("p", "card-foot",
        "Em recuo: " + falling.slice(0, 6).map((r) => `${r.ua_id} (${r.rd_prev}→${r.rd_now})`).join(" · ") +
        (falling.length > 6 ? " …" : "")));
    }
  }

  function renderDistributions(ana) {
    const root = document.getElementById("chart-dist");
    const d = ana.distributions || {};
    const note = document.getElementById("dist-note");
    root.innerHTML = "";
    if (!d.available) {
      note.textContent = "";
      return emptyMsg(root, "Sem acumulados no snapshot.");
    }
    note.textContent = fmtNum(d.uas) + " UAs · p50 / p90 / máx";
    const pair = el("div", "hist-pair");
    const mk = (title, block, color, unit) => {
      const box = el("div", "hist-box");
      box.innerHTML = `<h3>${esc(title)}<small>${fmtNum(block.p50, 1)} / ${fmtNum(block.p90, 1)} / ${fmtNum(block.max, 1)} ${unit}</small></h3>`;
      const area = el("div", "chart-box chart-box--sm");
      box.appendChild(area);
      pair.appendChild(box);
      return [area, block];
    };
    const specs = [
      mk("Acumulado 24 h", d.ac24h, NAVY, "mm"),
      mk("Acumulado 96 h", d.ac96h, GREEN, "mm"),
    ];
    root.appendChild(pair);
    specs.forEach(([area, block], i) => {
      barsChart(area, {
        groups: block.bins.map((b) => ({ label: b.label, values: [b.count] })),
        series: [{ name: "UAs", color: i === 0 ? NAVY : GREEN }],
        height: 170,
        legend: false,
        showValues: true,
      });
    });
    root.appendChild(el("p", "card-foot", "Faixas em mm · contagem de UAs (canal encosta; a chuva é amostrada uma vez por centróide)."));
  }

  function renderFireHorizons(ana) {
    const root = document.getElementById("chart-fire-horizons");
    const f = ana.fire_horizons || {};
    const note = document.getElementById("fire-horizon-note");
    root.innerHTML = "";
    if (!f.available) {
      note.textContent = "";
      return emptyMsg(root, "Produtos por horizonte indisponíveis.");
    }
    const order = ["minimo", "baixo", "medio", "alto", "critico"];
    note.textContent = "trechos por classe · observado e previsão D+1 a D+3";
    const area = el("div", "chart-box");
    root.appendChild(area);
    barsChart(area, {
      groups: f.horizons.map((h) => ({
        label: h.horizon,
        values: order.map((k) => h.classes[k] || 0),
      })),
      series: order.map((k) => ({ name: RF_LABELS[k], color: RF_COLORS[k] })),
      stacked: true,
      height: 200,
      showValues: true,
    });
    const tr = f.transitions || [];
    if (tr.length) {
      const t = el("table", "matrix-table matrix-table--dense");
      t.innerHTML =
        "<thead><tr><th>vs observado</th><th class='num'>Pioram</th><th class='num'>Melhoram</th><th class='num'>Iguais</th><th class='num'>Alto + crítico</th></tr></thead>";
      const tb = el("tbody");
      for (const x of tr) {
        const hz = f.horizons.find((h) => h.horizon === x.horizon) || {};
        const row = document.createElement("tr");
        row.innerHTML =
          `<td class="region-cell">${esc(x.horizon)}</td>` +
          `<td class="num lvl hot" style="--c:${RF_COLORS.critico}">${fmtNum(x.worsen)}</td>` +
          `<td class="num lvl hot" style="--c:${GREEN}">${fmtNum(x.improve)}</td>` +
          `<td class="num">${fmtNum(x.same)}</td>` +
          `<td class="num">${fmtNum(hz.alto_critico)}</td>`;
        tb.appendChild(row);
      }
      t.appendChild(tb);
      root.appendChild(el("div", "table-wrap")).appendChild(t);
    }
  }

  function renderQualityChart(ana) {
    const root = document.getElementById("chart-quality");
    const rows = ana.series?.rows || [];
    if (rows.length < 2) return emptyMsg(root, "Ainda não há ciclos suficientes na janela.");
    const labels = rows.map((r) => fmtShort(r.at));
    root.innerHTML = "";
    const stack = el("div", "chart-stack");
    root.appendChild(stack);
    const a = el("div");
    a.appendChild(el("h3", null, "Horas válidas de MERGE na janela de 96 h"));
    const aBox = el("div", "chart-box--sm");
    a.appendChild(aBox);
    stack.appendChild(a);
    lineChart(aBox, {
      labels,
      height: 150,
      yMax: 96,
      exactMax: true,
      series: [
        { name: "Horas válidas (0–96)", color: NAVY, values: rows.map((r) => r.files_ok), fill: true },
        { name: "Faltando na janela 24 h", color: "#ef4444", values: rows.map((r) => r.missing_24h) },
      ],
      hoverText: (i) => {
        const r = rows[i];
        return fmtDateTime(r.at) + "\nhoras válidas: " + (r.files_ok ?? "—") +
          " · faltando 24 h: " + (r.missing_24h ?? "—") +
          "\nstatus: " + fmtStatus(r.data_status);
      },
    });
    const b = el("div");
    b.appendChild(el("h3", null, "Fator médio da correção por solo (DAEE/CEMADEN) · 1,0 = satélite puro"));
    const bBox = el("div", "chart-box--sm");
    b.appendChild(bBox);
    stack.appendChild(b);
    const factors = rows.map((r) => r.gauge_factor);
    const fMax = Math.max(1.5, ...factors.filter((v) => v != null));
    lineChart(bBox, {
      labels,
      height: 120,
      yMax: Math.ceil(fMax * 2) / 2,
      exactMax: true,
      refs: [{ value: 1, label: "×1,0", color: INK3 }],
      series: [
        { name: "Fator médio", color: GREEN, values: factors, fill: true },
      ],
      hoverText: (i) => {
        const r = rows[i];
        return fmtDateTime(r.at) + "\nfator solo: " + (r.gauge_factor != null ? "×" + fmtNum(r.gauge_factor, 2) : "—") +
          " · estações: " + (r.gauge_stations ?? "—");
      },
    });
  }

  function renderOps(ana) {
    const root = document.getElementById("chart-ops");
    const ops = ana.ops || {};
    const rows = ana.series?.rows || [];
    const note = document.getElementById("ops-note");
    root.innerHTML = "";
    note.textContent = ops.cycles ? `${fmtNum(ops.cycles)} ciclos na janela` : "";
    const strip = el("div", "stat-strip stat-strip--4");
    strip.innerHTML =
      `<span>Sucesso <b>${ops.success_rate_pct != null ? fmtNum(ops.success_rate_pct, 1) + "%" : "—"}</b></span>` +
      `<span>Duração p50 <b>${fmtSec(ops.duration_p50_s)}</b></span>` +
      `<span>Duração p95 <b>${fmtSec(ops.duration_p95_s)}</b></span>` +
      `<span>Degradados <b>${fmtNum(ops.degraded)}</b></span>` +
      `<span>Intervalo p50 <b>${ops.interval_p50_min != null ? fmtNum(ops.interval_p50_min, 1) + " min" : "—"}</b></span>` +
      `<span>Maior intervalo <b>${ops.interval_max_min != null ? fmtNum(ops.interval_max_min, 1) + " min" : "—"}</b></span>` +
      `<span>Completude média <b>${ops.completeness_pct != null ? fmtNum(ops.completeness_pct, 1) + "%" : "—"}</b></span>` +
      `<span>Uptime processo <b>${fmtSec(ops.uptime_s)}</b></span>`;
    root.appendChild(strip);
    const area = el("div", "chart-box chart-box--sm");
    root.appendChild(area);
    if (rows.length < 2) {
      emptyMsg(area, "Ainda não há ciclos suficientes na janela.");
    } else {
      lineChart(area, {
        labels: rows.map((r) => fmtShort(r.at)),
        height: 150,
        series: [{ name: "Duração do ciclo (s)", color: NAVY, values: rows.map((r) => r.duration_s), fill: true }],
        hoverText: (i) => fmtDateTime(rows[i].at) + "\n" + fmtSec(rows[i].duration_s) + " · " + fmtStatus(rows[i].outcome),
      });
    }
    if (ops.last_error) {
      root.appendChild(el("div", "alert alert-error",
        `<b>Último erro</b> ${esc(ops.last_error_at_fmt || "")}<br><code>${esc(ops.last_error)}</code>`));
    }
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
        `<a class="btn-primary report-dl" href="${appPath(`/admin/api/reports/export?type=${r.id}`)}">Baixar</a>`;
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
        ["Trechos RF alto/crít", fire.alertas_rf],
        ["Top UA encosta", (geo.top_uas_geo[0] || {}).ua_id || "—"],
        ["Top trecho fogo", (fire.top_trechos[0] || {}).rodovia || "—"],
      ], 3)
    );
  }

  // ---- sistema técnico -------------------------------------------------
  function renderSystem() {
    const rt = document.getElementById("system-runtime");
    const pl = document.getElementById("system-pipeline");
    const sr = document.getElementById("system-sources");
    const au = document.getElementById("system-auth");
    [rt, pl, sr, au].forEach((r) => { r.innerHTML = ""; });
    if (!diagnostics) {
      emptyMsg(rt, "Diagnóstico técnico indisponível.");
      return;
    }
    const p = diagnostics.platform || {};
    const ov = diagnostics.overview || {};
    const pipe = diagnostics.pipeline || {};
    const sched = pipe.scheduler || {};
    const ingestSt = pipe.merge_ingest || {};

    const lights = el("div", "lights");
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
    rt.appendChild(lights);
    rt.appendChild(
      kvGrid([
        ["Gerado em", diagnostics.generated_at_fmt || fmtDateTime(diagnostics.generated_at)],
        ["Python", (p.python || {}).version],
        ["Hostname", (p.system || {}).hostname],
        ["Memória RSS", ((p.process || {}).memory_rss_mb || "—") + " MB"],
        ["eccodes", (p.dependencies || {}).eccodes_lib_loaded ? "OK" : "FALHA"],
        ["Uptime", fmtSec((p.process || {}).uptime_s)],
      ], 2)
    );

    pl.appendChild(
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
        ["Cache em disco", ingestSt.cache_disk ? fmtNum(ingestSt.cache_disk.grib_files) + " GRIB · " + fmtNum((ingestSt.cache_disk.bytes_total || 0) / 1048576, 0) + " MB" : "—"],
      ], 2)
    );

    const ext = diagnostics.external_sources || {};
    if (Object.keys(ext).length) {
      const t = el("table", "small-table");
      t.innerHTML =
        "<thead><tr><th>Fonte</th><th>Status</th><th class='num'>Tempo</th></tr></thead>";
      const tb = el("tbody");
      for (const src of Object.values(ext)) {
        const reach = src.reachability || {};
        const tr = document.createElement("tr");
        tr.innerHTML =
          `<td>${esc(src.name || "—")}</td>` +
          `<td>${lightDot(reach.ok ? "ok" : "fail")} ${reach.ok ? "OK" : "FALHA"}${reach.status ? " (" + reach.status + ")" : ""}</td>` +
          `<td class="num">${reach.elapsed_ms != null ? reach.elapsed_ms + " ms" : "—"}</td>`;
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      sr.appendChild(el("div", "table-wrap")).appendChild(t);
    } else {
      emptyMsg(sr, "Sem verificação de fontes externas.");
    }

    const auth = diagnostics.auth_backend || {};
    au.appendChild(
      el("div", "subcard",
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
      au.appendChild(
        el("div", "subcard",
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
