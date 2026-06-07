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
from app.monte_carlo_engine import MonteCarloEngine


def _is_true(v) -> bool:
    return str(v).strip().upper() in {"TRUE", "1", "SIM", "VERDADEIRO", "ON", "YES"}


def _num(v) -> float:
    return float(str(v).replace(",", "."))


def _int(v) -> int:
    return int(float(str(v).replace(",", ".")))


def _pct(v) -> float:
    return float(str(v).replace(",", ".")) / 100.0


def _fonte(v) -> str:
    s = str(v).strip().lower()
    if s not in {"scanner", "lucros", "auto"}:
        raise ValueError(f"fonte inválida: {v}")
    return s


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
    "ESCUDO_TOQUE_AVISO": ("toque_aviso", _pct, 0.0, 1.0),
    "ESCUDO_TOQUE_ALERTA": ("toque_alerta", _pct, 0.0, 1.0),
    "ESCUDO_HHI_MAX": ("hhi_max", _num, 0.0, 1.0),
    "ESCUDO_IBOV_EXPOSICAO_MAX": ("ibov_exposure_max", _pct, 0.0, 1.0),
    "ESCUDO_IBOV_CORREL_MIN": ("ibov_correl_threshold", _num, 0.0, 1.0),
}
_RADAR_MAP = {
    "RADAR_FONTE": ("fonte", _fonte, None, None),
    "RADAR_IV_RANK_MIN": ("iv_rank_min", _num, 0.0, 100.0),
    "RADAR_RATIO_MIN": ("spot_strike_ratio_min", _num, 1.0, 3.0),
    "RADAR_DTE_MIN": ("dte_min", _int, 0, 730),
    "RADAR_DTE_MAX": ("dte_max", _int, 0, 730),
    "RADAR_TOP_N": ("top_n", _int, 1, 50),
    "RADAR_MAX_POR_ATIVO": ("max_por_ativo", _int, 1, 50),
    "RADAR_EXIGIR_TENDENCIA_ALTA": ("require_trend_up", _is_true, None, None),
    "RADAR_EVITAR_TENDENCIA_BAIXA": ("evitar_tendencia_baixa", _is_true, None, None),
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


def _poe_max(cfg_sheet: dict) -> float:
    """Teto de probabilidade de exercício (POE_MAXIMA). É aplicado SEMPRE — mesmo
    com o Monte Carlo desligado, usando a POE da planilha — para nunca recomendar
    PUT acima do risco configurado. Default 25%."""
    try:
        return _pct(cfg_sheet.get("POE_MAXIMA", "25"))
    except (TypeError, ValueError):
        return config.RADAR.poe_max


def _mc_setup(cfg_sheet: dict):
    """Devolve o simulador Monte Carlo conforme a CONFIG, ou None se desligado. O
    teto de PoE é independente (ver _poe_max), para valer mesmo sem Monte Carlo."""
    if not _is_true(cfg_sheet.get("USAR_MONTECARLO", "TRUE")):
        return None
    try:
        n = _int(cfg_sheet.get("MC_CENARIOS", config.MC_N))
    except (TypeError, ValueError):
        n = config.MC_N
    try:
        drift = _num(cfg_sheet.get("MC_DRIFT", config.MC_DRIFT))
    except (TypeError, ValueError):
        drift = config.MC_DRIFT
    return montecarlo.MonteCarloSimulator(n, config.MC_SEED, drift)


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
            a.get("gamma"), a.get("poe"), a.get("poe_mc_gate"),
            a.get("pl_value"), a.get("pl_pct"),
            a.get("max_gain"), a.get("max_profit_pct"), a.get("notional"),
            a.get("analise"), a.get("acao_sugerida"), a.get("toque_gate")]


