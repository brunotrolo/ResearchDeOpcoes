"""Métricas de risco de PORTFÓLIO (camada agregada do Escudo).

Complementa a análise por-perna com visão de carteira:
    - HHI setorial: concentração das posições por setor (Herfindahl-Hirschman).
    - Exposição ao IBOV: fração do portfólio em ativos altamente correlacionados.
    - Tamanho de posição: nº de contratos para arriscar X% do capital.
    - Spread relativo: medida de liquidez (bid-ask) por opção.

Funções puras (sem I/O) — fáceis de testar. Pesos usam o NOTIONAL (capital
exposto) de cada posição como proxy de tamanho.
"""
from __future__ import annotations

from typing import Optional


def relative_spread(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    """Spread relativo = (ask - bid) / mid. None se inválido. Menor = mais líquido."""
    if bid is None or ask is None:
        return None
    mid = (ask + bid) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid


def hhi_setorial(sectors: list, weights: list) -> Optional[float]:
    """Índice HHI (0..1) de concentração setorial.

    1.0 = tudo num setor só; ~0 = bem diversificado. Acima de ~0.5 já é
    concentração relevante (regra do Escudo).
    """
    pares = [(str(s or "SEM_SETOR").strip().upper(), w)
             for s, w in zip(sectors, weights) if w and w > 0]
    total = sum(w for _, w in pares)
    if total <= 0:
        return None
    agg: dict[str, float] = {}
    for setor, w in pares:
        agg[setor] = agg.get(setor, 0.0) + w
    return sum((w / total) ** 2 for w in agg.values())


def exposicao_ibov(
    tickers: list,
    weights: list,
    correl_map: dict,
    correl_threshold: float = 0.50,
) -> Optional[float]:
    """Fração (0..1) do portfólio em ativos com |correlação ao IBOV| >= limiar.

    Mede quanto da carteira "anda junto" com o índice — risco direcional
    sistêmico (uma queda do IBOV bate em tudo ao mesmo tempo).
    """
    pares = [(str(t).strip().upper(), w) for t, w in zip(tickers, weights) if w and w > 0]
    total = sum(w for _, w in pares)
    if total <= 0:
        return None
    expostos = 0.0
    for tkr, w in pares:
        correl = correl_map.get(tkr)
        if correl is not None and abs(correl) >= correl_threshold:
            expostos += w
    return expostos / total


def tamanho_posicao(
    capital_disponivel: float,
    risco_por_contrato: float,
    risco_por_trade: float = 0.02,
) -> int:
    """Nº de contratos para arriscar `risco_por_trade` (ex.: 2%) do capital.

    risco_por_contrato = perda máxima estimada por contrato (ex.: para uma PUT
    cash-secured, ~ strike * 100). Retorna 0 se faltar dado.
    """
    if capital_disponivel <= 0 or risco_por_contrato <= 0:
        return 0
    orcamento_risco = capital_disponivel * risco_por_trade
    return int(orcamento_risco // risco_por_contrato)
