"""Auditoria Monte Carlo na aba LOGS.

Garante que CADA simulação vira uma linha SERVICE=MONTE_CARLO reprodutível
(entradas + saídas + validação fechada), com a 2ª opinião por simulação de
trajetória (motor independente) anexada no CONTEXT.
"""
import json

import main
from app import config, montecarlo
from app.logbook import Logbook
from app.monte_carlo_engine import MonteCarloEngine


def _registro(nivel="OK", **tags):
    sim = montecarlo.MonteCarloSimulator(n=10000, seed=42, drift=0.0)
    rec = montecarlo.simular_completo(sim, 100, 95, 30, 0.40, 0.30, tipo="PUT")
    rec.update({"ticker": "TICK", "option_ticker": "TICKX95", "nivel": nivel})
    rec.update(tags)
    return rec


def test_log_montecarlo_emite_uma_linha_por_simulacao():
    log = Logbook()
    engine = MonteCarloEngine(num_simulations=10000, seed=42)
    recs = [_registro(nivel="OK"), _registro(nivel="ALERTA", option_ticker="TICKY90")]
    main._log_montecarlo(log, "ESCUDO", recs, engine=engine)

    mc = [e for e in log._entries if e.service == "MONTE_CARLO"]
    assert len(mc) == 1 + len(recs)            # 1 resumo + 1 por simulação
    assert "2 simulação" in mc[0].summary

    item = mc[2]                                # a linha do 2º registro (ALERTA)
    assert item.status == "ALERTA"
    ctx = json.loads(item.context)
    for k in ("spot", "strike", "dte_dias", "sigma_gate", "drift_sim", "n_cenarios",
              "seed", "poe_mc_iv", "poe_mc_gate", "toque_gate", "poe_fechada_iv",
              "erro_vs_fechada", "cenarios", "validacao_simulada"):
        assert k in ctx, f"falta {k} no dossiê de auditoria"
    # 2ª opinião por simulação de trajetória (motor independente, drift 0).
    assert ctx["validacao_simulada"]["motor"] == "monte_carlo_engine"
    assert ctx["validacao_simulada"]["metodo"] == "TRAJETORIA"
    assert ctx["validacao_simulada"]["toque_sim"] is not None


def test_log_montecarlo_terminal_usa_motor_de_oportunidade():
    log = Logbook()
    engine = MonteCarloEngine(num_simulations=10000, seed=42)
    main._log_montecarlo(log, "RADAR", [_registro(nivel="OPORTUNIDADE")],
                         engine=engine, terminal=True)
    item = [e for e in log._entries if e.service == "MONTE_CARLO"][1]
    assert item.status == "OPORTUNIDADE"
    cc = json.loads(item.context)["validacao_simulada"]
    assert cc["metodo"] == "TERMINAL" and cc["poe_terminal_sim"] is not None


def test_log_montecarlo_sem_registros_nao_grava():
    log = Logbook()
    main._log_montecarlo(log, "ESCUDO", [], engine=None)
    assert [e for e in log._entries if e.service == "MONTE_CARLO"] == []


def test_mc_engine_respeita_audit_verbose(monkeypatch):
    sim = montecarlo.MonteCarloSimulator(n=10000, seed=42)
    monkeypatch.setattr(config, "AUDIT_VERBOSE", False)
    assert main._mc_engine(sim) is None
    monkeypatch.setattr(config, "AUDIT_VERBOSE", True)
    eng = main._mc_engine(sim)
    assert isinstance(eng, MonteCarloEngine) and eng.num_simulations == sim.n


def test_mc_crosscheck_dados_insuficientes():
    engine = MonteCarloEngine(num_simulations=1000, seed=1)
    assert "erro" in main._mc_crosscheck(engine, {"tipo": "PUT"}, terminal=False)
