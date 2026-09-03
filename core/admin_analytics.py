"""
Analytics do painel /admin — leituras derivadas para monitoramento.

Tudo aqui e calculado a partir de dados que o sistema ja produz:

* telemetria persistente por ciclo (``admin_telemetry``): evolucao das
  UAs por nivel, chuva maxima, completude do MERGE, duracao dos ciclos;
* serie horaria bruta do MERGE/IMERG do ultimo ciclo (``state``): chuva
  hora a hora por regiao monitorada (96 h);
* snapshot atual: acumulados vs limiares oficiais de cada regiao
  (``hid24h_breaks`` / ``cpc_breaks`` do PRODUTO 6), distribuicao dos
  acumulados entre as UAs;
* historico curto de RD por UA (``point_rd_history``): quais UAs estao
  em escalada ou em recuo nas ultimas 1 h e 4 h;
* produtos de risco de fogo por horizonte (observado, D+1..D+3).

Nenhum valor e inventado: quando uma fonte nao esta disponivel o bloco
correspondente sai com ``available=False`` e o motivo.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import admin_telemetry
from .admin_format import format_datetime_br
from .aggregator import state

log = logging.getLogger("admin_analytics")

ROOT = Path(__file__).resolve().parent.parent
_FIRE_PUB = ROOT / "static" / "data" / "queimadas"
FIRE_HORIZON_FILES = (
    ("observado", _FIRE_PUB / "risco_trechos_der_observado.geojson"),
    ("D+1", _FIRE_PUB / "risco_trechos_der_d1.geojson"),
    ("D+2", _FIRE_PUB / "risco_trechos_der_d2.geojson"),
    ("D+3", _FIRE_PUB / "risco_trechos_der_d3.geojson"),
)
RF_ORDER = ["minimo", "baixo", "medio", "alto", "critico", "SEM_DADO"]
_RF_RANK = {"minimo": 1, "baixo": 2, "medio": 3, "alto": 4, "critico": 5}

# Faixas (mm) para a distribuicao dos acumulados entre as UAs
AC24H_BINS = [0, 5, 15, 30, 60, 120]
AC96H_BINS = [0, 10, 30, 60, 120, 220]
INTENSITY_BINS = [0, 1, 3, 6, 12, 25]

DEFAULT_HOURS = 24
MIN_HOURS = 3
MAX_HOURS = 24 * 14

_fire_cache: Dict[str, Any] = {"key": None, "value": None}


# --------------------------------------------------------------------------
# utilitarios
# --------------------------------------------------------------------------
def clamp_hours(value: Any) -> int:
    try:
        h = int(value)
    except (TypeError, ValueError):
        return DEFAULT_HOURS
    return max(MIN_HOURS, min(MAX_HOURS, h))


def _percentile(values: List[float], q: float) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * q
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return round(vals[int(k)], 2)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 2)


def _bin_counts(values: List[float], edges: List[float]) -> List[Dict]:
    counts = [0] * len(edges)
    for v in values:
        idx = 0
        for i, e in enumerate(edges):
            if v >= e:
                idx = i
        counts[idx] += 1
    out = []
    for i, e in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else None
        label = f"{e:g}–{hi:g}" if hi is not None else f"≥ {e:g}"
        out.append({"from": e, "to": hi, "label": label, "count": counts[i]})
    return out


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _levels(d: Any) -> List[int]:
    if isinstance(d, list) and len(d) == 5:
        return [int(x or 0) for x in d]
    d = d or {}
    return [int(d.get(i, d.get(str(i), 0)) or 0) for i in range(5)]


# --------------------------------------------------------------------------
# 1) serie por ciclo (telemetria persistente)
# --------------------------------------------------------------------------
def _cycle_series(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for e in entries:
        levels = _levels(e.get("by_level"))
        gauge = e.get("gauge") or {}
        rows.append({
            "at": e.get("started_at"),
            "outcome": e.get("outcome"),
            "data_status": e.get("data_status"),
            "by_level": levels,
            "alert_count": int(
                e.get("alert_count", levels[3] + levels[4]) or 0
            ),
            "max_rd": int(e.get("max_rd") or 0),
            "ac24h_max": e.get("ac24h_max"),
            "ac96h_max": e.get("ac96h_max"),
            "intensity_max": e.get("intensity_max"),
            "files_ok": e.get("files_ok"),
            "missing_24h": e.get("missing_24h"),
            "duration_s": e.get("duration_s"),
            "gauge_factor": gauge.get("mean_factor"),
            "gauge_stations": gauge.get("stations_recent"),
        })
    return {
        "available": bool(rows),
        "count": len(rows),
        "from": rows[0]["at"] if rows else None,
        "to": rows[-1]["at"] if rows else None,
        "from_fmt": format_datetime_br(rows[0]["at"]) if rows else None,
        "to_fmt": format_datetime_br(rows[-1]["at"]) if rows else None,
        "rows": rows,
    }


def _delta_alerts(rows: List[Dict[str, Any]], hours: float) -> Optional[int]:
    """Variacao do numero de UAs em alerta (3+4) vs ``hours`` atras."""
    if len(rows) < 2:
        return None
    last = rows[-1]
    t_last = _parse_ts(last["at"])
    if not t_last:
        return None
    cutoff = t_last - timedelta(hours=hours)
    ref = None
    for r in rows:
        t = _parse_ts(r["at"])
        if t and t <= cutoff:
            ref = r
        else:
            break
    if ref is None:
        return None
    return int(last["alert_count"]) - int(ref["alert_count"])


# --------------------------------------------------------------------------
# 2) chuva regional: serie horaria bruta + acumulados vs limiares
# --------------------------------------------------------------------------
def _regional(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    regions = {
        int(r.get("regiao_id") or r.get("id")): r
        for r in snapshot.get("regions") or []
    }
    points = snapshot.get("points") or []
    by_region: Dict[int, Dict[str, Any]] = {}
    for rid, r in regions.items():
        by_region[rid] = {
            "regiao_id": rid,
            "regiao_nome": r.get("regiao_nome") or r.get("nome"),
            "sigla_rodovia": r.get("sigla_rodovia") or r.get("rodovia"),
            "hid24h_breaks": list(r.get("hid24h_breaks") or []),
            "cpc_breaks": list(r.get("cpc_breaks") or []),
            "k_geo": r.get("k_geo"),
            "uas_geo": 0,
            "uas_hidro": 0,
            "levels_geo": [0] * 5,
            "levels_hidro": [0] * 5,
            "_ac24": [],
            "_ac96": [],
            "_int": [],
            "_cpc": [],
        }
    unknown = 0
    for p in points:
        rid = p.get("regiao_id")
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            unknown += 1
            continue
        b = by_region.get(rid)
        if not b:
            unknown += 1
            continue
        rd = int(p.get("rd") or 0)
        if p.get("hazard") == "hidro":
            b["uas_hidro"] += 1
            b["levels_hidro"][rd] += 1
        else:
            b["uas_geo"] += 1
            b["levels_geo"][rd] += 1
            # chuva amostrada uma vez por centroide: usa so o canal geo
            if p.get("ac24h_mm") is not None:
                b["_ac24"].append(float(p["ac24h_mm"]))
                b["_ac96"].append(float(p.get("ac96h_mm") or 0.0))
                b["_int"].append(float(p.get("intensity_mmh") or 0.0))
            if p.get("cpc") is not None:
                try:
                    v = float(p["cpc"])
                    if math.isfinite(v):
                        b["_cpc"].append(v)
                except (TypeError, ValueError):
                    pass

    out = []
    for rid in sorted(by_region):
        b = by_region[rid]
        ac24 = b.pop("_ac24")
        ac96 = b.pop("_ac96")
        inten = b.pop("_int")
        cpc = b.pop("_cpc")
        b["ac24h_max"] = round(max(ac24), 1) if ac24 else None
        b["ac24h_mean"] = round(sum(ac24) / len(ac24), 1) if ac24 else None
        b["ac24h_p90"] = _percentile(ac24, 0.9)
        b["ac96h_max"] = round(max(ac96), 1) if ac96 else None
        b["ac96h_mean"] = round(sum(ac96) / len(ac96), 1) if ac96 else None
        b["intensity_max"] = round(max(inten), 2) if inten else None
        b["cpc_max"] = round(max(cpc), 2) if cpc else None
        # Posicao do acumulado 24 h maximo frente aos limiares oficiais
        breaks = b["hid24h_breaks"]
        if breaks and b["ac24h_max"] is not None:
            lvl = sum(1 for t in breaks if b["ac24h_max"] >= t)
            nxt = breaks[lvl] if lvl < len(breaks) else None
            b["hid_level_by_rain"] = lvl
            b["hid_next_break"] = nxt
            b["hid_margin_mm"] = (
                round(nxt - b["ac24h_max"], 1) if nxt is not None else 0.0
            )
        cb = b["cpc_breaks"]
        if cb and b["cpc_max"] is not None:
            lvl = sum(1 for t in cb if b["cpc_max"] >= t)
            b["cpc_level"] = lvl
            b["cpc_next_break"] = cb[lvl] if lvl < len(cb) else None
        out.append(b)
    return {"regions": out, "points_unassigned": unknown}


def _hourly_by_region(regional: Dict[str, Any]) -> Dict[str, Any]:
    cache = state.get_rain_series()
    if not cache or not cache.get("series"):
        return {
            "available": False,
            "reason": "serie horaria MERGE ainda nao carregada",
        }
    target: datetime = cache["target"]
    series: List[List[float]] = cache["series"]
    pts = cache["points"]
    n_h = len(series[0]) if series and series[0] else 0
    if n_h == 0:
        return {"available": False, "reason": "serie horaria vazia"}
    n_h = min(n_h, 96)
    idx_by_region: Dict[int, List[int]] = {}
    for i, p in enumerate(pts):
        try:
            rid = int(p.get("regiao_id"))
        except (TypeError, ValueError):
            continue
        idx_by_region.setdefault(rid, []).append(i)
    names = {
        r["regiao_id"]: r for r in regional.get("regions", [])
    }
    hours = [
        (target - timedelta(hours=h)).isoformat()
        for h in range(n_h - 1, -1, -1)
    ]
    out_regions = []
    for rid in sorted(idx_by_region):
        idxs = idx_by_region[rid]
        mean_s = []
        max_s = []
        for h in range(n_h - 1, -1, -1):
            vals = [series[i][h] for i in idxs if h < len(series[i])]
            if not vals:
                mean_s.append(0.0)
                max_s.append(0.0)
                continue
            mean_s.append(round(sum(vals) / len(vals), 2))
            max_s.append(round(max(vals), 2))
        meta = names.get(rid, {})
        out_regions.append({
            "regiao_id": rid,
            "regiao_nome": meta.get("regiao_nome") or f"Regiao {rid}",
            "sigla_rodovia": meta.get("sigla_rodovia"),
            "uas": len(idxs),
            "mean": mean_s,
            "max": max_s,
            "sum96_mean": round(sum(mean_s), 1),
            "peak_mmh": round(max(max_s), 2) if max_s else 0.0,
        })
    return {
        "available": True,
        "target_utc": target.isoformat(),
        "target_fmt": format_datetime_br(target.isoformat()),
        "built_at": cache["built_at"].isoformat(),
        "hours": hours,
        "hours_back": n_h,
        "source": "MERGE/IMERG-late bruto (antes da correcao por solo)",
        "regions": out_regions,
    }


# --------------------------------------------------------------------------
# 3) escalada / recuo de RD por UA (historico curto em RAM)
# --------------------------------------------------------------------------
def _escalation(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    hist = state.get_point_history()
    if not hist:
        return {
            "available": False,
            "reason": "sem historico de ciclos nesta execucao",
        }
    pts = {
        (p.get("ua_id"), p.get("hazard")): p
        for p in snapshot.get("points") or []
    }
    up_1h = down_1h = up_4h = down_4h = 0
    ranked: List[Tuple[int, int, Dict[str, Any]]] = []
    depth = 0
    for key, rows in hist.items():
        if not rows:
            continue
        depth = max(depth, len(rows))
        ua_id, _, hazard = key.rpartition(":")
        now_rd = int(rows[-1].get("rd") or 0)
        rd_1h = int(rows[-7].get("rd") or 0) if len(rows) >= 7 else None
        rd_4h = int(rows[0].get("rd") or 0) if len(rows) >= 2 else None
        if rd_1h is not None:
            if now_rd > rd_1h:
                up_1h += 1
            elif now_rd < rd_1h:
                down_1h += 1
        if rd_4h is not None:
            if now_rd > rd_4h:
                up_4h += 1
            elif now_rd < rd_4h:
                down_4h += 1
        ref = rd_4h if rd_4h is not None else now_rd
        delta = now_rd - ref
        if delta != 0 or now_rd >= 3:
            p = pts.get((ua_id, hazard), {})
            ranked.append((delta, now_rd, {
                "ua_id": ua_id,
                "hazard": hazard,
                "sigla_rodovia": p.get("sigla_rodovia"),
                "km_inicial": p.get("km_inicial"),
                "km_final": p.get("km_final"),
                "regiao_nome": p.get("regiao_nome"),
                "municipio": p.get("municipio"),
                "rd_prev": ref,
                "rd_now": now_rd,
                "delta": delta,
                "ac24h_mm": p.get("ac24h_mm"),
                "ac96h_mm": p.get("ac96h_mm"),
                "trail": [int(r.get("rd") or 0) for r in rows],
            }))
    ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)
    rising = [r for d, _, r in ranked if d > 0][:12]
    falling = sorted(
        [r for d, _, r in ranked if d < 0],
        key=lambda r: (r["delta"], -r["rd_prev"]),
    )[:12]
    # UAs em alerta (>=3) sem mudanca de nivel na janela: continuam
    # relevantes para a operacao mesmo sem tendencia.
    steady = sorted(
        [r for d, _, r in ranked if d == 0 and r["rd_now"] >= 3],
        key=lambda r: (r["rd_now"], r.get("ac24h_mm") or 0),
        reverse=True,
    )[:12]
    return {
        "available": True,
        "cycles_tracked": depth,
        "window_1h_cycles": 6,
        "up_1h": up_1h,
        "down_1h": down_1h,
        "up_4h": up_4h,
        "down_4h": down_4h,
        "rising": rising,
        "falling": falling,
        "steady_alert": steady,
        "steady_alert_total": sum(
            1 for d, _, r in ranked if d == 0 and r["rd_now"] >= 3
        ),
    }


# --------------------------------------------------------------------------
# 4) distribuicao dos acumulados entre as UAs (snapshot atual)
# --------------------------------------------------------------------------
def _distributions(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    ac24: List[float] = []
    ac96: List[float] = []
    inten: List[float] = []
    for p in snapshot.get("points_geo") or []:
        if p.get("ac24h_mm") is None:
            continue
        ac24.append(float(p["ac24h_mm"]))
        ac96.append(float(p.get("ac96h_mm") or 0.0))
        inten.append(float(p.get("intensity_mmh") or 0.0))
    summary = snapshot.get("summary") or {}
    return {
        "available": bool(ac24),
        "uas": len(ac24),
        "ac24h": {
            "bins": _bin_counts(ac24, AC24H_BINS),
            "p50": _percentile(ac24, 0.5),
            "p90": _percentile(ac24, 0.9),
            "max": round(max(ac24), 1) if ac24 else None,
        },
        "ac96h": {
            "bins": _bin_counts(ac96, AC96H_BINS),
            "p50": _percentile(ac96, 0.5),
            "p90": _percentile(ac96, 0.9),
            "max": round(max(ac96), 1) if ac96 else None,
        },
        "intensity": {
            "bins": _bin_counts(inten, INTENSITY_BINS),
            "p50": _percentile(inten, 0.5),
            "p90": _percentile(inten, 0.9),
            "max": round(max(inten), 2) if inten else None,
        },
        "by_level_geo": _levels(summary.get("by_level_geo")),
        "by_level_hidro": _levels(summary.get("by_level_hidro")),
    }


# --------------------------------------------------------------------------
# 5) risco de fogo por horizonte (observado, D+1, D+2, D+3)
# --------------------------------------------------------------------------
def _read_horizon(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: Dict[str, str] = {}
    for f in data.get("features") or []:
        props = f.get("properties") or {}
        tid = props.get("trecho_id")
        if tid is None:
            continue
        out[str(tid)] = str(props.get("rf_classe") or "SEM_DADO")
    return out


def _fire_horizons() -> Dict[str, Any]:
    key = []
    for name, path in FIRE_HORIZON_FILES:
        try:
            key.append((name, path.stat().st_mtime_ns))
        except OSError:
            key.append((name, None))
    key_t = tuple(key)
    if _fire_cache["key"] == key_t and _fire_cache["value"] is not None:
        return _fire_cache["value"]

    horizons = []
    by_id: Dict[str, Dict[str, str]] = {}
    for name, path in FIRE_HORIZON_FILES:
        if not path.exists():
            continue
        try:
            classes = _read_horizon(path)
        except (OSError, ValueError) as e:
            log.warning("horizonte %s ilegivel: %s", name, e)
            continue
        by_id[name] = classes
        counts = {k: 0 for k in RF_ORDER}
        for c in classes.values():
            counts[c if c in counts else "SEM_DADO"] += 1
        horizons.append({
            "horizon": name,
            "total": len(classes),
            "classes": counts,
            "alto_critico": counts["alto"] + counts["critico"],
        })
    transitions = []
    obs = by_id.get("observado")
    if obs:
        for name in ("D+1", "D+2", "D+3"):
            nxt = by_id.get(name)
            if not nxt:
                continue
            up = down = same = 0
            for tid, c0 in obs.items():
                c1 = nxt.get(tid)
                r0 = _RF_RANK.get(c0)
                r1 = _RF_RANK.get(c1)
                if r0 is None or r1 is None:
                    continue
                if r1 > r0:
                    up += 1
                elif r1 < r0:
                    down += 1
                else:
                    same += 1
            transitions.append({
                "horizon": name, "worsen": up, "improve": down, "same": same,
            })
    value = {
        "available": bool(horizons),
        "order": RF_ORDER,
        "horizons": horizons,
        "transitions": transitions,
    }
    _fire_cache["key"] = key_t
    _fire_cache["value"] = value
    return value


# --------------------------------------------------------------------------
# 6) operacao do pipeline
# --------------------------------------------------------------------------
def _ops(entries: List[Dict[str, Any]], runtime: Dict[str, Any]) -> Dict:
    durations = [
        float(e["duration_s"]) for e in entries
        if e.get("duration_s") is not None
    ]
    ok = sum(1 for e in entries if e.get("outcome") == "ok")
    err = sum(1 for e in entries if e.get("outcome") == "error")
    skipped = sum(1 for e in entries if e.get("outcome") == "skipped")
    degraded = sum(1 for e in entries if e.get("data_status") == "degraded")
    files = [
        float(e["files_ok"]) for e in entries
        if e.get("files_ok") is not None
    ]
    total = len(entries)
    success_rate = round(100.0 * ok / total, 1) if total else None
    gaps = []
    prev = None
    for e in entries:
        t = _parse_ts(e.get("started_at"))
        if t and prev:
            gaps.append((t - prev).total_seconds() / 60.0)
        prev = t
    return {
        "cycles": total,
        "ok": ok,
        "error": err,
        "skipped": skipped,
        "degraded": degraded,
        "success_rate_pct": success_rate,
        "duration_p50_s": _percentile(durations, 0.5),
        "duration_p95_s": _percentile(durations, 0.95),
        "duration_max_s": round(max(durations), 2) if durations else None,
        "completeness_pct": (
            round(100.0 * (sum(files) / len(files)) / 96.0, 1)
            if files else None
        ),
        "interval_p50_min": _percentile(gaps, 0.5),
        "interval_max_min": round(max(gaps), 1) if gaps else None,
        "uptime_s": runtime.get("uptime_s"),
        "process_cycles": runtime.get("cycle_count"),
        "last_error": runtime.get("last_error"),
        "last_error_at_fmt": format_datetime_br(runtime.get("last_error_at")),
        "persisted_total": admin_telemetry.count(),
    }


# --------------------------------------------------------------------------
# payload
# --------------------------------------------------------------------------
def build_analytics(
    runtime: Dict[str, Any], hours: int = DEFAULT_HOURS,
) -> Dict[str, Any]:
    hours = clamp_hours(hours)
    snapshot = state.get_snapshot()
    entries = admin_telemetry.load(hours=hours)
    series = _cycle_series(entries)
    regional = _regional(snapshot)
    summary = snapshot.get("summary") or {}
    levels_now = _levels(summary.get("by_level"))
    rows = series["rows"]
    last = rows[-1] if rows else {}
    return {
        "window_hours": hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headline": {
            "alert_count": levels_now[3] + levels_now[4],
            "alert_delta_1h": _delta_alerts(rows, 1),
            "alert_delta_24h": _delta_alerts(rows, 24),
            "max_rd": int(summary.get("max_rd") or 0),
            "max_rd_name": summary.get("max_rd_name"),
            "ac24h_max": last.get("ac24h_max"),
            "ac96h_max": last.get("ac96h_max"),
            "intensity_max": last.get("intensity_max"),
            "files_ok": summary.get("files_ok"),
            "missing_24h": summary.get("missing_24h"),
            "data_status": summary.get("data_status"),
            "gauge_factor": last.get("gauge_factor"),
            "gauge_stations": last.get("gauge_stations"),
        },
        "series": series,
        "regional": regional,
        "hourly": _hourly_by_region(regional),
        "escalation": _escalation(snapshot),
        "distributions": _distributions(snapshot),
        "fire_horizons": _fire_horizons(),
        "ops": _ops(entries, runtime),
        "recent_cycles": [
            {
                **e,
                "started_at_fmt": format_datetime_br(e.get("started_at")),
                "finished_at_fmt": format_datetime_br(e.get("finished_at")),
            }
            for e in reversed(admin_telemetry.load(limit=12))
        ],
    }
