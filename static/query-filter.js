/**
 * Busca avançada — filtro por atributo nas camadas monitoradas.
 */
(function () {
  "use strict";

  const RL = window.PLI_RISK_LAYERS;
  const GEO = RL.LAYERS.geo;
  const HIDRO = RL.LAYERS.hidro;
  const FIRE = RL.LAYERS.fire;

  const OPS = [
    { id: "eq", label: "=", types: ["text", "enum", "number", "bool"] },
    { id: "ne", label: "≠", types: ["text", "enum", "number", "bool"] },
    { id: "gt", label: ">", types: ["number"] },
    { id: "gte", label: "≥", types: ["number"] },
    { id: "lt", label: "<", types: ["number"] },
    { id: "lte", label: "≤", types: ["number"] },
    { id: "contains", label: "contém", types: ["text"] },
    { id: "empty", label: "é vazio", types: ["text", "enum", "number"] },
    { id: "not_empty", label: "não é vazio", types: ["text", "enum", "number"] },
  ];

  const NIVEL_LABELS = [
    "Monitoramento", "Observação", "Atenção", "Alerta", "Alerta Máximo",
  ];

  const LAYERS = {
    roads: {
      label: "Malha Rodoviária Estadual",
      kind: "roads",
      fields: [
        { key: "rodovia", label: "Rodovia", type: "text" },
        { key: "tipo_pista", label: "Tipo de pista", type: "enum", enumKey: "tipos_pista" },
        { key: "regional", label: "Regional DER", type: "enum", enumKey: "regionais" },
        { key: "administra", label: "Administração", type: "enum", enumKey: "administra" },
        { key: "municipio", label: "Município", type: "text" },
        { key: "extensao", label: "Extensão (m)", type: "number" },
        { key: "monitored", label: "Monitorado", type: "bool" },
        { key: "region_id", label: "Região PLI", type: "number" },
      ],
    },
    encosta: {
      label: `${GEO.alias} (${GEO.label})`,
      kind: "ua",
      hazard: "encosta",
      fields: [
        { key: "rd", label: "Nível RD", type: "enum", enumKey: "niveis" },
        { key: "regiao_id", label: "Região PLI", type: "number" },
        { key: "regiao_nome", label: "Região (nome)", type: "text" },
        { key: "sigla_rodovia", label: "Rodovia", type: "text" },
        { key: "escala", label: "Escala (UA)", type: "text" },
        { key: "tipo", label: "Tipo (UTB/SR)", type: "text" },
        { key: "RAGEO", label: "RA geológico", type: "number" },
        { key: "trecho_critico_geo", label: "Trecho crítico geo", type: "bool" },
        { key: "ac96h_mm", label: "Chuva 96 h (mm)", type: "number" },
        { key: "ac24h_mm", label: "Chuva 24 h (mm)", type: "number" },
        { key: "intensity_mmh", label: "Intensidade (mm/h)", type: "number" },
        { key: "cpc", label: "CPC", type: "number" },
        { key: "regional", label: "Sede Regional DER", type: "text" },
        { key: "residencia_dr", label: "Residência DER", type: "text" },
        { key: "uba_codigo", label: "UBA (código)", type: "text" },
        { key: "uba_nome", label: "UBA (nome)", type: "text" },
        { key: "municipio", label: "Município", type: "text" },
      ],
    },
    inundacao: {
      label: `${HIDRO.alias} (${HIDRO.label})`,
      kind: "ua",
      hazard: "inundacao",
      fields: [
        { key: "rd", label: "Nível RD", type: "enum", enumKey: "niveis" },
        { key: "regiao_id", label: "Região PLI", type: "number" },
        { key: "regiao_nome", label: "Região (nome)", type: "text" },
        { key: "sigla_rodovia", label: "Rodovia", type: "text" },
        { key: "escala", label: "Escala (UA)", type: "text" },
        { key: "tipo", label: "Tipo (UTB/SR)", type: "text" },
        { key: "RAHID", label: "RA hidrológico", type: "number" },
        { key: "trecho_critico_hid", label: "Trecho crítico hidro", type: "bool" },
        { key: "ac24h_mm", label: "Chuva 24 h (mm)", type: "number" },
        { key: "ac96h_mm", label: "Chuva 96 h (mm)", type: "number" },
        { key: "regional", label: "Sede Regional DER", type: "text" },
        { key: "residencia_dr", label: "Residência DER", type: "text" },
        { key: "uba_codigo", label: "UBA (código)", type: "text" },
        { key: "uba_nome", label: "UBA (nome)", type: "text" },
        { key: "municipio", label: "Município", type: "text" },
      ],
    },
    fireRisk: {
      label: `${FIRE.alias} (${FIRE.label} · ${FIRE.source})`,
      kind: "fireRisk",
      fields: [
        { key: "rf_classe", label: "Classe RF", type: "enum", enumKey: "rf_classes" },
        { key: "rf_valor", label: "RF contínuo", type: "number" },
        { key: "rf_p90", label: "RF P90", type: "number" },
        { key: "rf_media", label: "RF médio", type: "number" },
        { key: "horizonte", label: "Horizonte", type: "enum", enumKey: "rf_horizontes" },
        { key: "rodovia", label: "Rodovia", type: "text" },
        { key: "sede_regional", label: "Sede Regional DER", type: "text" },
        { key: "residencia_dr", label: "Residência DER", type: "text" },
        { key: "uba_codigo", label: "UBA (código)", type: "text" },
        { key: "uba_nome", label: "UBA (nome)", type: "text" },
        { key: "municipio", label: "Município", type: "text" },
        { key: "jurisdicao", label: "Jurisdição", type: "text" },
        { key: "conservado_por", label: "Conservado por", type: "text" },
        { key: "data_referencia", label: "Data referência", type: "text" },
      ],
    },
  };

  const enums = {
    tipos_pista: [],
    regionais: [],
    administra: [],
    niveis: NIVEL_LABELS.map((l, i) => ({ v: String(i), l: `${i} · ${l}` })),
    rf_classes: [
      { v: "minimo", l: "mínimo" },
      { v: "baixo", l: "baixo" },
      { v: "medio", l: "médio" },
      { v: "alto", l: "alto" },
      { v: "critico", l: "crítico" },
      { v: "SEM_DADO", l: "sem dado" },
    ],
    rf_horizontes: [
      { v: "observado", l: "observado" },
      { v: "D+1", l: "D+1" },
      { v: "D+2", l: "D+2" },
      { v: "D+3", l: "D+3" },
    ],
  };

  /** Uma consulta por camada monitorada. */
  let activeRules = [];
  let rowSeq = 0;
  let joinSeq = 0;

  function fieldIds(rowId) {
    const rid = String(rowId);
    return {
      field: `qf-field-${rid}`,
      op: `qf-op-${rid}`,
      value: `qf-value-${rid}`,
    };
  }

  function bridge() {
    return window.pliMapBridge || {};
  }

  function layerDef(id) {
    return LAYERS[id] || null;
  }

  function fieldDef(layerId, key) {
    const L = layerDef(layerId);
    return (L?.fields || []).find((f) => f.key === key) || null;
  }

  function opsForField(field) {
    if (!field) return OPS;
    return OPS.filter((o) => o.types.includes(field.type));
  }

  function getProp(props, key, layerId) {
    if (!props) return null;
    if (key === "rd") {
      if (layerId === "inundacao") return props.rd_hid ?? props.rd;
      if (layerId === "encosta") return props.rd_geo ?? props.rd;
    }
    // Atributos NATIVOS de uas_area_estudo (case-sensitive: RAGEO/RAHID)
    return props[key];
  }

  function evalCond(raw, op, target, field) {
    if (op === "empty") {
      return raw == null || raw === "" || Number.isNaN(raw);
    }
    if (op === "not_empty") {
      return raw != null && raw !== "" && !Number.isNaN(raw);
    }
    if (field?.type === "bool") {
      const b = raw === true || raw === "true" || raw === 1;
      const t = target === "true" || target === "1";
      return op === "eq" ? b === t : b !== t;
    }
    if (field?.type === "number") {
      const n = Number(raw);
      const t = Number(target);
      if (Number.isNaN(n) || Number.isNaN(t)) return false;
      if (op === "eq") return n === t;
      if (op === "ne") return n !== t;
      if (op === "gt") return n > t;
      if (op === "gte") return n >= t;
      if (op === "lt") return n < t;
      if (op === "lte") return n <= t;
      return false;
    }
    const s = String(raw ?? "").toLowerCase();
    const t = String(target ?? "").toLowerCase();
    if (op === "eq") return s === t;
    if (op === "ne") return s !== t;
    if (op === "contains") return s.includes(t);
    return false;
  }

  function matchesRule(props, rule) {
    const L = layerDef(rule.layerId);
    if (!L || !rule.conditions?.length) return true;
    const parts = rule.conditions.map((c) => {
      const f = fieldDef(rule.layerId, c.field);
      const raw = getProp(props, c.field, rule.layerId);
      return evalCond(raw, c.op, c.value, f);
    });
    return rule.join === "or"
      ? parts.some(Boolean)
      : parts.every(Boolean);
  }

  function matchLayer(layerId, props) {
    const rule = activeRules.find((r) => r.layerId === layerId);
    if (!rule) return true;
    return matchesRule(props, rule);
  }

  function clauseText(layerId, cond) {
    const f = fieldDef(layerId, cond.field);
    const op = OPS.find((o) => o.id === cond.op)?.label || cond.op;
    const label = f?.label || cond.field;
    if (cond.op === "empty" || cond.op === "not_empty") {
      return `${label} ${op}`;
    }
    return `${label} ${op} ${cond.value}`;
  }

  function formatExpression(rule) {
    if (!rule?.conditions?.length) return "—";
    const bits = rule.conditions.map((c) => clauseText(rule.layerId, c));
    if (bits.length === 1) return bits[0];
    const join = rule.join === "or" ? " OU " : " E ";
    return bits.join(join);
  }

  function readJoin() {
    const sel = document.querySelector(".qf-join-select");
    return sel?.value || "and";
  }

  function setJoinOnAll(join) {
    document.querySelectorAll(".qf-join-select").forEach((s) => {
      s.value = join;
    });
  }

  function connectorHtml(join, joinId) {
    const andSel = join === "and" ? " selected" : "";
    const orSel = join === "or" ? " selected" : "";
    const selId = `qf-join-${joinId}`;
    return (
      '<span class="qf-connector-label">Relação entre critérios</span>'
      + `<label class="visually-hidden" for="${selId}">Relação entre critérios</label>`
      + `<select class="qf-join-select" id="${selId}" name="${selId}"`
      + ` aria-label="Relação entre critérios">`
      + `<option value="and"${andSel}>E — todos os critérios ligados</option>`
      + `<option value="or"${orSel}>OU — qualquer critério ligado</option>`
      + "</select>"
    );
  }

  function bindConnector(conn) {
    const sel = conn.querySelector(".qf-join-select");
    sel?.addEventListener("change", () => {
      setJoinOnAll(sel.value);
      updatePreview();
    });
  }

  function createConnector(join) {
    const conn = document.createElement("div");
    conn.className = "qf-connector";
    conn.setAttribute("role", "group");
    const jid = ++joinSeq;
    conn.dataset.joinId = String(jid);
    conn.innerHTML = connectorHtml(join || "and", jid);
    bindConnector(conn);
    return conn;
  }

  function rebuildConnectors() {
    const box = document.getElementById("qf-conditions");
    if (!box) return;
    const join = readJoin() || "and";
    box.querySelectorAll(".qf-connector").forEach((el) => el.remove());
    const clauses = [...box.querySelectorAll(".qf-clause")];
    for (let i = 1; i < clauses.length; i++) {
      box.insertBefore(createConnector(join), clauses[i]);
    }
    setJoinOnAll(join);
  }

  function readBuilder() {
    const layerId = document.getElementById("qf-layer")?.value;
    const rows = [...document.querySelectorAll("#qf-conditions .qf-clause")];
    const conditions = rows.map((row) => ({
      field: row.querySelector(".qf-field")?.value,
      op: row.querySelector(".qf-op")?.value,
      value: row.querySelector(".qf-value")?.value ?? "",
    })).filter((c) => c.field && c.op);
    return { layerId, conditions, join: readJoin() };
  }

  function valueInputHtml(field, rowId) {
    const ids = fieldIds(rowId);
    if (!field) {
      return (
        `<input class="qf-value" id="${ids.value}" name="${ids.value}"`
        + ' type="text" disabled aria-label="Valor">'
      );
    }
    if (field.type === "bool") {
      return (
        `<select class="qf-value" id="${ids.value}" name="${ids.value}"`
        + ' aria-label="Valor">'
        + '<option value="true">Sim</option>'
        + '<option value="false">Não</option>'
        + "</select>"
      );
    }
    if (field.type === "enum" && field.enumKey) {
      const opts = (enums[field.enumKey] || []).map((e) => {
        const v = typeof e === "string" ? e : e.v;
        const l = typeof e === "string" ? e : e.l;
        return `<option value="${v}">${l}</option>`;
      }).join("");
      return (
        `<select class="qf-value" id="${ids.value}" name="${ids.value}"`
        + ' aria-label="Valor">'
        + `<option value="">—</option>${opts}</select>`
      );
    }
    const step = field.type === "number" ? ' step="any"' : "";
    const type = field.type === "number" ? "number" : "text";
    return (
      `<input class="qf-value" id="${ids.value}" name="${ids.value}"`
      + ` type="${type}"${step} aria-label="Valor">`
    );
  }

  function updatePreview() {
    const el = document.getElementById("qf-expression-text");
    if (!el) return;
    const draft = readBuilder();
    el.textContent = formatExpression(draft);
  }

  function bindClause(row, layerId) {
    const fieldSel = row.querySelector(".qf-field");
    const opSel = row.querySelector(".qf-op");
    const valWrap = row.querySelector(".qf-value-wrap");

    const refresh = () => {
      const f = fieldDef(layerId, fieldSel.value);
      const ops = opsForField(f);
      const cur = opSel.value;
      opSel.innerHTML = ops.map(
        (o) => `<option value="${o.id}">${o.label}</option>`
      ).join("");
      if (ops.some((o) => o.id === cur)) opSel.value = cur;
      valWrap.innerHTML = valueInputHtml(f, row.dataset.id);
      const hideVal = ["empty", "not_empty"].includes(opSel.value);
      valWrap.hidden = hideVal;
      valWrap.closest(".qf-clause-val")?.classList.toggle("is-hidden", hideVal);
      updatePreview();
    };

    fieldSel.addEventListener("change", refresh);
    opSel.addEventListener("change", refresh);
    row.querySelector(".qf-value-wrap")?.addEventListener("input", updatePreview);
    row.querySelector(".qf-value-wrap")?.addEventListener("change", updatePreview);
    row.querySelector(".qf-rm")?.addEventListener("click", () => {
      row.remove();
      rebuildConnectors();
      updatePreview();
    });
    refresh();
  }

  function clauseHtml(fieldOpts, rowId) {
    const ids = fieldIds(rowId);
    return (
      '<div class="qf-clause-grid">'
      + '<div class="filter-group qf-clause-field">'
      + `<label class="qf-inline-label" for="${ids.field}">Campo</label>`
      + `<select class="qf-field" id="${ids.field}" name="${ids.field}"`
      + ` aria-label="Campo">${fieldOpts}</select>`
      + "</div>"
      + '<div class="filter-group qf-clause-op">'
      + `<label class="qf-inline-label" for="${ids.op}">Operador</label>`
      + `<select class="qf-op" id="${ids.op}" name="${ids.op}"`
      + ' aria-label="Operador"></select>'
      + "</div>"
      + '<div class="filter-group qf-clause-val">'
      + `<label class="qf-inline-label" for="${ids.value}">Valor</label>`
      + '<span class="qf-value-wrap"></span>'
      + "</div>"
      + "</div>"
      + '<button type="button" class="qf-rm" title="Remover critério"'
      + ' aria-label="Remover critério">×</button>'
    );
  }

  function addClause(layerId) {
    const L = layerDef(layerId);
    const box = document.getElementById("qf-conditions");
    if (!box || !L) return;
    const row = document.createElement("div");
    row.className = "qf-clause";
    row.dataset.id = String(++rowSeq);
    const fieldOpts = L.fields.map(
      (f) => `<option value="${f.key}">${f.label}</option>`
    ).join("");
    row.innerHTML = clauseHtml(fieldOpts, row.dataset.id);
    box.appendChild(row);
    bindClause(row, layerId);
    rebuildConnectors();
    updatePreview();
  }

  function loadRuleIntoBuilder(rule) {
    const layerSel = document.getElementById("qf-layer");
    if (!layerSel || !rule) return;
    layerSel.value = rule.layerId;
    const box = document.getElementById("qf-conditions");
    if (box) box.innerHTML = "";
    const join = rule.join || "and";
    rule.conditions.forEach(() => addClause(rule.layerId));
    const rows = [...document.querySelectorAll("#qf-conditions .qf-clause")];
    rule.conditions.forEach((c, i) => {
      const row = rows[i];
      if (!row) return;
      const fieldSel = row.querySelector(".qf-field");
      const opSel = row.querySelector(".qf-op");
      if (fieldSel) fieldSel.value = c.field;
      fieldSel?.dispatchEvent(new Event("change"));
      if (opSel) opSel.value = c.op;
      opSel?.dispatchEvent(new Event("change"));
      const valEl = row.querySelector(".qf-value");
      if (valEl && c.value != null) valEl.value = c.value;
    });
    rebuildConnectors();
    setJoinOnAll(join);
    updatePreview();
  }

  function resetBuilder(layerId) {
    const sel = document.getElementById("qf-layer");
    const lid = layerId || sel?.value || "roads";
    if (sel) sel.value = lid;
    const box = document.getElementById("qf-conditions");
    if (box) box.innerHTML = "";
    addClause(lid);
    updatePreview();
  }

  function layerOptionsHtml() {
    return Object.entries(LAYERS).map(
      ([id, L]) => `<option value="${id}">${L.label}</option>`
    ).join("");
  }

  function applyBuilderFilter() {
    const rule = readBuilder();
    if (!rule.layerId || !rule.conditions.length) return;
    activeRules = activeRules.filter((r) => r.layerId !== rule.layerId);
    activeRules.push({ ...rule });
    renderActiveFilters();
    bridge().onFiltersChanged?.();
  }

  function removeLayerFilter(layerId) {
    activeRules = activeRules.filter((r) => r.layerId !== layerId);
    renderActiveFilters();
    bridge().onFiltersChanged?.();
  }

  function renderActiveFilters() {
    const list = document.getElementById("qf-active-list");
    const empty = document.getElementById("qf-active-empty");
    if (!list || !empty) return;
    if (!activeRules.length) {
      list.innerHTML = "";
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    list.innerHTML = activeRules.map((rule) => {
      const L = layerDef(rule.layerId);
      return (
        `<li class="qf-active-item" data-layer="${rule.layerId}">`
        + '<div class="qf-active-item-head">'
        + `<strong>${L?.label || rule.layerId}</strong>`
        + `<button type="button" class="qf-active-edit" data-layer="${rule.layerId}"`
        + ' title="Editar filtro">Editar</button>'
        + `<button type="button" class="qf-active-rm" data-layer="${rule.layerId}"`
        + ' title="Remover filtro">×</button>'
        + "</div>"
        + `<p class="qf-active-expr">${formatExpression(rule)}</p>`
        + "</li>"
      );
    }).join("");

    list.querySelectorAll(".qf-active-rm").forEach((btn) => {
      btn.addEventListener("click", () => {
        removeLayerFilter(btn.dataset.layer);
      });
    });
    list.querySelectorAll(".qf-active-edit").forEach((btn) => {
      btn.addEventListener("click", () => {
        const rule = activeRules.find((r) => r.layerId === btn.dataset.layer);
        if (rule) loadRuleIntoBuilder(rule);
      });
    });
  }

  function setOptions(select, items, placeholder) {
    if (!select) return;
    const opts = items.map((item) => {
      const value = typeof item === "string" ? item : (item.v ?? item.key);
      const label = typeof item === "string" ? item : (item.l ?? item.label);
      return `<option value="${value}">${label}</option>`;
    }).join("");
    select.innerHTML = `<option value="">${placeholder}</option>${opts}`;
    select.disabled = !items.length;
  }

  function simpleEnumValues(field) {
    if (!field?.enumKey) return null;
    return enums[field.enumKey] || [];
  }

  function refreshSimpleFields() {
    const layerSel = document.getElementById("simple-layer");
    const fieldSel = document.getElementById("simple-field");
    const valueSel = document.getElementById("simple-value");
    const L = layerDef(layerSel?.value);
    setOptions(fieldSel, L?.fields || [], "Selecione um campo");
    setOptions(valueSel, [], "Selecione um valor");
  }

  function refreshSimpleValues() {
    const layerId = document.getElementById("simple-layer")?.value;
    const fieldKey = document.getElementById("simple-field")?.value;
    const valueSel = document.getElementById("simple-value");
    const field = fieldDef(layerId, fieldKey);
    if (!field) {
      setOptions(valueSel, [], "Selecione um valor");
      return;
    }
    const enumValues = simpleEnumValues(field);
    const values = enumValues
      ?? (bridge().getLayerValues?.(layerId, fieldKey) || []);
    setOptions(
      valueSel,
      values,
      values.length ? "Selecione um valor" : "Sem valores",
    );
  }

  function readSimpleSearch() {
    const layerId = document.getElementById("simple-layer")?.value;
    const field = document.getElementById("simple-field")?.value;
    const value = document.getElementById("simple-value")?.value;
    if (!layerId || !field || value === "") return null;
    return {
      layerId,
      join: "and",
      conditions: [{ field, op: "eq", value }],
    };
  }

  function initSimpleSearch() {
    const layerSel = document.getElementById("simple-layer");
    if (!layerSel) return;
    layerSel.innerHTML = layerOptionsHtml();
    layerSel.addEventListener("change", refreshSimpleFields);
    document
      .getElementById("simple-field")
      ?.addEventListener("change", refreshSimpleValues);
    document
      .getElementById("simple-value")
      ?.addEventListener("focus", refreshSimpleValues);
    document
      .getElementById("simple-search-apply")
      ?.addEventListener("click", () => {
        const rule = readSimpleSearch();
        if (!rule) return;
        activeRules = activeRules.filter((r) => r.layerId !== rule.layerId);
        activeRules.push(rule);
        renderActiveFilters();
        bridge().onFiltersChanged?.();
      });
    document
      .getElementById("simple-search-clear")
      ?.addEventListener("click", () => clearAll());
    refreshSimpleFields();
  }

  function clearAll() {
    activeRules = [];
    renderActiveFilters();
    resetBuilder("roads");
    bridge().onFiltersChanged?.();
  }

  function initAdvancedSearch() {
    const layerSel = document.getElementById("qf-layer");
    if (!layerSel) return;
    layerSel.innerHTML = layerOptionsHtml();
    layerSel.addEventListener("change", () => {
      const existing = activeRules.find((r) => r.layerId === layerSel.value);
      if (existing) loadRuleIntoBuilder(existing);
      else resetBuilder(layerSel.value);
    });

    document.getElementById("qf-add-row")?.addEventListener("click", () => {
      addClause(layerSel.value);
    });

    document.getElementById("qf-apply")?.addEventListener("click", () => {
      applyBuilderFilter();
    });

    document.getElementById("qf-clear-builder")?.addEventListener("click", () => {
      resetBuilder(layerSel.value);
    });

    document.getElementById("qf-clear-all")?.addEventListener("click", () => {
      clearAll();
    });

    resetBuilder("roads");
    renderActiveFilters();
  }

  function initUi() {
    initSimpleSearch();
    initAdvancedSearch();
  }

  window.QueryFilter = {
    init: initUi,
    setRoadEnums(stats) {
      enums.tipos_pista = stats.tipos_pista || [];
      enums.regionais = stats.regionais || [];
      enums.administra = stats.administra || [];
    },
    matchRoad(props) {
      return matchLayer("roads", props);
    },
    matchUa(hazardKey, props) {
      const layerId = hazardKey === "inundacao" ? "inundacao" : "encosta";
      if (!activeRules.some((r) => r.layerId === layerId)) return true;
      return matchLayer(layerId, props);
    },
    matchFireRisk(props) {
      if (!activeRules.some((r) => r.layerId === "fireRisk")) return true;
      return matchLayer("fireRisk", props);
    },
    hasActiveRules() {
      return activeRules.length > 0;
    },
    clearAll,
  };
})();
