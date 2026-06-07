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

from app import config, frames, montecarlo, parsing, risk_metrics


def build_vol_map(df_dados: pd.DataFrame | None) -> dict[str, dict]:
    """{ticker: {iv: anual, real: anual}} a partir de DADOS_ATIVOS (anualizado)."""
    if df_dados is None or df_dados.empty:
        return {}
    tickers = [str(t).strip().upper() for t in frames.raw(df_dados, "dados_ativos", "ticker")]
    iv = _clean_list(frames.num(df_dados, "dados_ativos", "iv"))
    garch = _clean_list(frames.num(df_dados, "dados_ativos", "garch_1y"))
    stdv = _clean_list(frames.num(df_dados, "dados_ativos", "stdv_1y"))
    out: dict[str, dict] = {}
    for i, t in enumerate(tickers):
        if not t:
            continue
        # GARCH11_1Y já é vol ANUAL em % (como o IV); STDV_1Y é desvio DIÁRIO.
        real = (montecarlo.anual_from_iv_pct(garch[i]) if garch[i] is not None
                else montecarlo.anual_from_daily(stdv[i]))
        out[t] = {"iv": montecarlo.anual_from_iv_pct(iv[i]), "real": real}
    return out


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
                  "iv_current", "volume_fin", "ve_over_strike", "bid", "ask",
                  "profit_rate", "m9m21_trend"):
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
    g = rec.get("poe_mc_gate")
    if g is not None:
        partes.append(f"PoE {g * 100:.0f}% (Monte Carlo)")
    return " · ".join(partes) if partes else "—"


def _v(series, i):
    """Valor da Series na posição i, com NaN -> None."""
    x = series.iloc[i]
    return None if (isinstance(x, float) and math.isnan(x)) else x


def _isnan(x) -> bool:
    return isinstance(x, float) and math.isnan(x)


def _eh_put(cat) -> bool:
    c = str(cat or "").strip().upper()
    return c.startswith("PUT") or c == "P"


def _mid(bid, ask):
    """Meio do book (bid+ask)/2 — prêmio de referência quando não há CLOSE."""
    if bid and ask and bid > 0 and ask > 0:
        return round((bid + ask) / 2.0, 2)
    return None


def _premio_valido(p, strike) -> bool:
    """Prêmio plausível: positivo e menor que o strike (teto teórico de uma PUT).
    Descarta valores 0/vazios e outliers (ex.: CLOSE 'stale' maior que o strike)."""
    return p is not None and p > 0 and (not strike or p < strike)


def _resolve_premio(close, mid_price, price, bid, ask, strike):
    """Melhor prêmio REAL da linha do scanner + a FONTE usada.
    Ordem de preferência: CLOSE -> MID_PRICE -> PRICE -> meio do book (bid+ask)/2."""
    for valor, fonte in ((close, "CLOSE"), (mid_price, "MID_PRICE"),
                         (price, "PRICE"), (_mid(bid, ask), "BID/ASK")):
        if _premio_valido(valor, strike):
            return round(float(valor), 2), fonte
    return None, None


def _r2(v) -> str:
    """Formata um número com 2 casas em pt-BR (8.0 -> '8,00')."""
    return "—" if v is None else f"{v:.2f}".replace(".", ",")


