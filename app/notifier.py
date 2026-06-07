"""Notificador (pager) — alertas por e-mail via smtplib.

Dois tipos de alerta:
    - URGENTE (Escudo): posição de risco passou de gatilho (ALERTA/CRÍTICO).
    - OPORTUNIDADE (Radar): Top-N operações que passaram em todos os filtros.

Usa SMTP sobre SSL (Gmail por padrão). Em DRY_RUN, apenas registra e não envia.
"""
from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app import config


def _send(subject: str, html_body: str) -> bool:
    cfg = config.EMAIL
    if config.RUNTIME.dry_run:
        print(f"[DRY_RUN] E-mail NÃO enviado -> '{subject}'")
        return False
    if not cfg.enabled:
        return False
    if not (cfg.user and cfg.app_password and cfg.recipients):
        raise RuntimeError("Config de e-mail incompleta (EMAIL_USER/APP_PASSWORD/ALERT_RECIPIENTS).")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg.sender or cfg.user
    msg["To"] = ", ".join(cfg.recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, context=context) as server:
        server.login(cfg.user, cfg.app_password)
        server.sendmail(cfg.sender or cfg.user, cfg.recipients, msg.as_string())
    return True


# --- Templates --------------------------------------------------------------
def _table(rows: list[list[str]], headers: list[str]) -> str:
    head = "".join(f"<th style='padding:6px 10px;text-align:left'>{h}</th>" for h in headers)
    body = ""
    for r in rows:
        tds = "".join(f"<td style='padding:6px 10px;border-top:1px solid #eee'>{c}</td>" for c in r)
        body += f"<tr>{tds}</tr>"
    return (
        "<table style='border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:14px'>"
        f"<thead style='background:#f3f4f6'><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def send_escudo_alert(alerts: list[dict]) -> bool:
    """alerts: lista de dicts já filtrada para níveis que merecem e-mail."""
    if not alerts:
        return False
    n_crit = sum(1 for a in alerts if a.get("nivel") == "CRITICO")
    headers = ["Opção", "Ativo", "Nível", "Moneyness", "DTE", "Δ", "Recompra", "P&L", "Ação"]
    rows = [
        [
            a.get("option_ticker", ""),
            a.get("ticker", ""),
            a.get("nivel", ""),
            a.get("moneyness", ""),
            str(a.get("dte", "")),
            f"{a.get('delta'):.2f}" if a.get("delta") is not None else "-",
            f"{a.get('buyback_mult'):.2f}x" if a.get("buyback_mult") is not None else "-",
            f"R$ {a.get('pl_value'):.0f}" if a.get("pl_value") is not None else "-",
            a.get("acao_sugerida", ""),
        ]
        for a in alerts
    ]
    subject = f"🛡️ ESCUDO — {len(alerts)} alerta(s)" + (f" | {n_crit} CRÍTICO(s)" if n_crit else "")
    body = (
        f"<h2 style='font-family:Segoe UI,Arial'>🛡️ Alerta de Defesa de Posições</h2>"
        f"<p style='font-family:Segoe UI,Arial'>O Escudo detectou {len(alerts)} perna(s) "
        f"vendida(s) em zona de atenção/perigo:</p>{_table(rows, headers)}"
        "<p style='font-family:Segoe UI,Arial;color:#666;font-size:12px'>"
        "Gerado automaticamente pelo motor ResearchDeOpcoes.</p>"
    )
    return _send(subject, body)


def send_radar_opportunities(opps: list[dict]) -> bool:
    if not opps:
        return False
    headers = ["Opção", "Ativo", "Strike", "Spot", "Spot/Strike", "IV Rank", "Taxa%", "DTE", "Vol.Fin"]
    rows = [
        [
            o.get("option_ticker", ""),
            o.get("ticker", ""),
            f"{o.get('strike'):.2f}" if o.get("strike") is not None else "-",
            f"{o.get('spot'):.2f}" if o.get("spot") is not None else "-",
            f"{o.get('spot_strike_ratio'):.4f}" if o.get("spot_strike_ratio") is not None else "-",
            f"{o.get('iv_rank'):.1f}" if o.get("iv_rank") is not None else "-",
            f"{o.get('profit_rate'):.2f}" if o.get("profit_rate") is not None else "-",
            str(o.get("dte", "")),
            f"{o.get('volume_fin'):.0f}" if o.get("volume_fin") is not None else "-",
        ]
        for o in opps
    ]
    subject = f"🎯 RADAR — {len(opps)} oportunidade(s) de PUT (prêmio gordo)"
    body = (
        f"<h2 style='font-family:Segoe UI,Arial'>🎯 Oportunidades de Venda de PUT</h2>"
        f"<p style='font-family:Segoe UI,Arial'>Top {len(opps)} que passaram em todos os filtros "
        f"(IV Rank alto, OTM com margem, líquidas):</p>{_table(rows, headers)}"
        "<p style='font-family:Segoe UI,Arial;color:#666;font-size:12px'>"
        "Gerado automaticamente pelo motor ResearchDeOpcoes. Não é recomendação de investimento.</p>"
    )
    return _send(subject, body)
