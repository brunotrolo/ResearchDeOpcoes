"""Testes das métricas de risco de portfólio (camada agregada do Escudo)."""
from app import risk_metrics


def test_relative_spread():
    assert abs(risk_metrics.relative_spread(0.95, 1.05) - 0.1) < 1e-9
    assert risk_metrics.relative_spread(None, 1.0) is None
    assert risk_metrics.relative_spread(0, 0) is None


def test_hhi_concentrado_vs_diversificado():
    assert risk_metrics.hhi_setorial(["BANCOS", "BANCOS"], [100, 100]) == 1.0
    h = risk_metrics.hhi_setorial(["A", "B", "C", "D"], [1, 1, 1, 1])
    assert abs(h - 0.25) < 1e-9
    assert risk_metrics.hhi_setorial([], []) is None


def test_exposicao_ibov():
    correl = {"VALE3": 0.9, "BBAS3": 0.8, "NATU3": 0.1}
    exp = risk_metrics.exposicao_ibov(["VALE3", "BBAS3", "NATU3"], [1, 1, 1], correl, 0.5)
    assert abs(exp - 2 / 3) < 1e-9
    assert risk_metrics.exposicao_ibov(["NATU3"], [1], correl, 0.5) == 0.0


def test_tamanho_posicao():
    # capital 100k, risco 2% = 2000; risco/contrato 1000 -> 2 contratos
    assert risk_metrics.tamanho_posicao(100000, 1000, 0.02) == 2
    assert risk_metrics.tamanho_posicao(0, 1000) == 0
    assert risk_metrics.tamanho_posicao(100000, 0) == 0
