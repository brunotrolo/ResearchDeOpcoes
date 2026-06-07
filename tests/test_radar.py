"""Testes do Radar (Módulo 2): filtros PUT / IV_RANK / SPOT_STRIKE_RATIO /
liquidez e whitelist DADOS_ATIVOS (com HAS_OPTIONS)."""
import pandas as pd

from app import config, radar


def _opt(**kw) -> dict:
    base = dict(CATEGORY="PUT", EXPIRY="2026-07-17", DTE_CALENDAR="40", IV_CURRENT="29",
                VOLUME_FIN="500000", M9M21_TREND="-1", SECTOR="", COMPANY_NAME="")
    base.update(kw)
    return base


def test_filtros_basicos_sem_whitelist():
    df = pd.DataFrame([
        _opt(OPTION_TICKER="OK1", TICKER="VALE3", STRIKE="76.00", SPOT="78.99",
             SPOT_STRIKE_RATIO="1.05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="3.5"),
        _opt(OPTION_TICKER="RATIO_BAIXO", TICKER="VALE3", STRIKE="78.00", SPOT="78.99",
             SPOT_STRIKE_RATIO="1.01", IV_RANK="80", PROFIT_RATE_IF_EXERCISED="9"),
        _opt(OPTION_TICKER="EH_CALL", TICKER="VALE3", CATEGORY="CALL", STRIKE="85.00",
             SPOT="78.99", SPOT_STRIKE_RATIO="1.05", IV_RANK="80", PROFIT_RATE_IF_EXERCISED="9"),
        _opt(OPTION_TICKER="IV_BAIXO", TICKER="VALE3", STRIKE="70.00", SPOT="78.99",
             SPOT_STRIKE_RATIO="1.12", IV_RANK="40", PROFIT_RATE_IF_EXERCISED="9"),
        _opt(OPTION_TICKER="SEM_LIQUIDEZ", TICKER="VALE3", STRIKE="74.00", SPOT="78.99",
             SPOT_STRIKE_RATIO="1.06", IV_RANK="70", VOLUME_FIN="0", PROFIT_RATE_IF_EXERCISED="9"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)
    opps = radar.scan(df, cfg=cfg)
    assert [o["option_ticker"] for o in opps] == ["OK1"]


def test_whitelist_has_options():
    df = pd.DataFrame([
        _opt(OPTION_TICKER="VALE_P", TICKER="VALE3", STRIKE="76.00", SPOT="78.99",
             SPOT_STRIKE_RATIO="1.05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="3.5"),
        _opt(OPTION_TICKER="FORA_P", TICKER="XXXX3", STRIKE="9.00", SPOT="9.50",
             SPOT_STRIKE_RATIO="1.05", IV_RANK="90", PROFIT_RATE_IF_EXERCISED="9"),
    ])
    dados = pd.DataFrame([
        dict(TICKER="VALE3", HAS_OPTIONS="TRUE"),
        dict(TICKER="XXXX3", HAS_OPTIONS="FALSE"),  # sem opções -> fora do universo
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=True, require_has_options=True)
    opps = radar.scan(df, df_dados_ativos=dados, cfg=cfg)
    assert [o["option_ticker"] for o in opps] == ["VALE_P"]


def test_ordena_por_profit_rate():
    df = pd.DataFrame([
        _opt(OPTION_TICKER="MENOR", TICKER="VALE3", STRIKE="76.00", SPOT="78.99",
             SPOT_STRIKE_RATIO="1.05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="3.5"),
        _opt(OPTION_TICKER="MAIOR", TICKER="BRKM5", STRIKE="8.50", SPOT="8.67",
             SPOT_STRIKE_RATIO="1.02", IV_RANK="79", PROFIT_RATE_IF_EXERCISED="6.0"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)
    opps = radar.scan(df, cfg=cfg)
    assert [o["option_ticker"] for o in opps] == ["MAIOR", "MENOR"]


def test_janela_dte():
    df = pd.DataFrame([
        _opt(OPTION_TICKER="DENTRO", TICKER="VALE3", STRIKE="76.00", SPOT="78.99",
             SPOT_STRIKE_RATIO="1.05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="3.5", DTE_CALENDAR="30"),
        _opt(OPTION_TICKER="CURTO", TICKER="VALE3", STRIKE="76.00", SPOT="78.99",
             SPOT_STRIKE_RATIO="1.05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="9", DTE_CALENDAR="10"),
        _opt(OPTION_TICKER="LONGO", TICKER="VALE3", STRIKE="76.00", SPOT="78.99",
             SPOT_STRIKE_RATIO="1.05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="9", DTE_CALENDAR="120"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)  # dte_min=21, dte_max=45
    opps = radar.scan(df, cfg=cfg)
    assert [o["option_ticker"] for o in opps] == ["DENTRO"]
