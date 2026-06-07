"""Portão de mercado (relógio de ponto) — única chamada à internet fora do Google.

Regra: bater em GET {OPLAB_BASE_URL}/market/status ANTES de tudo. Se o campo
"market_status" != "A" (Aberto), a execução deve ser abortada para poupar
processamento/limites de API. Resposta típica:
    {"server_time": "2026-06-07T01:58:01-03:00", "market_status": "F"}
"""
from __future__ import annotations

from dataclasses import dataclass

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from app import config


@dataclass
class MarketStatus:
    is_open: bool
    code: str
    server_time: str
    raw: dict


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=16))
def _fetch() -> dict:
    url = f"{config.OPLAB.base_url.rstrip('/')}{config.OPLAB.market_status_path}"
    resp = requests.get(
        url,
        headers={"Access-Token": config.OPLAB.token},
        timeout=config.OPLAB.timeout_seconds,
    )
    resp.raise_for_status()
    return resp.json()


def check_market() -> MarketStatus:
    """Consulta o status do mercado. Lança em caso de falha de rede (após retries)."""
    data = _fetch()
    code = str(data.get("market_status", "")).strip().upper()
    return MarketStatus(
        is_open=(code == config.OPLAB.open_status_code.upper()),
        code=code,
        server_time=str(data.get("server_time", "")),
        raw=data,
    )
