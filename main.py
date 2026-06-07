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

import dataclasses
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
    montecarlo,
    notifier,
    radar,
    sheets_client,
    state,
)
from app.logbook import Logbook


def _is_true(v) -> bool:
    return str(v).strip().upper() in {"TRUE", "1", "SIM", "VERDADEIRO", "ON", "YES"}


def _num(v) -> float:
    return float(str(v).replace(",", "."))


def _int(v) -> int:
    return int(float(str(v).replace(",", ".")))


def _pct(v) -> float:
    return float(str(v).replace(",", ".")) / 100.0


# CHAVE da aba CONFIG -> (campo da dataclass, conversor, min, max). O min/max
# protege contra valores absurdos (ex.: "1.02" que o Sheets converteu em data).
_DEFAULTS = {c[0]: c[1] for c in config.DEFAULT_CONFIG}
_ESCUDO_MAP = {
    "ESCUDO_RECOMPRA_OTM": ("buyback_mult_otm", _num, 1.0, 20.0),
    "ESCUDO_RECOMPRA_OTM_CRIT": ("buyback_mult_otm_crit", _num, 1.0, 30.0),
    "ESCUDO_RECOMPRA_ATM": ("buyback_mult_atm", _num, 1.0, 20.0),
    "ESCUDO_DELTA_ALERTA": ("delta_warn", _num, 0.0, 1.0),
    "ESCUDO_DELTA_URGENTE": ("delta_urgent", _num, 0.0, 1.0),
    "ESCUDO_DTE_CRITICO": ("dte_critical", _int, 0, 365),
    "ESCUDO_PERDA_MAX_PCT": ("loss_vs_maxloss_pct", _pct, 0.0, 5.0),
    "ESCUDO_GAMMA_MAX": ("gamma_max", _num, 0.0, 5.0),
    "ESCUDO_HHI_MAX": ("hhi_max", _num, 0.0, 1.0),
    "ESCUDO_IBOV_EXPOSICAO_MAX": ("ibov_exposure_max", _pct, 0.0, 1.0),
    "ESCUDO_IBOV_CORREL_MIN": ("ibov_correl_threshold", _num, 0.0, 1.0),
}
_RADAR_MAP = {
    "RADAR_IV_RANK_MIN": ("iv_rank_min", _num, 0.0, 100.0),
    "RADAR_RATIO_MIN": ("spot_strike_ratio_min", _num, 1.0, 3.0),
    "RADAR_DTE_MIN": ("dte_min", _int, 0, 730),
    "RADAR_DTE_MAX": ("dte_max", _int, 0, 730),
    "RADAR_TOP_N": ("top_n", _int, 1, 50),
    "RADAR_EXIGIR_TENDENCIA_ALTA": ("require_trend_up", _is_true, None, None),
    "RADAR_USAR_TRAVA": ("usar_trava", _is_true, None, None),
    "RADAR_TRAVA_LARGURA_PCT": ("trava_largura_pct", _pct, 0.005, 0.5),
}


def _apply_config(cfg_sheet: dict, mapping: dict):
    """Devolve (overrides validos, {chave: valor_padrao} a corrigir na planilha)."""
    overrides, repair = {}, {}
    for chave, (field, caster, lo, hi) in mapping.items():
        v = cfg_sheet.get(chave)
        if v in (None, ""):
            continue
        try:
            val = caster(v)
        except (TypeError, ValueError):
            repair[chave] = _DEFAULTS.get(chave)
            continue
        if lo is not None and not (lo <= val <= hi):
            repair[chave] = _DEFAULTS.get(chave)   # valor absurdo -> usa padrao
            continue
        overrides[field] = val
    return overrides, repair


def _escudo_cfg(cfg_sheet: dict) -> config.EscudoCfg:
    ov, _ = _apply_config(cfg_sheet, _ESCUDO_MAP)
    return dataclasses.replace(config.ESCUDO, **ov) if ov else config.ESCUDO


def _radar_cfg(cfg_sheet: dict) -> config.RadarCfg:
    ov, _ = _apply_config(cfg_sheet, _RADAR_MAP)
    return dataclasses.replace(config.RADAR, **ov) if ov else config.RADAR


def _config_repairs(cfg_sheet: dict) -> dict:
    r = {}
    for mp in (_ESCUDO_MAP, _RADAR_MAP):
        _, rep = _apply_config(cfg_sheet, mp)
        r.update({k: v for k, v in rep.items() if v is not None})
    return r


