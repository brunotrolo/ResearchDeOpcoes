"""Testes do parser — formatos reais vistos nas abas-espelho.

Rode com:  .venv\\Scripts\\python.exe -m pytest -q
"""
from datetime import date

from app import parsing


def test_to_float_moeda_e_percent():
    assert parsing.to_float("R$ 33.91") == 33.91
    assert parsing.to_float("-R$ 916.00") == -916.0
    assert parsing.to_float("75.98%") == 75.98
    assert parsing.to_float("1.0133") == 1.0133


def test_to_float_milhar():
    assert parsing.to_float("3,000") == 3000.0
    assert parsing.to_float("R$ 14,670.00") == 14670.0
    assert parsing.to_float("939,000") == 939000.0


def test_to_float_decimal_virgula_br():
    # 1.234,56 (pt-BR) -> 1234.56
    assert parsing.to_float("1.234,56") == 1234.56
    assert parsing.to_float("1,5") == 1.5


def test_to_float_negativo_parenteses():
    assert parsing.to_float("(120.00)") == -120.0


def test_to_float_vazio_e_invalido():
    assert parsing.to_float("") is None
    assert parsing.to_float(None) is None
    assert parsing.to_float("#N/A") is None
    assert parsing.to_float("-") is None


def test_to_date_formatos():
    assert parsing.to_date("16/10/2026") == date(2026, 10, 16)
    assert parsing.to_date("2026-07-17") == date(2026, 7, 17)
    assert parsing.to_date("28/05/2026 19:26") == date(2026, 5, 28)


def test_days_to_expiry():
    hoje = date(2026, 6, 7)
    assert parsing.days_to_expiry("19/06/2026", hoje) == 12
    assert parsing.days_to_expiry("", hoje) is None


def test_to_upper():
    assert parsing.to_upper(" venda ") == "VENDA"
    assert parsing.to_upper(None) == ""
