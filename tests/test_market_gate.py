"""Testes do relógio de ponto (OpLab /market/status) — sem rede real."""
from app import market_gate


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_mercado_aberto(monkeypatch):
    monkeypatch.setattr(market_gate.requests, "get",
                        lambda *a, **k: _FakeResp({"market_status": "A", "server_time": "x"}))
    st = market_gate.check_market()
    assert st.is_open is True
    assert st.code == "A"


def test_mercado_fechado(monkeypatch):
    monkeypatch.setattr(market_gate.requests, "get",
                        lambda *a, **k: _FakeResp({"market_status": "F", "server_time": "x"}))
    st = market_gate.check_market()
    assert st.is_open is False
    assert st.code == "F"
