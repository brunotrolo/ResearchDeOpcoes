"""Módulo 1 — ESCUDO (defesa de posições ativas).

Lê a aba PAINEL_ATIVAS e avalia as pernas VENDIDAS (a perna de risco de
Travas de Alta com Put / vendas de PUT e CALL a seco). Regra calibrada por
moneyness (ITM/ATM/OTM), combinando sinais:

    1. Múltiplo de recompra:  LAST_PREMIUM / ENTRY_PRICE
    2. |Delta| da perna vendida — early-warning de DRIFT, só na zona OTM
       (em ATM/ITM o |Δ| já é alto por natureza; lá quem manda é DTE + perda).
    3. Perda corrente vs. MAX_LOSS da estratégia.
    4. DTE_CALENDAR (risco de exercício) e POE (prob. de exercício), lidos da aba.

Taxonomia (alinhada ao motor existente do Bruno):
    - OTM saudável -> sem alerta.   - ATM -> AVISO (vigiar, sem e-mail).
    - ITM -> ALERTA.                - ITM/perda alta perto do vencimento -> CRITICO.

Saída: lista de alertas (dicts). Quem decide enviar e-mail é o orquestrador.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app import config, frames, parsing, risk_metrics

_NIVEL_RANK = {"OK": 0, "AVISO": 1, "ALERTA": 2, "CRITICO": 3}


def _escalate(current: str, candidate: str) -> str:
    return candidate if _NIVEL_RANK[candidate] > _NIVEL_RANK[current] else current


def _acao(moneyness: str, nivel: str) -> str:
    if nivel == "CRITICO":
        if moneyness == "ITM":
            return "Avaliar encerramento ou rolagem imediata (risco de exercício)"
        return "Reduzir/rolar agora — gatilho de perda atingido"
    if nivel == "ALERTA":
        if moneyness == "ITM":
            return "Monitorar diariamente; preparar rolagem"
        if moneyness == "ATM":
            return "Monitorar de perto; preparar rolagem (gamma alto)"
        return "Acompanhar; recompra ao dobrar o prêmio"
    return "Acompanhar (vigiar moneyness/DTE)"


def analise(a: dict) -> str:
    """Conclusão textual gerada pelo MOTOR para a operação (vai ao e-mail e ao painel)."""
    if str(a.get("option_ticker", "")).startswith("PORTFOLIO"):
        return a.get("descricao", "")
    otype, side, m = a.get("option_type", ""), a.get("side", ""), a.get("moneyness", "")
    tipo = f"{otype} {'vendida' if side == 'VENDA' else 'comprada'}".strip()
    p = [f"{tipo} {m}".strip()]
    if a.get("dte") is not None:
        p.append(f"{a['dte']} dias até o vencimento")
    if a.get("delta") is not None:
        p.append(f"Δ {a['delta']:.2f}".replace(".", ","))
    if a.get("poe") is not None:
        p.append(f"POE {a['poe'] * 100:.0f}%")
    frase = ", ".join(p) + "."
    sinais = []
    if a.get("buyback_mult") is not None and a["buyback_mult"] >= 1.5:
        sinais.append(f"recompra já a {a['buyback_mult']:.1f}x o prêmio".replace(".", ","))
    if a.get("pl_pct") is not None and a["pl_pct"] <= -50:
        sinais.append(f"P/L aberto {a['pl_pct']:.0f}%".replace(".", ","))
    if a.get("gamma") is not None and a["gamma"] >= 0.05:
        sinais.append("gamma alto (aceleração)")
    if sinais:
        frase += " " + "; ".join(sinais) + "."
    if a.get("acao_sugerida"):
        frase += f" → {a['acao_sugerida']}."
    return frase


def _classify(row: dict, cfg: config.EscudoCfg, today: date) -> dict | None:
    moneyness = parsing.to_upper(row.get("moneyness"))
    delta = row.get("delta")
    abs_delta = abs(delta) if delta is not None else None
    gamma = row.get("gamma")
    entry = row.get("entry_price")
    last = row.get("last_premium")
    pl_value = row.get("pl_value")
    max_loss = row.get("max_loss")
    poe = row.get("poe")
    spot = row.get("spot")
    strike = row.get("strike")
    dist_pct = ((spot / strike - 1) * 100) if (spot is not None and strike) else None
    # PL_PCT e MAX_PROFIT_PCT são frações na espelho (-1,66 = -166%) -> x100.
    pl_pct = row.get("pl_pct")
    pl_pct = pl_pct * 100 if pl_pct is not None else None
    max_profit_pct = row.get("max_profit_pct")
    max_profit_pct = max_profit_pct * 100 if max_profit_pct is not None else None
    # DTE: prefere a coluna da planilha (DTE_CALENDAR); senão calcula do EXPIRY.
    dte = row.get("dte_calendar")
    if dte is None:
        dte = parsing.days_to_expiry(row.get("expiry"), today)
    dte = int(dte) if dte is not None else None

    buyback_mult = (last / entry) if (entry and last is not None and entry > 0) else None
    loss = -pl_value if (pl_value is not None and pl_value < 0) else 0.0
    loss_ratio = (loss / abs(max_loss)) if (max_loss not in (None, 0)) else None

    nivel = "OK"
    motivos: list[str] = []

    # --- Sinal 2: bandas de |Delta| — só na zona OTM (drift rumo ao perigo) ---
    if abs_delta is not None and moneyness == "OTM":
        if abs_delta >= cfg.delta_urgent:
            nivel = _escalate(nivel, "CRITICO")
            motivos.append(f"DELTA_URGENTE(|Δ|={abs_delta:.2f})")
        elif abs_delta >= cfg.delta_warn:
            nivel = _escalate(nivel, "ALERTA")
            motivos.append(f"DELTA_ALERTA(|Δ|={abs_delta:.2f})")

    # --- Sinal 1: múltiplo de recompra, calibrado por moneyness ---
    if buyback_mult is not None:
        if moneyness == "OTM":
            if buyback_mult >= cfg.buyback_mult_otm_crit:
                nivel = _escalate(nivel, "CRITICO")
                motivos.append(f"RECOMPRA_{cfg.buyback_mult_otm_crit:g}x")
            elif buyback_mult >= cfg.buyback_mult_otm:
                nivel = _escalate(nivel, "ALERTA")
                motivos.append(f"RECOMPRA_{cfg.buyback_mult_otm:g}x")
        elif moneyness in {"ATM", "ITM"}:
            if buyback_mult >= cfg.buyback_mult_atm:
                nivel = _escalate(nivel, "ALERTA")
                motivos.append(f"RECOMPRA_{cfg.buyback_mult_atm:g}x")

    # --- Baseline por moneyness ---
    if moneyness == "ITM":
        nivel = _escalate(nivel, "ALERTA")
        motivos.append("ITM")
        if dte is not None and dte <= cfg.dte_critical:
            nivel = _escalate(nivel, "CRITICO")
            motivos.append(f"DTE_CRITICO({dte}d)")
    elif moneyness == "ATM":
        nivel = _escalate(nivel, "AVISO")
        motivos.append("ATM")
        if abs_delta is not None and abs_delta >= cfg.delta_atm:
            motivos.append(f"DELTA_ATM(|Δ|={abs_delta:.2f})")
        # ATM só sobe para ALERTA se estiver perto do vencimento E perdendo.
        if dte is not None and dte <= cfg.dte_critical and (pl_value is not None and pl_value < 0):
            nivel = _escalate(nivel, "ALERTA")
            motivos.append(f"ATM_DTE({dte}d)_PERDA")

    # --- Sinal 3: perda corrente vs. MAX_LOSS (todas as zonas) ---
    if loss_ratio is not None and loss_ratio >= cfg.loss_vs_maxloss_pct:
        nivel = _escalate(nivel, "CRITICO")
        motivos.append(f"PERDA_{loss_ratio*100:.0f}%_DO_MAXLOSS")

    # --- Sinal extra: Gamma alto = pré-perigo (aceleração do delta) ---
    if gamma is not None and gamma >= cfg.gamma_max:
        nivel = _escalate(nivel, "AVISO")
        motivos.append(f"GAMMA_ALTO({gamma:.2f})")

    # --- Heads-up de vencimento próximo (AVISO, sem e-mail) p/ pernas saudáveis ---
    if nivel == "OK" and dte is not None and dte <= cfg.dte_critical:
        nivel = "AVISO"
        motivos.append(f"DTE_PROXIMO({dte}d)")

    if nivel == "OK":
        return None

    return {
        "option_ticker": row.get("option_ticker"),
        "ticker": row.get("ticker"),
        "id_strategy": row.get("id_strategy"),
        "sector": row.get("sector"),
        "side": row.get("side"),
        "option_type": row.get("option_type"),
        "moneyness": moneyness,
        "quantity": row.get("quantity"),
        "dte": dte,
        "expiry": row.get("expiry"),
        "strike": strike,
        "spot": spot,
        "dist_pct": dist_pct,
        "break_even": row.get("break_even"),
        "entry_price": entry,
        "last_premium": last,
        "buyback_mult": buyback_mult,
        "delta": delta,
        "gamma": gamma,
        "poe": poe,
        "max_gain": row.get("max_gain"),
        "max_profit_pct": max_profit_pct,
        "notional": row.get("notional"),
        "pl_value": pl_value,
        "pl_pct": pl_pct,
        "loss_ratio": loss_ratio,
        "nivel": nivel,
        "motivo": "+".join(motivos),
        "acao_sugerida": _acao(moneyness, nivel),
    }


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Constrói um DataFrame normalizado (colunas lógicas, valores parseados)."""
    out = pd.DataFrame(index=df.index)
    for field in ("option_ticker", "ticker", "id_strategy", "expiry", "sector"):
        out[field] = frames.raw(df, "ativas", field)
    for field in ("side", "option_type", "moneyness", "status"):
        out[field] = frames.txt(df, "ativas", field)
    for field in ("strike", "spot", "entry_price", "last_premium", "delta", "gamma",
                  "poe", "pl_value", "pl_pct", "max_loss", "max_gain", "max_profit_pct",
                  "notional", "quantity", "break_even", "moneyness_ratio", "dte_calendar",
                  "control_flag"):
        out[field] = frames.num(df, "ativas", field)
    return out


