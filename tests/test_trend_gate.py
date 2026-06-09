"""Trend-Safety nas ENTRADAS do Radar: não vender PUT em ticker baixista.

Cobre (1) o classificador multi-horizonte trend_score_label, (2) o gate que
BLOQUEIA de fato as entradas baixistas (off/medio/estrito), (3) a PoE consciente
da tendência (drift de continuação) como 2º porteiro e número de confiança."""
import pandas as pd

from app import config, montecarlo, radar


# --- fixtures (formato pt-BR, como as abas reais) ---------------------------
def _scan_full(**kw) -> dict:
    base = dict(CATEGORY="PUT", DTE_CALENDAR="30", SPOT="80,00",
                VOLUME_FIN="500.000,00", BID="", ASK="", POE="")
    base.update(kw)
    return base


def _dados(**kw) -> dict:
    base = dict(TICKER="VALE3", HAS_OPTIONS="TRUE", IV_RANK="70",
                M9_M21_TREND="1", MIDDLE_TERM_TREND="1", SHORT_TERM_TREND="1")
    base.update(kw)
    return base


# --- 1. Classificador multi-horizonte --------------------------------------
def test_trend_score_label_alta_confirmada():
    r = radar.trend_score_label(1, 1, 1)
    assert r == {"trend_score": 3, "trend_label": "ALTA"}


def test_trend_score_label_repique_em_baixa():
    """Curto em ALTA mas médio em BAIXA = faca caindo com repique (o caso que o
    gate binário de M9/M21 não pega)."""
    r = radar.trend_score_label(1, -1, 1)
    assert r["trend_label"] == "REPIQUE_BAIXA"


def test_trend_score_label_baixa_por_medio_ou_dois_de_tres():
    assert radar.trend_score_label(0, -1, 0)["trend_label"] == "BAIXA"      # médio em baixa
    assert radar.trend_score_label(-1, 0, -1)["trend_label"] == "BAIXA"     # 2 de 3 em baixa


def test_trend_score_label_neutro_e_desconhecido():
    assert radar.trend_score_label(None, None, None)["trend_label"] == "NEUTRO"
    assert radar.trend_score_label(1, None, None)["trend_label"] == "NEUTRO"   # só 1 alta


# --- 2. Predicado de bloqueio por strictness -------------------------------
def test_trend_blocks_por_nivel():
    # 'medio' (padrão): bloqueia BAIXA, REPIQUE e M9<M21; deixa ALTA/NEUTRO.
    assert radar._trend_blocks("BAIXA", 0, "medio") is True
    assert radar._trend_blocks("REPIQUE_BAIXA", 1, "medio") is True
    assert radar._trend_blocks("NEUTRO", -1, "medio") is True      # M9<M21 cru
    assert radar._trend_blocks("ALTA", 1, "medio") is False
    assert radar._trend_blocks("NEUTRO", 0, "medio") is False
    # 'off' = legado: só barra M9<M21.
    assert radar._trend_blocks("BAIXA", 0, "off") is False
    assert radar._trend_blocks("NEUTRO", -1, "off") is True
    # 'estrito': só passa ALTA confirmada.
    assert radar._trend_blocks("NEUTRO", 0, "estrito") is True
    assert radar._trend_blocks("ALTA", 1, "estrito") is False


