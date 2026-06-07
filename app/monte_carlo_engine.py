"""monte_carlo_engine.py — Motor de Monte Carlo (GBM) vetorizado p/ risco de opções B3.

Distingue, com rigor matemático, DOIS riscos de uma opção VENDIDA:

  • Risco de TRAJETÓRIA (path-dependent) — "a ação vai ENCOSTAR no strike em
    algum dia?". É o risco de chamada de margem antecipada: mesmo que a ação
    volte a subir, se o FUNDO da trajetória cruzar o strike a corretora pode
    liquidar. Avaliado com `np.min(paths, axis=0)` (ou `np.max` p/ CALL).

  • Risco TERMINAL — "a opção vai expirar ITM no vencimento?". Só o ÚLTIMO dia
    importa. Avaliado com `paths[-1, :]`.

Vetorização ESTRITA (numpy): nenhum loop `for` percorre os cenários. Uma única
matriz `(passos_uteis, num_simulacoes)` é gerada de uma vez — 10.000 trajetórias
de uma opção de ~30 dias rodam em ~0,01 s.

GBM (sob medida risk-neutral, drift = taxa livre de risco):
    S_t = S_{t-1} · exp( (r − ½σ²)·dt + σ·√dt·Z )

Os métodos públicos devolvem DICIONÁRIOS ESTRUTURADOS, prontos para virar o JSON
da coluna CONTEXT da aba LOGS (SERVICE="MONTE_CARLO").
"""
from __future__ import annotations

import numpy as np

# Convenção de mercado: 252 pregões/ano. O passo estocástico é 1 dia útil.
DIAS_UTEIS_ANO = 252
DT = 1.0 / DIAS_UTEIS_ANO

# Thresholds de negócio (calibráveis pelo chamador, se quiser).
ESCUDO_TOQUE_CRITICO = 0.15   # > 15% de toque na trajetória  -> CRITICAL
RADAR_TERMINAL_MAX = 0.10     # < 10% de ITM no vencimento     -> APPROVED


