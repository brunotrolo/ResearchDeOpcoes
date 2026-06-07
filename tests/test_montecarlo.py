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


# --- Probabilidade de TOQUE (first-passage, fórmula fechada) ----------------
def test_toque_maior_que_poe_terminal():
    """Tocar o strike no caminho é sempre ≥ terminar ITM (princípio da reflexão)."""
    sim = montecarlo.MonteCarloSimulator(drift=0.0)
    toque = sim.prob_toque(100, 95, 30, 0.30, tipo="PUT")
    terminal = sim.poe_put_fechada(100, 95, 30, 0.30)
    assert toque > terminal
    assert abs(toque - 2 * terminal) < 0.05    # ~2x com drift ≈ 0 (reflexão)


def test_toque_ja_no_dinheiro_e_certo():
    sim = montecarlo.MonteCarloSimulator()
    assert sim.prob_toque(90, 95, 30, 0.30, tipo="PUT") == 1.0    # PUT já ITM
    assert sim.prob_toque(110, 105, 30, 0.30, tipo="CALL") == 1.0  # CALL já ITM


def test_toque_baixa_aumenta_para_put():
    """Drift negativo (tendência de baixa) eleva o toque de uma PUT vendida."""
    sim = montecarlo.MonteCarloSimulator()
    neutro = sim.prob_toque(100, 95, 30, 0.30, drift=0.0, tipo="PUT")
    baixa = sim.prob_toque(100, 95, 30, 0.30, drift=-0.30, tipo="PUT")
    assert baixa > neutro


def test_toque_dados_invalidos_none():
    sim = montecarlo.MonteCarloSimulator()
    assert sim.prob_toque(None, 95, 30, 0.30) is None
    assert sim.prob_toque(100, 95, 0, 0.30) is None
    assert sim.prob_toque(100, 95, 30, None) is None


def test_toque_resumo_gate_e_o_maior_e_tendencia():
    sim = montecarlo.MonteCarloSimulator()
    r = montecarlo.toque_resumo(sim, 100, 95, 30, 0.40, 0.20, tipo="PUT", drift_tendencia=-0.30)
    assert r["toque_gate"] == max(r["toque_iv"], r["toque_real"])
    assert r["toque_iv"] > r["toque_real"]            # mais vol -> mais toque
    assert r["toque_tendencia"] > r["toque_gate"]     # baixa continua -> pior


def test_cenarios_preco_ordenados():
    sim = montecarlo.MonteCarloSimulator(drift=0.0)
    c = sim.cenarios_preco(100, 0.30, 30)
    assert c["p05"] < c["p50"] < c["p95"]


def test_simular_completo_contrato_de_auditoria():
    """O dossiê de auditoria carrega entradas (reprodutibilidade), saídas e a
    validação fechada; e o MC converge à fórmula N(-d2) (erro pequeno)."""
    sim = montecarlo.MonteCarloSimulator(n=40000, seed=42, drift=0.0)
    a = montecarlo.simular_completo(sim, 100, 95, 30, 0.40, 0.25, tipo="PUT", drift_tendencia=-0.30)
    # Entradas presentes (dá para reproduzir a simulação a partir do log).
    for k in ("spot", "strike", "dte_dias", "sigma_iv", "sigma_real", "sigma_gate",
              "drift_sim", "drift_tendencia", "n_cenarios", "seed"):
        assert k in a
    assert a["n_cenarios"] == 40000 and a["seed"] == 42 and a["sigma_gate"] == 0.40
    # Saídas + validação.
    assert a["poe_mc_gate"] == max(a["poe_mc_iv"], a["poe_mc_real"])
    assert a["toque_gate"] >= a["poe_mc_gate"]            # toque ⊇ terminal
    assert a["cenarios"]["p05"] < a["cenarios"]["p50"] < a["cenarios"]["p95"]
    # Convergência: o MC (IV) bate com a fórmula fechada N(-d2).
    assert a["erro_vs_fechada"] is not None and a["erro_vs_fechada"] < 0.02


def test_simular_completo_e_reprodutivel():
    """Mesmas entradas + seed => MESMO dossiê (auditoria reprodutível)."""
    sim = montecarlo.MonteCarloSimulator(n=10000, seed=7, drift=0.0)
    a = montecarlo.simular_completo(sim, 100, 96, 35, 0.45, 0.30)
    b = montecarlo.simular_completo(sim, 100, 96, 35, 0.45, 0.30)
    assert a == b
