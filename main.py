"""Orquestrador do motor ResearchDeOpcoes.

Ordem de execução (chamado pelo GitHub Actions / Task Scheduler):

    1. Lock-file (execução única).
    2. RELÓGIO DE PONTO: OpLab /market/status. Se != "A", encerra.
    3. ESCUDO: lê PAINEL_ATIVAS (+ correlação) -> defesa por perna e carteira.
    4. RADAR: lê seleções -> filtra oportunidades de PUT.
    5. Heartbeat na aba MONITOR + flush dos LOGS.

AUDITORIA: com AUDIT_VERBOSE (padrão), registra na aba LOGS TODOS os passos —
cada leitura de aba (linhas/colunas), a resposta da OpLab, as métricas de
carteira calculadas (HHI, exposição IBOV), o funil de filtros do Radar, os
alertas/oportunidades detalhados e o resultado dos e-mails. O detalhe por item
fica nas abas ESCUDO_HISTORICO / RADAR_HISTORICO.
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from app import (
    config,
    escudo,
    frames,
    market_gate,
    notifier,
    radar,
    sheets_client,
    state,
)
from app.logbook import Logbook


def _is_true(v) -> bool:
    return str(v).strip().upper() in {"TRUE", "1", "SIM", "VERDADEIRO", "ON", "YES"}


def _read_config(log: Logbook) -> dict:
    """Lê a aba CONFIG (cria com padrões se faltar) -> {CHAVE: VALOR}."""
    out = {c[0]: c[1] for c in config.DEFAULT_CONFIG}
    try:
        sheets_client.ensure_config(config.TAB_CONFIG, config.CONFIG_HEADER, config.DEFAULT_CONFIG)
        df = sheets_client.read_tab("config")
        for k, v in zip(frames.raw(df, "config", "chave"), frames.raw(df, "config", "valor")):
            k = str(k).strip().upper()
            if k:
                out[k] = str(v).strip()
    except Exception as exc:
        log.warn("CONFIG", "Não foi possível ler CONFIG; usando padrões", {"erro": str(exc)})
    return out

_ESCUDO_HIST_HEADER = [
    "UPDATED_AT", "OPTION_TICKER", "TICKER", "ID_STRATEGY", "NIVEL", "MONEYNESS",
    "DTE", "DELTA", "POE", "BUYBACK_MULT", "PL_VALUE", "MOTIVO", "ACAO_SUGERIDA",
]
_RADAR_HIST_HEADER = [
    "UPDATED_AT", "OPTION_TICKER", "TICKER", "STRIKE", "SPOT", "SPOT_STRIKE_RATIO",
    "IV_RANK", "PROFIT_RATE", "DTE", "VOLUME_FIN",
]
_ALERT_FIELDS = ("option_ticker", "ticker", "nivel", "moneyness", "dte", "delta",
                 "poe", "buyback_mult", "pl_value", "motivo")
_OPP_FIELDS = ("option_ticker", "ticker", "strike", "spot", "spot_strike_ratio",
               "iv_rank", "profit_rate", "dte", "volume_fin", "contratos_sugeridos")


def _now_str(tz) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def _run_url() -> str:
    server = os.getenv("GITHUB_SERVER_URL")
    repo = os.getenv("GITHUB_REPOSITORY")
    run_id = os.getenv("GITHUB_RUN_ID")
    return f"{server}/{repo}/actions/runs/{run_id}" if (server and repo and run_id) else ""


def _audit_read(log: Logbook, nome: str, df) -> None:
    """Registra a leitura de uma aba (auditoria)."""
    ctx = {"aba": nome, "linhas": len(df), "colunas": list(df.columns)} if config.AUDIT_VERBOSE else None
    log.info("SHEET_READ", f"{nome}: {len(df)} linha(s)", ctx)


def _write_heartbeat(log: Logbook, tz, summary: dict, status: str, duration_s: float, notes: str = "") -> None:
    """Sinal de vida na aba MONITOR (1 linha sobrescrita). Nunca derruba o run."""
    if config.RUNTIME.dry_run:
        log.info("MONITOR", f"Heartbeat (DRY_RUN, não gravado) status={status}", summary)
        return
    row = [_now_str(tz), status, summary.get("market", ""), round(duration_s, 1),
           summary.get("escudo_alerts", 0), summary.get("radar_opps", 0), _run_url(), notes]
    try:
        sheets_client.upsert_status_row(config.TAB_MONITOR, config.MONITOR_HEADER, row)
        log.info("MONITOR", f"Heartbeat gravado (status={status})")
    except Exception as exc:
        log.error("MONITOR", "Falha ao gravar heartbeat", {"erro": str(exc)})


def _run_escudo(log: Logbook, tz, summary: dict, cfg_sheet: dict) -> None:
    df = sheets_client.read_tab("ativas")
    _audit_read(log, "PAINEL_ATIVAS", df)
    try:
        df_correl = sheets_client.read_tab("correl")
        _audit_read(log, "RANKING_CORREL_IBOV", df_correl)
    except Exception as exc:
        df_correl = None
        log.warn("ESCUDO", "Sem RANKING_CORREL_IBOV (segue sem exposição IBOV)", {"erro": str(exc)})

    today = datetime.now(tz).date()
    port_audit: dict = {}
    port_alerts = escudo.analyze_portfolio(df, df_correl, audit=port_audit)
    log.info("ESCUDO", "Métricas de carteira calculadas", port_audit)
    alerts = port_alerts + escudo.analyze(df, today)

    por_nivel: dict = {}
    for a in alerts:
        por_nivel[a["nivel"]] = por_nivel.get(a["nivel"], 0) + 1
    summary["escudo_alerts"] = len(alerts)
    summary["escudo_criticos"] = por_nivel.get("CRITICO", 0)
    log.info("ESCUDO", f"{len(alerts)} alerta(s) detectado(s)",
             {"por_nivel": por_nivel,
              "detalhe": [{k: a.get(k) for k in _ALERT_FIELDS} for a in alerts]})

    ts = _now_str(tz)
    if not config.RUNTIME.dry_run:
        # PAINEL_ESCUDO (sobrescreve = estado atual, alimenta o web app)
        painel = [[ts, a.get("ticker"), a.get("option_ticker"), a["nivel"], a.get("moneyness"), a.get("dte"),
                   f"{a['delta']:.4f}" if a.get("delta") is not None else "",
                   f"{a['poe']:.2f}" if a.get("poe") is not None else "",
                   a.get("pl_value"), a.get("analise"), a.get("acao_sugerida")] for a in alerts]
        try:
            sheets_client.replace_tab(config.TAB_PAINEL_ESCUDO, config.PAINEL_ESCUDO_HEADER, painel)
        except Exception as exc:
            log.error("ESCUDO", "Falha ao gravar PAINEL_ESCUDO", {"erro": str(exc)})
        if alerts:
            hist = [[ts, a["option_ticker"], a["ticker"], a["id_strategy"], a["nivel"], a["moneyness"], a["dte"],
                     f"{a['delta']:.4f}" if a.get("delta") is not None else "",
                     f"{a['poe']:.2f}" if a.get("poe") is not None else "",
                     f"{a['buyback_mult']:.2f}" if a.get("buyback_mult") is not None else "",
                     a.get("pl_value"), a["motivo"], a["acao_sugerida"]] for a in alerts]
            sheets_client.append_rows(config.TAB_HIST_ESCUDO, hist, header=_ESCUDO_HIST_HEADER)
            log.info("ESCUDO", f"{len(hist)} linha(s) em {config.TAB_HIST_ESCUDO} + painel atualizado")

    worthy = escudo.email_worthy(alerts)
    if cfg_sheet.get("ESCUDO_NIVEL_MINIMO_EMAIL", "ALERTA").upper() == "CRITICO":
        worthy = [a for a in worthy if a["nivel"] == "CRITICO"]
    enviar = _is_true(cfg_sheet.get("ENVIAR_EMAIL")) and _is_true(cfg_sheet.get("ENVIAR_EMAIL_ESCUDO"))
    if config.RUNTIME.dry_run:
        log.info("ESCUDO", f"[DRY_RUN] {len(worthy)} elegíveis a e-mail (não enviado)",
                 {"opcoes": [a["option_ticker"] for a in worthy]})
    elif not enviar:
        log.info("ESCUDO", f"E-mail do Escudo DESLIGADO na CONFIG ({len(worthy)} elegíveis não enviados)")
    else:
        fresh = state.filter_new_alerts(worthy)
        if fresh:
            sent = notifier.send_escudo_alert(fresh)
            log.info("ESCUDO", f"E-mail urgente {'enviado' if sent else 'NÃO enviado'} ({len(fresh)} novo(s))",
                     {"opcoes": [a["option_ticker"] for a in fresh]})
        else:
            log.info("ESCUDO", f"Sem novos alertas para e-mail ({len(worthy)} elegíveis já notificados hoje)")


def _run_radar(log: Logbook, tz, summary: dict, cfg_sheet: dict) -> None:
    df_lucros = sheets_client.read_tab("lucros")
    _audit_read(log, "SELECAO_OPCOES_MAIORES_LUCROS", df_lucros)
    df_volumes = sheets_client.read_tab("volumes")
    _audit_read(log, "SELECAO_MAIORES_VOLUMES", df_volumes)
    df_dados = None
    if config.RADAR.use_dados_ativos_whitelist:
        df_dados = sheets_client.read_tab("dados_ativos")
        _audit_read(log, "DADOS_ATIVOS", df_dados)

    funil: dict = {}
    opps = radar.scan(df_lucros, df_volumes, df_dados, audit=funil)
    log.info("RADAR", "Funil de filtros", funil)
    summary["radar_opps"] = len(opps)
    log.info("RADAR", f"{len(opps)} oportunidade(s) após filtros",
             {"detalhe": [{k: o.get(k) for k in _OPP_FIELDS} for o in opps]})

    ts = _now_str(tz)
    if not config.RUNTIME.dry_run:
        painel = [[ts, o.get("ticker"), o.get("option_ticker"), o.get("strike"), o.get("spot"),
                   f"{o['dist_pct']:.2f}" if o.get("dist_pct") is not None else "",
                   o.get("iv_rank"), o.get("dte"), o.get("analise")] for o in opps]
        try:
            sheets_client.replace_tab(config.TAB_PAINEL_RADAR, config.PAINEL_RADAR_HEADER, painel)
        except Exception as exc:
            log.error("RADAR", "Falha ao gravar PAINEL_RADAR", {"erro": str(exc)})
        if opps:
            hist = [[ts, o["option_ticker"], o["ticker"], o.get("strike"), o.get("spot"),
                     o.get("spot_strike_ratio"), o.get("iv_rank"), o.get("profit_rate"),
                     o.get("dte"), o.get("volume_fin")] for o in opps]
            sheets_client.append_rows(config.TAB_HIST_RADAR, hist, header=_RADAR_HIST_HEADER)
            log.info("RADAR", f"{len(hist)} linha(s) em {config.TAB_HIST_RADAR} + painel atualizado")

    enviar = _is_true(cfg_sheet.get("ENVIAR_EMAIL")) and _is_true(cfg_sheet.get("ENVIAR_EMAIL_RADAR"))
    if config.RUNTIME.dry_run:
        log.info("RADAR", f"[DRY_RUN] {len(opps)} oportunidade(s) (e-mail não enviado)",
                 {"opcoes": [o["option_ticker"] for o in opps]})
    elif not enviar:
        log.info("RADAR", f"E-mail do Radar DESLIGADO na CONFIG ({len(opps)} oportunidades não enviadas)")
    else:
        fresh = state.filter_new_opportunities(opps)
        if fresh:
            sent = notifier.send_radar_opportunities(opps)
            log.info("RADAR", f"E-mail de oportunidade {'enviado' if sent else 'NÃO enviado'} ({len(fresh)} nova(s))",
                     {"novas": [o["option_ticker"] for o in fresh]})
        else:
            log.info("RADAR", "Nenhuma oportunidade nova para e-mail")


def run() -> int:
    tz = ZoneInfo(config.RUNTIME.timezone)
    log = Logbook()
    started = time.monotonic()
    summary = {"market": None, "escudo_alerts": 0, "escudo_criticos": 0, "radar_opps": 0, "errors": 0}
    status_final = "OK"
    rc = 0

    log.info("RUN", f"Início do ciclo (motor v{__import__('app').__version__})",
             {"dry_run": config.RUNTIME.dry_run, "last_run_ok": state.get_last_run_ok(), "run_url": _run_url()})

    try:
        with state.run_lock():
            # --- Relógio de ponto ---
            try:
                market = market_gate.check_market()
            except Exception as exc:
                log.error("MARKET_GATE", "Falha ao consultar OpLab — abortando por segurança", {"erro": str(exc)})
                summary["market"] = "ERRO"
                status_final = "ERROR"
                rc = 2
                return rc
            summary["market"] = market.code
            log.info("MARKET_GATE", f"market_status={market.code}", market.raw)
            if not market.is_open and not config.RUNTIME.force_run:
                log.info("MARKET_GATE", "Mercado fechado — encerrando para poupar processamento", {"code": market.code})
                status_final = "FECHADO"
                return 0
            if not market.is_open and config.RUNTIME.force_run:
                log.warn("MARKET_GATE", "Mercado FECHADO, mas FORCE_RUN ativo — rodando para HOMOLOGAÇÃO",
                         {"code": market.code})

            if config.RUNTIME.email_test_only:
                # Homologação rápida do pager: só manda um e-mail de teste.
                sent = notifier.send_test_email()
                log.info("EMAIL_TESTE", f"E-mail de teste {'enviado' if sent else 'NÃO enviado'}")
                status_final = "EMAIL_TESTE"
            else:
                cfg_sheet = _read_config(log)
                log.info("CONFIG", "Configuração lida da planilha",
                         {k: cfg_sheet.get(k) for k in
                          ("ENVIAR_EMAIL", "ENVIAR_EMAIL_ESCUDO", "ENVIAR_EMAIL_RADAR", "ESCUDO_NIVEL_MINIMO_EMAIL")})
                # --- Módulos ---
                for name, fn in (("ESCUDO", _run_escudo), ("RADAR", _run_radar)):
                    try:
                        fn(log, tz, summary, cfg_sheet)
                    except Exception as exc:
                        summary["errors"] += 1
                        status_final = "ERROR"
                        rc = 1
                        log.error(name, f"Erro no módulo {name}",
                                  {"erro": str(exc), "trace": traceback.format_exc()[:2000]})

            state.mark_run_ok({"market": market.code, **summary})
            if status_final == "OK":
                log.info("RUN", "Ciclo concluído com sucesso", summary)

    except RuntimeError as exc:  # lock ocupado por outra instância
        log.warn("LOCK", "Execução ignorada (lock ativo)", {"motivo": str(exc)})
        status_final = "SKIP"
    except Exception as exc:
        log.error("FATAL", "Erro não tratado no orquestrador",
                  {"erro": str(exc), "trace": traceback.format_exc()[:2000]})
        status_final = "ERROR"
        rc = 1
    finally:
        dur = time.monotonic() - started
        _write_heartbeat(log, tz, summary, status_final, dur)
        log.info("RUN", "Fim do ciclo", {"status": status_final, "duracao_s": round(dur, 1), **summary})
        log.flush()

    return rc


if __name__ == "__main__":
    sys.exit(run())
