"""Parsing e limpeza de valores vindos das planilhas-espelho.

As abas misturam formatos:
    - Painel_Ativas: strings formatadas -> "R$ 33.91", "75.98%", "3,000", "-R$ 916.00"
    - SELECAO_*: floats em string "limpa" -> "1.0133", "81.50"
Estas funções normalizam tudo para float/int/date de forma tolerante,
retornando None quando o valor é vazio/ inválido (em vez de quebrar).
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Optional

_NUMERIC_CLEANER = re.compile(r"[^\d,.\-]")  # remove R$, %, espaços, letras, etc.


def to_float(value) -> Optional[float]:
    """Converte um valor de planilha para float, tolerante a R$, %, vírgula.

    Exemplos:
        "R$ 33.91"  -> 33.91
        "75.98%"    -> 75.98     (mantém em unidade de %; não divide por 100)
        "3,000"     -> 3000.0
        "-R$ 916.00"-> -916.0
        "1.0133"    -> 1.0133
        "(120.00)"  -> -120.0    (parênteses = negativo, padrão contábil)
        ""/None     -> None
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and math.isnan(value)) else float(value)

    text = str(value).strip()
    if text == "" or text in {"-", "--", "N/A", "n/a", "#N/A", "nan"}:
        return None

    negative = text.startswith("(") and text.endswith(")")
    text = _NUMERIC_CLEANER.sub("", text)
    if text in {"", "-", ".", ","}:
        return None

    # Heurística de separador: se tem ',' e '.', o último é o decimal.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")   # 1.234,56 -> 1234.56
        else:
            text = text.replace(",", "")                      # 1,234.56 -> 1234.56
    elif "," in text:
        # Só vírgula: trata como separador de milhar se houver 3 dígitos após
        # (ex.: "3,000" -> 3000); caso contrário como decimal ("1,5" -> 1.5).
        if re.match(r"^-?\d{1,3}(,\d{3})+$", text):
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")

    try:
        result = float(text)
    except ValueError:
        return None
    if negative:
        result = -abs(result)
    return result


def to_int(value) -> Optional[int]:
    f = to_float(value)
    return int(round(f)) if f is not None else None


def to_upper(value) -> str:
    return str(value or "").strip().upper()


def to_date(value, dayfirst: bool = True) -> Optional[date]:
    """Parse de data tolerante a dd/mm/aaaa, aaaa-mm-dd e variações.

    dayfirst=True cobre o padrão brasileiro (Painel_Ativas: '16/10/2026').
    A aba SELECAO_OPCOES_MAIORES_LUCROS usa ISO 'aaaa-mm-dd'.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.split(" ")[0]  # descarta hora, se houver

    formats = (
        ["%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%m/%d/%Y"]
        if dayfirst
        else ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def days_to_expiry(expiry, today: Optional[date] = None) -> Optional[int]:
    """DTE em dias corridos a partir de hoje (timezone-aware tratado fora)."""
    exp = to_date(expiry)
    if exp is None:
        return None
    base = today or date.today()
    return (exp - base).days