def analyze(df_ativas: pd.DataFrame, today: date, cfg: config.EscudoCfg | None = None) -> list[dict]:
    """Analisa a PAINEL_ATIVAS e devolve a lista de alertas (todos os níveis)."""
    cfg = cfg or config.ESCUDO
    if df_ativas is None or df_ativas.empty:
        return []

    norm = _normalize(df_ativas)
    norm = norm[norm["status"] == "ATIVO"]
    if cfg.only_short_legs:
        norm = norm[norm["side"] == "VENDA"]
    # CONTROL_FLAG == 0 -> linha desativada manualmente na planilha.
    norm = norm[~(norm["control_flag"] == 0)]

    alerts: list[dict] = []
    for _, row in norm.iterrows():
        record = {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in row.items()}
        result = _classify(record, cfg, today)
        if result is not None:
            result["analise"] = analise(result)
            alerts.append(result)

    alerts.sort(key=lambda a: (_NIVEL_RANK[a["nivel"]], -(a.get("pl_value") or 0)), reverse=True)
    return alerts


def _portfolio_alert(key: str, motivo: str, nivel: str, descricao: str, acao: str, extra: dict) -> dict:
    """Monta um alerta de nível de carteira no mesmo formato dos alertas por-perna.

    `key` é o identificador único (vira option_ticker), para o dedupe não fundir
    alertas de carteira distintos (ex.: PORTFOLIO_HHI vs PORTFOLIO_IBOV).
    """
    base = {
        "option_ticker": key, "ticker": "—", "id_strategy": key,
        "side": "—", "option_type": "—", "moneyness": "—", "dte": None,
        "strike": None, "spot": None, "delta": None, "gamma": None, "poe": None,
        "entry_price": None, "last_premium": None, "buyback_mult": None,
        "pl_value": None, "loss_ratio": None, "nivel": nivel, "motivo": motivo,
        "descricao": descricao, "acao_sugerida": acao, "analise": descricao,
    }
    base.update(extra)
    return base


