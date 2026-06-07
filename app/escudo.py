"""Módulo 1 — ESCUDO (defesa de posições ativas).

Lê a aba Painel_Ativas e avalia as pernas VENDIDAS (a perna de risco de
Travas de Alta com Put / vendas de PUT e CALL a seco). Aplica a regra de
negócio calibrada por moneyness (ITM/ATM/OTM), combinando 3 sinais:

    1. Múltiplo de recompra:  LAST_PREMIUM / ENTRY_PRICE
    2. |Delta| da perna vendida (lido direto da planilha)
    3. Perda corrente vs. MAX_LOSS da estratégia  (+ DTE para risco de exercício)

Saída: lista de alertas (dicts) com nível AVISO/ALERTA/CRITICO, motivo,
descrição e ação sugerida. Quem decide enviar e-mail é o orquestrador.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app import config, frames, parsing

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
    return "Acompanhar"


def _classify(row: dict, cfg: config.EscudoCfg, today: date) -> dict | None:
    moneyness = parsing.to_upper(row.get("moneyness"))
    delta = row.get("delta")
    abs_delta = abs(delta) if delta is not None else None
    entry = row.get("entry_price")
    last = row.get("last_premium")
    pl_value = row.get("pl_value")
    max_loss = row.get("max_loss")
    dte = parsing.days_to_expiry(row.get("expiry"), today)

    buyback_mult = (last / entry) if (entry and last is not None and entry > 0) else None
    loss = -pl_value if (pl_value is not None and pl_value < 0) else 0.0
    loss_ratio = (loss / abs(max_loss)) if (max_loss not in (None, 0)) else None

    nivel = "OK"
    motivos: list[str] = []

    # --- Sinal 2: bandas de |Delta| — early-warning de DRIFT na zona OTM.
    #     Em ATM/ITM o |Δ| é naturalmente alto (>0.5) e não acrescenta sinal:
    #     essas zonas são regidas por moneyness + DTE + perda (abaixo).
    if abs_delta is not None and moneyness not in {"ATM", "ITM"}:
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
        elif moneyness == "ATM":
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
        nivel = _escalate(nivel, "ALERTA")
        motivos.append("ATM")
        if abs_delta is not None and abs_delta >= cfg.delta_atm:
            motivos.append(f"DELTA_ATM(|Δ|={abs_delta:.2f})")
        if dte is not None and dte <= cfg.dte_critical:
            nivel = _escalate(nivel, "CRITICO")
            motivos.append(f"DTE_CRITICO({dte}d)")

    # --- Sinal 3: perda corrente vs. MAX_LOSS (todas as zonas) ---
    if loss_ratio is not None and loss_ratio >= cfg.loss_vs_maxloss_pct:
        nivel = _escalate(nivel, "CRITICO")
        motivos.append(f"PERDA_{loss_ratio*100:.0f}%_DO_MAXLOSS")

    if nivel == "OK":
        return None

    return {
        "option_ticker": row.get("option_ticker"),
        "ticker": row.get("ticker"),
        "id_strategy": row.get("id_strategy"),
        "side": row.get("side"),
        "option_type": row.get("option_type"),
        "moneyness": moneyness,
        "dte": dte,
        "strike": row.get("strike"),
        "spot": row.get("spot"),
        "delta": delta,
        "entry_price": entry,
        "last_premium": last,
        "buyback_mult": buyback_mult,
        "pl_value": pl_value,
        "loss_ratio": loss_ratio,
        "nivel": nivel,
        "motivo": "+".join(motivos),
        "acao_sugerida": _acao(moneyness, nivel),
    }


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Constrói um DataFrame normalizado (colunas lógicas, valores parseados)."""
    out = pd.DataFrame(index=df.index)
    for field in ("option_ticker", "ticker", "id_strategy", "expiry"):
        out[field] = frames.raw(df, "ativas", field)
    for field in ("side", "option_type", "moneyness", "status"):
        out[field] = frames.txt(df, "ativas", field)
    for field in ("strike", "spot", "entry_price", "last_premium",
                  "delta", "pl_value", "pl_pct", "max_loss"):
        out[field] = frames.num(df, "ativas", field)
    return out


def analyze(df_ativas: pd.DataFrame, today: date, cfg: config.EscudoCfg | None = None) -> list[dict]:
    """Analisa o Painel_Ativas e devolve a lista de alertas (todos os níveis)."""
    cfg = cfg or config.ESCUDO
    if df_ativas is None or df_ativas.empty:
        return []

    norm = _normalize(df_ativas)
    norm = norm[norm["status"] == "ATIVO"]
    if cfg.only_short_legs:
        norm = norm[norm["side"] == "VENDA"]

    alerts: list[dict] = []
    for _, row in norm.iterrows():
        record = {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in row.items()}
        result = _classify(record, cfg, today)
        if result is not None:
            alerts.append(result)

    # Ordena por severidade desc, depois por perda
    alerts.sort(key=lambda a: (_NIVEL_RANK[a["nivel"]], -(a.get("pl_value") or 0)), reverse=True)
    return alerts


def email_worthy(alerts: list[dict]) -> list[dict]:
    """Só ALERTA/CRITICO viram e-mail urgente; AVISO fica no log/planilha."""
    return [a for a in alerts if a["nivel"] in {"ALERTA", "CRITICO"}]