def _mc_setup(cfg_sheet: dict):
    """Devolve (simulador, poe_max) conforme a CONFIG; (None, None) se desligado."""
    if not _is_true(cfg_sheet.get("USAR_MONTECARLO", "TRUE")):
        return None, None
    try:
        poe_max = _pct(cfg_sheet.get("POE_MAXIMA", "25"))
    except (TypeError, ValueError):
        poe_max = config.RADAR.poe_max
    try:
        n = _int(cfg_sheet.get("MC_CENARIOS", config.MC_N))
    except (TypeError, ValueError):
        n = config.MC_N
    try:
        drift = _num(cfg_sheet.get("MC_DRIFT", config.MC_DRIFT))
    except (TypeError, ValueError):
        drift = config.MC_DRIFT
    return montecarlo.MonteCarloSimulator(n, config.MC_SEED, drift), poe_max


def _mc_enrich(items: list[dict], vol_map: dict, sim) -> None:
    """Adiciona poe_mc_iv/real/gate a cada item (usa spot/strike/dte + vol do ativo)."""
    for it in items:
        vm = vol_map.get(str(it.get("ticker", "")).strip().upper(), {})
        it.update(montecarlo.poe_resumo(sim, it.get("spot"), it.get("strike"), it.get("dte"),
                                        vm.get("iv"), vm.get("real"), tipo=it.get("option_type", "PUT")))


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
                 "poe", "poe_mc_gate", "buyback_mult", "pl_value", "motivo")
_OPP_FIELDS = ("option_ticker", "ticker", "strike", "spot", "spot_strike_ratio",
               "iv_rank", "profit_rate", "dte", "volume_fin", "poe_mc_gate", "contratos_sugeridos")


def _now_str(tz) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def _run_url() -> str:
    server = os.getenv("GITHUB_SERVER_URL")
    repo = os.getenv("GITHUB_REPOSITORY")
    run_id = os.getenv("GITHUB_RUN_ID")
    return f"{server}/{repo}/actions/runs/{run_id}" if (server and repo and run_id) else ""


def _audit_read(log: Logbook, nome: str, df) -> None:
    """Registra a leitura de uma aba (auditoria)."""
    n = 0 if df is None else len(df)
    cols = [] if df is None else list(df.columns)
    ctx = {"aba": nome, "linhas": n, "colunas": cols} if config.AUDIT_VERBOSE else None
    log.info("SHEET_READ", f"{nome}: {n} linha(s)", ctx)


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


