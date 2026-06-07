"""Testes do MonteCarloEngine (GBM vetorizado): risco de trajetória vs terminal.

Parametriza uma Venda de PUT OTM SEGURA e uma Venda de PUT PERIGOSA, além de
checar a vetorização (formato da matriz), a conversão de DTE, a normalização de
IV e a relação fundamental toque ≥ terminal.
"""
import numpy as np
import pytest

from app.monte_carlo_engine import MonteCarloEngine


@pytest.fixture
def engine() -> MonteCarloEngine:
    # seed fixa -> resultado reprodutível (Selic e 10.000 simulações padrão).
    return MonteCarloEngine(num_simulations=10000, seed=42)


# (nome, spot, strike, dte, iv, is_put, status_radar, status_escudo)
CASOS = [
    # PUT bem OTM (20% de margem), vol moderada, ~30d -> vira pó e nem encosta.
    ("PUT OTM segura", 100.0, 80.0, 30, 0.30, True, "APPROVED", "SAFE"),
    # PUT quase ATM (2% de margem), vol alta, ~45d -> encosta muito e arrisca exercício.
    ("PUT perigosa", 100.0, 98.0, 45, 0.60, True, "REJECTED", "CRITICAL"),
]


@pytest.mark.parametrize("nome,spot,strike,dte,iv,is_put,radar,escudo", CASOS)
def test_classificacao_radar_e_escudo(engine, nome, spot, strike, dte, iv, is_put, radar, escudo):
    op = engine.evaluate_opportunity(spot, strike, dte, iv, is_put=is_put,
                                     ticker="TST", option_ticker="TSTX1")
    risk = engine.check_active_risk(spot, strike, dte, iv, is_put=is_put,
                                    ticker="TST", option_ticker="TSTX1")
    assert op["status"] == radar, f"{nome}: Radar esperava {radar}, veio {op}"
    assert risk["status"] == escudo, f"{nome}: Escudo esperava {escudo}, veio {risk}"
    # contratos do dicionário de log
    assert op["method"] == "TERMINAL_PRICE" and risk["method"] == "PATH_DEPENDENT"
    assert op["simulations_run"] == 10000 and risk["simulations_run"] == 10000


def test_toque_nunca_menor_que_terminal(engine):
    """Tocar o strike na trajetória é sempre ≥ terminar ITM (o fundo inclui o fim)."""
    risk = engine.check_active_risk(100, 95, 40, 0.45, is_put=True)
    op = engine.evaluate_opportunity(100, 95, 40, 0.45, is_put=True)
    assert risk["poe_mc_gate"] >= op["poe_mc_terminal"]


def test_generate_paths_e_2d_e_vetorizado(engine):
    dte_uteis = engine._dte_uteis(30)               # 30 corridos -> 20 úteis
    paths = engine._generate_paths(100.0, 0.30, dte_uteis)
    assert paths.shape == (dte_uteis, engine.num_simulations)   # (passos, cenários)
    assert np.all(paths > 0)                        # GBM nunca é negativo


def test_conversao_dte_corridos_para_uteis(engine):
    assert engine._dte_uteis(30) == 20              # int(30 * 252/365)
    assert engine._dte_uteis(365) == 252


def test_dte_curto_demais_levanta_erro(engine):
    # dte=1 -> int(1*252/365)=0 dias úteis -> inválido.
    with pytest.raises(ValueError):
        engine.check_active_risk(100, 95, 1, 0.30)
    with pytest.raises(ValueError):
        engine.evaluate_opportunity(100, 95, 0, 0.30)


def test_iv_percentual_e_decimal_sao_equivalentes():
    # 45.0 (percentual) deve ser tratado como 0.45 (decimal) -> mesmo resultado.
    a = MonteCarloEngine(seed=7).evaluate_opportunity(100, 90, 30, 45.0)
    b = MonteCarloEngine(seed=7).evaluate_opportunity(100, 90, 30, 0.45)
    assert a["poe_mc_terminal"] == b["poe_mc_terminal"]


def test_reprodutivel_com_seed():
    a = MonteCarloEngine(seed=123).check_active_risk(100, 96, 30, 0.40)
    b = MonteCarloEngine(seed=123).check_active_risk(100, 96, 30, 0.40)
    assert a["poe_mc_gate"] == b["poe_mc_gate"]


def test_strike_mais_alto_tem_mais_toque(engine):
    """PUT com strike mais perto do spot encosta mais (monotonicidade)."""
    perto = engine.check_active_risk(100, 99, 40, 0.45, is_put=True)["poe_mc_gate"]
    longe = engine.check_active_risk(100, 85, 40, 0.45, is_put=True)["poe_mc_gate"]
    assert perto > longe


def test_dict_de_log_tem_as_chaves_esperadas(engine):
    risk = engine.check_active_risk(100, 98, 45, 0.60, ticker="PETR4", option_ticker="PETRQ400")
    assert set(risk) == {"ticker", "option_ticker", "status", "poe_mc_gate",
                         "min_price_avg", "simulations_run", "method"}
    op = engine.evaluate_opportunity(100, 80, 30, 0.30, ticker="VALE3", option_ticker="VALES790")
    assert set(op) == {"ticker", "option_ticker", "status", "poe_mc_terminal",
                       "terminal_price_avg", "simulations_run", "method"}
