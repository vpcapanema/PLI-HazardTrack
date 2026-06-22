"""
Painel administrativo — dados agregados dos dois modulos de monitoramento.

Geodinamico (RD por UA, MERGE/INPE) + Risco de fogo (RF por trecho, INPE).
"""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .aggregator import state
from .merge_ingest import ingest

ROOT = Path(__file__).resolve().parent.parent
_FIRE_PUB = ROOT / "static" / "data" / "queimadas"
FIRE_STATS = _FIRE_PUB / "risco_trechos_der_stats.json"
FIRE_SNAPSHOT = _FIRE_PUB / "risco_trechos_der_latest.json"
FIRE_MARKER = ROOT / "data" / "queimadas" / "metadata" / "auto_runner.json"
FIRE_LOCK = ROOT / "data" / "queimadas" / "metadata" / ".auto_runner.lock"

RD_LABELS = {
    0: "Monitoramento",
    1: "Observacao",
    2: "Atencao",
    3: "Alerta",
    4: "Alerta Maximo",
}

RF_LABELS = {
    "minimo": "Minimo",
    "baixo": "Baixo",
    "medio": "Medio",
    "alto": "Alto",
    "critico": "Critico",
    "SEM_DADO": "Sem dado",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Optional[Dict] = None) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default or {}


def _light(status: Optional[str]) -> str:
    if status in {"ok", "fresh"}:
        return "ok"
    if status in {"degraded", "loading", "warn", "no_data"}:
        return "warn"
    return "fail"


def _top_points(points: List[Dict], n: int = 10) -> List[Dict[str, Any]]:
    rows = []
    for p in points or []:
        rd = p.get("rd")
        if rd is None:
            continue
        rows.append({
            "ua_id": p.get("ua_id"),
            "sigla_rodovia": p.get("sigla_rodovia"),
            "regiao_nome": p.get("regiao_nome"),
            "municipio": p.get("municipio"),
            "km_inicial": p.get("km_inicial"),
            "km_final": p.get("km_final"),
            "rd": rd,
            "nivel": RD_LABELS.get(int(rd), str(rd)),
            "hazard": p.get("hazard"),
            "RAGEO": p.get("RAGEO"),
            "RAHID": p.get("RAHID"),
            "ac96h_mm": p.get("ac96h_mm"),
            "hid24h_mm": p.get("hid24h_mm"),
        })
    rows.sort(key=lambda r: (r["rd"], r.get("ac96h_mm") or 0), reverse=True)
    return rows[:n]


