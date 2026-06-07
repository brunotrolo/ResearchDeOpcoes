"""Testes do Monte Carlo (GBM) — convergência vs. fórmula fechada e robustez."""
import math

from app import montecarlo


def test_poe_converge_para_formula_fechada():
    sim = montecarlo.MonteCarloSimulator(n=200000, seed=1, drift=0.0)
    spot, strike, dte, sig = 100.0, 90.0, 30, 0.30
    mc = sim.poe_put(spot, strike, dte, sig)
    fechada = sim.poe_put_fechada(spot, strike, dte, sig)
    assert abs(mc - fechada) < 0.01   # converge para a lognormal N(-d2)


def test_seed_reprodutivel():
    a = montecarlo.MonteCarloSimulator(n=5000, seed=42).poe_put(100, 95, 20, 0.3)
    b = montecarlo.MonteCarloSimulator(n=5000, seed=42).poe_put(100, 95, 20, 0.3)
    assert a == b


def test_strike_mais_alto_tem_mais_poe():
    sim = montecarlo.MonteCarloSimulator(n=20000, seed=3)
    assert sim.poe_put(100, 100, 30, 0.3) > sim.poe_put(100, 90, 30, 0.3)


def test_dados_invalidos_retornam_none():
    sim = montecarlo.MonteCarloSimulator(n=100)
    assert sim.poe_put(None, 90, 30, 0.3) is None
    assert sim.poe_put(100, 90, 0, 0.3) is None
    assert sim.poe_put(100, 90, 30, None) is None


def test_anualizacao():
    assert abs(montecarlo.anual_from_daily(0.02) - 0.02 * math.sqrt(252)) < 1e-9
    assert montecarlo.anual_from_iv_pct(30.0) == 0.30
    assert montecarlo.anual_from_daily(None) is None


def test_poe_resumo_gate_e_o_maior():
    sim = montecarlo.MonteCarloSimulator(n=20000, seed=7)
    r = montecarlo.poe_resumo(sim, 100, 92, 30, 0.40, 0.20)   # iv alto, vol real baixa
    assert r["poe_mc_gate"] == max(r["poe_mc_iv"], r["poe_mc_real"])
    assert r["poe_mc_iv"] > r["poe_mc_real"]                  # mais vol -> mais PoE


def test_poe_call_e_complemento_da_put():
    sim = montecarlo.MonteCarloSimulator(n=20000, seed=5)
    put = montecarlo.poe_resumo(sim, 100, 90, 30, 0.30, None, tipo="PUT")["poe_mc_iv"]
    call = montecarlo.poe_resumo(sim, 100, 90, 30, 0.30, None, tipo="CALL")["poe_mc_iv"]
    assert abs((put + call) - 1.0) < 1e-9   # P(S<K) + P(S>K) = 1
