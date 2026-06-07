"""Testes do Escudo (Módulo 1) com valores reais em pt-BR da PAINEL_ATIVAS.

Garante que a taxonomia por moneyness + o parser pt-BR não regridam.
"""
from datetime import date

import pandas as pd

from app import escudo, montecarlo

HOJE = date(2026, 6, 7)


def _ativa(**kw) -> dict:
    base = dict(STATUS="ATIVO", SIDE="VENDA", OPTION_TYPE="PUT", CONTROL_FLAG="1",
                ID_STRATEGY="STR", TICKER="TICK", PL_PCT="", POE="0,50",
                EXPIRY="17/07/2026", DTE_CALENDAR="40")
    base.update(kw)
    return base


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_itm_curto_prazo_e_critico():
    alerts = escudo.analyze(_df([_ativa(
        OPTION_TICKER="PRIOR660", MONEYNESS="ITM", STRIKE="R$ 66,00", SPOT="R$ 60,54",
        ENTRY_PRICE="R$ 1,80", LAST_PREMIUM="R$ 4,79", DELTA="-1,00", POE="1,00",
        PL_VALUE="-R$ 897,00", MAX_LOSS="R$ 19.260,00", DTE_CALENDAR="12", EXPIRY="19/06/2026")]), HOJE)
    assert alerts[0]["nivel"] == "CRITICO"


def test_itm_longo_prazo_e_alerta_com_parser_ptbr():
    alerts = escudo.analyze(_df([_ativa(
        OPTION_TICKER="SANBV329", MONEYNESS="ITM", STRIKE="R$ 31,91", SPOT="R$ 26,74",
        ENTRY_PRICE="R$ 2,57", LAST_PREMIUM="R$ 3,80", DELTA="-0,72", POE="0,77",
        PL_VALUE="-R$ 615,00", MAX_LOSS="R$ 14.670,00", DTE_CALENDAR="131", EXPIRY="16/10/2026")]), HOJE)
    a = alerts[0]
    assert a["nivel"] == "ALERTA"
    assert a["delta"] == -0.72       # "-0,72" pt-BR
    assert a["strike"] == 31.91      # "R$ 31,91" pt-BR


def test_otm_saudavel_com_toque_alto_vira_alerta_preditivo():
    """Escudo PREDITIVO: uma perna OTM 'saudável' (sem delta/recompra/perda) mas com
    alta probabilidade de TOCAR o strike antes de vencer é surfada via Monte Carlo —
    o que evita que um OTM vire ATM/ITM sem aviso."""
    sim = montecarlo.MonteCarloSimulator(seed=1)
    vol_map = {"TICK": {"iv": 0.50, "real": 0.45}}
    df = _df([_ativa(OPTION_TICKER="TICKX95", MONEYNESS="OTM", STRIKE="R$ 95,00", SPOT="R$ 100,00",
                     ENTRY_PRICE="R$ 2,00", LAST_PREMIUM="R$ 1,90", DELTA="-0,20",
                     PL_VALUE="R$ 10,00", MAX_LOSS="R$ 9.500,00", DTE_CALENDAR="40")])
    # Sem Monte Carlo: posição saudável -> nenhum alerta.
    assert escudo.analyze(df, HOJE) == []
    # Com Monte Carlo: alta prob. de toque -> ALERTA preditivo, antes de dar ruim.
    a = escudo.analyze(df, HOJE, sim=sim, vol_map=vol_map)[0]
    assert a["nivel"] in {"AVISO", "ALERTA"}
    assert a["toque_gate"] is not None and a["toque_gate"] > 0.5
    assert "TOQUE" in a["motivo"]


def test_toque_estresse_usa_tendencia_de_baixa():
    """Com trend_map de baixa, o cenário de continuação eleva o toque (drift adverso)."""
    sim = montecarlo.MonteCarloSimulator(seed=1)
    vol_map = {"TICK": {"iv": 0.40, "real": 0.35}}
    df = _df([_ativa(OPTION_TICKER="TICKX95", MONEYNESS="OTM", STRIKE="R$ 95,00", SPOT="R$ 100,00",
                     ENTRY_PRICE="R$ 2,00", LAST_PREMIUM="R$ 1,90", DELTA="-0,20",
                     PL_VALUE="R$ 10,00", MAX_LOSS="R$ 9.500,00", DTE_CALENDAR="40")])
    a = escudo.analyze(df, HOJE, sim=sim, vol_map=vol_map, trend_map={"TICK": -1})[0]
    assert a.get("toque_tendencia") is not None
    assert a["toque_tendencia"] >= a["toque_gate"]   # baixa continuar -> pior ou igual


def test_atm_benigno_e_aviso():
    alerts = escudo.analyze(_df([_ativa(
        OPTION_TICKER="DIRRR123", MONEYNESS="ATM", STRIKE="R$ 12,33", SPOT="R$ 12,26",
        ENTRY_PRICE="R$ 0,38", LAST_PREMIUM="R$ 0,33", DELTA="-0,49", POE="0,51",
        PL_VALUE="R$ 50,00", MAX_LOSS="R$ 11.950,00", DTE_CALENDAR="12", EXPIRY="19/06/2026")]), HOJE)
    assert alerts[0]["nivel"] == "AVISO"