def scanner_index(df_scanner: "pd.DataFrame | None") -> tuple[dict, dict]:
    """A partir de SCANNER_OPCOES devolve (prem_map, chain).

        prem_map: {OPTION_TICKER: {"close", "bid", "ask"}} — prêmio REAL (CLOSE)
        chain:    {TICKER: [ {strike, premio, opt, dte}, ... ]} — cadeia de PUTs

    A cadeia (todas as PUTs por ativo) é a fonte da perna comprada da Trava.
    """
    prem_map: dict[str, dict] = {}
    chain: dict[str, list] = {}
    if df_scanner is None or df_scanner.empty:
        return prem_map, chain
    opt = frames.raw(df_scanner, "scanner", "option_ticker")
    tkr = frames.txt(df_scanner, "scanner", "ticker")
    cat = frames.txt(df_scanner, "scanner", "category")
    typ = frames.txt(df_scanner, "scanner", "type")
    strike = frames.num(df_scanner, "scanner", "strike")
    close = frames.num(df_scanner, "scanner", "close")
    price = frames.num(df_scanner, "scanner", "price")
    mid_price = frames.num(df_scanner, "scanner", "mid_price")
    bid = frames.num(df_scanner, "scanner", "bid")
    ask = frames.num(df_scanner, "scanner", "ask")
    dte = frames.num(df_scanner, "scanner", "dte")
    for i in range(len(df_scanner)):
        o = str(opt.iloc[i]).strip().upper()
        k = _v(strike, i)
        premio, fonte = _resolve_premio(_v(close, i), _v(mid_price, i), _v(price, i),
                                        _v(bid, i), _v(ask, i), k)
        if o:
            prem_map[o] = {"premio": premio, "fonte": fonte, "close": _v(close, i),
                           "bid": _v(bid, i), "ask": _v(ask, i)}
        if not (_eh_put(cat.iloc[i]) or _eh_put(typ.iloc[i])):
            continue
        t = str(tkr.iloc[i]).strip().upper()
        if t and k:
            chain.setdefault(t, []).append(
                {"strike": k, "premio": premio, "opt": o, "dte": _v(dte, i)})
    return prem_map, chain


def _chain_from_lucros(df_norm: "pd.DataFrame") -> dict:
    """Cadeia de PUTs estimada da aba de lucros (prêmio ≈ VE/strike). Fallback
    quando o SCANNER_OPCOES não traz a perna comprada."""
    chain: dict[str, list] = {}
    puts = df_norm[df_norm["category"] == "PUT"]
    for _, r in puts.iterrows():
        t = str(r.get("ticker") or "").strip().upper()
        k = r.get("strike")
        ve = r.get("ve_over_strike")
        if not t or k is None or _isnan(k):
            continue
        premio = round(ve / 100.0 * k, 2) if (ve is not None and not _isnan(ve)) else None
        chain.setdefault(t, []).append(
            {"strike": k, "premio": premio, "opt": r.get("option_ticker"),
             "dte": (None if _isnan(r.get("dte")) else r.get("dte"))})
    return chain


def _premio_opcao(rec: dict, prem_map: dict) -> tuple[float | None, bool, str]:
    """Prêmio da PUT vendida: valor REAL do scanner, senão estimativa VE/strike.

    Devolve (premio, estimado, fonte). estimado=True => aproximado (rótulo '≈').
    fonte = coluna usada (CLOSE/MID_PRICE/PRICE/BID/ASK) ou 'VE≈' / 'sem match'."""
    o = str(rec.get("option_ticker") or "").strip().upper()
    info = prem_map.get(o)
    if info and info.get("premio"):
        return float(info["premio"]), False, info.get("fonte") or "SCANNER"
    ve, k = rec.get("ve_over_strike"), rec.get("strike")
    if ve is not None and not _isnan(ve) and k:
        return float(round(ve / 100.0 * k, 2)), True, ("VE≈" if o in prem_map else "VE≈ (fora do scanner)")
    return None, True, "sem match"


def _diag_premio(option_ticker, prem_map: dict) -> str:
    """Diz, p/ o log, POR QUE o prêmio caiu na estimativa: opção ausente do
    scanner OU presente mas sem preço válido (mostra close/bid/ask crus)."""
    o = str(option_ticker or "").strip().upper()
    if o not in prem_map:
        return "opção AUSENTE do scanner (vencimento/série não baixados)"
    info = prem_map[o]
    return (f"no scanner, porém sem preço válido — close={info.get('close')}, "
            f"bid={info.get('bid')}, ask={info.get('ask')}")


def _porque_sem_trava(rec: dict, chain: dict, largura_pct: float) -> str:
    """Explica, em português, por que NÃO foi possível montar a Trava (para o log)."""
    t = str(rec.get("ticker") or "").strip().upper()
    ks = rec.get("strike")
    if not rec.get("premio"):
        return "sem prêmio da PUT vendida"
    legs = chain.get(t, [])
    if not legs:
        return f"cadeia de PUTs de {t} ausente no scanner"
    abaixo = [c for c in legs if c.get("strike") and c["strike"] < ks]
    if not abaixo:
        return f"nenhuma PUT com strike < {ks:g} na cadeia"
    com_premio = [c for c in abaixo if c.get("premio") is not None]
    if not com_premio:
        return "pernas de proteção sem prêmio (preço vazio no scanner)"
    dte = rec.get("dte")
    mesmo_venc = [c for c in com_premio
                  if dte is None or c.get("dte") is None or abs(c["dte"] - dte) <= 3]
    if not mesmo_venc:
        return "perna de proteção só existe em outro vencimento"
    return "crédito ou largura não positivos"