def _correl_map(df_correl: pd.DataFrame | None) -> dict[str, float]:
    if df_correl is None or df_correl.empty:
        return {}
    tickers = frames.raw(df_correl, "correl", "ticker")
    valores = frames.num(df_correl, "correl", "correl_value")
    return {str(t).strip().upper(): v
            for t, v in zip(tickers, valores) if t and not pd.isna(v)}


def analyze_portfolio(df_ativas: pd.DataFrame, df_correl: pd.DataFrame | None = None,
                      cfg: config.EscudoCfg | None = None, audit: dict | None = None) -> list[dict]:
    """Alertas de RISCO DE CARTEIRA: concentração setorial (HHI) e exposição ao IBOV.

    Se `audit` (dict) for passado, é preenchido com os valores calculados
    (hhi, exposicao_ibov, nº de pernas) para registro na auditoria.
    """
    cfg = cfg or config.ESCUDO
    if df_ativas is None or df_ativas.empty:
        return []

    norm = _normalize(df_ativas)
    norm = norm[norm["status"] == "ATIVO"]
    if cfg.only_short_legs:
        norm = norm[norm["side"] == "VENDA"]
    norm = norm[~(norm["control_flag"] == 0)]
    if norm.empty:
        return []

    # Peso de cada posição = NOTIONAL (capital exposto); fallback: 1 por posição.
    pesos = [(n if (n is not None and not pd.isna(n) and n > 0) else 0.0) for n in norm["notional"]]
    if not any(pesos):
        pesos = [1.0] * len(norm)
    setores = list(norm["sector"])
    tickers = [str(t).strip().upper() for t in norm["ticker"]]

    alerts: list[dict] = []

    hhi = risk_metrics.hhi_setorial(setores, pesos)
    correl_map = _correl_map(df_correl)
    exp = risk_metrics.exposicao_ibov(tickers, pesos, correl_map, cfg.ibov_correl_threshold)
    if audit is not None:
        audit.update({
            "n_pernas_vendidas": int(len(norm)),
            "hhi": round(hhi, 4) if hhi is not None else None,
            "hhi_max": cfg.hhi_max,
            "exposicao_ibov": round(exp, 4) if exp is not None else None,
            "ibov_exposure_max": cfg.ibov_exposure_max,
        })

    if hhi is not None and hhi > cfg.hhi_max:
        alerts.append(_portfolio_alert(
            "PORTFOLIO_HHI", f"HHI_SETORIAL({hhi:.2f})", "ALERTA",
            f"Concentração setorial alta (HHI {hhi:.2f} > {cfg.hhi_max:.2f})",
            "Diversificar setores; evitar novas posições no setor dominante",
            {"hhi": round(hhi, 4)}))

    if exp is not None and exp > cfg.ibov_exposure_max:
        alerts.append(_portfolio_alert(
            "PORTFOLIO_IBOV", f"EXPOSICAO_IBOV({exp*100:.0f}%)", "ALERTA",
            f"Carteira {exp*100:.0f}% correlacionada ao IBOV (> {cfg.ibov_exposure_max*100:.0f}%)",
            "Reduzir exposição direcional; considerar hedge de índice",
            {"exposicao_ibov": round(exp, 4)}))

    return alerts


def email_worthy(alerts: list[dict]) -> list[dict]:
    """Só ALERTA/CRITICO viram e-mail urgente; AVISO fica no log/planilha."""
    return [a for a in alerts if a["nivel"] in {"ALERTA", "CRITICO"}]