class MonteCarloEngine:
    """Motor de simulação GBM vetorizado. Reaproveitável entre as 50+ opções de
    uma varredura sem derreter um Dell Inspiron 16GB."""

    def __init__(self, risk_free_rate: float = 0.105, num_simulations: int = 10000,
                 seed: int | None = None):
        self.risk_free_rate = float(risk_free_rate)   # Selic anualizada (drift do GBM)
        self.num_simulations = int(num_simulations)   # padrão obrigatório: 10.000
        self.seed = seed                              # fixa p/ reprodutibilidade nos testes

    # ---- helpers de normalização de entrada -------------------------------
    @staticmethod
    def _norm_iv(iv: float) -> float:
        """IV já anualizada. Se vier em PERCENTUAL (ex.: 45.0), converte p/ decimal.
        Heurística: vol > 1.5 (150%) é, na prática da B3, sempre percentual."""
        iv = float(iv)
        return iv / 100.0 if iv > 1.5 else iv

    @staticmethod
    def _dte_uteis(dte: int) -> int:
        """DTE_CALENDAR (dias corridos da planilha) -> dias ÚTEIS aproximados.
        A matemática estocástica usa dt=1/252, então o nº de passos é em pregões."""
        return int(int(dte) * (DIAS_UTEIS_ANO / 365.0))

    # ---- núcleo vetorizado ------------------------------------------------
    def _generate_paths(self, spot: float, sigma: float, dte_uteis: int) -> np.ndarray:
        """Matriz 2D `(dte_uteis, num_simulations)` de preços diários simulados.

        Tudo vetorizado: gera a matriz de choques Z de uma vez, calcula o expoente
        diário, soma ao longo do TEMPO (`np.cumsum(axis=0)`) e aplica `np.exp`.
        Cada COLUNA é uma trajetória completa; cada LINHA é um dia."""
        rng = np.random.default_rng(self.seed)        # Generator moderno (seedável)
        z = rng.standard_normal((dte_uteis, self.num_simulations))   # (passos, cenários)
        # Expoente diário do GBM: (r − ½σ²)dt  +  σ√dt·Z
        incremento = (self.risk_free_rate - 0.5 * sigma ** 2) * DT + sigma * np.sqrt(DT) * z
        log_retorno_acumulado = np.cumsum(incremento, axis=0)        # soma no eixo do tempo
        return spot * np.exp(log_retorno_acumulado)                  # (passos, cenários)

    def _preparar(self, spot, strike, dte, iv) -> tuple[float, int]:
        """Valida e normaliza as entradas comuns aos dois métodos."""
        if not (spot and spot > 0 and strike and strike > 0):
            raise ValueError(f"spot/strike inválidos: spot={spot}, strike={strike}")
        sigma = self._norm_iv(iv)
        if not (sigma and sigma > 0):
            raise ValueError(f"IV inválida: {iv}")
        dte_uteis = self._dte_uteis(dte)
        if dte_uteis <= 0:
            raise ValueError(f"DTE muito curto (dte={dte} -> {dte_uteis} dias úteis); "
                             "opção praticamente no vencimento, ignorar.")
        return sigma, dte_uteis

    # ---- MÓDULO 1: ESCUDO (risco de trajetória) ---------------------------
    def check_active_risk(self, spot: float, strike: float, dte: int, iv: float,
                          is_put: bool = True, ticker: str = "", option_ticker: str = "") -> dict:
        """Risco PATH-DEPENDENT de uma posição vendida (defesa).

        Simula a trajetória inteira e mede em quantos cenários o preço ENCOSTOU no
        strike (PUT: fundo < strike; CALL: topo > strike). Acima de 15% -> CRITICAL.
        """
        sigma, dte_uteis = self._preparar(spot, strike, dte, iv)
        paths = self._generate_paths(spot, sigma, dte_uteis)
        if is_put:
            extremos = np.min(paths, axis=0)          # menor preço de cada trajetória
            tocou_itm = extremos < strike
        else:
            extremos = np.max(paths, axis=0)          # maior preço (CALL vendida)
            tocou_itm = extremos > strike
        prob_toque = float(np.mean(tocou_itm))
        return {
            "ticker": ticker,
            "option_ticker": option_ticker,
            "status": "CRITICAL" if prob_toque > ESCUDO_TOQUE_CRITICO else "SAFE",
            "poe_mc_gate": round(prob_toque, 4),        # prob. de tocar o strike na trajetória
            "min_price_avg": round(float(np.mean(extremos)), 2),
            "simulations_run": self.num_simulations,
            "method": "PATH_DEPENDENT",
        }

    # ---- MÓDULO 2: RADAR (risco terminal) ---------------------------------
    def evaluate_opportunity(self, spot: float, strike: float, dte: int, iv: float,
                             is_put: bool = True, ticker: str = "", option_ticker: str = "") -> dict:
        """Risco TERMINAL de uma nova venda (ataque).

        Olha SÓ o último dia da simulação. PUT aprovada se a prob. de terminar ITM
        (S_T < strike) for estritamente < 10% (90%+ de chance de virar pó)."""
        sigma, dte_uteis = self._preparar(spot, strike, dte, iv)
        paths = self._generate_paths(spot, sigma, dte_uteis)
        terminal = paths[-1, :]                        # último dia de cada trajetória
        itm = terminal < strike if is_put else terminal > strike
        prob_terminal = float(np.mean(itm))
        return {
            "ticker": ticker,
            "option_ticker": option_ticker,
            "status": "APPROVED" if prob_terminal < RADAR_TERMINAL_MAX else "REJECTED",
            "poe_mc_terminal": round(prob_terminal, 4),   # prob. de exercício no vencimento
            "terminal_price_avg": round(float(np.mean(terminal)), 2),
            "simulations_run": self.num_simulations,
            "method": "TERMINAL_PRICE",
        }