def _build_trava(rec: dict, chain: dict, largura_pct: float) -> dict | None:
    """Monta a Trava de Alta com PUT (Bull Put Spread): VENDE a PUT da
    oportunidade e COMPRA uma PUT mais OTM (~largura_pct abaixo) para LIMITAR o
    risco. Escolhe, na cadeia do ativo, o strike disponível mais próximo do alvo
    e estritamente abaixo do strike vendido. None se não houver perna comprada."""
    t = str(rec.get("ticker") or "").strip().upper()
    ks = rec.get("strike")
    premio_short = rec.get("premio")
    if not (t and ks and premio_short):
        return None
    dte = rec.get("dte")
    alvo = ks * (1.0 - largura_pct)
    cand = [c for c in chain.get(t, [])
            if c.get("strike") and c["strike"] < ks and c.get("premio") is not None
            and (dte is None or c.get("dte") is None or abs(c["dte"] - dte) <= 3)]
    if not cand:
        return None
    long_leg = min(cand, key=lambda c: abs(c["strike"] - alvo))
    ks_long, premio_long = float(long_leg["strike"]), float(long_leg["premio"])
    largura = round(float(ks) - ks_long, 2)
    credito = round(float(premio_short) - premio_long, 2)
    if largura <= 0 or credito <= 0:
        return None
    risco_max = round(largura - credito, 2)
    return {
        "sell_strike": float(ks), "sell_premio": float(premio_short), "sell_opt": rec.get("option_ticker"),
        "buy_strike": ks_long, "buy_premio": premio_long, "buy_opt": long_leg.get("opt"),
        "largura": largura, "credito": credito, "risco_max": risco_max,
        "retorno_risco": (round(credito / risco_max, 4) if risco_max > 0 else None),
        "estimado": bool(rec.get("premio_estimado", False)),
    }


def analise(o: dict) -> str:
    """Recomendação textual gerada pelo MOTOR (vai ao e-mail e ao painel)."""
    tk = o.get("ticker", "")
    tr = o.get("trava")
    if tr:
        aprox = "≈ " if o.get("premio_estimado") else ""
        base = (f"Trava de ALTA com PUT em {tk}: vender PUT strike R$ {_r2(tr['sell_strike'])} "
                f"e comprar PUT strike R$ {_r2(tr['buy_strike'])} — crédito {aprox}R$ "
                f"{_r2(tr['credito'])}/ação, risco limitado a R$ {_r2(tr['risco_max'])}/ação")
    else:
        base = f"Vender PUT de {tk}"
        if o.get("strike") is not None:
            base += f" no strike R$ {_r2(o['strike'])}"
        if o.get("premio"):
            aprox = "≈ " if o.get("premio_estimado") else ""
            base += f" (prêmio {aprox}R$ {_r2(o['premio'])}/ação)"
    m = o.get("motivo")
    return base + "." + ((" " + m) if (m and m != "—") else "")


