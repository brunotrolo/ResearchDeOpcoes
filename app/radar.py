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


def build_trend_map(df_dados: "pd.DataFrame | None") -> dict[str, int]:
    """{ticker: M9M21_TREND} (1 alta, -1 baixa) de DADOS_ATIVOS — usado pelo Escudo
    para o cenário de continuação da tendência no Monte Carlo."""
    if df_dados is None or df_dados.empty:
        return {}
    tickers = [str(t).strip().upper() for t in frames.raw(df_dados, "dados_ativos", "ticker")]
    trend = _clean_list(frames.num(df_dados, "dados_ativos", "m9m21_trend"))
    return {t: int(trend[i]) for i, t in enumerate(tickers)
            if t and trend[i] is not None and trend[i] in (1, -1)}


def _fmt_expiry(raw) -> str:
    """A aba de lucros/scanner traz EXPIRY como número serial do Sheets — converte
    p/ data. Detecta o separador automaticamente (a planilha pode vir em pt-BR ou
    US) e só converte dentro de uma faixa plausível de serial (~2009 a 2064);
    fora dela devolve o texto cru, evitando overflow de data (o Sheets exporta o
    serial COM fração de tempo, ex.: '46192.5833', que mal-parseado estoura)."""
    n = parsing.to_float(raw, "auto")
    if n is not None and 40000 < n < 60000:
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


# --- Tendência multi-horizonte: não vender PUT em ticker baixista -----------
# Rótulos legíveis (web app/e-mail) para cada classificação.
TREND_LABELS_PT = {
    "ALTA": "ALTA confirmada", "NEUTRO": "Neutro",
    "REPIQUE_BAIXA": "Repique em tendência de baixa", "BAIXA": "Tendência de BAIXA",
}


def _as_sign(v) -> int:
    """Normaliza um sinal de tendência para {1, -1, 0}; desconhecido/NaN -> 0."""
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return 0
    return 1 if n > 0 else (-1 if n < 0 else 0)


def trend_score_label(short_term, middle_term, m9m21) -> dict:
    """Combina os 3 horizontes (curto, médio, M9/M21) num score [-3..+3] e num
    rótulo honesto. Médio em baixa OU ≥2 de 3 em baixa = BAIXA; curto↑ com médio↓
    = REPIQUE_BAIXA (faca caindo com repique — o caso que o gate binário M9/M21 não
    pega). É a base do bloqueio de entradas em ativo baixista."""
    s, m, l = _as_sign(short_term), _as_sign(middle_term), _as_sign(m9m21)
    score = s + m + l
    n_baixa = sum(1 for v in (s, m, l) if v == -1)
    n_alta = sum(1 for v in (s, m, l) if v == 1)
    if m == -1 and s == 1:
        label = "REPIQUE_BAIXA"
    elif n_baixa >= 2 or m == -1:
        label = "BAIXA"
    elif n_alta >= 2 and m != -1:
        label = "ALTA"
    else:
        label = "NEUTRO"
    return {"trend_score": score, "trend_label": label}


def _trend_blocks(label, m9m21, level: str) -> bool:
    """Decide se a oportunidade é BLOQUEADA pelo gate de tendência (entrada).
    `off` = legado (só M9<M21); `medio` (padrão) = bloqueia BAIXA/REPIQUE/M9<M21;
    `estrito` = só passa ALTA confirmada."""
    l = _as_sign(m9m21)
    if level == "off":
        return l == -1
    if level == "estrito":
        return label != "ALTA"
    return label in ("BAIXA", "REPIQUE_BAIXA") or l == -1   # 'medio'


def _entry_trend_drift(m9m21, sigma_gate):
    """Drift de continuação da tendência p/ a PoE de entrada (sinal M9/M21 × σ).
    None quando não há tendência definida ou vol — aí não há cenário a simular."""
    l = _as_sign(m9m21)
    if l == 0 or not sigma_gate:
        return None
    return l * float(sigma_gate)


