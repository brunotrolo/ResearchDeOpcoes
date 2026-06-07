"""Testes do parser — formatos reais das abas-espelho (US e pt-BR).

Rode com:  .venv\\Scripts\\python.exe -m pytest -q
"""
from datetime import date

from app import parsing


# --- US / ISO (SELECAO_*, RANKING_*): ponto decimal, vírgula = milhar ---------
def test_to_float_us_default():
    assert parsing.to_float("R$ 14,670.00") == 14670.0
    assert parsing.to_float("3,000") == 3000.0
    assert parsing.to_float("939,000") == 939000.0
    assert parsing.to_float("1.0133") == 1.0133
    assert parsing.to_float("81.50") == 81.5
    assert parsing.to_float("(120.00)") == -120.0


# --- pt-BR (PAINEL_ATIVAS, DADOS_ATIVOS): vírgula decimal, ponto = milhar ------
def test_to_float_ptbr():
    assert parsing.to_float("R$ 33,91", ",") == 33.91
    assert parsing.to_float("-0,72", ",") == -0.72
    assert parsing.to_float("1.000", ",") == 1000.0
    assert parsing.to_float("R$ 1.285,00", ",") == 1285.0
    assert parsing.to_float("-1313,33", ",") == -1313.33
    assert parsing.to_float("75,98", ",") == 75.98
    assert parsing.to_float("464052000,00", ",") == 464052000.0
    assert parsing.to_float("(120,00)", ",") == -120.0


def test_to_float_auto_heuristica():
    assert parsing.to_float("1.234,56", None) == 1234.56
    assert parsing.to_float("1,5", None) == 1.5


def test_to_float_vazio_e_invalido():
    assert parsing.to_float("") is None
    assert parsing.to_float(None) is None
    assert parsing.to_float("#N/A") is None
    assert parsing.to_float("-") is None
    assert parsing.to_float("", ",") is None


def test_to_date_formatos():
    assert parsing.to_date("16/10/2026") == date(2026, 10, 16)
    assert parsing.to_date("2026-07-17") == date(2026, 7, 17)
    assert parsing.to_date("05/06/2026 23:57:05") == date(2026, 6, 5)


def test_days_to_expiry():
    hoje = date(2026, 6, 7)
    assert parsing.days_to_expiry("19/06/2026", hoje) == 12
    assert parsing.days_to_expiry("", hoje) is None


def test_to_upper():
    assert parsing.to_upper(" venda ") == "VENDA"
    assert parsing.to_upper(None) == ""
