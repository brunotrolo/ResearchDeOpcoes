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


def _Phi(x: float) -> float:
    """CDF da normal padrão."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


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

    def prob_toque(self, spot, strike, dte_dias, sigma_anual, drift=None, tipo: str = "PUT") -> float | None:
        """P(tocar o strike ANTES do vencimento) — probabilidade de primeira passagem
        de um GBM, em fórmula FECHADA (princípio da reflexão).

        É a pergunta certa para gerir posição vendida: não "vai exercer no
        vencimento?" (terminal), mas "meu OTM vai VIRAR ATM/ITM no caminho?".
        Sempre ≥ a PoE terminal. PUT = barreira abaixo (spot cai até o strike);
        CALL = barreira acima. `drift` sobrepõe o drift do simulador (p/ cenário
        de continuação da tendência). None se faltar dado."""
        if not (spot and strike and sigma_anual and dte_dias and dte_dias > 0):
            return None
        eh_call = str(tipo).strip().upper() == "CALL"
        # Já no/após o strike -> o toque é certo.
        if (eh_call and spot >= strike) or (not eh_call and spot <= strike):
            return 1.0
        mu = self.drift if drift is None else float(drift)
        sig = float(sigma_anual)
        T = float(dte_dias) / 365.0
        nu = mu - 0.5 * sig * sig            # drift do log-preço
        b = math.log(strike / spot)         # PUT: b<0 ; CALL: b>0
        sqrtT = sig * math.sqrt(T)
        try:
            expo = max(min(2.0 * nu * b / (sig * sig), 50.0), -50.0)
            if eh_call:
                p = _Phi((-b + nu * T) / sqrtT) + math.exp(expo) * _Phi((-b - nu * T) / sqrtT)
            else:
                p = _Phi((b - nu * T) / sqrtT) + math.exp(expo) * _Phi((b + nu * T) / sqrtT)
        except (ValueError, ZeroDivisionError, OverflowError):
            return None
        return float(min(max(p, 0.0), 1.0))

    def cenarios_preco(self, spot, sigma_anual, dte_dias, drift=None) -> dict | None:
        """Cenários do preço no vencimento (quantis da lognormal): P5/P50/P95."""
        if not (spot and sigma_anual and dte_dias and dte_dias > 0):
            return None
        mu = self.drift if drift is None else float(drift)
        sig, T = float(sigma_anual), float(dte_dias) / 365.0
        m, s = (mu - 0.5 * sig * sig) * T, sig * math.sqrt(T)
        return {"p05": float(spot * math.exp(m - 1.6448536 * s)),
                "p50": float(spot * math.exp(m)),
                "p95": float(spot * math.exp(m + 1.6448536 * s))}


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


def toque_resumo(sim: MonteCarloSimulator, spot, strike, dte_dias, iv_anual, real_anual,
                 tipo: str = "PUT", drift_tendencia: float | None = None) -> dict:
    """Probabilidade de TOQUE (virar ATM/ITM antes de vencer) com IV e com vol
    realizada; gate = a MAIOR (mais conservador). Se `drift_tendencia` for dado,
    calcula também o cenário de CONTINUAÇÃO DA TENDÊNCIA (drift != 0)."""
    def _toque(sig, drift=None):
        return sim.prob_toque(spot, strike, dte_dias, sig, drift=drift, tipo=tipo) if sig else None

    t_iv, t_real = _toque(iv_anual), _toque(real_anual)
    vals = [t for t in (t_iv, t_real) if t is not None]
    out = {"toque_iv": t_iv, "toque_real": t_real, "toque_gate": (max(vals) if vals else None)}
    if drift_tendencia is not None:
        # Mesma vol conservadora do gate + o drift da tendência (comparável ao gate).
        sig = max([s for s in (iv_anual, real_anual) if s], default=None)
        out["toque_tendencia"] = _toque(sig, drift=drift_tendencia)
    return out


def simular_completo(sim: MonteCarloSimulator, spot, strike, dte_dias, iv_anual,
                     real_anual, tipo: str = "PUT", drift_tendencia: float | None = None) -> dict:
    """Bateria COMPLETA de Monte Carlo para AUDITORIA (aba LOGS, SERVICE=MONTE_CARLO).

    Roda de uma vez tudo o que decide uma posição/oportunidade e devolve um
    dicionário PLANO e REPRODUTÍVEL (mesmas entradas + seed ⇒ mesma saída):

      • ENTRADAS: spot, strike, DTE, vol IV e realizada, drift, nº de cenários, seed
        — para reproduzir a simulação exatamente a partir do log;
      • PoE terminal (IV, realizada, gate) + a VALIDAÇÃO fechada N(-d2) e o
        `erro_vs_fechada` (distância MC↔fórmula lognormal; mede convergência ≈0);
      • TOQUE/primeira passagem (IV, realizada, gate, cenário de tendência);
      • CENÁRIOS de preço no vencimento (P5/P50/P95).

    Não dispara exceção: campo sem dado vem como None."""
    eh_call = str(tipo).strip().upper() == "CALL"
    poe = poe_resumo(sim, spot, strike, dte_dias, iv_anual, real_anual, tipo=tipo)
    toque = toque_resumo(sim, spot, strike, dte_dias, iv_anual, real_anual,
                         tipo=tipo, drift_tendencia=drift_tendencia)
    sig_gate = max([s for s in (iv_anual, real_anual) if s], default=None)
    cen = sim.cenarios_preco(spot, sig_gate, dte_dias) if sig_gate else None
    # Validação independente: fórmula fechada N(-d2) com a IV, na MESMA convenção
    # do poe_mc_iv (PUT = P(S_T<K); CALL = complemento). O MC deve convergir a ela.
    fechada = sim.poe_put_fechada(spot, strike, dte_dias, iv_anual) if iv_anual else None
    if fechada is not None and eh_call:
        fechada = 1.0 - fechada
    p_iv = poe.get("poe_mc_iv")
    erro = round(abs(p_iv - fechada), 4) if (p_iv is not None and fechada is not None) else None
    return {
        # --- entradas (reprodutibilidade) ---
        "spot": spot, "strike": strike, "dte_dias": dte_dias, "tipo": str(tipo).upper(),
        "sigma_iv": iv_anual, "sigma_real": real_anual, "sigma_gate": sig_gate,
        "drift_sim": sim.drift, "drift_tendencia": drift_tendencia,
        "n_cenarios": sim.n, "seed": sim.seed,
        # --- PoE terminal + validação fechada ---
        "poe_mc_iv": p_iv, "poe_mc_real": poe.get("poe_mc_real"), "poe_mc_gate": poe.get("poe_mc_gate"),
        "poe_fechada_iv": (round(fechada, 4) if fechada is not None else None), "erro_vs_fechada": erro,
        # --- Toque (primeira passagem) ---
        "toque_iv": toque.get("toque_iv"), "toque_real": toque.get("toque_real"),
        "toque_gate": toque.get("toque_gate"), "toque_tendencia": toque.get("toque_tendencia"),
        # --- cenários terminais ---
        "cenarios": cen,
    }