def _rad_panel_row(ts: str, o: dict) -> list:
    tr = o.get("trava") or {}
    fonte = "estimado (≈)" if o.get("premio_estimado") else (o.get("premio_fonte") or "real")
    return [ts, o.get("ticker"), o.get("option_ticker"), o.get("expiry_fmt"), o.get("dte"),
            o.get("strike"), o.get("spot"), o.get("dist_pct"), o.get("premio"), fonte,
            o.get("iv_rank"), o.get("profit_rate"), o.get("poe_mc_gate"),
            o.get("volume_fin"),
            tr.get("sell_opt"), tr.get("sell_strike"), tr.get("sell_premio"),
            tr.get("buy_opt"), tr.get("buy_strike"), tr.get("buy_premio"),
            tr.get("credito"), tr.get("risco_max"), tr.get("retorno_risco"),
            o.get("motivo"), o.get("analise"), o.get("toque_gate")]


# --- logs didáticos (passo a passo, p/ auditoria detalhada) -----------------
def _log_escudo_alerta(log: Logbook, a: dict) -> None:
    if str(a.get("option_ticker", "")).startswith("PORTFOLIO"):
        log.info("ESCUDO", f"Carteira [{a['nivel']}]: {a.get('descricao', '')}",
                 {"acao": a.get("acao_sugerida")})
        return
    cab = (f"{a.get('ticker')} {a.get('option_ticker')} [{a['nivel']}] — {a.get('moneyness')}, "
           f"DTE {_g(a.get('dte'))}, Δ {_g(a.get('delta'))}, γ {_g(a.get('gamma'))}, "
           f"recompra {_g(a.get('buyback_mult'))}x, PoE {_pctg(a.get('poe'))}, "
           f"PoE-MC {_pctg(a.get('poe_mc_gate'))}, Toque {_pctg(a.get('toque_gate'))}, "
           f"P/L R$ {_g(a.get('pl_value'))} ({_g(a.get('pl_pct'))}%)")
    ctx = {"gatilhos": a.get("motivo"), "acao": a.get("acao_sugerida"), "analise": a.get("analise")}
    if a.get("toque_tendencia") is not None:
        ctx["toque_se_tendencia_continuar"] = _pctg(a.get("toque_tendencia"))
    if a.get("cenarios"):
        c = a["cenarios"]
        ctx["cenarios_preco"] = f"P5 {_g(c.get('p05'))} · P50 {_g(c.get('p50'))} · P95 {_g(c.get('p95'))}"
    log.info("ESCUDO", f"Posição {cab}", ctx)


