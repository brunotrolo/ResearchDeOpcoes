"""Monte Carlo (GBM) para PROBABILIDADE DE EXERCÍCIO — numpy puro.

Simula o preço terminal do ativo por Movimento Geométrico Browniano e estima
P(S_T < strike) = probabilidade de exercício de uma PUT vendida.

É a SEGUNDA OPINIÃO da coluna POE da planilha (que é risk-neutral, via IV):
aqui calculamos com vol IMPLÍCITA E com vol REALIZADA (GARCH/STDV) e usamos a
MAIOR (gate mais conservador). Drift padrão = 0 (martingale, sem viés).

Validação: `poe_put_fechada` é a fórmula lognormal fechada N(-d2) — o Monte
Carlo deve convergir para ela (ver tests/test_montecarlo.py).
"""
from __future__ import annotations

import math

import numpy as np

_SQRT_252 = math.sqrt(252.0)


class MonteCarloSimulator:
    """GBM de preço terminal, vetorizado. drift e sigma em base ANUAL (decimal)."""

    def __init__(self, n: int = 10000, seed: int | None = 42, drift: float = 0.0):
        self.n = int(n)
        self.seed = seed
        self.drift = float(drift)

    def _terminal(self, spot: float, sigma_anual: float, dte_dias: float) -> np.ndarray:
        T = max(float(dte_dias), 0.0) / 365.0
        rng = np.random.default_rng(self.seed)
        z = rng.standard_normal(self.n)
        return spot * np.exp((self.drift - 0.5 * sigma_anual ** 2) * T + sigma_anual * math.sqrt(T) * z)

    def poe_put(self, spot, strike, dte_dias, sigma_anual) -> float | None:
        """P(S_T < strike) por simulação (PoE de PUT vendida). None se faltar dado."""
        if not (spot and strike and sigma_anual and dte_dias and dte_dias > 0):
            return None
        return float(np.mean(self._terminal(spot, sigma_anual, dte_dias) < strike))

    def poe_put_fechada(self, spot, strike, dte_dias, sigma_anual) -> float | None:
        """P(S_T < strike) pela fórmula lognormal fechada = N(-d2). Para validação."""
        if not (spot and strike and sigma_anual and dte_dias and dte_dias > 0):
            return None
        T = dte_dias / 365.0
        d2 = (math.log(spot / strike) + (self.drift - 0.5 * sigma_anual ** 2) * T) / (sigma_anual * math.sqrt(T))
        return 0.5 * (1.0 + math.erf(-d2 / math.sqrt(2.0)))


def anual_from_daily(daily) -> float | None:
    """Vol diária (ex.: STDV/GARCH = 0,02) -> anual (× √252)."""
    return float(daily) * _SQRT_252 if daily else None


def anual_from_iv_pct(iv_pct) -> float | None:
    """IV em % anual (ex.: 30,01) -> decimal (0,3001)."""
    return float(iv_pct) / 100.0 if iv_pct else None


def poe_resumo(sim: MonteCarloSimulator, spot, strike, dte_dias, iv_anual, real_anual,
               tipo: str = "PUT") -> dict:
    """PoE de exercício com IV e com vol realizada; gate = a MAIOR (conservador).

    PUT exerce com S_T < strike; CALL exerce com S_T > strike (complemento)."""
    eh_call = str(tipo).strip().upper() == "CALL"

    def _poe(sig):
        if not sig:
            return None
        p = sim.poe_put(spot, strike, dte_dias, sig)   # P(S_T < strike)
        return None if p is None else (1.0 - p if eh_call else p)

    p_iv, p_real = _poe(iv_anual), _poe(real_anual)
    vals = [p for p in (p_iv, p_real) if p is not None]
    return {"poe_mc_iv": p_iv, "poe_mc_real": p_real, "poe_mc_gate": (max(vals) if vals else None)}