def scan(
    df_lucros: pd.DataFrame,
    df_volumes: pd.DataFrame | None = None,
    df_dados_ativos: pd.DataFrame | None = None,
    cfg: config.RadarCfg | None = None,
    audit: dict | None = None,
    mc: "montecarlo.MonteCarloSimulator | None" = None,
    vol_map: dict | None = None,
    poe_max: float | None = None,
    df_scanner: pd.DataFrame | None = None,
) -> list[dict]:
    """Aplica filtros e devolve as Top-N oportunidades de venda de PUT.

    Se `audit` (dict) for passado, é preenchido com o FUNIL (quantas opções
    sobreviveram a cada filtro) para registro na auditoria.

    `df_scanner` (SCANNER_OPCOES) traz o prêmio REAL (CLOSE) de cada opção e a
    cadeia completa de PUTs — fonte da perna comprada da Trava de Alta.
    """
    cfg = cfg or config.RADAR
    if df_lucros is None or df_lucros.empty:
        if audit is not None:
            audit.update({"total": 0})
        return []

    df = _normalize(df_lucros)

    # Prêmios (CLOSE) e cadeia de PUTs: SCANNER tem precedência por ativo; onde
    # faltar, cai para a estimativa (VE/strike) da própria aba de lucros.
    prem_map, chain = scanner_index(df_scanner)
    for t, legs in _chain_from_lucros(df).items():
        chain.setdefault(t, legs)

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

    # Filtro Monte Carlo: só mantém PUT com prob. de exercício <= poe_max.
    if mc is not None and vol_map and not df.empty:
        gates, ivs, reals = [], [], []
        for _, r in df.iterrows():
            vm = vol_map.get(str(r["ticker"]).strip().upper(), {})
            res = montecarlo.poe_resumo(mc, r["spot"], r["strike"], r["dte"], vm.get("iv"), vm.get("real"))
            gates.append(res["poe_mc_gate"])
            ivs.append(res["poe_mc_iv"])
            reals.append(res["poe_mc_real"])
        df["poe_mc_gate"] = pd.to_numeric(gates, errors="coerce")
        df["poe_mc_iv"] = pd.to_numeric(ivs, errors="coerce")
        df["poe_mc_real"] = pd.to_numeric(reals, errors="coerce")
        if audit is not None:
            validos = [g for g in gates if g is not None]
            audit["poe_min"] = round(min(validos), 4) if validos else None
        if poe_max is not None:
            df = df[df["poe_mc_gate"].isna() | (df["poe_mc_gate"] <= poe_max)]
        if audit is not None:
            audit["apos_montecarlo"] = int(len(df))

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
        rec["premio"], rec["premio_estimado"], rec["premio_fonte"] = _premio_opcao(rec, prem_map)
        if rec["premio_estimado"]:
            rec["premio_diag"] = _diag_premio(rec.get("option_ticker"), prem_map)
        if cfg.usar_trava:
            rec["trava"] = _build_trava(rec, chain, cfg.trava_largura_pct)
            if rec["trava"] is None:
                rec["trava_motivo"] = _porque_sem_trava(rec, chain, cfg.trava_largura_pct)
        rec["analise"] = analise(rec)

    if audit is not None:
        audit["scanner_opcoes"] = len(prem_map)
        audit["scanner_puts_na_cadeia"] = sum(len(v) for v in chain.values())
        audit["premios_reais"] = sum(1 for r in records if not r.get("premio_estimado"))
        audit["premios_estimados"] = sum(1 for r in records if r.get("premio_estimado"))
        audit["travas_montadas"] = sum(1 for r in records if r.get("trava"))
        audit["oportunidades"] = [_audit_opp(r) for r in records]

    # Sugestão de sizing (nº de contratos p/ arriscar RISK_PER_TRADE do capital).
    # Proxy de margem para PUT cash-secured: strike * 100 (tamanho do lote).
    if config.CAPITAL_DISPONIVEL > 0:
        for rec in records:
            strike = rec.get("strike")
            if strike:
                rec["contratos_sugeridos"] = risk_metrics.tamanho_posicao(
                    config.CAPITAL_DISPONIVEL, strike * 100, config.RISK_PER_TRADE)
    return records


def _audit_opp(r: dict) -> dict:
    """Linha de auditoria (didática) de uma oportunidade, p/ o log detalhado."""
    tr = r.get("trava")
    if tr:
        trava_txt = (f"vende PUT {tr['sell_strike']:g}@{tr['sell_premio']:g} + "
                     f"compra PUT {tr['buy_strike']:g}@{tr['buy_premio']:g} "
                     f"(crédito {tr['credito']:g}, risco {tr['risco_max']:g})")
    else:
        trava_txt = f"SEM trava — {r.get('trava_motivo', '—')}"
    return {
        "opcao": r.get("option_ticker"), "ticker": r.get("ticker"),
        "strike": r.get("strike"), "dte": r.get("dte"),
        "premio": r.get("premio"), "fonte_premio": r.get("premio_fonte"),
        "estimado": bool(r.get("premio_estimado")), "diag_premio": r.get("premio_diag"),
        "iv_rank": r.get("iv_rank"), "poe_mc": r.get("poe_mc_gate"),
        "trava": trava_txt,
    }


def _to_record(row: pd.Series) -> dict:
    def clean(v):
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    return {k: clean(v) for k, v in row.to_dict().items()}