# --- 3. Gate end-to-end no scan_scanner ------------------------------------
def test_gate_bloqueia_repique_em_baixa_por_padrao():
    scanner = pd.DataFrame([_scan_full(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00")])
    dados = pd.DataFrame([_dados(SHORT_TERM_TREND="1", MIDDLE_TERM_TREND="-1", M9_M21_TREND="1")])
    # Padrão (medio): repique em baixa é BLOQUEADO de fato.
    assert radar.scan_scanner(scanner, df_dados_ativos=dados, cfg=config.RadarCfg()) == []
    # 'off' (legado) só barraria M9<M21 — aqui M9M21=1, então entra (com o rótulo honesto).
    o = radar.scan_scanner(scanner, df_dados_ativos=dados, cfg=config.RadarCfg(trend_gate="off"))[0]
    assert o["trend_label"] == "REPIQUE_BAIXA"


def test_gate_audita_bloqueadas_por_rotulo():
    scanner = pd.DataFrame([
        _scan_full(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00"),
        _scan_full(OPTION_TICKER="PETRX30", TICKER="PETR4", STRIKE="30,00", CLOSE="1,00", SPOT="31,00"),
    ])
    dados = pd.DataFrame([
        _dados(TICKER="VALE3"),                                                        # ALTA -> passa
        _dados(TICKER="PETR4", M9_M21_TREND="-1", MIDDLE_TERM_TREND="-1", SHORT_TERM_TREND="-1"),  # BAIXA -> bloqueia
    ])
    audit: dict = {}
    opps = radar.scan_scanner(scanner, df_dados_ativos=dados, cfg=config.RadarCfg(), audit=audit)
    assert [o["ticker"] for o in opps] == ["VALE3"]
    assert audit["tendencia_bloqueadas"] == 1
    assert audit["tendencia_rotulos"].get("BAIXA") == 1
    assert audit["trend_gate"] == "medio"


def test_estrito_so_passa_alta_confirmada():
    scanner = pd.DataFrame([_scan_full(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00")])
    dados = pd.DataFrame([_dados(M9_M21_TREND="1", MIDDLE_TERM_TREND="0", SHORT_TERM_TREND="0")])  # NEUTRO
    assert radar.scan_scanner(scanner, df_dados_ativos=dados, cfg=config.RadarCfg(trend_gate="estrito")) == []
    # Em 'medio' o mesmo NEUTRO passa.
    assert radar.scan_scanner(scanner, df_dados_ativos=dados, cfg=config.RadarCfg(trend_gate="medio"))


# --- 4. PoE consciente da tendência (drift de continuação) -----------------
def test_entry_trend_drift():
    assert radar._entry_trend_drift(-1, 0.40) == -0.40
    assert radar._entry_trend_drift(1, 0.40) == 0.40
    assert radar._entry_trend_drift(0, 0.40) is None       # sem tendência definida
    assert radar._entry_trend_drift(-1, None) is None      # sem vol


def test_poe_tendencia_baixa_supera_o_gate():
    """Numa ação caindo (M9<M21), a PoE com o drift de continuação é PIOR que a
    risk-neutral — é o número que diz 'se a queda seguir, exerce mais'."""
    scanner = pd.DataFrame([_scan_full(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00")])
    dados = pd.DataFrame([_dados(M9_M21_TREND="-1", MIDDLE_TERM_TREND="0", SHORT_TERM_TREND="0")])
    sim = montecarlo.MonteCarloSimulator(n=20000, seed=42)
    vol_map = {"VALE3": {"iv": 0.40, "real": 0.40}}
    cfg = config.RadarCfg(evitar_tendencia_baixa=False, usar_trava=False)  # gate qualitativo inativo
    o = radar.scan_scanner(scanner, df_dados_ativos=dados, cfg=cfg,
                           mc=sim, vol_map=vol_map, poe_max=0.99)[0]
    assert o["poe_mc_tendencia"] > o["mc_audit"]["poe_mc_gate"]
    assert o["mc_audit"]["poe_mc_tendencia"] is not None       # também no dossiê de auditoria


def test_segundo_porteiro_remove_por_poe_de_tendencia():
    """A PoE risk-neutral (~0,27) passa o teto 0,30, mas a PoE com a baixa (~0,37)
    o estoura: a oportunidade é removida pelo 2º porteiro (não pelo 1º)."""
    scanner = pd.DataFrame([_scan_full(OPTION_TICKER="VALEX74", TICKER="VALE3", STRIKE="74,00", CLOSE="1,40")])
    dados = pd.DataFrame([_dados(M9_M21_TREND="-1", MIDDLE_TERM_TREND="0", SHORT_TERM_TREND="0")])
    sim = montecarlo.MonteCarloSimulator(n=20000, seed=42)
    vol_map = {"VALE3": {"iv": 0.40, "real": 0.40}}
    cfg = config.RadarCfg(evitar_tendencia_baixa=False, usar_trava=False)  # deixa a baixa chegar ao MC
    audit: dict = {}
    opps = radar.scan_scanner(scanner, df_dados_ativos=dados, cfg=cfg,
                              mc=sim, vol_map=vol_map, poe_max=0.30, audit=audit)
    assert opps == []
    assert audit["tendencia_poe_bloqueou"] == 1


# --- Regressão: "Trava de ALTA num ticker exibido como BAIXA" ---------------
def _luc(o, k, c, m9="1"):
    return dict(OPTION_TICKER=o, TICKER="CSNA3", CATEGORY="PUT", EXPIRY="46.220,00", DTE_CALENDAR="30",
                STRIKE=k, SPOT="6,68", SPOT_STRIKE_RATIO="1,03", IV_RANK="56", IV_CURRENT="40",
                VOLUME_FIN="144.953,00", PROFIT_RATE_IF_EXERCISED=c, M9M21_TREND=m9, SECTOR="", COMPANY_NAME="")


def test_scan_lucros_nao_vaza_baixa_quando_m9m21_diverge():
    """BUG real: a aba de lucros dizia M9M21=ALTA (1) e o DADOS_ATIVOS dizia BAIXA
    (-1). O gate usava o M9M21 da lucros e DEIXAVA PASSAR; o card recomputava pelo
    DADOS_ATIVOS e mostrava ⛔ BAIXA. Agora o M9M21 do gate vem do DADOS_ATIVOS
    (mesma fonte do rótulo) e a guarda final remove de vez."""
    dados = pd.DataFrame([dict(TICKER="CSNA3", HAS_OPTIONS="TRUE", IV_RANK="56",
                               M9_M21_TREND="-1", MIDDLE_TERM_TREND="0", SHORT_TERM_TREND="-1")])
    lucros = pd.DataFrame([_luc("CSNAS650", "6,50", "10,6"), _luc("CSNAS640", "6,40", "10,0")])
    audit: dict = {}
    opps = radar.scan(lucros, df_dados_ativos=dados, cfg=config.RADAR, audit=audit)
    assert opps == []                                            # nada baixista vaza
    assert audit["tendencia_bloqueadas"] >= 2 and audit["tendencia_rotulos"].get("BAIXA")


def test_guarda_final_usa_o_rotulo_do_card():
    """A guarda final decide pelo MESMO trend_label que aparece no card: BAIXA e
    REPIQUE_BAIXA nunca saem (medio); ALTA sai. Desligadas as travas altistas, não age."""
    cfg = config.RadarCfg()
    assert radar._rec_bloqueado_tendencia({"trend_label": "BAIXA", "m9m21_trend": 1}, cfg) is True
    assert radar._rec_bloqueado_tendencia({"trend_label": "REPIQUE_BAIXA", "m9m21_trend": 1}, cfg) is True
    assert radar._rec_bloqueado_tendencia({"trend_label": "ALTA", "m9m21_trend": 1}, cfg) is False
    cfg_off = config.RadarCfg(evitar_tendencia_baixa=False, usar_trava=False)
    assert radar._rec_bloqueado_tendencia({"trend_label": "BAIXA", "m9m21_trend": -1}, cfg_off) is False
