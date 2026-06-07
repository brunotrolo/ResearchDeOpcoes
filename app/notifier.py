"""Notificador (pager) — alertas por e-mail via smtplib.

Dois tipos de alerta:
    - URGENTE (Escudo): posição/carteira em zona de gatilho (ALERTA/CRÍTICO).
    - OPORTUNIDADE (Radar): Top-N operações que passaram em todos os filtros.

Cada e-mail é multipart: parte TEXTO (legível no celular) + parte HTML (tabela).
Usa SMTP sobre SSL (Gmail por padrão). Em DRY_RUN, apenas registra e não envia.
"""
from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app import config


def _send(subject: str, html_body: str, text_body: str = "") -> bool:
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
    # Em multipart/alternative o cliente prefere a ÚLTIMA parte: texto antes, HTML depois.
    msg.attach(MIMEText(text_body or _strip(html_body), "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, context=context) as server:
        server.login(cfg.user, cfg.app_password)
        server.sendmail(cfg.sender or cfg.user, cfg.recipients, msg.as_string())
    return True


def _strip(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", " ", html)


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


def _fmt(v, spec: str = "", dash: str = "-") -> str:
    return format(v, spec) if v is not None else dash


def send_test_email() -> bool:
    """E-mail de teste — prova que segredos, SMTP e envio estão OK (homologação)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    agora = datetime.now(ZoneInfo(config.RUNTIME.timezone)).strftime("%d/%m/%Y %H:%M:%S")
    subject = "✅ ResearchDeOpcoes — e-mail de teste OK"
    text = (f"Se você recebeu este e-mail, o pager está funcionando.\n\n"
            f"Segredos, SMTP e envio: OK.\nHorário: {agora}\n— motor ResearchDeOpcoes")
    html = (f"<h2 style='font-family:Segoe UI,Arial'>✅ E-mail de teste OK</h2>"
            f"<p style='font-family:Segoe UI,Arial'>Se você recebeu este e-mail, o <b>pager está "
            f"funcionando</b>: segredos, SMTP e envio OK.</p>"
            f"<p style='font-family:Segoe UI,Arial;color:#666'>Horário: {agora} · motor ResearchDeOpcoes</p>")
    return _send(subject, html, text)


def send_escudo_alert(alerts: list[dict]) -> bool:
    """alerts: lista já filtrada para níveis que merecem e-mail (ALERTA/CRÍTICO)."""
    if not alerts:
        return False
    n_crit = sum(1 for a in alerts if a.get("nivel") == "CRITICO")
    subject = f"🚨 ESCUDO — {len(alerts)} alerta(s)" + (f" | {n_crit} CRÍTICO(s)" if n_crit else "")

    # --- TEXTO (celular) ---
    linhas = []
    for a in alerts:
        contexto = a.get("descricao") or a.get("motivo", "")
        ident = a.get("option_ticker", "") if str(a.get("option_ticker", "")).startswith("PORTFOLIO") else \
            f"{a.get('option_ticker','')} ({a.get('ticker','')}, {a.get('moneyness','')})"
        linhas.append(f"[{a.get('nivel')}] {ident}\n    {contexto}\n    → {a.get('acao_sugerida','')}")
    text_body = "🚨 DEFESA DE POSIÇÕES\n\n" + "\n\n".join(linhas) + \
        "\n\n— motor ResearchDeOpcoes"

    # --- HTML ---
    headers = ["Opção", "Ativo", "Nível", "Money.", "DTE", "Δ", "POE", "Recompra", "P&L", "Ação"]
    rows = [[
        a.get("option_ticker", ""), a.get("ticker", ""), a.get("nivel", ""),
        a.get("moneyness", ""), _fmt(a.get("dte")),
        _fmt(a.get("delta"), ".2f"),
        f"{a.get('poe'):.0%}" if a.get("poe") is not None else "-",
        f"{a.get('buyback_mult'):.2f}x" if a.get("buyback_mult") is not None else "-",
        f"R$ {a.get('pl_value'):.0f}" if a.get("pl_value") is not None else "-",
        a.get("acao_sugerida", ""),
    ] for a in alerts]
    html = (
        "<h2 style='font-family:Segoe UI,Arial'>🚨 Alerta de Defesa de Posições</h2>"
        f"<p style='font-family:Segoe UI,Arial'>{len(alerts)} item(ns) em zona de atenção/perigo:</p>"
        f"{_table(rows, headers)}"
        "<p style='font-family:Segoe UI,Arial;color:#666;font-size:12px'>"
        "Gerado automaticamente pelo motor ResearchDeOpcoes.</p>"
    )
    return _send(subject, html, text_body)


def send_radar_opportunities(opps: list[dict]) -> bool:
    if not opps:
        return False
    subject = f"📡 RADAR — Top {len(opps)} oportunidade(s) de PUT (prêmio gordo)"

    # --- TEXTO (celular) ---
    linhas = []
    for i, o in enumerate(opps, 1):
        sizing = f" | contratos sug.: {o['contratos_sugeridos']}" if o.get("contratos_sugeridos") else ""
        linhas.append(
            f"{i}. {o.get('option_ticker','')} ({o.get('ticker','')})\n"
            f"    Strike R$ {_fmt(o.get('strike'), '.2f')} | Spot R$ {_fmt(o.get('spot'), '.2f')} "
            f"| IV Rank {_fmt(o.get('iv_rank'), '.0f')} | DTE {_fmt(o.get('dte'))}"
            f" | taxa {_fmt(o.get('profit_rate'), '.2f')}%{sizing}")
    text_body = "📡 OPORTUNIDADES DE VENDA DE PUT\n\n" + "\n\n".join(linhas) + \
        "\n\nNão é recomendação de investimento.\n— motor ResearchDeOpcoes"

    # --- HTML ---
    has_sizing = any(o.get("contratos_sugeridos") is not None for o in opps)
    headers = ["Opção", "Ativo", "Strike", "Spot", "Spot/Strike", "IV Rank", "Taxa%", "DTE", "Vol.Fin"]
    if has_sizing:
        headers.append("Contratos")
    rows = []
    for o in opps:
        row = [
            o.get("option_ticker", ""), o.get("ticker", ""),
            _fmt(o.get("strike"), ".2f"), _fmt(o.get("spot"), ".2f"),
            _fmt(o.get("spot_strike_ratio"), ".4f"), _fmt(o.get("iv_rank"), ".1f"),
            _fmt(o.get("profit_rate"), ".2f"), _fmt(o.get("dte")),
            f"{o.get('volume_fin'):.0f}" if o.get("volume_fin") is not None else "-",
        ]
        if has_sizing:
            row.append(_fmt(o.get("contratos_sugeridos")))
        rows.append(row)
    html = (
        "<h2 style='font-family:Segoe UI,Arial'>📡 Oportunidades de Venda de PUT</h2>"
        f"<p style='font-family:Segoe UI,Arial'>Top {len(opps)} (IV Rank alto, OTM com margem, "
        f"DTE no alvo, líquidas):</p>{_table(rows, headers)}"
        "<p style='font-family:Segoe UI,Arial;color:#666;font-size:12px'>"
        "Gerado automaticamente pelo motor ResearchDeOpcoes. Não é recomendação de investimento.</p>"
    )
    return _send(subject, html, text_body)
