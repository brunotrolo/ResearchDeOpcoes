"""Orquestrador do motor ResearchDeOpcoes.

Ordem de execução (chamado de hora em hora pelo Task Scheduler, 10h–17h):

    1. Lock-file (execução única).
    2. RELÓGIO DE PONTO: OpLab /market/status. Se != "A", encerra.
    3. ESCUDO: lê Painel_Ativas -> alertas de defesa -> histórico + e-mail urgente.
    4. RADAR: lê seleções -> filtra oportunidades -> histórico + e-mail de oportunidade.
    5. Marca última execução OK; faz flush dos LOGS na planilha.

Tudo é registrado na aba LOGS (UPDATED_AT, SERVICE, STATUS, SUMMARY, CONTEXT)
para debug ponta-a-ponta. Erros de um módulo não impedem o outro.
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from app import (
    config,
    escudo,
    market_gate,
    notifier,
    radar,
    sheets_client,
    state,
)
from app.logbook import Logbook

_ESCUDO_HIST_HEADER = [
    "UPDATED_AT", "OPTION_TICKER", "TICKER", "ID_STRATEGY", "NIVEL", "MONEYNESS",
    "DTE", "DELTA", "POE", "BUYBACK_MULT", "PL_VALUE", "MOTIVO", "ACAO_SUGERIDA",
]
_RADAR_HIST_HEADER = [
    "UPDATED_AT", "OPTION_TICKER", "TICKER", "STRIKE", "SPOT", "SPOT_STRIKE_RATIO",
    "IV_RANK", "PROFIT_RATE", "DTE", "VOLUME_FIN",
]


def _now_str(tz) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def _run_escudo(log: Logbook, tz) -> None:
    log.info("ESCUDO", "Lendo Painel_Ativas")
    df = sheets_client.read_tab("ativas")
    log.info("ESCUDO", f"{len(df)} linhas lidas")

    today = datetime.now(tz).date()
    alerts = escudo.analyze(df, today)
    log.info("ESCUDO", f"{len(alerts)} alerta(s) detectado(s)",
             {"niveis": [a["nivel"] for a in alerts]})

    # Histórico (todos os níveis) na planilha
    if alerts and not config.RUNTIME.dry_run:
        ts = _now_str(tz)
        rows = [[ts, a["option_ticker"], a["ticker"], a["id_strategy"], a["nivel"],
                 a["moneyness"], a["dte"],
                 f"{a['delta']:.4f}" if a.get("delta") is not None else "",
                 f"{a['poe']:.2f}" if a.get("poe") is not None else "",
                 f"{a['buyback_mult']:.2f}" if a.get("buyback_mult") is not None else "",
                 a.get("pl_value"), a["motivo"], a["acao_sugerida"]] for a in alerts]
        sheets_client.append_rows(config.TAB_HIST_ESCUDO, rows, header=_ESCUDO_HIST_HEADER)

    # E-mail urgente — só níveis relevantes e só o que é novo no dia (dedupe)
    worthy = escudo.email_worthy(alerts)
    fresh = state.filter_new_alerts(worthy)
    if fresh:
        sent = notifier.send_escudo_alert(fresh)
        log.info("ESCUDO", f"E-mail urgente {'enviado' if sent else 'NÃO enviado'} "
                            f"({len(fresh)} novo(s))",
                 {"opcoes": [a["option_ticker"] for a in fresh]})
    else:
        log.info("ESCUDO", "Sem novos alertas para e-mail")


def _run_radar(log: Logbook, tz) -> None:
    log.info("RADAR", "Lendo seleções (lucros/volumes/dados_ativos)")
    df_lucros = sheets_client.read_tab("lucros")
    df_volumes = sheets_client.read_tab("volumes")
    df_dados = sheets_client.read_tab("dados_ativos") if config.RADAR.use_dados_ativos_whitelist else None
    log.info("RADAR", f"lucros={len(df_lucros)} volumes={len(df_volumes)}")

    opps = radar.scan(df_lucros, df_volumes, df_dados)
    log.info("RADAR", f"{len(opps)} oportunidade(s) após filtros",
             {"top": [o["option_ticker"] for o in opps]})

    if opps and not config.RUNTIME.dry_run:
        ts = _now_str(tz)
        rows = [[ts, o["option_ticker"], o["ticker"],
                 o.get("strike"), o.get("spot"), o.get("spot_strike_ratio"),
                 o.get("iv_rank"), o.get("profit_rate"), o.get("dte"),
                 o.get("volume_fin")] for o in opps]
        sheets_client.append_rows(config.TAB_HIST_RADAR, rows, header=_RADAR_HIST_HEADER)

    fresh = state.filter_new_opportunities(opps)
    if fresh:
        sent = notifier.send_radar_opportunities(opps)  # e-mail mostra o Top-N atual
        log.info("RADAR", f"E-mail de oportunidade {'enviado' if sent else 'NÃO enviado'} "
                          f"({len(fresh)} nova(s))",
                 {"novas": [o["option_ticker"] for o in fresh]})
    else:
        log.info("RADAR", "Nenhuma oportunidade nova para e-mail")


def run() -> int:
    tz = ZoneInfo(config.RUNTIME.timezone)
    log = Logbook()
    log.info("BOOT", f"Motor v{__import__('app').__version__} iniciado",
             {"dry_run": config.RUNTIME.dry_run, "last_run_ok": state.get_last_run_ok()})

    try:
        with state.run_lock():
            # --- Relógio de ponto ---
            try:
                status = market_gate.check_market()
            except Exception as exc:
                log.error("MARKET_GATE", "Falha ao consultar OpLab — abortando por segurança",
                          {"erro": str(exc)})
                log.flush()
                return 2

            log.info("MARKET_GATE", f"market_status={status.code}", status.raw)
            if not status.is_open:
                log.info("MARKET_GATE", "Mercado fechado — encerrando para poupar processamento",
                         {"code": status.code})
                log.flush()
                return 0

            # --- Módulos ---
            for name, fn in (("ESCUDO", _run_escudo), ("RADAR", _run_radar)):
                try:
                    fn(log, tz)
                except Exception as exc:
                    log.error(name, f"Erro no módulo {name}",
                              {"erro": str(exc), "trace": traceback.format_exc()[:2000]})

            state.mark_run_ok({"market": status.code})
            log.info("BOOT", "Execução concluída com sucesso")

    except RuntimeError as exc:  # lock ocupado por outra instância
        log.warn("LOCK", "Execução ignorada", {"motivo": str(exc)})
    except Exception as exc:
        log.error("FATAL", "Erro não tratado no orquestrador",
                  {"erro": str(exc), "trace": traceback.format_exc()[:2000]})
        log.flush()
        return 1

    log.flush()
    return 0


if __name__ == "__main__":
    sys.exit(run())
