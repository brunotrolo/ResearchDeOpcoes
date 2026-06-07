"""Módulo 2 — RADAR (prospecção de prêmios).

Lê SELECAO_OPCOES_MAIORES_LUCROS e aplica os filtros do Bruno via Pandas:

    - CATEGORY == PUT
    - IV_RANK >= 50            (pânico / prêmio gordo)
    - SPOT_STRIKE_RATIO >= 1.02 (OTM com margem de segurança)
    - DTE entre 21 e 45 dias    (sweet spot de theta sem gamma de vencimento)
    - Liquidez: VOLUME_FIN da opção > piso  E  (opcional) volume do ativo-mãe
      (SELECAO_MAIORES_VOLUMES) acima do piso  E  (opcional) spread bid-ask
      relativo <= limite — evita book vazio.

Cruzamentos opcionais:
    - RANKING_TENDENCIA_M9M21: exigir tendência de alta da ação-mãe.
    - DADOS_ATIVOS: restringir ao universo monitorado.

Saída: Top-N oportunidades (dicts), ranqueadas por taxa de retorno e IV Rank.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from app import config, frames, parsing, risk_metrics


def _fmt_expiry(raw) -> str:
    """A aba de lucros traz EXPIRY como número serial do Sheets — converte p/ data."""
    n = parsing.to_float(raw, ",")
    if n is not None and n > 40000:
        return (date(1899, 12, 30) + timedelta(days=int(n))).strftime("%d/%m/%Y")
    return str(raw or "")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for field in ("option_ticker", "ticker", "sector", "company", "expiry"):
        out[field] = frames.raw(df, "lucros", field)
    out["category"] = frames.txt(df, "lucros", "category")
    for field in ("dte", "strike", "spot", "spot_strike_ratio", "iv_rank",
                  "iv_current", "volume_fin", "bid", "ask", "profit_rate", "m9m21_trend"):
        out[field] = frames.num(df, "lucros", field)
    return out


def _underlying_volume(df_volumes: pd.DataFrame) -> dict[str, float]:
    if df_volumes is None or df_volumes.empty:
        return {}
    tickers = frames.raw(df_volumes, "volumes", "ticker")
    totals = frames.num(df_volumes, "volumes", "volume_total")
    return {t: v for t, v in zip(tickers, totals) if t}


def _whitelist(df_dados: pd.DataFrame, require_has_options: bool = True) -> set[str]:
    """Universo monitorado da aba DADOS_ATIVOS (opcionalmente só com opções)."""
    if df_dados is None or df_dados.empty:
        return set()
    tickers = frames.raw(df_dados, "dados_ativos", "ticker")
    has_opts = frames.txt(df_dados, "dados_ativos", "has_options")  # "TRUE"/"FALSE"
    allowed: set[str] = set()
    for tkr, ho in zip(tickers, has_opts):
        if not tkr:
            continue
        if require_has_options and ho not in {"TRUE", "1", "SIM", "VERDADEIRO", ""}:
            continue
        allowed.add(tkr)
    return allowed


def _clean_list(series) -> list:
    return [None if (isinstance(x, float) and math.isnan(x)) else x for x in series.tolist()]


def _underlying_signals(df_dados: pd.DataFrame | None) -> dict[str, dict]:
    """Sinais por ativo-mãe (tendência, score, IV) de DADOS_ATIVOS — o 'porquê'."""
    if df_dados is None or df_dados.empty:
        return {}
    tickers = [str(t).strip().upper() for t in frames.raw(df_dados, "dados_ativos", "ticker")]
    cols = {k: _clean_list(frames.num(df_dados, "dados_ativos", k))
            for k in ("m9m21_trend", "middle_term_trend", "short_term_trend",
                      "oplab_score", "iv_rank", "correl_ibov")}
    out: dict[str, dict] = {}
    for i, t in enumerate(tickers):
        if t:
            out[t] = {k: cols[k][i] for k in cols}
    return out


def _motivo_radar(rec: dict) -> str:
    """Texto curto explicando POR QUE o ativo foi recomendado."""
    partes = []
    t = rec.get("m9m21_trend")
    if t == 1:
        partes.append("Tendência de ALTA (M9>M21)")
    elif t == -1:
        partes.append("Tendência de baixa (M9<M21)")
    if rec.get("short_term_trend") == 1 and rec.get("middle_term_trend") == 1:
        partes.append("alta no curto e médio prazo")
    iv = rec.get("iv_rank")
    if iv is not None:
        partes.append(f"IV Rank {iv:.0f} ({'prêmio gordo' if iv >= 70 else 'prêmio ok'})")
    d = rec.get("dist_pct")
    if d is not None:
        partes.append(f"spot {d:+.1f}% do strike (margem)")
    sc = rec.get("oplab_score")
    if sc is not None:
        partes.append(f"Score OpLab {sc:.0f}")
    return " · ".join(partes) if partes else "—"


def scan(
    df_lucros: pd.DataFrame,
    df_volumes: pd.DataFrame | None = None,
    df_dados_ativos: pd.DataFrame | None = None,
    cfg: config.RadarCfg | None = None,
    audit: dict | None = None,
) -> list[dict]:
    """Aplica filtros e devolve as Top-N oportunidades de venda de PUT.

    Se `audit` (dict) for passado, é preenchido com o FUNIL (quantas opções
    sobreviveram a cada filtro) para registro na auditoria.
    """
    cfg = cfg or config.RADAR
    if df_lucros is None or df_lucros.empty:
        if audit is not None:
            audit.update({"total": 0})
        return []

    df = _normalize(df_lucros)

    # Máscaras cumulativas, para registrar o funil estágio a estágio.
    m_put = df["category"] == cfg.option_type.upper()
    m_iv = m_put & (df["iv_rank"] >= cfg.iv_rank_min)
    m_ratio = m_iv & (df["spot_strike_ratio"] >= cfg.spot_strike_ratio_min)
    m_vol = m_ratio & (df["volume_fin"].fillna(0) >= cfg.min_option_volume_fin)
    m_dte = m_vol & (df["dte"] >= cfg.dte_min) & (df["dte"] <= cfg.dte_max)
    mask = m_dte
    if cfg.require_trend_up:
        mask = mask & (df["m9m21_trend"] == 1)

    if audit is not None:
        audit.update({
            "total": int(len(df)),
            "put": int(m_put.sum()),
            "iv_rank_ok": int(m_iv.sum()),
            "ratio_ok": int(m_ratio.sum()),
            "volume_ok": int(m_vol.sum()),
            "dte_ok": int(m_dte.sum()),
            "apos_tendencia": int(mask.sum()),
            "filtros": {"iv_rank_min": cfg.iv_rank_min, "ratio_min": cfg.spot_strike_ratio_min,
                        "dte_min": cfg.dte_min, "dte_max": cfg.dte_max},
        })

    df = df[mask].copy()

    # Filtro de spread bid-ask por opção (liquidez fina) — só se habilitado e
    # houver BID/ASK na aba de lucros (ex.: espelhando o SCANNER_OPCOES).
    if cfg.use_spread_filter and df["ask"].notna().any():
        spread = df.apply(lambda r: risk_metrics.relative_spread(r["bid"], r["ask"]), axis=1)
        df = df[(df["bid"].fillna(0) > 0) & (spread.fillna(1.0) <= cfg.bid_ask_spread_max)]

    # Liquidez do ativo-mãe (piso opcional)
    if cfg.min_underlying_volume > 0:
        vol_map = _underlying_volume(df_volumes)
        df["underlying_volume"] = df["ticker"].map(lambda t: vol_map.get(t, 0.0))
        df = df[df["underlying_volume"] >= cfg.min_underlying_volume]
    else:
        df["underlying_volume"] = df["ticker"].map(
            lambda t: _underlying_volume(df_volumes).get(t) if df_volumes is not None else None
        )

    # Universo monitorado (DADOS_ATIVOS) — só ativos com opções, por padrão
    if cfg.use_dados_ativos_whitelist:
        allowed = _whitelist(df_dados_ativos, cfg.require_has_options)
        if allowed:
            df = df[df["ticker"].isin(allowed)]

    if audit is not None:
        audit["apos_filtros"] = int(len(df))

    if df.empty:
        if audit is not None:
            audit["final"] = 0
        return []

    df = df.sort_values(
        by=["profit_rate", "iv_rank"], ascending=[False, False], na_position="last"
    ).head(cfg.top_n)

    records = [_to_record(r) for _, r in df.iterrows()]
    if audit is not None:
        audit["final"] = len(records)

    # Enriquece cada oportunidade com distância e sinais do ativo-mãe (o "porquê").
    sig = _underlying_signals(df_dados_ativos)
    for rec in records:
        spot, strike = rec.get("spot"), rec.get("strike")
        rec["dist_pct"] = ((spot / strike - 1) * 100) if (spot and strike) else None
        rec["expiry_fmt"] = _fmt_expiry(rec.get("expiry"))
        rec.update(sig.get(str(rec.get("ticker", "")).strip().upper(), {}))
        rec["motivo"] = _motivo_radar(rec)

    # Sugestão de sizing (nº de contratos p/ arriscar RISK_PER_TRADE do capital).
    # Proxy de margem para PUT cash-secured: strike * 100 (tamanho do lote).
    if config.CAPITAL_DISPONIVEL > 0:
        for rec in records:
            strike = rec.get("strike")
            if strike:
                rec["contratos_sugeridos"] = risk_metrics.tamanho_posicao(
                    config.CAPITAL_DISPONIVEL, strike * 100, config.RISK_PER_TRADE)
    return records


def _to_record(row: pd.Series) -> dict:
    def clean(v):
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    return {k: clean(v) for k, v in row.to_dict().items()}
