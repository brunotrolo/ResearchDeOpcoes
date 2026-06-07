"""Helpers para acessar DataFrames pelo nome LÓGICO da coluna (via COLUMN_MAP).

Isola o acoplamento ao schema das abas: se um cabeçalho real mudar, basta
ajustar config.COLUMN_MAP — os módulos de negócio continuam falando em
"iv_rank", "delta", "spot_strike_ratio", etc.
"""
from __future__ import annotations

import pandas as pd

from app import config, parsing


def actual_col(table: str, field: str) -> str | None:
    return config.COLUMN_MAP.get(table, {}).get(field)


def _decimal_sep(table: str) -> str:
    spec = config.TABS.get(table)
    return spec.decimal_sep if spec else "."


def num(df: pd.DataFrame, table: str, field: str) -> pd.Series:
    """Série numérica (float) parseada com o locale decimal da aba; NaN se vazio."""
    col = actual_col(table, field)
    if col is None or col not in df.columns:
        return pd.Series([float("nan")] * len(df), index=df.index, dtype="float64")
    sep = _decimal_sep(table)
    return pd.to_numeric(df[col].map(lambda v: parsing.to_float(v, sep)), errors="coerce")


def txt(df: pd.DataFrame, table: str, field: str) -> pd.Series:
    """Série de texto normalizada (strip + upper)."""
    col = actual_col(table, field)
    if col is None or col not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[col].astype(str).str.strip().str.upper()


def raw(df: pd.DataFrame, table: str, field: str) -> pd.Series:
    col = actual_col(table, field)
    if col is None or col not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[col].astype(str).str.strip()
