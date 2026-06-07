"""Módulo 2 — RADAR (prospecção de prêmios).

Lê SELECAO_OPCOES_MAIORES_LUCROS e aplica os filtros do Bruno via Pandas:

    - CATEGORY == PUT
    - IV_RANK >= 50            (pânico / prêmio gordo)
    - SPOT_STRIKE_RATIO >= 1.02 (OTM com margem de segurança)
    - Liquidez: VOLUME_FIN da opção > piso  E  (opcional) volume do ativo-mãe
      (SELECAO_MAIORES_VOLUMES) acima do piso — evita book vazio.

Cruzamentos opcionais:
    - RANKING_TENDENCIA_M9M21: exigir tendência de alta da ação-mãe.
    - DADOS_ATIVOS: restringir ao universo monitorado.

Saída: Top-N oportunidades (dicts), ranqueadas por taxa de retorno e IV Rank.
"""
from __future__ import annotations

import math

import pandas as pd

from app import config, frames


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for field in ("option_ticker", "ticker", "sector", "company", "expiry"):
        out[field] = frames.raw(df, "lucros", field)
    out["category"] = frames.txt(df, "lucros", "category")
    for field in ("dte", "strike", "spot", "spot_strike_ratio", "iv_rank",
                  "iv_current", "volume_fin", "profit_rate", "m9m21_trend"):
        out[field] = frames.num(df, "lucros", field)
    return out


def _underlying_volume(df_volumes: pd.DataFrame) -> dict[str, float]:
    if df_volumes is None or df_volumes.empty:
        return {}
    tickers = frames.raw(df_volumes, "volumes", "ticker")
    totals = frames.num(df_volumes, "volumes", "volume_total")
    return {t: v for t, v in zip(tickers, totals) if t}


def _whitelist(df_dados: pd.DataFrame) -> set[str]:
    if df_dados is None or df_dados.empty:
        return set()
    return set(t for t in frames.raw(df_dados, "dados_ativos", "ticker") if t)


def scan(
    df_lucros: pd.DataFrame,
    df_volumes: pd.DataFrame | None = None,
    df_dados_ativos: pd.DataFrame | None = None,
    cfg: config.RadarCfg | None = None,
) -> list[dict]:
    """Aplica filtros e devolve as Top-N oportunidades de venda de PUT."""
    cfg = cfg or config.RADAR
    if df_lucros is None or df_lucros.empty:
        return []

    df = _normalize(df_lucros)

    mask = (
        (df["category"] == cfg.option_type.upper())
        & (df["iv_rank"] >= cfg.iv_rank_min)
        & (df["spot_strike_ratio"] >= cfg.spot_strike_ratio_min)
        & (df["volume_fin"].fillna(0) >= cfg.min_option_volume_fin)
    )
    if cfg.require_trend_up:
        mask &= (df["m9m21_trend"] == 1)

    df = df[mask].copy()

    # Liquidez do ativo-mãe (piso opcional)
    if cfg.min_underlying_volume > 0:
        vol_map = _underlying_volume(df_volumes)
        df["underlying_volume"] = df["ticker"].map(lambda t: vol_map.get(t, 0.0))
        df = df[df["underlying_volume"] >= cfg.min_underlying_volume]
    else:
        df["underlying_volume"] = df["ticker"].map(
            lambda t: _underlying_volume(df_volumes).get(t) if df_volumes is not None else None
        )

    # Universo monitorado (opcional)
    if cfg.use_dados_ativos_whitelist:
        allowed = _whitelist(df_dados_ativos)
        if allowed:
            df = df[df["ticker"].isin(allowed)]

    if df.empty:
        return []

    df = df.sort_values(
        by=["profit_rate", "iv_rank"], ascending=[False, False], na_position="last"
    ).head(cfg.top_n)

    return [_to_record(r) for _, r in df.iterrows()]


def _to_record(row: pd.Series) -> dict:
    def clean(v):
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    return {k: clean(v) for k, v in row.to_dict().items()}