def _by_region(points: List[Dict]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for p in points or []:
        name = p.get("regiao_nome") or "Fora de cobertura"
        rd = int(p.get("rd") or 0)
        bucket = out.setdefault(name, {str(i): 0 for i in range(5)})
        bucket[str(rd)] = bucket.get(str(rd), 0) + 1
    return out


def _fire_health() -> Dict[str, Any]:
    from core import fire_pipeline

    stats = _read_json(FIRE_STATS)
    marker = _read_json(FIRE_MARKER)
    latest_inpe = fire_pipeline.latest_observed_filename(timeout=8)
    ref = stats.get("data_referencia")
    today = date.today().isoformat()
    fresh = ref == today and stats.get("data_status") == "ok"
    inpe_new = (
        latest_inpe
        and marker.get("observed_file")
        and latest_inpe != marker.get("observed_file")
    )
    lock_active = FIRE_LOCK.exists()
    auto_on = os.environ.get("QUEIMADAS_AUTO", "1") != "0"
    try:
        poll_min = int(os.environ.get("QUEIMADAS_POLL_MIN", "30") or 30)
    except ValueError:
        poll_min = 30

    if fresh:
        status = "ok"
    elif stats.get("data_status"):
        status = "warn"
    else:
        status = "fail"
    return {
        "modulo": "risco_fogo",
        "status": status,
        "lights": {
            "produto": _light(status),
            "auto_runner": "ok" if auto_on else "warn",
            "inpe_poll": "warn" if inpe_new else "ok",
            "pipeline_lock": "warn" if lock_active else "ok",
        },
        "data_referencia": ref,
        "data_status": stats.get("data_status"),
        "total_trechos": stats.get("total_trechos"),
        "horizontes": stats.get("horizontes_disponiveis", []),
        "auto_runner": {
            "enabled": auto_on,
            "poll_min": poll_min,
            "last_file": marker.get("observed_file"),
            "last_run": marker.get("ran_at"),
            "lock_active": lock_active,
        },
        "inpe": {
            "latest_file": latest_inpe,
            "pending_update": bool(inpe_new),
        },
        "metodologia": stats.get("metodologia", "INPE-RF-v11"),
    }


def _fire_stats() -> Dict[str, Any]:
    stats = _read_json(FIRE_STATS)
    snap = _read_json(FIRE_SNAPSHOT)
    classes = stats.get("classes") or {}
    trechos = snap.get("trechos") or []
    by_regional: Dict[str, Dict[str, int]] = {}
    top: List[Dict[str, Any]] = []
    order = {"critico": 5, "alto": 4, "medio": 3, "baixo": 2, "minimo": 1}
    for t in trechos:
        cls = str(t.get("rf_classe") or "SEM_DADO")
        reg = t.get("regional") or t.get("sede_regional") or "—"
        bucket = by_regional.setdefault(reg, {})
        bucket[cls] = bucket.get(cls, 0) + 1
        val = t.get("rf_valor")
        if val is not None and cls not in {"SEM_DADO", "None"}:
            top.append({
                "trecho_id": t.get("trecho_id"),
                "rodovia": t.get("rodovia"),
                "km_ini": t.get("km_ini"),
                "km_fim": t.get("km_fim"),
                "municipio": t.get("municipio"),
                "regional": reg,
                "rf_valor": round(float(val), 3),
                "rf_classe": cls,
            })
    top.sort(
        key=lambda r: (order.get(r["rf_classe"], 0), r["rf_valor"]),
        reverse=True,
    )
    crit = sum(
        int(v) for k, v in classes.items()
        if k in {"alto", "critico"}
    )
    return {
        "modulo": "risco_fogo",
        "data_referencia": stats.get("data_referencia"),
        "total_trechos": stats.get("total_trechos", 0),
        "classes": {str(k): int(v) for k, v in classes.items()},
        "classes_label": {
            RF_LABELS.get(k, k): int(v) for k, v in classes.items()
        },
        "alertas_rf": crit,
        "by_regional": by_regional,
        "top_trechos": top[:15],
        "horizontes": stats.get("horizontes_disponiveis", []),
    }


def _geo_stats() -> Dict[str, Any]:
    snap = state.get_snapshot()
    summary = snap.get("summary", {})
    points = snap.get("points", []) or []
    geo_pts = [p for p in points if p.get("hazard") == "geo"]
    hid_pts = [p for p in points if p.get("hazard") == "hidro"]
    by_level = summary.get("by_level") or {}
    alert_count = sum(
        int(by_level.get(str(i), by_level.get(i, 0)))
        for i in (3, 4)
    )
    return {
        "modulo": "geodinamico",
        "data_status": summary.get("data_status"),
        "data_source": summary.get("data_source"),
        "last_update": snap.get("timestamp_utc"),
        "uas_total": len(points),
        "uas_geo": len(geo_pts),
        "uas_hidro": len(hid_pts),
        "max_rd": summary.get("max_rd", 0),
        "max_rd_name": summary.get("max_rd_name"),
        "by_level": {
            str(k): int(v) for k, v in by_level.items()
        },
        "by_level_label": {
            RD_LABELS.get(int(k), str(k)): int(v)
            for k, v in by_level.items()
        },
        "by_level_geo": summary.get("by_level_geo") or {},
        "by_level_hidro": summary.get("by_level_hidro") or {},
        "by_region_geo": _by_region(geo_pts),
        "by_region_hidro": _by_region(hid_pts),
        "top_uas_geo": _top_points(geo_pts, 10),
        "top_uas_hidro": _top_points(hid_pts, 10),
        "missing_24h": summary.get("missing_24h"),
        "missing_96h": summary.get("missing_96h"),
        "alert_count": alert_count,
    }


def _geo_health(runtime: Dict[str, Any]) -> Dict[str, Any]:
    snap = state.get_snapshot()
    summary = snap.get("summary", {})
    data_status = summary.get("data_status")
    from core.merge_inpe import _eccodes_available

    eccodes_ok = _eccodes_available()
    return {
        "modulo": "geodinamico",
        "status": data_status or "unknown",
        "lights": {
            "dados": _light(data_status),
            "scheduler": "ok" if runtime.get("cycle_count", 0) > 0 else "warn",
            "eccodes": "ok" if eccodes_ok else "fail",
            "erros": "fail" if runtime.get("last_error") else "ok",
        },
        "merge_ingest": ingest.status(),
        "scheduler": {
            "interval_min": 10,
            "cycle_count": runtime.get("cycle_count"),
            "cycle_success": runtime.get("cycle_success"),
            "cycle_fail": runtime.get("cycle_fail"),
            "last_duration_s": runtime.get("last_cycle_duration_s"),
            "last_error": runtime.get("last_error"),
        },
        "data_quality": {
            "files_ok": summary.get("files_ok"),
            "missing_24h": summary.get("missing_24h"),
            "missing_96h": summary.get("missing_96h"),
        },
    }


def _analytics(runtime: Dict[str, Any]) -> Dict[str, Any]:
    history = runtime.get("history") or []
    rd_trend = []
    duration_trend = []
    for h in history[-24:]:
        rd_trend.append({
            "at": h.get("started_at"),
            "max_rd": h.get("max_rd", 0),
            "data_status": h.get("data_status"),
        })
        duration_trend.append({
            "at": h.get("started_at"),
            "duration_s": h.get("duration_s"),
            "outcome": h.get("outcome"),
        })
    success_rate = 0.0
    if runtime.get("cycle_count"):
        success_rate = round(
            100.0 * runtime["cycle_success"] / runtime["cycle_count"], 1,
        )
    return {
        "cycle_success_rate_pct": success_rate,
        "uptime_s": runtime.get("uptime_s"),
        "rd_trend": rd_trend,
        "duration_trend": duration_trend,
        "recent_cycles": list(reversed(history[-12:])),
    }


def collect_dashboard() -> Dict[str, Any]:
    """Payload principal do painel admin."""
    runtime = state.get_runtime()
    geo = _geo_stats()
    fire = _fire_stats()
    geo_h = _geo_health(runtime)
    fire_h = _fire_health()

    overview = {
        "geodinamico": {
            "status": geo_h["status"],
            "max_rd": geo["max_rd"],
            "max_rd_label": RD_LABELS.get(int(geo["max_rd"] or 0), "—"),
            "uas_monitoradas": geo["uas_total"],
            "alertas_rd": geo["alert_count"],
            "last_update": geo["last_update"],
        },
        "risco_fogo": {
            "status": fire_h["status"],
            "total_trechos": fire["total_trechos"],
            "alertas_rf": fire["alertas_rf"],
            "data_referencia": fire["data_referencia"],
            "classes_top": fire["classes"],
        },
    }

    return {
        "generated_at": _now_iso(),
        "overview": overview,
        "health": {
            "geodinamico": geo_h,
            "risco_fogo": fire_h,
        },
        "stats": {
            "geodinamico": geo,
            "risco_fogo": fire,
        },
        "analytics": _analytics(runtime),
    }


def _rows_geodynamic_report(dashboard: Dict) -> List[Dict[str, Any]]:
    geo = dashboard["stats"]["geodinamico"]
    rows = []
    for p in geo.get("top_uas_geo", []):
        rows.append({**p, "canal": "movimento_massa"})
    for p in geo.get("top_uas_hidro", []):
        rows.append({**p, "canal": "inundacao"})
    rows.sort(key=lambda r: r.get("rd", 0), reverse=True)
    return rows


def _rows_fire_report(dashboard: Dict) -> List[Dict[str, Any]]:
    return dashboard["stats"]["risco_fogo"].get("top_trechos", [])


def build_report(
    report_type: str,
    dashboard: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, str]:
    """Retorna (content_type, filename, body)."""
    data = dashboard or collect_dashboard()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    if report_type == "overview":
        payload = {
            "gerado_em": data["generated_at"],
            "visao_geral": data["overview"],
            "resumo_geodinamico": {
                k: data["stats"]["geodinamico"].get(k)
                for k in (
                    "by_level_label", "alert_count", "max_rd",
                    "missing_24h", "last_update",
                )
            },
            "resumo_fogo": {
                k: data["stats"]["risco_fogo"].get(k)
                for k in (
                    "classes_label", "alertas_rf", "data_referencia",
                    "total_trechos",
                )
            },
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        return (
            "application/json; charset=utf-8",
            f"pli_overview_{ts}.json",
            body,
        )

    if report_type == "geodinamico":
        rows = _rows_geodynamic_report(data)
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        else:
            buf.write("sem_dados\n")
        return (
            "text/csv; charset=utf-8",
            f"pli_geodinamico_top_uas_{ts}.csv",
            buf.getvalue(),
        )

    if report_type == "fogo":
        rows = _rows_fire_report(data)
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        else:
            buf.write("sem_dados\n")
        return (
            "text/csv; charset=utf-8",
            f"pli_fogo_top_trechos_{ts}.csv",
            buf.getvalue(),
        )

    if report_type == "operacional":
        return _html_operacional_report(data, ts)

    raise ValueError(f"tipo de relatorio desconhecido: {report_type}")


def _html_operacional_report(data: Dict, ts: str) -> Tuple[str, str, str]:
    ov = data["overview"]
    geo = data["stats"]["geodinamico"]
    fire = data["stats"]["risco_fogo"]
    ana = data["analytics"]

    def bar_items(counts: Dict, labels: Dict) -> str:
        total = sum(int(v) for v in counts.values()) or 1
        parts = []
        for k, v in sorted(counts.items(), key=lambda x: -int(x[1])):
            pct = round(100 * int(v) / total, 1)
            lbl = labels.get(k, k)
            parts.append(
                f"<tr><td>{lbl}</td><td>{v}</td>"
                f"<td><div class='bar'><i style='width:{pct}%'></i>"
                f"</div> {pct}%</td></tr>"
            )
        return "\n".join(parts)

    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>Relatorio operacional PLI-HazardTrack</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;margin:2rem;color:#0f172a}}
h1{{color:#0f3a1f;font-size:1.4rem}}
h2{{color:#003b5a;font-size:1rem;margin-top:1.5rem}}
.meta{{color:#64748b;font-size:.85rem}}
table{{width:100%;border-collapse:collapse;font-size:.85rem;margin:.5rem 0}}
th, td{{border:1px solid #e2e8f0;padding:.4rem .6rem;text-align:left}}
th{{background:#f1f5f4}}
.bar{{background:#e2e8f0;height:8px;border-radius:4px;width:120px;
display:inline-block;vertical-align:middle}}
.bar i{{display:block;height:100%;background:#3ec26e;border-radius:4px}}
.kpi{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0}}
.kpi div{{border:1px solid #e2e8f0;border-radius:8px;padding:.8rem 1rem;
min-width:140px}}
.kpi b{{display:block;font-size:1.4rem;color:#0f3a1f}}
@media print{{body{{margin:1cm}}}}
</style></head><body>
<h1>PLI-HazardTrack — Relatorio operacional</h1>
<p class="meta">Gerado em {data['generated_at']} · ref {ts}</p>
<div class="kpi">
<div><small>RD maximo</small><b>{ov['geodinamico']['max_rd']}</b>
{ov['geodinamico']['max_rd_label']}</div>
<div><small>UAs monitoradas</small>
<b>{ov['geodinamico']['uas_monitoradas']}</b></div>
<div><small>Alertas RD (3+4)</small>
<b>{ov['geodinamico']['alertas_rd']}</b></div>
<div><small>Trechos fogo</small>
<b>{ov['risco_fogo']['total_trechos']}</b></div>
<div><small>RF alto/critico</small>
<b>{ov['risco_fogo']['alertas_rf']}</b></div>
<div><small>Ciclos OK</small>
<b>{ana['cycle_success_rate_pct']}%</b></div>
</div>
<h2>Movimentos de massa e inundacao — distribuicao RD</h2>
<table><thead><tr><th>Nivel</th><th>UAs</th><th>Share</th></tr></thead>
<tbody>{bar_items(geo['by_level'], geo['by_level_label'])}</tbody></table>
<h2>Risco de fogo — classes RF</h2>
<table><thead><tr><th>Classe</th><th>Trechos</th><th>Share</th></tr></thead>
<tbody>{bar_items(fire['classes'], fire['classes_label'])}</tbody></table>
<h2>Top UAs — movimento de massa</h2>
<table><thead><tr><th>UA</th><th>Rodovia</th><th>RD</th><th>Chuva 96h</th></tr>
</thead><tbody>
"""
    for p in geo.get("top_uas_geo", [])[:8]:
        html += (
            f"<tr><td>{p.get('ua_id', '')}</td>"
            f"<td>{p.get('sigla_rodovia', '')}</td>"
            f"<td>{p.get('rd')} — {p.get('nivel', '')}</td>"
            f"<td>{p.get('ac96h_mm', '—')} mm</td></tr>\n"
        )
    html += "</tbody></table><h2>Top trechos — risco de fogo</h2><table>"
    html += "<thead><tr><th>Rodovia</th><th>Km</th><th>RF</th><th>Classe</th>"
    html += "</tr></thead><tbody>"
    for t in fire.get("top_trechos", [])[:8]:
        html += (
            f"<tr><td>{t.get('rodovia', '')}</td>"
            f"<td>{t.get('km_ini', '')}–{t.get('km_fim', '')}</td>"
            f"<td>{t.get('rf_valor', '')}</td>"
            f"<td>{t.get('rf_classe', '')}</td></tr>\n"
        )
    html += "</tbody></table></body></html>"
    return (
        "text/html; charset=utf-8",
        f"pli_operacional_{ts}.html",
        html,
    )
