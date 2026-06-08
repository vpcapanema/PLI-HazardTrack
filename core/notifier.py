"""
Servico de notificacao de alertas (e-mail / webhook).

Dispara quando uma ZONA atinge Risco Dinamico (RD) >= limiar, com politica
anti-spam (cooldown por zona + reenvio so em escalada de nivel).

Canais (configurados por ambiente; sem config -> servico DESABILITADO, nunca
mock):
- E-mail (SMTP):   SAMAEG_SMTP_HOST, SAMAEG_SMTP_PORT, SAMAEG_SMTP_USER,
                   SAMAEG_SMTP_PASS, SAMAEG_ALERT_EMAIL_FROM,
                   SAMAEG_ALERT_EMAIL_TO (lista separada por virgula).
- Webhook (HTTP):  SAMAEG_ALERT_WEBHOOK_URL  (POST JSON; serve Slack/Telegram/
                   gateway de SMS/etc).

Parametros:
- SAMAEG_RD_ALERT_THRESHOLD (default 3 = "Alto")
- SAMAEG_ALERT_COOLDOWN_H   (default 6 h)

Politica de dados: nunca inventa. Se um canal falha, registra erro e segue;
falha de notificacao NUNCA interrompe o ciclo de monitoramento.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from threading import Lock
from typing import Dict, List, Optional, Tuple, Any
import logging
import os
import smtplib

log = logging.getLogger("notifier")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _emails_to() -> List[str]:
    raw = _env("SAMAEG_ALERT_EMAIL_TO")
    return [e.strip() for e in raw.split(",") if e.strip()]


@dataclass
class NotifierStatus:
    enabled_email: bool = False
    enabled_webhook: bool = False
    threshold: int = 3
    cooldown_h: float = 6.0
    sent_total: int = 0
    last_sent_at: Optional[str] = None
    last_error: Optional[str] = None
    last_error_at: Optional[str] = None
    last_alert_count: int = 0
    channels_ok: Dict[str, bool] = field(default_factory=dict)


class Notifier:
    def __init__(self):
        self._lock = Lock()
        self.threshold = int(_env("SAMAEG_RD_ALERT_THRESHOLD", "3"))
        self.cooldown = timedelta(
            hours=float(_env("SAMAEG_ALERT_COOLDOWN_H", "6"))
        )
        # e-mail
        self.smtp_host = _env("SAMAEG_SMTP_HOST")
        self.smtp_port = int(_env("SAMAEG_SMTP_PORT", "587") or "587")
        self.smtp_user = _env("SAMAEG_SMTP_USER")
        self.smtp_pass = _env("SAMAEG_SMTP_PASS")
        self.email_from = _env("SAMAEG_ALERT_EMAIL_FROM") or self.smtp_user
        self.email_to = _emails_to()
        # webhook
        self.webhook_url = _env("SAMAEG_ALERT_WEBHOOK_URL")

        self.enabled_email = bool(self.smtp_host and self.email_to)
        self.enabled_webhook = bool(self.webhook_url)

        # estado anti-spam: zone_id -> (nivel_alertado, quando)
        self._last_alert: Dict[str, Tuple[int, datetime]] = {}
        # telemetria
        self.sent_total = 0
        self.last_sent_at: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.last_error_at: Optional[datetime] = None
        self.last_alert_count = 0
        self.last_channels_ok: Dict[str, bool] = {}

        if not (self.enabled_email or self.enabled_webhook):
            log.info("Notifier DESABILITADO (nenhum canal configurado).")
        else:
            log.info(
                "Notifier ativo: email=%s webhook=%s limiar=RD%d cooldown=%sh",
                self.enabled_email, self.enabled_webhook,
                self.threshold, self.cooldown.total_seconds() / 3600,
            )

    # ----------------------------------------------------------------- API
    def evaluate(self, points: List[Dict[str, Any]], summary: Dict[str, Any],
                 now: Optional[datetime] = None) -> int:
        """Avalia o snapshot e dispara notificacoes se necessario.

        Retorna o numero de zonas alertadas neste ciclo (0 se nada)."""
        now = now or datetime.now(timezone.utc)
        if not (self.enabled_email or self.enabled_webhook):
            return 0

        try:
            alerts = self._select_alerts(points, now)
            self.last_alert_count = len(alerts)
            if not alerts:
                return 0
            self._dispatch(alerts, summary, now)
            return len(alerts)
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            self.last_error_at = now
            log.exception("falha ao notificar: %s", e)
            return 0

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            st = NotifierStatus(
                enabled_email=self.enabled_email,
                enabled_webhook=self.enabled_webhook,
                threshold=self.threshold,
                cooldown_h=self.cooldown.total_seconds() / 3600,
                sent_total=self.sent_total,
                last_sent_at=(self.last_sent_at.isoformat()
                              if self.last_sent_at else None),
                last_error=self.last_error,
                last_error_at=(self.last_error_at.isoformat()
                               if self.last_error_at else None),
                last_alert_count=self.last_alert_count,
                channels_ok=dict(self.last_channels_ok),
            )
            return st.__dict__

    # ------------------------------------------------------------- internos
    def _select_alerts(self, points: List[Dict[str, Any]],
                       now: datetime) -> List[Dict[str, Any]]:
        """Decide quais zonas alertar (novo / escalada / lembrete pos-cooldown)
        e limpa zonas que retornaram abaixo do limiar."""
        alerts: List[Dict[str, Any]] = []
        with self._lock:
            active_ids = set()
            for p in points:
                rd = p.get("rd")
                if p.get("source") == "NO_DATA" or rd is None:
                    continue
                zid = p.get("id")
                if rd >= self.threshold:
                    active_ids.add(zid)
                    prev = self._last_alert.get(zid)
                    fire = (
                        prev is None                       # novo
                        or rd > prev[0]                    # escalada
                        or (now - prev[1]) >= self.cooldown  # lembrete
                    )
                    if fire:
                        self._last_alert[zid] = (rd, now)
                        alerts.append(p)
            # de-escalada: remove zonas que sairam do alerta
            for zid in [z for z in self._last_alert if z not in active_ids]:
                del self._last_alert[zid]
        # pior caso primeiro
        alerts.sort(key=lambda p: (p.get("rd", 0), p.get("ac96h_mm", 0)),
                    reverse=True)
        return alerts

    def _dispatch(self, alerts: List[Dict[str, Any]],
                  summary: Dict[str, Any], now: datetime) -> None:
        subject, body = self._format(alerts, summary, now)
        channels_ok: Dict[str, bool] = {}
        if self.enabled_email:
            channels_ok["email"] = self._send_email(subject, body)
        if self.enabled_webhook:
            channels_ok["webhook"] = self._send_webhook(
                subject, body, alerts, now)

        with self._lock:
            self.last_channels_ok = channels_ok
            if any(channels_ok.values()):
                self.sent_total += 1
                self.last_sent_at = now
        log.warning("ALERTA: %d zona(s) RD>=%d | canais=%s",
                    len(alerts), self.threshold, channels_ok)

    def _format(self, alerts: List[Dict[str, Any]],
                summary: Dict[str, Any], now: datetime) -> Tuple[str, str]:
        n = len(alerts)
        subject = (f"[HazardTrack] {n} zona(s) em risco "
                   f"(RD>={self.threshold}) - max RD{summary.get('max_rd', 0)}")
        linhas = [
            "Sistema de Alerta - Plano de Contingencia (rodovias SP-055/SP-098)",
            f"Horario (UTC): {now.isoformat(timespec='seconds')}",
            f"Fonte de chuva: {summary.get('data_source', '-')} "
            f"(status: {summary.get('data_status', '-')})",
            "",
            f"{n} zona(s) com Risco Dinamico >= {self.threshold}:",
            "",
        ]
        for p in alerts[:50]:
            km = p.get("km")
            km_txt = f" km {km}" if km is not None else ""
            linhas.append(
                f"- [{p.get('nome', p.get('id'))}] {p.get('rodovia', '')}"
                f"{km_txt} | RD{p.get('rd')} ({p.get('nivel', '')}) "
                f"| RA{p.get('ra')} "
                f"| chuva24h={p.get('ac24h_mm')}mm 96h={p.get('ac96h_mm')}mm "
                f"| {p.get('region_name', '')}"
            )
        if n > 50:
            linhas.append(f"... (+{n - 50} zonas)")
        return subject, "\n".join(linhas)

    def _send_email(self, subject: str, body: str) -> bool:
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.email_from
            msg["To"] = ", ".join(self.email_to)
            msg.set_content(body)
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port,
                                      timeout=20) as s:
                    if self.smtp_user:
                        s.login(self.smtp_user, self.smtp_pass)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port,
                                  timeout=20) as s:
                    s.ehlo()
                    try:
                        s.starttls()
                        s.ehlo()
                    except smtplib.SMTPException:
                        pass
                    if self.smtp_user:
                        s.login(self.smtp_user, self.smtp_pass)
                    s.send_message(msg)
            return True
        except Exception as e:  # noqa: BLE001
            self.last_error = f"email: {e}"
            self.last_error_at = datetime.now(timezone.utc)
            log.error("falha email: %s", e)
            return False

    def _send_webhook(self, subject: str, body: str,
                      alerts: List[Dict[str, Any]], now: datetime) -> bool:
        try:
            import requests
            payload = {
                "text": subject + "\n" + body,   # Slack/Telegram-friendly
                "subject": subject,
                "timestamp": now.isoformat(),
                "count": len(alerts),
                "threshold": self.threshold,
                "zones": [
                    {
                        "id": p.get("id"), "nome": p.get("nome"),
                        "rodovia": p.get("rodovia"), "km": p.get("km"),
                        "rd": p.get("rd"), "nivel": p.get("nivel"),
                        "ra": p.get("ra"),
                        "lat": p.get("lat"), "lon": p.get("lon"),
                        "ac24h_mm": p.get("ac24h_mm"),
                        "ac96h_mm": p.get("ac96h_mm"),
                        "region": p.get("region_name"),
                    } for p in alerts[:100]
                ],
            }
            r = requests.post(self.webhook_url, json=payload, timeout=15)
            return 200 <= r.status_code < 300
        except Exception as e:  # noqa: BLE001
            self.last_error = f"webhook: {e}"
            self.last_error_at = datetime.now(timezone.utc)
            log.error("falha webhook: %s", e)
            return False


# Singleton
notifier = Notifier()