def _log_radar_funil(log: Logbook, f: dict) -> None:
    fl = f.get("filtros", {})
    scanner = f.get("fonte") == "scanner"
    partida = "linhas no SCANNER_OPCOES" if scanner else "opções na aba de lucros"
    log.info("RADAR", f"Funil — partida: {f.get('total', 0)} {partida}")
    log.info("RADAR", f"Funil 1 — categoria PUT: {f.get('put', 0)} de {f.get('total', 0)}")
    if scanner:
        log.info("RADAR", f"Funil 2 — com prêmio REAL (CLOSE) válido: {f.get('premio_ok', 0)} sobram")
        log.info("RADAR", f"Funil 3 — IV Rank ≥ {fl.get('iv_rank_min')} (ou ativo fora de DADOS_ATIVOS): "
                          f"{f.get('iv_rank_ok', 0)} sobram")
    else:
        log.info("RADAR", f"Funil 2 — IV Rank ≥ {fl.get('iv_rank_min')}: {f.get('iv_rank_ok', 0)} sobram")
    log.info("RADAR", f"Funil 4 — distância spot/strike ≥ {fl.get('ratio_min')}: {f.get('ratio_ok', 0)} sobram")
    log.info("RADAR", f"Funil 5 — liquidez (volume mínimo): {f.get('volume_ok', 0)} sobram")
    log.info("RADAR", f"Funil 6 — DTE entre {fl.get('dte_min')} e {fl.get('dte_max')} dias: {f.get('dte_ok', 0)} sobram")
    # Diagnóstico crucial: quais DTEs o scanner realmente trouxe. Se o funil 6
    # zerou, quase sempre é a janela RADAR_DTE_MIN/MAX fora do que foi baixado.
    dtes = f.get("dtes_disponiveis")
    if dtes is not None:
        if not dtes:
            log.warn("RADAR", "SCANNER_OPCOES não tem nenhuma PUT com prêmio — verifique o CLOSE da planilha")
        elif f.get("dte_ok", 0) == 0:
            log.warn("RADAR", f"NENHUMA opção no DTE pedido. O scanner só tem estes DTEs: {dtes}. "
                              f"Ajuste RADAR_DTE_MIN/RADAR_DTE_MAX para incluir {min(dtes)}–{max(dtes)}, "
                              f"ou alimente o scanner com os vencimentos que você opera.")
        else:
            log.info("RADAR", f"DTEs disponíveis no scanner: {dtes}")
    if fl.get("evitar_baixa"):
        log.info("RADAR", f"Funil 7 — descartando tendência de BAIXA (M9<M21): {f.get('apos_tendencia', 0)} sobram")
    else:
        log.info("RADAR", f"Funil 7 — tendência/whitelist: {f.get('apos_tendencia', 0)} sobram")
    if "apos_montecarlo" in f:
        teto = _pctg(fl.get("poe_max"))
        fonte_poe = "Monte Carlo" if not scanner else "Monte Carlo / POE da planilha"
        log.info("RADAR", f"Funil 8 — {fonte_poe} (PoE ≤ {teto}): {f.get('apos_montecarlo', 0)} sobram "
                          f"(menor PoE visto: {_pctg(f.get('poe_min'))})")
    if f.get("diversificacao_cortou"):
        log.info("RADAR", f"Funil 9 — diversificação (máx {fl.get('max_por_ativo')} por ativo): "
                          f"cortou {f.get('diversificacao_cortou')} repetida(s) do mesmo ativo-mãe")
    log.info("RADAR", f"Funil — FINAL: {f.get('final', 0)} oportunidade(s) selecionada(s) (Top {f.get('final', 0)})")
    log.info("RADAR", f"Prêmios: {f.get('premios_reais', 0)} REAIS (scanner) · "
                      f"{f.get('premios_estimados', 0)} estimados (≈) · travas montadas: {f.get('travas_montadas', 0)}",
             {"fonte": f.get("fonte"), "scanner_linhas_indexadas": f.get("scanner_opcoes"),
              "scanner_puts_na_cadeia": f.get("scanner_puts_na_cadeia")})


def _log_radar_opp(log: Logbook, o: dict) -> None:
    src = "estimado ≈" if o.get("premio_estimado") else (o.get("premio_fonte") or "real")
    poe_src = o.get("poe_fonte") or "Monte Carlo"
    cab = (f"{o.get('ticker')} {o.get('option_ticker')} — strike R$ {_g(o.get('strike'))}, "
           f"prêmio R$ {_g(o.get('premio'))} ({src}), IVR {_g(o.get('iv_rank'))}, "
           f"PoE {_pctg(o.get('poe_mc_gate'))} ({poe_src}), Toque {_pctg(o.get('toque_gate'))}, "
           f"DTE {_g(o.get('dte'))}, vol R$ {_g(o.get('volume_fin'))}")
    tr = o.get("trava")
    if tr:
        det = (f"TRAVA DE ALTA: vende PUT {_g(tr['sell_strike'])} @ R$ {_g(tr['sell_premio'])} + "
               f"compra PUT {_g(tr['buy_strike'])} @ R$ {_g(tr['buy_premio'])} → crédito R$ {_g(tr['credito'])}, "
               f"risco máx R$ {_g(tr['risco_max'])}, retorno/risco {_pctg(tr.get('retorno_risco'))}")
    else:
        det = f"SEM trava: {o.get('trava_motivo', '—')} (recomenda PUT a seco)"
    ctx = {"recomendacao": det, "porque": o.get("motivo")}
    if o.get("alerta_tendencia"):
        ctx["alerta"] = o.get("alerta_tendencia")
    if o.get("premio_estimado"):
        ctx["por_que_estimado"] = o.get("premio_diag")
    log.info("RADAR", f"Oportunidade {cab}", ctx)


