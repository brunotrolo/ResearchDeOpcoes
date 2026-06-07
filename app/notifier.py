"""Notificador (pager) — alertas por e-mail via smtplib, em CARDS por operação.

    - URGENTE (Escudo): card de cada posição que precisa de ação (ALERTA/CRÍTICO),
      com todos os dados (spot, strike, prêmios, gregas, P/L, etc.) + comentário.
    - OPORTUNIDADE (Radar): card de cada PUT recomendada, com os dados + o PORQUÊ
      (tendência/IV/score do ativo-mãe).

Cada e-mail é multipart: TEXTO (celular) + HTML (cards). Em DRY_RUN não envia.
"""
from __future__ import annotations

import re
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from app import config

_COR = {"CRITICO": "#dc2626", "ALERTA": "#ea580c", "AVISO": "#ca8a04"}
_BG = {"CRITICO": "#fef2f2", "ALERTA": "#fff7ed", "AVISO": "#fefce8"}
_EMOJI = {"CRITICO": "🚨", "ALERTA": "⚠️", "AVISO": "🟡"}


# --- envio -----------------------------------------------------------------
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
    msg.attach(MIMEText(text_body or _strip(html_body), "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, context=context) as server:
        server.login(cfg.user, cfg.app_password)
        server.sendmail(cfg.sender or cfg.user, cfg.recipients, msg.as_string())
    return True


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


# --- formatadores (pt-BR) --------------------------------------------------
def _brl(v) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("-R$ " if v < 0 else "R$ ") + s


def _pct(v, dec: int = 2) -> str:
    return "—" if v is None else f"{v:.{dec}f}".replace(".", ",") + "%"


def _num(v, dec: int = 4) -> str:
    return "—" if v is None else f"{v:.{dec}f}".replace(".", ",")


def _intbr(v) -> str:
    return "—" if v is None else f"{int(v):,}".replace(",", ".")


def _wrap(body: str, titulo: str, sub: str, rodape: str) -> str:
    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;max-width:680px;margin:0 auto;background:#f7f7f8;padding:14px'>"
        f"<h2 style='margin:4px 0'>{titulo}</h2>"
        f"<p style='color:#555;margin:0 0 12px'>{sub}</p>"
        f"{body}"
        f"<p style='color:#999;font-size:12px;margin-top:8px'>{rodape}</p></div>"
    )


def _grid(items: list[tuple[str, str]]) -> str:
    """Grade de métricas (3 colunas), cada célula com rótulo + valor."""
    cells = ""
    for i, (label, value) in enumerate(items):
        cells += (
            "<td width='33%' style='padding:6px 10px;vertical-align:top'>"
            f"<div style='font-size:11px;color:#888'>{label}</div>"
            f"<div style='font-size:15px;font-weight:600;color:#111'>{value}</div></td>"
        )
        if i % 3 == 2:
            cells += "</tr><tr>"
    return f"<table width='100%' style='border-collapse:collapse'><tr>{cells}</tr></table>"


# --- e-mail de teste -------------------------------------------------------
def send_test_email() -> bool:
    agora = datetime.now(ZoneInfo(config.RUNTIME.timezone)).strftime("%d/%m/%Y %H:%M:%S")
    subject = "✅ ResearchDeOpcoes — e-mail de teste OK"
    text = (f"Se você recebeu este e-mail, o pager está funcionando.\n\n"
            f"Segredos, SMTP e envio: OK.\nHorário: {agora}\n— motor ResearchDeOpcoes")
    html = _wrap("<p style='font-size:16px'>O <b>pager está funcionando</b>: segredos, SMTP e envio OK.</p>",
                 "✅ E-mail de teste OK", f"Horário: {agora}", "motor ResearchDeOpcoes")
    return _send(subject, html, text)


# --- ESCUDO ----------------------------------------------------------------
def _escudo_card(a: dict) -> str:
    nivel = a.get("nivel", "ALERTA")
    cor, bg, emoji = _COR.get(nivel, "#555"), _BG.get(nivel, "#fff"), _EMOJI.get(nivel, "")

    if str(a.get("option_ticker", "")).startswith("PORTFOLIO"):
        return (
            f"<table width='100%' style='border-collapse:collapse;margin:0 0 14px;background:#fff;"
            f"border:1px solid #e5e7eb;border-left:5px solid {cor}'>"
            f"<tr style='background:{bg}'><td style='padding:10px 14px'>"
            f"<b style='font-size:16px'>🛡️ Risco de Carteira</b>"
            f"<span style='float:right;font-weight:700;color:{cor}'>{emoji} {nivel}</span></td></tr>"
            f"<tr><td style='padding:10px 14px;color:#111'>{a.get('descricao', a.get('motivo',''))}</td></tr>"
            f"<tr><td style='padding:8px 14px;background:#f9fafb;border-top:1px solid #eee'>"
            f"⚠️ <b>Ação:</b> {a.get('acao_sugerida','')}</td></tr></table>")

    side = a.get("side", "")
    side_lbl = ("V" if side == "VENDA" else "C" if side == "COMPRA" else "") + " " + str(a.get("option_type") or "")
    plv = _brl(a.get("pl_value")) + " (" + _pct(a.get("pl_pct")) + ")"
    metrics = [
        ("Spot", _brl(a.get("spot"))), ("Dist.", _pct(a.get("dist_pct"), 1)), ("Strike", _brl(a.get("strike"))),
        ("Prêmio médio", _brl(a.get("entry_price"))), ("Prêmio atual", _brl(a.get("last_premium"))),
        ("Break-even", _brl(a.get("break_even"))),
        ("Recompra", f"{a.get('buyback_mult'):.2f}x".replace(".", ",") if a.get("buyback_mult") is not None else "—"),
        ("Delta", _num(a.get("delta"))), ("POE", _pct(a.get("poe") * 100, 0) if a.get("poe") is not None else "—"),
        ("Ganho máx.", _brl(a.get("max_gain"))), ("Lucro máx.", _pct(a.get("max_profit_pct"))),
        ("Nocional", _brl(a.get("notional"))),
    ]
    coment = ""
    if a.get("analise"):
        coment = (f"<tr><td style='padding:8px 14px;background:#eff6ff;border-top:1px solid #eee'>"
                  f"🔎 <b>Análise:</b> {a['analise']}</td></tr>")
    return (
        f"<table width='100%' style='border-collapse:collapse;margin:0 0 14px;background:#fff;"
        f"border:1px solid #e5e7eb;border-left:5px solid {cor}'>"
        f"<tr style='background:{bg}'><td style='padding:10px 14px'>"
        f"<span style='font-size:18px;font-weight:700'>{a.get('ticker','')}</span>"
        f"<span style='color:#555'> · {side_lbl} · {a.get('moneyness','')}</span>"
        f"<span style='float:right;font-weight:700;color:{cor}'>{emoji} {nivel}</span>"
        f"<div style='color:#666;font-size:13px;margin-top:2px'>{a.get('option_ticker','')} · "
        f"{_intbr(a.get('quantity'))} contratos · {a.get('dte','')}d ({a.get('expiry','')})</div></td></tr>"
        f"<tr><td style='padding:4px 4px'>{_grid(metrics)}</td></tr>"
        f"<tr><td style='padding:8px 14px;background:{bg};border-top:1px solid #eee'>"
        f"<b>L/P aberto:</b> {plv}</td></tr>"
        f"<tr><td style='padding:8px 14px;background:#f9fafb;border-top:1px solid #eee'>"
        f"⚠️ <b>Ação:</b> {a.get('acao_sugerida','')}</td></tr>{coment}</table>")


def send_escudo_alert(alerts: list[dict]) -> bool:
    if not alerts:
        return False
    n_crit = sum(1 for a in alerts if a.get("nivel") == "CRITICO")
    subject = f"🚨 ESCUDO — {len(alerts)} posição(ões) precisam de atenção" + (f" | {n_crit} CRÍTICO(s)" if n_crit else "")
    cards = "".join(_escudo_card(a) for a in alerts)
    html = _wrap(cards, "🛡️ Defesa de Posições",
                 f"{len(alerts)} operação(ões) precisam de ação. (As que estão tranquilas não entram aqui.)",
                 "Gerado pelo motor ResearchDeOpcoes.")
    # texto
    linhas = []
    for a in alerts:
        if str(a.get("option_ticker", "")).startswith("PORTFOLIO"):
            linhas.append(f"[{a['nivel']}] CARTEIRA — {a.get('descricao','')} → {a.get('acao_sugerida','')}")
            continue
        linhas.append(
            f"[{a['nivel']}] {a.get('ticker','')} {a.get('option_ticker','')} ({a.get('moneyness','')})\n"
            f"  Strike {_brl(a.get('strike'))} | Spot {_brl(a.get('spot'))} ({_pct(a.get('dist_pct'),1)}) | "
            f"Prêmio {_brl(a.get('entry_price'))}→{_brl(a.get('last_premium'))} | Δ {_num(a.get('delta'),2)} | "
            f"L/P {_brl(a.get('pl_value'))} ({_pct(a.get('pl_pct'))})\n  → {a.get('acao_sugerida','')}"
            + (f"\n  🔎 {a['analise']}" if a.get("analise") else ""))
    text = "🚨 DEFESA DE POSIÇÕES\n\n" + "\n\n".join(linhas) + "\n\n— motor ResearchDeOpcoes"
    return _send(subject, html, text)


# --- RADAR -----------------------------------------------------------------
def _radar_card(o: dict) -> str:
    iv = o.get("iv_rank")
    metrics = [
        ("Spot", _brl(o.get("spot"))), ("Strike", _brl(o.get("strike"))),
        ("Dist. (margem)", _pct(o.get("dist_pct"), 1)),
        ("IV Rank", _num(iv, 0)), ("Taxa retorno", _pct(o.get("profit_rate"))),
        ("Vol. financ.", _brl(o.get("volume_fin"))),
    ]
    if o.get("contratos_sugeridos") is not None:
        metrics.append(("Contratos sug.", _intbr(o.get("contratos_sugeridos"))))
    return (
        "<table width='100%' style='border-collapse:collapse;margin:0 0 14px;background:#fff;"
        "border:1px solid #e5e7eb;border-left:5px solid #16a34a'>"
        "<tr style='background:#f0fdf4'><td style='padding:10px 14px'>"
        f"<span style='font-size:18px;font-weight:700'>{o.get('ticker','')}</span>"
        f"<span style='color:#555'> · V PUT</span>"
        f"<span style='float:right;font-weight:700;color:#16a34a'>IV Rank {_num(iv,0)}</span>"
        f"<div style='color:#666;font-size:13px;margin-top:2px'>{o.get('option_ticker','')} · "
        f"{o.get('dte','')}d ({o.get('expiry_fmt','')})</div></td></tr>"
        f"<tr><td style='padding:4px 4px'>{_grid(metrics)}</td></tr>"
        f"<tr><td style='padding:8px 14px;background:#f0fdf4;border-top:1px solid #eee'>"
        f"💡 <b>Por quê:</b> {o.get('motivo','—')}</td></tr></table>")


def send_radar_opportunities(opps: list[dict]) -> bool:
    if not opps:
        return False
    subject = f"📡 RADAR — {len(opps)} oportunidade(s) de venda de PUT"
    cards = "".join(_radar_card(o) for o in opps)
    html = _wrap(cards, "📡 Oportunidades de Venda de PUT",
                 f"Top {len(opps)} (IV alto, OTM com margem, DTE no alvo, líquidas).",
                 "Gerado pelo motor ResearchDeOpcoes. Não é recomendação de investimento.")
    linhas = []
    for i, o in enumerate(opps, 1):
        linhas.append(
            f"{i}. {o.get('ticker','')} {o.get('option_ticker','')}\n"
            f"   Strike {_brl(o.get('strike'))} | Spot {_brl(o.get('spot'))} ({_pct(o.get('dist_pct'),1)}) | "
            f"IV Rank {_num(o.get('iv_rank'),0)} | DTE {o.get('dte','')} | Taxa {_pct(o.get('profit_rate'))}\n"
            f"   💡 {o.get('motivo','')}")
    text = "📡 OPORTUNIDADES DE VENDA DE PUT\n\n" + "\n\n".join(linhas) + \
        "\n\nNão é recomendação de investimento.\n— motor ResearchDeOpcoes"
    return _send(subject, html, text)