def _aplica_gate_tendencia(df, cfg, base_mask, audit):
    """Aplica o gate de tendência multi-horizonte sobre `base_mask` (que já passou
    pelos filtros anteriores). Bloqueia entradas em ticker baixista conforme
    RADAR_TREND_GATE e registra no funil quantas (e por qual rótulo) caíram.

    Mantém a compatibilidade: o gate só age quando alguma trava altista está ligada
    (`require_trend_up`/`evitar_tendencia_baixa`/`usar_trava`); com tudo desligado, a
    baixa entra (com aviso direcional), como antes."""
    gate_ativo = cfg.require_trend_up or cfg.evitar_tendencia_baixa or cfg.usar_trava
    mask = base_mask
    bloqueadas, rotulos = 0, {}
    if gate_ativo:
        if cfg.require_trend_up:
            novo = mask & (df["m9m21_trend"] == 1)
        else:
            level = getattr(cfg, "trend_gate", "medio")
            blk = df.apply(lambda r: _trend_blocks(r.get("trend_label"),
                                                   r.get("m9m21_trend"), level), axis=1)
            novo = mask & ~blk
        caiu = mask & ~novo
        bloqueadas = int(caiu.sum())
        if bloqueadas:
            rotulos = df.loc[caiu, "trend_label"].value_counts().to_dict()
        mask = novo
    if audit is not None:
        audit["apos_tendencia"] = int(mask.sum())
        audit["tendencia_bloqueadas"] = bloqueadas
        audit["tendencia_rotulos"] = rotulos
        audit["trend_gate"] = (getattr(cfg, "trend_gate", "medio") if gate_ativo else "off")
    return mask


def _set_trend_cols(df) -> None:
    """Calcula trend_label/trend_score por linha a partir dos 3 horizontes já no df."""
    if df.empty:
        df["trend_label"] = pd.Series(dtype=object)
        df["trend_score"] = pd.Series(dtype=object)
        return
    tl = df.apply(lambda r: trend_score_label(r.get("short_term_trend"),
                                              r.get("middle_term_trend"),
                                              r.get("m9m21_trend")), axis=1)
    df["trend_label"] = [d["trend_label"] for d in tl]
    df["trend_score"] = [d["trend_score"] for d in tl]


def _rec_bloqueado_tendencia(rec: dict, cfg) -> bool:
    """Decisão FINAL de bloqueio sobre o MESMO rótulo que vai aparecer no card —
    garante que o que é exibido nunca contradiz o gate (inclusão == display)."""
    if not (cfg.require_trend_up or cfg.evitar_tendencia_baixa or cfg.usar_trava):
        return False
    if cfg.require_trend_up:
        return rec.get("m9m21_trend") != 1
    return _trend_blocks(rec.get("trend_label"), rec.get("m9m21_trend"),
                         getattr(cfg, "trend_gate", "medio"))


def _guarda_final_tendencia(records: list, cfg, audit) -> list:
    """Rede de segurança: descarta QUALQUER oportunidade cujo RÓTULO FINAL (o do
    card) seja baixista. Fecha divergências entre o gate (sobre o df) e o rótulo
    recomputado no rec — ex.: M9M21 da aba de lucros ≠ do DADOS_ATIVOS — para nunca
    recomendar 'Trava de ALTA' num ticker exibido como BAIXA."""
    mantidos, cortados = [], []
    for r in records:
        (cortados if _rec_bloqueado_tendencia(r, cfg) else mantidos).append(r)
    if cortados and audit is not None:
        audit["tendencia_bloqueadas"] = audit.get("tendencia_bloqueadas", 0) + len(cortados)
        rot = dict(audit.get("tendencia_rotulos") or {})
        for r in cortados:
            lab = r.get("trend_label") or "?"
            rot[lab] = rot.get(lab, 0) + 1
        audit["tendencia_rotulos"] = rot
    return mantidos


def _motivo_radar(rec: dict) -> str:
    """Texto curto explicando POR QUE o ativo foi recomendado."""
    partes = []
    rotulo = rec.get("trend_label")
    if rotulo == "ALTA":
        partes.append("Tendência de ALTA confirmada")
    elif rotulo in ("BAIXA", "REPIQUE_BAIXA"):
        partes.append(TREND_LABELS_PT[rotulo])
    elif rec.get("m9m21_trend") == 1:
        partes.append("Tendência de ALTA (M9>M21)")
    elif rec.get("m9m21_trend") == -1:
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
        partes.append(f"PoE {g * 100:.0f}% ({rec.get('poe_fonte', 'Monte Carlo')})")
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