# --- AUDITORIA MONTE CARLO (aba LOGS, SERVICE=MONTE_CARLO) -------------------
def _mc_engine(sim):
    """MonteCarloEngine (simulação de TRAJETÓRIA) como 2ª opinião INDEPENDENTE na
    auditoria, espelhando n e seed do simulador de produção. None se o Monte Carlo
    estiver desligado ou a auditoria não for verbosa (AUDIT_VERBOSE)."""
    if sim is None or not config.AUDIT_VERBOSE:
        return None
    try:
        return MonteCarloEngine(num_simulations=sim.n, seed=sim.seed)
    except Exception:
        return None


def _mc_crosscheck(engine: MonteCarloEngine, r: dict, terminal: bool) -> dict:
    """2ª opinião por SIMULAÇÃO (motor independente) p/ validar o gate fechado.
    Risco (Escudo): trajetória, drift 0 (conservador). Oportunidade (Radar):
    terminal, drift Selic. Convenções propositalmente distintas do gate — é um
    cruzamento, não uma cópia."""
    spot, strike, dte, sig = r.get("spot"), r.get("strike"), r.get("dte_dias"), r.get("sigma_gate")
    if not (spot and strike and dte and sig):
        return {"erro": "dados insuficientes para simular"}
    is_put = str(r.get("tipo", "PUT")).upper() != "CALL"
    try:
        if terminal:
            d = engine.evaluate_opportunity(spot, strike, dte, sig, is_put=is_put)
            return {"motor": "monte_carlo_engine", "metodo": "TERMINAL", "drift": engine.risk_free_rate,
                    "poe_terminal_sim": d["poe_mc_terminal"], "preco_terminal_medio": d["terminal_price_avg"],
                    "n": d["simulations_run"]}
        d = engine.check_active_risk(spot, strike, dte, sig, is_put=is_put, drift=0.0)
        return {"motor": "monte_carlo_engine", "metodo": "TRAJETORIA", "drift": 0.0,
                "toque_sim": d["poe_mc_gate"], "preco_minimo_medio": d["min_price_avg"],
                "n": d["simulations_run"]}
    except Exception as exc:
        return {"erro": str(exc)}


def _mc_linha(r: dict, terminal: bool) -> str:
    nivel = r.get("nivel") or ("OPORTUNIDADE" if terminal else "OK")
    s = (f"{r.get('ticker')} {r.get('option_ticker')} {r.get('tipo', 'PUT')} [{nivel}] — "
         f"PoE {_pctg(r.get('poe_mc_gate'))} (gate)")
    if not terminal:
        s += f" · Toque {_pctg(r.get('toque_gate'))}"
    s += (f" · σ {_pctg(r.get('sigma_gate'))} · n={_g(r.get('n_cenarios'))} · "
          f"erro↔fechada {_pctg(r.get('erro_vs_fechada'))}")
    return s


