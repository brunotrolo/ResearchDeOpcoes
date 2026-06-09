"""RADAR_DIAGNOSTICO — raio-X didático: 1 linha por ticker do DADOS_ATIVOS, com
veredito (indicado/rejeitado), o motivo e a leitura do Monte Carlo em PT-BR."""
import pandas as pd

import main
from app import config, montecarlo, radar


def _sc(o, t, k, c, sp, vol="100000", dte="30"):
    return dict(OPTION_TICKER=o, TICKER=t, CATEGORY="PUT", STRIKE=k, CLOSE=c, SPOT=sp,
                DTE_CALENDAR=dte, VOLUME_FIN=vol, BID="", ASK="", POE="")


DADOS = pd.DataFrame([
    dict(TICKER="USIM5", HAS_OPTIONS="TRUE", IV_RANK="83", IV="53", GARCH11_1Y="41",
         M9_M21_TREND="1", MIDDLE_TERM_TREND="1", SHORT_TERM_TREND="1", OPLAB_SCORE="3"),
    dict(TICKER="CSNA3", HAS_OPTIONS="TRUE", IV_RANK="56", IV="63", GARCH11_1Y="50",
         M9_M21_TREND="1", MIDDLE_TERM_TREND="-1", SHORT_TERM_TREND="-1", OPLAB_SCORE="2"),
    dict(TICKER="PETR4", HAS_OPTIONS="TRUE", IV_RANK="30", IV="28", GARCH11_1Y="28",
         M9_M21_TREND="1", MIDDLE_TERM_TREND="1", SHORT_TERM_TREND="1", OPLAB_SCORE="2"),
    dict(TICKER="WEGE3", HAS_OPTIONS="FALSE", IV_RANK="70", IV="25", GARCH11_1Y="25",
         M9_M21_TREND="1", MIDDLE_TERM_TREND="1", SHORT_TERM_TREND="1", OPLAB_SCORE="3"),
])
SCANNER = pd.DataFrame([
    _sc("USIMS105", "USIM5", "10,54", "0,43", "11,46"),
    _sc("USIMS102", "USIM5", "10,29", "0,35", "11,46"),
    _sc("CSNAS650", "CSNA3", "6,50", "0,69", "6,68"),
    _sc("PETRX36", "PETR4", "36,00", "0,80", "38,00"),
])


def _por_ticker(**kw):
    return {d["ticker"]: d for d in radar.diagnosticar_universo(DADOS, SCANNER, cfg=config.RadarCfg(), **kw)}


def test_uma_linha_por_ticker_do_dados_ativos():
    diag = radar.diagnosticar_universo(DADOS, SCANNER, cfg=config.RadarCfg())
    assert [d["ticker"] for d in diag] != []
    assert {d["ticker"] for d in diag} == {"USIM5", "CSNA3", "PETR4", "WEGE3"}
    assert len(diag) == 4   # sem duplicar tickers do scanner


def test_rejeicao_por_tendencia_baixa():
    d = _por_ticker()["CSNA3"]
    assert d["veredito"] == "REJEITADO" and d["trend_label"] == "BAIXA"
    assert "BAIXA" in d["motivo"] and "maré" in d["motivo"]


def test_rejeicao_por_iv_baixo():
    d = _por_ticker()["PETR4"]
    assert d["veredito"] == "REJEITADO" and "IV Rank" in d["motivo"]


def test_rejeicao_sem_opcoes_listadas():
    d = _por_ticker()["WEGE3"]
    assert d["veredito"] == "REJEITADO" and "universo" in d["motivo"].lower()
    assert d["como_ler"] == "Sem opção listada para simular."


def test_indicado_quando_esta_na_lista_de_oportunidades():
    sim = montecarlo.MonteCarloSimulator(n=5000, seed=42)
    vmap = radar.build_vol_map(DADOS)
    cfg = config.RadarCfg()
    opps = radar.scan_scanner(SCANNER, DADOS, cfg=cfg, mc=sim, vol_map=vmap, poe_max=0.60)
    diag = {d["ticker"]: d for d in radar.diagnosticar_universo(
        DADOS, SCANNER, cfg=cfg, mc=sim, vol_map=vmap, poe_max=0.60, opps=opps)}
    assert any(o["ticker"] == "USIM5" for o in opps)
    assert diag["USIM5"]["veredito"] == "INDICADO"
    assert "exerc" in diag["USIM5"]["como_ler"].lower()
    # Indicados vêm primeiro na ordenação.
    ordem = [d["veredito"] for d in radar.diagnosticar_universo(
        DADOS, SCANNER, cfg=cfg, mc=sim, vol_map=vmap, poe_max=0.60, opps=opps)]
    assert ordem[0] == "INDICADO"


def test_monte_carlo_estressa_a_baixa_em_ticker_baixista():
    """No raio-X, ticker baixista mostra o risco REAL: se cair, o exercício SOBE."""
    sim = montecarlo.MonteCarloSimulator(n=20000, seed=42)
    vmap = radar.build_vol_map(DADOS)
    d = {x["ticker"]: x for x in radar.diagnosticar_universo(
        DADOS, SCANNER, cfg=config.RadarCfg(), mc=sim, vol_map=vmap, poe_max=0.25)}["CSNA3"]
    assert "baixa seguir" in d["como_ler"] and "sobe" in d["como_ler"]


def test_panel_row_formata_colunas_novas():
    row = main._diag_panel_row("2026-06-09 10:00:00", {
        "ticker": "USIM5", "veredito": "INDICADO", "trend_label": "ALTA", "iv_rank": 83.0,
        "spot": 11.46, "strike": 11.04, "margem": -3.66, "poe": 0.314, "toque": 0.61,
        "cenario_txt": "Hoje R$ 11,46 ...", "motivo": "x", "como_ler": "y"})
    h = config.DIAGNOSTICO_HEADER
    g = lambda n: row[h.index(n)]
    assert len(row) == len(h)
    assert g("VEREDITO") == "✅ Indicado" and g("TENDENCIA") == "ALTA" and g("IV_RANK") == 83
    assert g("SPOT") == 11.46 and g("STRIKE") == 11.04 and g("MARGEM") == "-3,7%"
    assert g("CHANCE_EXERCICIO") == "31%" and g("CHANCE_TOQUE") == "61%"
    assert g("CENARIO_30D").startswith("Hoje") and g("COMO_LER") == "y"


def test_cenario_e_como_ler_baseados_em_dados():
    """CENARIO_30D traz hoje→pior/provável/melhor; COMO_LER explica os % com a vol,
    o nº de cenários e a posição do strike — e o link 'ficou de fora' no rejeitado."""
    sim = montecarlo.MonteCarloSimulator(n=100000, seed=42)
    vmap = radar.build_vol_map(DADOS)
    diag = {x["ticker"]: x for x in radar.diagnosticar_universo(
        DADOS, SCANNER, cfg=config.RadarCfg(), mc=sim, vol_map=vmap, poe_max=0.25)}
    csna = diag["CSNA3"]
    assert "Hoje R$" in csna["cenario_txt"] and "pior 5%" in csna["cenario_txt"] and "melhor 5%" in csna["cenario_txt"]
    assert "mil cenários" in csna["como_ler"] and "vol " in csna["como_ler"]
    assert "FECHAM abaixo" in csna["como_ler"] and "Ficou de fora" in csna["como_ler"]
    assert "(0%)" not in csna["cenario_txt"] or "-0%" not in csna["cenario_txt"]   # sem "-0%"
