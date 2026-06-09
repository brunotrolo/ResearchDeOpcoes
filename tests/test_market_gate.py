"""Portão de mercado: relógio (padrão, dias úteis 10:00–16:30) e OpLab (legado)."""
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app import config, market_gate

TZ = ZoneInfo(config.RUNTIME.timezone)


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


# --- Modo OpLab (legado, opt-in via MARKET_GATE_MODE=oplab) -----------------
def test_oplab_aberto(monkeypatch):
    monkeypatch.setattr(market_gate.requests, "get",
                        lambda *a, **k: _FakeResp({"market_status": "A", "server_time": "x"}))
    st = market_gate.check_market_oplab()
    assert st.is_open is True and st.code == "A"


def test_oplab_fechado(monkeypatch):
    monkeypatch.setattr(market_gate.requests, "get",
                        lambda *a, **k: _FakeResp({"market_status": "F", "server_time": "x"}))
    st = market_gate.check_market_oplab()
    assert st.is_open is False and st.code == "F"


def test_check_market_modo_oplab_despacha(monkeypatch):
    monkeypatch.setattr(market_gate.requests, "get",
                        lambda *a, **k: _FakeResp({"market_status": "A"}))
    assert market_gate.check_market(mode="oplab").is_open is True


# --- Modo relógio (padrão) — determinístico, SEM rede ----------------------
def _clock(monkeypatch, dt, ini="10:00", fim="16:30"):
    r = config.RUNTIME
    monkeypatch.setattr(config, "RUNTIME", SimpleNamespace(
        timezone=r.timezone, trading_start=ini, trading_end=fim, market_gate_mode="clock"))
    return market_gate.check_market_clock(dt)


def test_clock_aberto_em_dia_util_no_horario(monkeypatch):
    st = _clock(monkeypatch, datetime(2026, 6, 8, 11, 0, tzinfo=TZ))   # segunda 11:00
    assert st.is_open is True and st.code == "A" and st.raw["mode"] == "clock"


def test_clock_fechado_antes_das_10(monkeypatch):
    assert _clock(monkeypatch, datetime(2026, 6, 8, 9, 59, tzinfo=TZ)).is_open is False


def test_clock_fechado_apos_1630(monkeypatch):
    assert _clock(monkeypatch, datetime(2026, 6, 8, 16, 31, tzinfo=TZ)).is_open is False


def test_clock_bordas_inclusivas(monkeypatch):
    assert _clock(monkeypatch, datetime(2026, 6, 8, 10, 0, tzinfo=TZ)).is_open is True    # abre 10:00
    assert _clock(monkeypatch, datetime(2026, 6, 8, 16, 30, tzinfo=TZ)).is_open is True   # fecha 16:30


def test_clock_fechado_no_fim_de_semana(monkeypatch):
    # Sábado 11:00 — dentro do horário, mas não é dia útil.
    assert _clock(monkeypatch, datetime(2026, 6, 6, 11, 0, tzinfo=TZ)).is_open is False


def test_check_market_padrao_e_relogio(monkeypatch):
    """Sem modo explícito, check_market usa o relógio (não chama a rede)."""
    def boom(*a, **k):
        raise AssertionError("não deveria bater na rede no modo relógio")
    monkeypatch.setattr(market_gate.requests, "get", boom)
    r = config.RUNTIME
    monkeypatch.setattr(config, "RUNTIME", SimpleNamespace(
        timezone=r.timezone, trading_start="10:00", trading_end="16:30", market_gate_mode="clock"))
    st = market_gate.check_market()          # sem rede, determinístico
    assert st.code in ("A", "F") and st.raw["mode"] == "clock"