def test_atm_perto_vencimento_e_perdendo_vira_alerta():
    alerts = escudo.analyze(_df([_ativa(
        OPTION_TICKER="BBDCR17", MONEYNESS="ATM", STRIKE="R$ 17,26", SPOT="R$ 17,43",
        ENTRY_PRICE="R$ 0,22", LAST_PREMIUM="R$ 0,23", DELTA="-0,36", POE="0,38",
        PL_VALUE="-R$ 10,00", MAX_LOSS="R$ 17.040,00", DTE_CALENDAR="12", EXPIRY="19/06/2026")]), HOJE)
    assert alerts[0]["nivel"] == "ALERTA"


def test_otm_saudavel_longe_sem_alerta():
    alerts = escudo.analyze(_df([_ativa(
        OPTION_TICKER="EMBJS693", MONEYNESS="OTM", STRIKE="R$ 69,30", SPOT="R$ 72,35",
        ENTRY_PRICE="R$ 2,10", LAST_PREMIUM="R$ 1,46", DELTA="-0,28", POE="0,31",
        PL_VALUE="R$ 640,00", MAX_LOSS="R$ 67.200,00", DTE_CALENDAR="40")]), HOJE)
    assert alerts == []


def test_otm_saudavel_perto_vencimento_e_aviso():
    alerts = escudo.analyze(_df([_ativa(
        OPTION_TICKER="CSNAF702", OPTION_TYPE="CALL", MONEYNESS="OTM", STRIKE="R$ 7,02",
        SPOT="R$ 5,98", ENTRY_PRICE="R$ 0,22", LAST_PREMIUM="R$ 0,05", DELTA="0,05", POE="0,11",
        PL_VALUE="R$ 510,00", MAX_LOSS="R$ 20.400,00", DTE_CALENDAR="12", EXPIRY="19/06/2026")]), HOJE)
    assert alerts[0]["nivel"] == "AVISO"
    assert "DTE_PROXIMO" in alerts[0]["motivo"]


def test_compra_exercida_e_control_flag_zero_sao_ignoradas():
    rows = [
        _ativa(OPTION_TICKER="LONG", SIDE="COMPRA", MONEYNESS="ITM", STRIKE="R$ 10,00",
               SPOT="R$ 8,00", ENTRY_PRICE="R$ 1,00", LAST_PREMIUM="R$ 2,00", DELTA="-0,80",
               PL_VALUE="-R$ 100,00", MAX_LOSS="R$ 1.000,00", DTE_CALENDAR="5"),
        _ativa(OPTION_TICKER="DONE", STATUS="EXERCIDA", MONEYNESS="ITM", STRIKE="R$ 10,00",
               SPOT="R$ 8,00", ENTRY_PRICE="R$ 1,00", LAST_PREMIUM="R$ 2,00", DELTA="-0,80",
               PL_VALUE="-R$ 100,00", MAX_LOSS="R$ 1.000,00", DTE_CALENDAR="5"),
        _ativa(OPTION_TICKER="OFF", MONEYNESS="ITM", CONTROL_FLAG="0", STRIKE="R$ 10,00",
               SPOT="R$ 8,00", ENTRY_PRICE="R$ 1,00", LAST_PREMIUM="R$ 2,00", DELTA="-0,80",
               PL_VALUE="-R$ 100,00", MAX_LOSS="R$ 1.000,00", DTE_CALENDAR="5"),
    ]
    assert escudo.analyze(_df(rows), HOJE) == []


def test_gamma_alto_gera_aviso():
    alerts = escudo.analyze(_df([_ativa(
        OPTION_TICKER="G1", MONEYNESS="OTM", SECTOR="X", STRIKE="R$ 10,00", SPOT="R$ 11,00",
        ENTRY_PRICE="R$ 1,00", LAST_PREMIUM="R$ 0,50", DELTA="-0,15", GAMMA="0,40",
        PL_VALUE="R$ 50,00", MAX_LOSS="R$ 5.000,00", DTE_CALENDAR="40")]), HOJE)
    assert alerts and alerts[0]["nivel"] == "AVISO"
    assert "GAMMA_ALTO" in alerts[0]["motivo"]


def test_portfolio_hhi_e_exposicao_ibov():
    def _banco(opt, ticker, strike, spot):
        return _ativa(OPTION_TICKER=opt, TICKER=ticker, MONEYNESS="OTM", SECTOR="BANCOS",
                      NOTIONAL="R$ 10.000,00", STRIKE=strike, SPOT=spot, ENTRY_PRICE="R$ 1,00",
                      LAST_PREMIUM="R$ 0,50", DELTA="-0,20", PL_VALUE="R$ 50,00",
                      MAX_LOSS="R$ 10.000,00", DTE_CALENDAR="40")
    rows = [_banco("A", "BBAS3", "R$ 20,00", "R$ 22,00"),
            _banco("B", "BBDC4", "R$ 18,00", "R$ 20,00"),
            _banco("C", "ITUB4", "R$ 30,00", "R$ 33,00")]
    correl = pd.DataFrame([dict(TICKER="BBAS3", CORREL_VALUE="0,85"),
                           dict(TICKER="BBDC4", CORREL_VALUE="0,84"),
                           dict(TICKER="ITUB4", CORREL_VALUE="0,80")])
    port = {a["option_ticker"]: a for a in escudo.analyze_portfolio(_df(rows), correl)}
    assert "PORTFOLIO_HHI" in port and port["PORTFOLIO_HHI"]["nivel"] == "ALERTA"
    assert "PORTFOLIO_IBOV" in port and port["PORTFOLIO_IBOV"]["nivel"] == "ALERTA"
