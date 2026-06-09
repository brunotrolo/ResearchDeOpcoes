"""Portão de mercado (relógio de ponto): decide se o motor deve rodar agora.

Dois modos (MARKET_GATE_MODE):
  - "clock" (PADRÃO): dias úteis (seg–sex) dentro da janela TRADING_START..TRADING_END
    no fuso MARKET_TZ. NÃO depende de rede — determinístico e à prova de API instável.
  - "oplab": consulta GET {OPLAB_BASE_URL}/market/status; abre só com "market_status"=="A".
    Resposta típica: {"server_time": "2026-06-07T01:58:01-03:00", "market_status": "F"}.

O modo "oplab" foi a causa de falsos "ATRASADO" no pager: quando a API caía, o motor
abortava e o heartbeat envelhecia. Por isso o padrão passou a ser o relógio.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from app import config


@dataclass
class MarketStatus:
    is_open: bool
    code: str
    server_time: str
    raw: dict


def _parse_hhmm(value: str, default: dtime) -> dtime:
    """'10:00' -> time(10, 0). Tolerante a lixo: cai no default."""
    try:
        h, m = str(value).strip().split(":")
        return dtime(int(h), int(m))
    except (ValueError, AttributeError):
        return default


def check_market_clock(now: datetime | None = None) -> MarketStatus:
    """Aberto = dia útil (seg–sex) e horário dentro de [TRADING_START, TRADING_END]
    no fuso MARKET_TZ. Sem rede: o relógio é a única verdade."""
    tz = ZoneInfo(config.RUNTIME.timezone)
    now = now.astimezone(tz) if now is not None else datetime.now(tz)
    ini = _parse_hhmm(config.RUNTIME.trading_start, dtime(10, 0))
    fim = _parse_hhmm(config.RUNTIME.trading_end, dtime(16, 30))
    dia_util = now.weekday() < 5                 # 0=seg ... 4=sex
    na_janela = ini <= now.time() <= fim
    is_open = dia_util and na_janela
    return MarketStatus(
        is_open=is_open,
        code="A" if is_open else "F",
        server_time=now.isoformat(),
        raw={"mode": "clock", "weekday": now.weekday(), "time": now.strftime("%H:%M"),
             "janela": f"{ini.strftime('%H:%M')}-{fim.strftime('%H:%M')}", "dia_util": dia_util},
    )


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


def check_market_oplab() -> MarketStatus:
    """Consulta o status do mercado na OpLab. Lança em caso de falha de rede (após retries)."""
    data = _fetch()
    code = str(data.get("market_status", "")).strip().upper()
    return MarketStatus(
        is_open=(code == config.OPLAB.open_status_code.upper()),
        code=code,
        server_time=str(data.get("server_time", "")),
        raw=data,
    )


def check_market(mode: str | None = None) -> MarketStatus:
    """Portão de mercado conforme MARKET_GATE_MODE (padrão: relógio, sem rede)."""
    mode = (mode or config.RUNTIME.market_gate_mode or "clock").strip().lower()
    if mode == "oplab":
        return check_market_oplab()
    return check_market_clock()