def _log_montecarlo(log: Logbook, contexto: str, registros: list, engine=None, terminal: bool = False) -> None:
    """Grava a auditoria Monte Carlo na aba LOGS: um RESUMO + UMA linha por
    simulação (SERVICE=MONTE_CARLO), com entradas (spot/strike/DTE/σ/drift/n/seed),
    saídas (PoE e Toque por IV/realizada/gate) e a validação fechada N(-d2) —
    reprodutível. Se `engine`, anexa a 2ª opinião por simulação de trajetória."""
    if not registros:
        return
    erros = [r["erro_vs_fechada"] for r in registros if r.get("erro_vs_fechada") is not None]
    resumo = {"motor_producao": "GBM (PoE terminal + toque por 1ª passagem fechada)",
              "n_cenarios": registros[0].get("n_cenarios"), "seed": registros[0].get("seed"),
              "drift_sim": registros[0].get("drift_sim")}
    if erros:
        resumo["erro_medio_mc_vs_fechada"] = f"{sum(erros) / len(erros) * 100:.2f}%"
        resumo["erro_max_mc_vs_fechada"] = f"{max(erros) * 100:.2f}%"
    if engine is not None:
        resumo["validacao_simulada"] = f"monte_carlo_engine (trajetória), n={engine.num_simulations}"
    log.info("MONTE_CARLO", f"{contexto}: {len(registros)} simulação(ões) auditada(s)", resumo)
    for r in registros:
        ctx = dict(r)
        if engine is not None:
            ctx["validacao_simulada"] = _mc_crosscheck(engine, r, terminal)
        log.log("MONTE_CARLO", r.get("nivel") or ("OPORTUNIDADE" if terminal else "OK"),
                _mc_linha(r, terminal), ctx)


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
    # Monte Carlo PREDITIVO: simulador + vol e tendência por ativo (DADOS_ATIVOS).
    # Alimenta a prob. de TOQUE (OTM virar ATM/ITM antes de vencer) como gatilho.
    sim = _mc_setup(cfg_sheet)
    vmap, trend_map = None, None
    if sim is not None:
        try:
            df_dados_esc = sheets_client.read_tab("dados_ativos")
            vmap = radar.build_vol_map(df_dados_esc)
            trend_map = radar.build_trend_map(df_dados_esc)
        except Exception as exc:
            log.warn("ESCUDO", "Monte Carlo sem DADOS_ATIVOS (segue sem PoE/toque)", {"erro": str(exc)})
            sim = None

    port_audit: dict = {}
    port_alerts = escudo.analyze_portfolio(df, df_correl, cfg=escudo_cfg, audit=port_audit)
    log.info("ESCUDO", "Métricas de carteira calculadas", port_audit)
    mc_records: list = []
    alerts = port_alerts + escudo.analyze(df, today, cfg=escudo_cfg, sim=sim,
                                          vol_map=vmap, trend_map=trend_map, mc_audit=mc_records)

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
    # Auditoria Monte Carlo: dossiê completo da simulação de CADA posição.
    _log_montecarlo(log, "ESCUDO", mc_records, engine=_mc_engine(sim))

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
    sim = _mc_setup(cfg_sheet)
    poe_max = _poe_max(cfg_sheet)   # teto de PoE sempre vale (com ou sem Monte Carlo)
    vmap = radar.build_vol_map(df_dados) if sim is not None else None
    funil: dict = {}
    tem_scanner = df_scanner is not None and not df_scanner.empty
    usar_scanner = radar_cfg.fonte == "scanner" or (radar_cfg.fonte == "auto" and tem_scanner)
    if usar_scanner and not tem_scanner:
        log.warn("RADAR", "RADAR_FONTE=scanner, mas SCANNER_OPCOES está vazio — caindo para a aba de lucros")
        usar_scanner = False
    if usar_scanner:
        log.info("RADAR", "Fonte: SCANNER_OPCOES (prêmio = CLOSE REAL da planilha; Trava no MESMO vencimento)")
        opps = radar.scan_scanner(df_scanner, df_dados, cfg=radar_cfg, audit=funil,
                                  mc=sim, vol_map=vmap, poe_max=poe_max)
    else:
        log.info("RADAR", "Fonte: SELECAO_OPCOES_MAIORES_LUCROS (prêmio do scanner por opção, quando casar)")
        opps = radar.scan(df_lucros, df_volumes, df_dados, cfg=radar_cfg, audit=funil,
                          mc=sim, vol_map=vmap, poe_max=poe_max, df_scanner=df_scanner)
    _log_radar_funil(log, funil)
    summary["radar_opps"] = len(opps)
    # Auditoria detalhada: uma linha por oportunidade, com prêmio, fonte e Trava.
    for o in opps:
        _log_radar_opp(log, o)
    # Auditoria Monte Carlo: dossiê completo da simulação de CADA oportunidade.
    mc_records = []
    for o in opps:
        if o.get("mc_audit"):
            rec = dict(o["mc_audit"])
            rec.update({"ticker": o.get("ticker"), "option_ticker": o.get("option_ticker"),
                        "nivel": "OPORTUNIDADE"})
            mc_records.append(rec)
    _log_montecarlo(log, "RADAR", mc_records, engine=_mc_engine(sim), terminal=True)

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
