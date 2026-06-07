"""Testes dos principais EVENTOS do orquestrador (main.run), com as fronteiras
de I/O mockadas — NÃO dependem de mercado aberto, planilha ou rede.

Cobre: mercado fechado, OpLab indisponível, alerta crítico do Escudo (e-mail +
auditoria) e oportunidade do Radar (e-mail + funil)."""
import contextlib
from types import SimpleNamespace

import pandas as pd
import pytest

import main as app_main


def _ativa(**kw) -> dict:
    base = dict(STATUS="ATIVO", SIDE="VENDA", OPTION_TYPE="PUT", CONTROL_FLAG="1",
                ID_STRATEGY="STR", TICKER="TICK", PL_PCT="", POE="0,50", SECTOR="X",
                NOTIONAL="R$ 10.000,00", EXPIRY="17/07/2026", DTE_CALENDAR="40")
    base.update(kw)
    return base


@pytest.fixture
def harness(monkeypatch):
    """Mocka OpLab, Sheets (leitura/escrita), e-mail e estado."""
    cap = {"escudo_email": [], "radar_email": [], "history": [], "heartbeat": [],
           "logs": [], "test_email": []}

    monkeypatch.setattr(app_main.notifier, "send_escudo_alert",
                        lambda alerts: cap["escudo_email"].append(alerts) or True)
    monkeypatch.setattr(app_main.notifier, "send_radar_opportunities",
                        lambda opps: cap["radar_email"].append(opps) or True)
    monkeypatch.setattr(app_main.sheets_client, "append_rows",
                        lambda tab, rows, header=None: cap["history"].append((tab, len(rows))))
    monkeypatch.setattr(app_main.sheets_client, "upsert_status_row",
                        lambda tab, header, row: cap["heartbeat"].append(row))
    monkeypatch.setattr(app_main.state, "run_lock", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(app_main.state, "filter_new_alerts", lambda x: x)
    monkeypatch.setattr(app_main.state, "filter_new_opportunities", lambda x: x)
    monkeypatch.setattr(app_main.state, "mark_run_ok", lambda *a, **k: None)
    monkeypatch.setattr(app_main.state, "get_last_run_ok", lambda: None)
    monkeypatch.setattr(app_main.Logbook, "flush", lambda self: cap["logs"].extend(self._entries))
    return cap


def _tabs(monkeypatch, mapping: dict):
    monkeypatch.setattr(app_main.sheets_client, "read_tab",
                        lambda name: mapping.get(name, pd.DataFrame()))


def _market(monkeypatch, code="A"):
    monkeypatch.setattr(app_main.market_gate, "check_market",
                        lambda: SimpleNamespace(is_open=(code == "A"), code=code,
                                                server_time="x", raw={"market_status": code}))


def _runtime(**over):
    """Cria um RUNTIME (namespace) baseado no real, com sobrescritas (RUNTIME é frozen)."""
    r = app_main.config.RUNTIME
    base = dict(timezone=r.timezone, dry_run=r.dry_run, force_run=r.force_run,
                email_test_only=r.email_test_only, state_dir=r.state_dir,
                log_file=r.log_file, lock_file=r.lock_file, state_file=r.state_file)
    base.update(over)
    return SimpleNamespace(**base)


def test_mercado_fechado_nao_analisa(monkeypatch, harness):
    _market(monkeypatch, "F")
    _tabs(monkeypatch, {})
    rc = app_main.run()
    assert rc == 0
    assert harness["escudo_email"] == [] and harness["radar_email"] == []
    assert harness["heartbeat"], "heartbeat deve ser sempre escrito"


def test_oplab_indisponivel_aborta(monkeypatch, harness):
    def boom():
        raise RuntimeError("timeout OpLab")
    monkeypatch.setattr(app_main.market_gate, "check_market", boom)
    _tabs(monkeypatch, {})
    rc = app_main.run()
    assert rc == 2
    assert harness["escudo_email"] == []


def test_escudo_critico_dispara_email_e_auditoria(monkeypatch, harness):
    _market(monkeypatch, "A")
    ativas = pd.DataFrame([_ativa(
        OPTION_TICKER="PRIOR660", TICKER="PRIO3", MONEYNESS="ITM", STRIKE="R$ 66,00",
        SPOT="R$ 60,54", ENTRY_PRICE="R$ 1,80", LAST_PREMIUM="R$ 4,79", DELTA="-1,00",
        POE="1,00", PL_VALUE="-R$ 897,00", MAX_LOSS="R$ 19.260,00", DTE_CALENDAR="12",
        EXPIRY="19/06/2026")])
    _tabs(monkeypatch, {"ativas": ativas})
    rc = app_main.run()
    assert rc == 0
    assert len(harness["escudo_email"]) == 1
    tickers = [a["option_ticker"] for a in harness["escudo_email"][0]]
    assert "PRIOR660" in tickers
    services = [e.service for e in harness["logs"]]
    assert "SHEET_READ" in services  # auditoria registrou a leitura
    assert any(e.service == "ESCUDO" and "carteira" in e.summary for e in harness["logs"])
    assert harness["heartbeat"]


def test_radar_oportunidade_dispara_email_e_funil(monkeypatch, harness):
    _market(monkeypatch, "A")
    lucros = pd.DataFrame([dict(
        OPTION_TICKER="USIMS112", TICKER="USIM5", CATEGORY="PUT", EXPIRY="46.220,00",
        DTE_CALENDAR="30,00", STRIKE="11,29", SPOT="11,52", SPOT_STRIKE_RATIO="1,02",
        IV_RANK="84", IV_CURRENT="55", VOLUME_FIN="500.000,00",
        PROFIT_RATE_IF_EXERCISED="3,5", M9M21_TREND="1", SECTOR="", COMPANY_NAME="")])
    dados = pd.DataFrame([dict(TICKER="USIM5", HAS_OPTIONS="TRUE")])
    _tabs(monkeypatch, {"lucros": lucros, "dados_ativos": dados})
    rc = app_main.run()
    assert rc == 0
    assert len(harness["radar_email"]) == 1
    assert harness["radar_email"][0][0]["option_ticker"] == "USIMS112"
    assert any(e.service == "RADAR" and "Funil" in e.summary for e in harness["logs"])


def test_email_teste_mesmo_com_mercado_fechado(monkeypatch, harness):
    # ação "email_teste": manda e-mail de teste e ignora o pregão fechado.
    monkeypatch.setattr(app_main.config, "RUNTIME", _runtime(force_run=True, email_test_only=True))
    monkeypatch.setattr(app_main.notifier, "send_test_email",
                        lambda: harness["test_email"].append(True) or True)
    _market(monkeypatch, "F")
    _tabs(monkeypatch, {})
    rc = app_main.run()
    assert rc == 0
    assert harness["test_email"] == [True]      # e-mail de teste enviado
    assert harness["escudo_email"] == []        # não roda os módulos
    assert harness["heartbeat"]                 # heartbeat gravado


def test_homologar_ignora_mercado_fechado(monkeypatch, harness):
    # ação "homologar": roda TUDO de verdade mesmo com a B3 fechada.
    monkeypatch.setattr(app_main.config, "RUNTIME", _runtime(force_run=True))
    _market(monkeypatch, "F")
    ativas = pd.DataFrame([_ativa(
        OPTION_TICKER="PRIOR660", TICKER="PRIO3", MONEYNESS="ITM", STRIKE="R$ 66,00",
        SPOT="R$ 60,54", ENTRY_PRICE="R$ 1,80", LAST_PREMIUM="R$ 4,79", DELTA="-1,00",
        POE="1,00", PL_VALUE="-R$ 897,00", MAX_LOSS="R$ 19.260,00", DTE_CALENDAR="12",
        EXPIRY="19/06/2026")])
    _tabs(monkeypatch, {"ativas": ativas})
    rc = app_main.run()
    assert rc == 0
    # rodou os módulos mesmo com o mercado fechado -> e-mail do Escudo disparado
    assert len(harness["escudo_email"]) == 1
    assert "PRIOR660" in [a["option_ticker"] for a in harness["escudo_email"][0]]