# --- formatação curta p/ logs didáticos ------------------------------------
def _g(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def _pctg(v) -> str:
    return "—" if v is None else f"{float(v) * 100:.0f}%"


# --- linhas dos painéis (alimentam o web app; lidas por NOME do cabeçalho) ---
def _esc_panel_row(ts: str, a: dict) -> list:
    return [ts, a.get("ticker"), a.get("option_ticker"), a.get("side"), a.get("option_type"),
            a.get("nivel"), a.get("moneyness"), a.get("dte"), a.get("expiry"), a.get("quantity"),
            a.get("spot"), a.get("strike"), a.get("dist_pct"), a.get("entry_price"),
            a.get("last_premium"), a.get("buyback_mult"), a.get("break_even"), a.get("delta"),
            a.get("gamma"), a.get("poe"), a.get("poe_mc_gate"), a.get("pl_value"), a.get("pl_pct"),
            a.get("max_gain"), a.get("max_profit_pct"), a.get("notional"),
            a.get("analise"), a.get("acao_sugerida")]


def _rad_panel_row(ts: str, o: dict) -> list:
    tr = o.get("trava") or {}
    fonte = "estimado (≈)" if o.get("premio_estimado") else (o.get("premio_fonte") or "real")
    return [ts, o.get("ticker"), o.get("option_ticker"), o.get("expiry_fmt"), o.get("dte"),
            o.get("strike"), o.get("spot"), o.get("dist_pct"), o.get("premio"), fonte,
            o.get("iv_rank"), o.get("profit_rate"), o.get("poe_mc_gate"), o.get("volume_fin"),
            tr.get("sell_strike"), tr.get("sell_premio"), tr.get("buy_strike"), tr.get("buy_premio"),
            tr.get("credito"), tr.get("risco_max"), tr.get("retorno_risco"),
            o.get("motivo"), o.get("analise")]


# --- logs didáticos (passo a passo, p/ auditoria detalhada) -----------------
def _log_escudo_alerta(log: Logbook, a: dict) -> None:
    if str(a.get("option_ticker", "")).startswith("PORTFOLIO"):
        log.info("ESCUDO", f"Carteira [{a['nivel']}]: {a.get('descricao', '')}",
                 {"acao": a.get("acao_sugerida")})
        return
    cab = (f"{a.get('ticker')} {a.get('option_ticker')} [{a['nivel']}] — {a.get('moneyness')}, "
           f"DTE {_g(a.get('dte'))}, Δ {_g(a.get('delta'))}, γ {_g(a.get('gamma'))}, "
           f"recompra {_g(a.get('buyback_mult'))}x, PoE {_pctg(a.get('poe'))}, "
           f"PoE-MC {_pctg(a.get('poe_mc_gate'))}, P/L R$ {_g(a.get('pl_value'))} ({_g(a.get('pl_pct'))}%)")
    log.info("ESCUDO", f"Posição {cab}",
             {"gatilhos": a.get("motivo"), "acao": a.get("acao_sugerida"), "analise": a.get("analise")})


def _log_radar_funil(log: Logbook, f: dict) -> None:
    fl = f.get("filtros", {})
    log.info("RADAR", f"Funil — partida: {f.get('total', 0)} opções na aba de lucros")
    log.info("RADAR", f"Funil 1/7 — categoria PUT: {f.get('put', 0)} de {f.get('total', 0)}")
    log.info("RADAR", f"Funil 2/7 — IV Rank ≥ {fl.get('iv_rank_min')}: {f.get('iv_rank_ok', 0)} sobram")
    log.info("RADAR", f"Funil 3/7 — distância spot/strike ≥ {fl.get('ratio_min')}: {f.get('ratio_ok', 0)} sobram")
    log.info("RADAR", f"Funil 4/7 — liquidez (volume mínimo): {f.get('volume_ok', 0)} sobram")
    log.info("RADAR", f"Funil 5/7 — DTE entre {fl.get('dte_min')} e {fl.get('dte_max')} dias: {f.get('dte_ok', 0)} sobram")
    log.info("RADAR", f"Funil 6/7 — tendência/whitelist: {f.get('apos_tendencia', 0)} sobram")
    if "apos_montecarlo" in f:
        log.info("RADAR", f"Funil 7/7 — Monte Carlo (PoE ≤ máx): {f.get('apos_montecarlo', 0)} sobram "
                          f"(menor PoE visto: {_pctg(f.get('poe_min'))})")
    log.info("RADAR", f"Funil — FINAL: {f.get('final', 0)} oportunidade(s) selecionada(s) (Top {f.get('final', 0)})")
    log.info("RADAR", f"Prêmios: {f.get('premios_reais', 0)} REAIS (scanner) · "
                      f"{f.get('premios_estimados', 0)} estimados (≈) · travas montadas: {f.get('travas_montadas', 0)}",
             {"scanner_opcoes_indexadas": f.get("scanner_opcoes"),
              "scanner_puts_na_cadeia": f.get("scanner_puts_na_cadeia")})


def _log_radar_opp(log: Logbook, o: dict) -> None:
    src = "estimado ≈" if o.get("premio_estimado") else (o.get("premio_fonte") or "real")
    cab = (f"{o.get('ticker')} {o.get('option_ticker')} — strike R$ {_g(o.get('strike'))}, "
           f"prêmio R$ {_g(o.get('premio'))} ({src}), IVR {_g(o.get('iv_rank'))}, "
           f"PoE {_pctg(o.get('poe_mc_gate'))}, DTE {_g(o.get('dte'))}, vol R$ {_g(o.get('volume_fin'))}")
    tr = o.get("trava")
    if tr:
        det = (f"TRAVA DE ALTA: vende PUT {_g(tr['sell_strike'])} @ R$ {_g(tr['sell_premio'])} + "
               f"compra PUT {_g(tr['buy_strike'])} @ R$ {_g(tr['buy_premio'])} → crédito R$ {_g(tr['credito'])}, "
               f"risco máx R$ {_g(tr['risco_max'])}, retorno/risco {_pctg(tr.get('retorno_risco'))}")
    else:
        det = f"SEM trava: {o.get('trava_motivo', '—')} (recomenda PUT a seco)"
    log.info("RADAR", f"Oportunidade {cab}", {"recomendacao": det, "porque": o.get("motivo")})


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
    escudo_cfg = _escudo_cfg(cfg_sheet)
    port_audit: dict = {}
    port_alerts = escudo.analyze_portfolio(df, df_correl, cfg=escudo_cfg, audit=port_audit)
    log.info("ESCUDO", "Métricas de carteira calculadas", port_audit)
    alerts = port_alerts + escudo.analyze(df, today, cfg=escudo_cfg)

    sim, _ = _mc_setup(cfg_sheet)
    if sim is not None:
        try:
            _mc_enrich(alerts, radar.build_vol_map(sheets_client.read_tab("dados_ativos")), sim)
        except Exception as exc:
            log.warn("ESCUDO", "Monte Carlo não aplicado (DADOS_ATIVOS)", {"erro": str(exc)})

    por_nivel: dict = {}
    for a in alerts:
        por_nivel[a["nivel"]] = por_nivel.get(a["nivel"], 0) + 1
    summary["escudo_alerts"] = len(alerts)
    summary["escudo_criticos"] = por_nivel.get("CRITICO", 0)
    log.info("ESCUDO", f"{len(alerts)} alerta(s) detectado(s)",
             {"por_nivel": por_nivel,
              "detalhe": [{k: a.get(k) for k in _ALERT_FIELDS} for a in alerts]})
    # Auditoria detalhada: uma linha por posição, em sequência (CRITICO -> AVISO).
    for a in alerts:
        _log_escudo_alerta(log, a)

    ts = _now_str(tz)
    if not config.RUNTIME.dry_run:
        # PAINEL_ESCUDO (sobrescreve = estado atual, alimenta o web app)
        painel = [_esc_panel_row(ts, a) for a in alerts]
        try:
            sheets_client.replace_tab(config.TAB_PAINEL_ESCUDO, config.PAINEL_ESCUDO_HEADER, painel)
        except Exception as exc:
            log.error("ESCUDO", "Falha ao gravar PAINEL_ESCUDO", {"erro": str(exc)})
        if alerts:
            hist = [[ts, a["option_ticker"], a["ticker"], a["id_strategy"], a["nivel"], a["moneyness"], a["dte"],
                     a.get("delta"), a.get("poe"), a.get("buyback_mult"),
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
        # Homologação (FORCE_RUN) reenvia tudo; agendado respeita o dedupe diário.
        fresh = worthy if config.RUNTIME.force_run else state.filter_new_alerts(worthy)
        if fresh:
            sent = notifier.send_escudo_alert(fresh)
            log.info("ESCUDO", f"E-mail {'enviado' if sent else 'NÃO enviado'} ({len(fresh)} item(ns))",
                     {"opcoes": [a["option_ticker"] for a in fresh], "homologacao": config.RUNTIME.force_run})
        else:
            log.info("ESCUDO", f"Sem novos alertas para e-mail ({len(worthy)} elegíveis já notificados hoje)")


def _run_radar(log: Logbook, tz, summary: dict, cfg_sheet: dict) -> None:
    df_lucros = sheets_client.read_tab("lucros")
    _audit_read(log, "SELECAO_OPCOES_MAIORES_LUCROS", df_lucros)
    df_volumes = sheets_client.read_tab("volumes")
    _audit_read(log, "SELECAO_MAIORES_VOLUMES", df_volumes)
    df_dados = sheets_client.read_tab("dados_ativos")
    _audit_read(log, "DADOS_ATIVOS", df_dados)
    try:
        df_scanner = sheets_client.read_tab("scanner")
    except Exception as exc:  # aba ausente -> cai para a estimativa (VE/strike)
        df_scanner = None
        log.info("RADAR", "SCANNER_OPCOES indisponível (usando estimativa de prêmio)", {"erro": str(exc)})
    _audit_read(log, "SCANNER_OPCOES", df_scanner)

    radar_cfg = _radar_cfg(cfg_sheet)
    sim, poe_max = _mc_setup(cfg_sheet)
    vmap = radar.build_vol_map(df_dados) if sim is not None else None
    funil: dict = {}
    opps = radar.scan(df_lucros, df_volumes, df_dados, cfg=radar_cfg, audit=funil,
                      mc=sim, vol_map=vmap, poe_max=poe_max, df_scanner=df_scanner)
    _log_radar_funil(log, funil)
    summary["radar_opps"] = len(opps)
    # Auditoria detalhada: uma linha por oportunidade, com prêmio, fonte e Trava.
    for o in opps:
        _log_radar_opp(log, o)

    ts = _now_str(tz)
    if not config.RUNTIME.dry_run:
        painel = [_rad_panel_row(ts, o) for o in opps]
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
        # Homologação (FORCE_RUN) reenvia tudo; agendado respeita o dedupe diário.
        fresh = opps if config.RUNTIME.force_run else state.filter_new_opportunities(opps)
        if fresh:
            sent = notifier.send_radar_opportunities(opps)
            log.info("RADAR", f"E-mail de oportunidade {'enviado' if sent else 'NÃO enviado'} ({len(fresh)} item(ns))",
                     {"novas": [o["option_ticker"] for o in fresh], "homologacao": config.RUNTIME.force_run})
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
                repairs = _config_repairs(cfg_sheet)
                if repairs:
                    cfg_sheet.update(repairs)   # usa os valores corrigidos já neste ciclo
                    log.warn("CONFIG", "Valores inválidos detectados; usando padrão (ex.: data por engano)", repairs)
                    if not config.RUNTIME.dry_run:
                        try:
                            sheets_client.set_config_values(config.TAB_CONFIG, repairs)
                        except Exception as exc:
                            log.error("CONFIG", "Falha ao corrigir CONFIG na planilha", {"erro": str(exc)})
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
