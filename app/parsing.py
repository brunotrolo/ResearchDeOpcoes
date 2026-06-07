"""Parsing e limpeza de valores vindos das planilhas-espelho.

As abas usam DOIS locales numéricos diferentes:
    - PAINEL_ATIVAS / DADOS_ATIVOS  -> pt-BR: vírgula decimal, ponto de milhar
        "R$ 33,91" -> 33.91 ; "1.000" -> 1000 ; "-0,72" -> -0.72 ; "75,98%" -> 75.98
    - SELECAO_* / RANKING_*         -> US/ISO: ponto decimal, vírgula de milhar
        "1.0133" -> 1.0133 ; "R$ 14,670.00" -> 14670.0 ; "939,000" -> 939000
Por isso `to_float` recebe o separador decimal da aba (decimal_sep). O chamador
(frames.num) injeta o locale correto por tabela. Tudo é tolerante: valor
vazio/ inválido vira None em vez de quebrar.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Optional

_NUMERIC_CLEANER = re.compile(r"[^\d,.\-]")  # remove R$, %, espaços, letras, etc.
_SENTINELS = {"", "-", "--", "N/A", "n/a", "#N/A", "nan", "None", "null"}


def to_float(value, decimal_sep: str | None = ".") -> Optional[float]:
    """Converte um valor de planilha em float, ciente do separador decimal.

    decimal_sep=".":  US/ISO (ponto decimal, vírgula = milhar).
    decimal_sep=",":  pt-BR  (vírgula decimal, ponto = milhar).
    decimal_sep=None: heurística automática (o ÚLTIMO separador é o decimal).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and math.isnan(value)) else float(value)

    text = str(value).strip()
    if text in _SENTINELS:
        return None

    negative = text.startswith("(") and text.endswith(")")  # padrão contábil
    text = _NUMERIC_CLEANER.sub("", text)
    if text in {"", "-", ".", ","}:
        return None

    if decimal_sep == ",":
        text = text.replace(".", "").replace(",", ".")       # pt-BR
    elif decimal_sep == ".":
        text = text.replace(",", "")                         # US/ISO
    else:  # auto: o último separador encontrado é o decimal
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            if re.match(r"^-?\d{1,3}(,\d{3})+$", text):
                text = text.replace(",", "")                 # 3,000 -> 3000
            else:
                text = text.replace(",", ".")                # 1,5 -> 1.5

    try:
        result = float(text)
    except ValueError:
        return None
    return -abs(result) if negative else result


def to_int(value, decimal_sep: str | None = ".") -> Optional[int]:
    f = to_float(value, decimal_sep)
    return int(round(f)) if f is not None else None


def to_upper(value) -> str:
    return str(value or "").strip().upper()


def to_date(value, dayfirst: bool = True) -> Optional[date]:
    """Parse de data tolerante a dd/mm/aaaa, aaaa-mm-dd e variações.

    dayfirst=True cobre o padrão brasileiro (PAINEL_ATIVAS: '16/10/2026' e
    'dd/mm/aaaa hh:mm:ss'). A aba SELECAO_* usa ISO 'aaaa-mm-dd'.
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