def _iv_rank_map(df_dados: pd.DataFrame | None) -> dict[str, float]:
    """{TICKER: IV_RANK} de DADOS_ATIVOS — o scanner traz IV_CALC (vol implícita
    da opção), não o IV RANK (percentil do ano). Cruzamos pelo ativo-mãe."""
    if df_dados is None or df_dados.empty:
        return {}
    tickers = [str(t).strip().upper() for t in frames.raw(df_dados, "dados_ativos", "ticker")]
    iv = _clean_list(frames.num(df_dados, "dados_ativos", "iv_rank"))
    return {t: iv[i] for i, t in enumerate(tickers) if t and iv[i] is not None}


def _normalize_scanner(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza SCANNER_OPCOES para o schema do Radar. O prêmio é SEMPRE o
    valor REAL da planilha (CLOSE -> MID_PRICE -> PRICE -> meio do book), nunca
    estimado. Também marca se a linha é PUT (por CATEGORY ou TYPE) e calcula a
    distância spot/strike e a taxa de retorno (prêmio/strike)."""
    out = pd.DataFrame(index=df.index)
    out["option_ticker"] = frames.raw(df, "scanner", "option_ticker")
    out["ticker"] = frames.txt(df, "scanner", "ticker")
    out["category"] = frames.txt(df, "scanner", "category")
    out["type"] = frames.txt(df, "scanner", "type")
    out["moneyness"] = frames.txt(df, "scanner", "moneyness")
    out["expiry"] = frames.raw(df, "scanner", "expiry")
    for field in ("strike", "spot", "close", "price", "mid_price", "bid", "ask",
                  "dte", "poe", "iv_calc", "moneyness_ratio", "return_on_strike",
                  "volume_fin", "delta"):
        out[field] = frames.num(df, "scanner", field)

    # É PUT? (CATEGORY ou TYPE — exportações preenchem ora um, ora outro.)
    out["eh_put"] = [_eh_put(c) or _eh_put(t)
                     for c, t in zip(out["category"], out["type"])]

    # Prêmio REAL + fonte, linha a linha (mesmo critério da scanner_index).
    prem, fonte = [], []
    for i in range(len(out)):
        p, f = _resolve_premio(_v(out["close"], i), _v(out["mid_price"], i),
                               _v(out["price"], i), _v(out["bid"], i),
                               _v(out["ask"], i), _v(out["strike"], i))
        prem.append(p)
        fonte.append(f)
    out["premio"] = prem
    out["premio_fonte"] = fonte

    # Distância spot/strike: usa SPOT/STRIKE reais; cai no MONEYNESS_RATIO.
    ratio = out["spot"] / out["strike"]
    out["spot_strike_ratio"] = ratio.where(
        ratio.notna() & (out["strike"] > 0), out["moneyness_ratio"])

    # Taxa de retorno da venda = prêmio / strike (%).
    def _rate(p, k):
        return round(float(p) / float(k) * 100, 2) if (p and k and not _isnan(k)) else None
    out["profit_rate"] = [_rate(p, k) for p, k in zip(out["premio"], out["strike"])]
    return out


def scan_scanner(
    df_scanner: pd.DataFrame,
    df_dados_ativos: pd.DataFrame | None = None,
    cfg: config.RadarCfg | None = None,
    audit: dict | None = None,
    mc: "montecarlo.MonteCarloSimulator | None" = None,
    vol_map: dict | None = None,
    poe_max: float | None = None,
) -> list[dict]:
    """RADAR lendo DIRETO do SCANNER_OPCOES — o prêmio é SEMPRE o CLOSE real da
    planilha e a Trava de Alta usa pernas do MESMO vencimento (mesma cadeia).

    Mantém os filtros do Bruno (PUT, IV Rank, distância OTM, liquidez, DTE,
    Monte Carlo) e devolve as Top-N oportunidades já com a Trava montada. O
    `audit` recebe o funil estágio a estágio (incl. os DTEs disponíveis no
    scanner — útil quando a janela de DTE não bate com o que foi baixado)."""
    cfg = cfg or config.RADAR
    if df_scanner is None or df_scanner.empty:
        if audit is not None:
            audit.update({"fonte": "scanner", "total": 0, "final": 0})
        return []

    df = _normalize_scanner(df_scanner)
    _, chain = scanner_index(df_scanner)
    sig = _underlying_signals(df_dados_ativos)
    iv_rank = _iv_rank_map(df_dados_ativos)
    df["iv_rank"] = pd.to_numeric(
        df["ticker"].map(lambda t: iv_rank.get(str(t).strip().upper())), errors="coerce")
    # Tendência da ação-mãe em 3 horizontes (curto/médio/M9M21) + score OpLab — base
    # do gate que BLOQUEIA entrada em ticker baixista (não vender PUT na queda).
    for campo in ("m9m21_trend", "short_term_trend", "middle_term_trend", "oplab_score"):
        df[campo] = df["ticker"].map(
            lambda t, c=campo: (sig.get(str(t).strip().upper()) or {}).get(c))
    _set_trend_cols(df)

    premio_ok = df["premio"].map(lambda p: _premio_valido(p, None))

    # Máscaras cumulativas (mesma didática do scan da aba de lucros).
    m_put = df["eh_put"].astype(bool)
    m_prem = m_put & premio_ok
    # IV Rank é "nice to have": onde o ativo não está em DADOS_ATIVOS, não barra.
    m_iv = m_prem & ((df["iv_rank"] >= cfg.iv_rank_min) | df["iv_rank"].isna())
    m_ratio = m_iv & (df["spot_strike_ratio"] >= cfg.spot_strike_ratio_min)
    m_vol = m_ratio & (df["volume_fin"].fillna(0) >= cfg.min_option_volume_fin)
    m_dte = m_vol & (df["dte"] >= cfg.dte_min) & (df["dte"] <= cfg.dte_max)

    if audit is not None:
        dtes = sorted({int(d) for d in df.loc[m_prem, "dte"].dropna().tolist()})
        audit.update({
            "fonte": "scanner",
            "total": int(len(df)),
            "put": int(m_put.sum()),
            "premio_ok": int(m_prem.sum()),
            "iv_rank_ok": int(m_iv.sum()),
            "ratio_ok": int(m_ratio.sum()),
            "volume_ok": int(m_vol.sum()),
            "dte_ok": int(m_dte.sum()),
            "dtes_disponiveis": dtes,
            "filtros": {"iv_rank_min": cfg.iv_rank_min, "ratio_min": cfg.spot_strike_ratio_min,
                        "dte_min": cfg.dte_min, "dte_max": cfg.dte_max,
                        "max_por_ativo": cfg.max_por_ativo, "poe_max": poe_max},
        })

    # Gate de tendência multi-horizonte: bloqueia entradas baixistas de fato
    # (BAIXA/REPIQUE/M9<M21, conforme RADAR_TREND_GATE) e audita o que caiu.
    mask = _aplica_gate_tendencia(df, cfg, m_dte, audit)
    df = df[mask].copy()

    # Universo monitorado (DADOS_ATIVOS), igual ao scan da aba de lucros.
    if cfg.use_dados_ativos_whitelist:
        allowed = _whitelist(df_dados_ativos, cfg.require_has_options)
        if allowed:
            df = df[df["ticker"].isin(allowed)]

    # Porteiro de probabilidade de exercício (PoE): Monte Carlo quando há vol do
    # ativo; senão a POE risk-neutral que já vem no scanner (OpLab). O teto
    # (poe_max) é SEMPRE aplicado — mesmo com o Monte Carlo desligado — usando a
    # melhor PoE disponível, para nunca recomendar PUT acima do risco configurado.
    if not df.empty:
        if mc is not None and vol_map:
            gates, ivs, reals, tends = [], [], [], []
            for _, r in df.iterrows():
                vm = vol_map.get(str(r["ticker"]).strip().upper(), {})
                res = montecarlo.poe_resumo(mc, r["spot"], r["strike"], r["dte"], vm.get("iv"), vm.get("real"))
                gates.append(res["poe_mc_gate"])
                ivs.append(res["poe_mc_iv"])
                reals.append(res["poe_mc_real"])
                # PoE no cenário de CONTINUAÇÃO DA TENDÊNCIA (entrada baixista).
                sg = max([s for s in (vm.get("iv"), vm.get("real")) if s], default=None)
                dft = _entry_trend_drift(r.get("m9m21_trend"), sg)
                tends.append(mc.poe_put(r["spot"], r["strike"], r["dte"], sg, drift=dft)
                             if (sg and dft is not None) else None)
            df["poe_mc_gate"] = pd.to_numeric(gates, errors="coerce")
            df["poe_mc_iv"] = pd.to_numeric(ivs, errors="coerce")
            df["poe_mc_real"] = pd.to_numeric(reals, errors="coerce")
            df["poe_mc_tendencia"] = pd.to_numeric(tends, errors="coerce")
            df["poe_fonte"] = "Monte Carlo"
            # Onde o MC não tem vol (ativo fora de DADOS_ATIVOS), cai p/ a POE da
            # planilha — assim o teto de PoE não fica "cego" nessas linhas.
            sem_mc = df["poe_mc_gate"].isna()
            if sem_mc.any():
                df.loc[sem_mc, "poe_mc_gate"] = df.loc[sem_mc, "poe"]
                df.loc[sem_mc, "poe_fonte"] = "OpLab"
        else:
            df["poe_mc_gate"] = df["poe"]  # POE risk-neutral da OpLab
            df["poe_mc_tendencia"] = float("nan")
            df["poe_fonte"] = "OpLab"
        if audit is not None:
            validos = [g for g in df["poe_mc_gate"].tolist() if g is not None and not _isnan(g)]
            audit["poe_min"] = round(min(validos), 4) if validos else None
        if poe_max is not None:
            df = df[df["poe_mc_gate"].isna() | (df["poe_mc_gate"] <= poe_max)]
            # 2º porteiro: se a PoE com a tendência de baixa estoura o teto, remove
            # (pega o baixista que o rótulo qualitativo não pegou).
            antes_t = len(df)
            df = df[df["poe_mc_tendencia"].isna() | (df["poe_mc_tendencia"] <= poe_max)]
            if audit is not None:
                audit["tendencia_poe_bloqueou"] = int(antes_t - len(df))
        if audit is not None:
            audit["apos_montecarlo"] = int(len(df))

    if audit is not None:
        audit["apos_filtros"] = int(len(df))
        audit["scanner_opcoes"] = int(len(df_scanner))
        audit["scanner_puts_na_cadeia"] = sum(len(v) for v in chain.values())

    if df.empty:
        if audit is not None:
            audit.update({"final": 0, "premios_reais": 0,
                          "premios_estimados": 0, "travas_montadas": 0, "oportunidades": []})
        return []

    df = df.sort_values(by=["profit_rate", "iv_rank"], ascending=[False, False],
                        na_position="last")
    # Diversificação: no máximo N oportunidades por ativo-mãe (mantém as melhores,
    # já que está ordenado por taxa de retorno) — evita o Top-N inteiro virar um
    # papel só. Depois corta no Top-N global.
    if cfg.max_por_ativo and cfg.max_por_ativo > 0:
        antes = len(df)
        df = df[df.groupby("ticker").cumcount() < cfg.max_por_ativo]
        if audit is not None:
            audit["diversificacao_cortou"] = int(antes - len(df))
    df = df.head(cfg.top_n)

    records = [_to_record(r) for _, r in df.iterrows()]
    if audit is not None:
        audit["final"] = len(records)

    for rec in records:
        spot, strike = rec.get("spot"), rec.get("strike")
        rec["dist_pct"] = ((spot / strike - 1) * 100) if (spot and strike) else None
        rec["expiry_fmt"] = _fmt_expiry(rec.get("expiry"))
        rec.update(sig.get(str(rec.get("ticker", "")).strip().upper(), {}))
        rec.update(trend_score_label(rec.get("short_term_trend"),
                                     rec.get("middle_term_trend"), rec.get("m9m21_trend")))
        rec["premio_estimado"] = False  # scanner = CLOSE real, nunca estimado
        # TOQUE + PoE no cenário de tendência + dossiê COMPLETO (auditoria Monte Carlo).
        if mc is not None and vol_map:
            vm = vol_map.get(str(rec.get("ticker", "")).strip().upper(), {})
            sg = max([s for s in (vm.get("iv"), vm.get("real")) if s], default=None)
            full = montecarlo.simular_completo(
                mc, spot, strike, rec.get("dte"), vm.get("iv"), vm.get("real"), tipo="PUT",
                drift_tendencia=_entry_trend_drift(rec.get("m9m21_trend"), sg))
            rec["toque_gate"] = full.get("toque_gate")
            rec["toque_tendencia"] = full.get("toque_tendencia")
            rec["poe_mc_tendencia"] = full.get("poe_mc_tendencia")
            if full.get("sigma_gate") is not None:
                rec["mc_audit"] = full
        # Aviso direcional (caso a baixa tenha passado, ex.: gate em 'off').
        if rec.get("m9m21_trend") == -1:
            rec["alerta_tendencia"] = "Ação em tendência de BAIXA (M9<M21) — venda de PUT é direcional"
        rec["motivo"] = _motivo_radar(rec)
        if cfg.usar_trava:
            rec["trava"] = _build_trava(rec, chain, cfg.trava_largura_pct)
            if rec["trava"] is None:
                rec["trava_motivo"] = _porque_sem_trava(rec, chain, cfg.trava_largura_pct)
        rec["analise"] = analise(rec)

    # Rede de segurança: o rótulo do card é a palavra final — nada baixista passa.
    records = _guarda_final_tendencia(records, cfg, audit)
    if audit is not None:
        audit["final"] = len(records)
        audit["premios_reais"] = len(records)
        audit["premios_estimados"] = 0
        audit["travas_montadas"] = sum(1 for r in records if r.get("trava"))
        audit["oportunidades"] = [_audit_opp(r) for r in records]

    # Sizing (proxy de margem: strike * 100 = tamanho do lote).
    if config.CAPITAL_DISPONIVEL > 0:
        for rec in records:
            strike = rec.get("strike")
            if strike:
                rec["contratos_sugeridos"] = risk_metrics.tamanho_posicao(
                    config.CAPITAL_DISPONIVEL, strike * 100, config.RISK_PER_TRADE)
    return records


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

    # Sinais do ativo-mãe (curto/médio + score) p/ o gate de tendência multi-horizonte.
    sig = _underlying_signals(df_dados_ativos)
    for campo in ("short_term_trend", "middle_term_trend", "oplab_score"):
        df[campo] = df["ticker"].map(
            lambda t, c=campo: (sig.get(str(t).strip().upper()) or {}).get(c))
    # M9M21 CANÔNICO = DADOS_ATIVOS (a MESMA fonte do rótulo exibido). Antes o gate
    # usava o M9M21 da aba de lucros, que podia divergir do DADOS_ATIVOS e deixar
    # passar um ticker que o card mostra como BAIXA. Cai p/ o da aba de lucros só
    # quando o ativo não está no DADOS_ATIVOS.
    def _m9_canon(r):
        v = (sig.get(str(r["ticker"]).strip().upper()) or {}).get("m9m21_trend")
        return v if v is not None else r.get("m9m21_trend")
    df["m9m21_trend"] = df.apply(_m9_canon, axis=1)
    _set_trend_cols(df)

    # Máscaras cumulativas, para registrar o funil estágio a estágio.
    m_put = df["category"] == cfg.option_type.upper()
    m_iv = m_put & (df["iv_rank"] >= cfg.iv_rank_min)
    m_ratio = m_iv & (df["spot_strike_ratio"] >= cfg.spot_strike_ratio_min)
    m_vol = m_ratio & (df["volume_fin"].fillna(0) >= cfg.min_option_volume_fin)
    m_dte = m_vol & (df["dte"] >= cfg.dte_min) & (df["dte"] <= cfg.dte_max)

    if audit is not None:
        audit.update({
            "total": int(len(df)),
            "put": int(m_put.sum()),
            "iv_rank_ok": int(m_iv.sum()),
            "ratio_ok": int(m_ratio.sum()),
            "volume_ok": int(m_vol.sum()),
            "dte_ok": int(m_dte.sum()),
            "filtros": {"iv_rank_min": cfg.iv_rank_min, "ratio_min": cfg.spot_strike_ratio_min,
                        "dte_min": cfg.dte_min, "dte_max": cfg.dte_max},
        })

    # Gate de tendência multi-horizonte: bloqueia entradas baixistas de fato.
    mask = _aplica_gate_tendencia(df, cfg, m_dte, audit)
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
        gates, ivs, reals, tends = [], [], [], []
        for _, r in df.iterrows():
            vm = vol_map.get(str(r["ticker"]).strip().upper(), {})
            res = montecarlo.poe_resumo(mc, r["spot"], r["strike"], r["dte"], vm.get("iv"), vm.get("real"))
            gates.append(res["poe_mc_gate"])
            ivs.append(res["poe_mc_iv"])
            reals.append(res["poe_mc_real"])
            sg = max([s for s in (vm.get("iv"), vm.get("real")) if s], default=None)
            dft = _entry_trend_drift(r.get("m9m21_trend"), sg)
            tends.append(mc.poe_put(r["spot"], r["strike"], r["dte"], sg, drift=dft)
                         if (sg and dft is not None) else None)
        df["poe_mc_gate"] = pd.to_numeric(gates, errors="coerce")
        df["poe_mc_iv"] = pd.to_numeric(ivs, errors="coerce")
        df["poe_mc_real"] = pd.to_numeric(reals, errors="coerce")
        df["poe_mc_tendencia"] = pd.to_numeric(tends, errors="coerce")
        if audit is not None:
            validos = [g for g in gates if g is not None]
            audit["poe_min"] = round(min(validos), 4) if validos else None
        if poe_max is not None:
            df = df[df["poe_mc_gate"].isna() | (df["poe_mc_gate"] <= poe_max)]
            antes_t = len(df)
            df = df[df["poe_mc_tendencia"].isna() | (df["poe_mc_tendencia"] <= poe_max)]
            if audit is not None:
                audit["tendencia_poe_bloqueou"] = int(antes_t - len(df))
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
    )
    # Diversificação: no máximo N oportunidades por ativo-mãe (mantém as melhores).
    if cfg.max_por_ativo and cfg.max_por_ativo > 0:
        antes = len(df)
        df = df[df.groupby("ticker").cumcount() < cfg.max_por_ativo]
        if audit is not None:
            audit["diversificacao_cortou"] = int(antes - len(df))
    df = df.head(cfg.top_n)

    records = [_to_record(r) for _, r in df.iterrows()]
    if audit is not None:
        audit["final"] = len(records)

    # Enriquece cada oportunidade com distância e sinais do ativo-mãe (o "porquê").
    for rec in records:
        spot, strike = rec.get("spot"), rec.get("strike")
        rec["dist_pct"] = ((spot / strike - 1) * 100) if (spot and strike) else None
        rec["expiry_fmt"] = _fmt_expiry(rec.get("expiry"))
        rec.update(sig.get(str(rec.get("ticker", "")).strip().upper(), {}))
        rec.update(trend_score_label(rec.get("short_term_trend"),
                                     rec.get("middle_term_trend"), rec.get("m9m21_trend")))
        if rec.get("m9m21_trend") == -1:
            rec["alerta_tendencia"] = "Ação em tendência de BAIXA (M9<M21) — venda de PUT é direcional"
        # TOQUE + PoE no cenário de tendência + dossiê COMPLETO (auditoria Monte Carlo).
        if mc is not None and vol_map:
            vm = vol_map.get(str(rec.get("ticker", "")).strip().upper(), {})
            sg = max([s for s in (vm.get("iv"), vm.get("real")) if s], default=None)
            full = montecarlo.simular_completo(
                mc, spot, strike, rec.get("dte"), vm.get("iv"), vm.get("real"), tipo="PUT",
                drift_tendencia=_entry_trend_drift(rec.get("m9m21_trend"), sg))
            rec["toque_gate"] = full.get("toque_gate")
            rec["toque_tendencia"] = full.get("toque_tendencia")
            rec["poe_mc_tendencia"] = full.get("poe_mc_tendencia")
            if full.get("sigma_gate") is not None:
                rec["mc_audit"] = full
        rec["motivo"] = _motivo_radar(rec)
        rec["premio"], rec["premio_estimado"], rec["premio_fonte"] = _premio_opcao(rec, prem_map)
        if rec["premio_estimado"]:
            rec["premio_diag"] = _diag_premio(rec.get("option_ticker"), prem_map)
        if cfg.usar_trava:
            rec["trava"] = _build_trava(rec, chain, cfg.trava_largura_pct)
            if rec["trava"] is None:
                rec["trava_motivo"] = _porque_sem_trava(rec, chain, cfg.trava_largura_pct)
        rec["analise"] = analise(rec)

    # Rede de segurança: o rótulo do card é a palavra final — nada baixista passa.
    records = _guarda_final_tendencia(records, cfg, audit)
    if audit is not None:
        audit["final"] = len(records)
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
