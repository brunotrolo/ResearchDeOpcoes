"""Testes do Radar (Módulo 2): filtros PUT / IV_RANK / SPOT_STRIKE_RATIO /
janela DTE / liquidez e whitelist DADOS_ATIVOS. Fixtures em pt-BR (como a aba real)."""
import pandas as pd

from app import config, radar


def _opt(**kw) -> dict:
    base = dict(CATEGORY="PUT", EXPIRY="46.220,00", DTE_CALENDAR="40", IV_CURRENT="29",
                VOLUME_FIN="500.000,00", M9M21_TREND="-1,00", SECTOR="", COMPANY_NAME="")
    base.update(kw)
    return base


def _scan(**kw) -> dict:
    """Linha do SCANNER_OPCOES (cadeia de opções com prêmio CLOSE real)."""
    base = dict(CATEGORY="PUT", DTE_CALENDAR="30", BID="", ASK="")
    base.update(kw)
    return base


def test_filtros_basicos_sem_whitelist():
    df = pd.DataFrame([
        _opt(OPTION_TICKER="OK1", TICKER="VALE3", STRIKE="76,00", SPOT="78,99",
             SPOT_STRIKE_RATIO="1,05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="3,5"),
        _opt(OPTION_TICKER="RATIO_BAIXO", TICKER="VALE3", STRIKE="78,00", SPOT="78,99",
             SPOT_STRIKE_RATIO="1,01", IV_RANK="80", PROFIT_RATE_IF_EXERCISED="9"),
        _opt(OPTION_TICKER="EH_CALL", TICKER="VALE3", CATEGORY="CALL", STRIKE="85,00",
             SPOT="78,99", SPOT_STRIKE_RATIO="1,05", IV_RANK="80", PROFIT_RATE_IF_EXERCISED="9"),
        _opt(OPTION_TICKER="IV_BAIXO", TICKER="VALE3", STRIKE="70,00", SPOT="78,99",
             SPOT_STRIKE_RATIO="1,12", IV_RANK="40", PROFIT_RATE_IF_EXERCISED="9"),
        _opt(OPTION_TICKER="SEM_LIQUIDEZ", TICKER="VALE3", STRIKE="74,00", SPOT="78,99",
             SPOT_STRIKE_RATIO="1,06", IV_RANK="70", VOLUME_FIN="0", PROFIT_RATE_IF_EXERCISED="9"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)
    opps = radar.scan(df, cfg=cfg)
    assert [o["option_ticker"] for o in opps] == ["OK1"]


def test_whitelist_has_options():
    df = pd.DataFrame([
        _opt(OPTION_TICKER="VALE_P", TICKER="VALE3", STRIKE="76,00", SPOT="78,99",
             SPOT_STRIKE_RATIO="1,05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="3,5"),
        _opt(OPTION_TICKER="FORA_P", TICKER="XXXX3", STRIKE="9,00", SPOT="9,50",
             SPOT_STRIKE_RATIO="1,05", IV_RANK="90", PROFIT_RATE_IF_EXERCISED="9"),
    ])
    dados = pd.DataFrame([
        dict(TICKER="VALE3", HAS_OPTIONS="TRUE"),
        dict(TICKER="XXXX3", HAS_OPTIONS="FALSE"),  # sem opções -> fora do universo
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=True, require_has_options=True)
    opps = radar.scan(df, df_dados_ativos=dados, cfg=cfg)
    assert [o["option_ticker"] for o in opps] == ["VALE_P"]


def test_ordena_por_profit_rate():
    df = pd.DataFrame([
        _opt(OPTION_TICKER="MENOR", TICKER="VALE3", STRIKE="76,00", SPOT="78,99",
             SPOT_STRIKE_RATIO="1,05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="3,5"),
        _opt(OPTION_TICKER="MAIOR", TICKER="BRKM5", STRIKE="8,50", SPOT="8,67",
             SPOT_STRIKE_RATIO="1,02", IV_RANK="79", PROFIT_RATE_IF_EXERCISED="6,0"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)
    opps = radar.scan(df, cfg=cfg)
    assert [o["option_ticker"] for o in opps] == ["MAIOR", "MENOR"]


def test_janela_dte():
    df = pd.DataFrame([
        _opt(OPTION_TICKER="DENTRO", TICKER="VALE3", STRIKE="76,00", SPOT="78,99",
             SPOT_STRIKE_RATIO="1,05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="3,5", DTE_CALENDAR="30,00"),
        _opt(OPTION_TICKER="CURTO", TICKER="VALE3", STRIKE="76,00", SPOT="78,99",
             SPOT_STRIKE_RATIO="1,05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="9", DTE_CALENDAR="10,00"),
        _opt(OPTION_TICKER="LONGO", TICKER="VALE3", STRIKE="76,00", SPOT="78,99",
             SPOT_STRIKE_RATIO="1,05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="9", DTE_CALENDAR="120,00"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)  # dte_min=21, dte_max=45
    opps = radar.scan(df, cfg=cfg)
    assert [o["option_ticker"] for o in opps] == ["DENTRO"]


# --- Prêmio (CLOSE) + Trava de Alta com PUT --------------------------------
def _opp_vale() -> pd.DataFrame:
    return pd.DataFrame([
        _opt(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", SPOT="78,99",
             SPOT_STRIKE_RATIO="1,05", IV_RANK="65", PROFIT_RATE_IF_EXERCISED="3,5",
             DTE_CALENDAR="30", VE_OVER_STRIKE="5"),
    ])


def test_premio_real_do_scanner_e_trava():
    """Com SCANNER_OPCOES: usa o CLOSE real e monta a trava ~5% abaixo."""
    scanner = pd.DataFrame([
        _scan(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00"),
        _scan(OPTION_TICKER="VALEX74", TICKER="VALE3", STRIKE="74,00", CLOSE="1,40"),
        _scan(OPTION_TICKER="VALEX72", TICKER="VALE3", STRIKE="72,00", CLOSE="1,00"),
        _scan(OPTION_TICKER="VALEX70", TICKER="VALE3", STRIKE="70,00", CLOSE="0,60"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)  # usar_trava=True (padrão)
    opps = radar.scan(_opp_vale(), cfg=cfg, df_scanner=scanner)
    assert len(opps) == 1
    o = opps[0]
    assert o["premio"] == 2.00 and o["premio_estimado"] is False        # CLOSE real
    tr = o["trava"]
    assert tr["sell_strike"] == 76.0 and tr["buy_strike"] == 72.0       # alvo 72,2 -> 72
    assert tr["sell_premio"] == 2.00 and tr["buy_premio"] == 1.00
    assert tr["largura"] == 4.00 and tr["credito"] == 1.00 and tr["risco_max"] == 3.00
    assert tr["retorno_risco"] == 0.3333 and tr["estimado"] is False


def test_premio_estimado_quando_sem_scanner():
    """Sem SCANNER: prêmio aproximado por VE/strike, marcado como estimado."""
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)
    o = radar.scan(_opp_vale(), cfg=cfg, df_scanner=None)[0]
    assert o["premio_estimado"] is True
    assert abs(o["premio"] - 3.80) < 1e-9                               # 5% de 76,00


def test_trava_desligada_mantem_premio():
    scanner = pd.DataFrame([
        _scan(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00"),
        _scan(OPTION_TICKER="VALEX72", TICKER="VALE3", STRIKE="72,00", CLOSE="1,00"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False, usar_trava=False)
    o = radar.scan(_opp_vale(), cfg=cfg, df_scanner=scanner)[0]
    assert o.get("trava") is None
    assert o["premio"] == 2.00                                          # prêmio real ainda aparece


def test_scanner_formato_us_ponto_decimal():
    """SCANNER_OPCOES vem em formato US (ponto decimal); auto-detecta e usa CLOSE real."""
    scanner = pd.DataFrame([
        _scan(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76.00", CLOSE="2.00"),
        _scan(OPTION_TICKER="VALEX72", TICKER="VALE3", STRIKE="72.00", CLOSE="1.00"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)
    o = radar.scan(_opp_vale(), cfg=cfg, df_scanner=scanner)[0]
    assert o["premio"] == 2.00 and o["premio_estimado"] is False     # CLOSE "2.00" -> 2,00 (não 200)
    assert o["trava"]["buy_strike"] == 72.0 and o["trava"]["credito"] == 1.00


def test_premio_usa_meio_do_book_quando_sem_close():
    """Sem CLOSE mas com BID/ASK, usa o meio do book como prêmio real (não estimativa)."""
    scanner = pd.DataFrame([
        _scan(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76.00", CLOSE="", BID="1.90", ASK="2.10"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False, usar_trava=False)
    o = radar.scan(_opp_vale(), cfg=cfg, df_scanner=scanner)[0]
    assert o["premio"] == 2.00 and o["premio_estimado"] is False     # (1,90+2,10)/2


def test_categoria_put_via_coluna_type():
    """Se CATEGORY não disser PUT mas TYPE sim, ainda entra na cadeia da trava."""
    scanner = pd.DataFrame([
        _scan(OPTION_TICKER="VALEX76", TICKER="VALE3", CATEGORY="OPTION", TYPE="PUT", STRIKE="76.00", CLOSE="2.00"),
        _scan(OPTION_TICKER="VALEX72", TICKER="VALE3", CATEGORY="OPTION", TYPE="PUT", STRIKE="72.00", CLOSE="1.00"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)
    o = radar.scan(_opp_vale(), cfg=cfg, df_scanner=scanner)[0]
    assert o["trava"] is not None and o["trava"]["buy_strike"] == 72.0


def test_trava_largura_maior_escolhe_strike_mais_baixo():
    """largura_pct=10% -> alvo 68,4 -> strike 70 (mais próximo abaixo)."""
    scanner = pd.DataFrame([
        _scan(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00"),
        _scan(OPTION_TICKER="VALEX72", TICKER="VALE3", STRIKE="72,00", CLOSE="1,00"),
        _scan(OPTION_TICKER="VALEX70", TICKER="VALE3", STRIKE="70,00", CLOSE="0,60"),
        _scan(OPTION_TICKER="VALEX66", TICKER="VALE3", STRIKE="66,00", CLOSE="0,30"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False, trava_largura_pct=0.10)
    o = radar.scan(_opp_vale(), cfg=cfg, df_scanner=scanner)[0]
    assert o["trava"]["buy_strike"] == 70.0
    assert o["trava"]["credito"] == 1.40 and o["trava"]["risco_max"] == 4.60


# --- Radar lendo DIRETO do SCANNER_OPCOES (prêmio SEMPRE CLOSE real) --------
def _scan_full(**kw) -> dict:
    """Linha completa do SCANNER_OPCOES para o scan_scanner (cadeia toda)."""
    base = dict(CATEGORY="PUT", DTE_CALENDAR="30", SPOT="78,99",
                VOLUME_FIN="500.000,00", BID="", ASK="", POE="")
    base.update(kw)
    return base


def test_scan_scanner_premio_real_e_trava():
    """Lendo o scanner: prêmio é o CLOSE real e a Trava sai do mesmo vencimento."""
    scanner = pd.DataFrame([
        _scan_full(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00"),
        _scan_full(OPTION_TICKER="VALEX74", TICKER="VALE3", STRIKE="74,00", CLOSE="1,40"),
        _scan_full(OPTION_TICKER="VALEX72", TICKER="VALE3", STRIKE="72,00", CLOSE="1,00"),
        _scan_full(OPTION_TICKER="VALEX70", TICKER="VALE3", STRIKE="70,00", CLOSE="0,60"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)
    audit: dict = {}
    opps = radar.scan_scanner(scanner, cfg=cfg, audit=audit)
    assert opps, "scanner deveria gerar oportunidades"
    top = opps[0]
    assert top["option_ticker"] == "VALEX76"          # maior taxa (2/76)
    assert top["premio"] == 2.00 and top["premio_estimado"] is False
    assert top["premio_fonte"] == "CLOSE"
    tr = top["trava"]
    assert tr["sell_strike"] == 76.0 and tr["buy_strike"] == 72.0   # alvo 72,2 -> 72
    assert tr["credito"] == 1.00 and tr["risco_max"] == 3.00
    assert audit["fonte"] == "scanner" and audit["premios_reais"] == len(opps)
    assert audit["premios_estimados"] == 0


def test_scan_scanner_dte_fora_da_janela_reporta_dtes():
    """Se o scanner só tem DTE 10 e a janela é 21-45, zera e reporta os DTEs."""
    scanner = pd.DataFrame([
        _scan_full(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00", DTE_CALENDAR="10"),
        _scan_full(OPTION_TICKER="VALEX72", TICKER="VALE3", STRIKE="72,00", CLOSE="1,00", DTE_CALENDAR="10"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)   # dte_min=21
    audit: dict = {}
    opps = radar.scan_scanner(scanner, cfg=cfg, audit=audit)
    assert opps == []
    assert audit["dte_ok"] == 0 and audit["dtes_disponiveis"] == [10]


def test_scan_scanner_iv_rank_do_dados_ativos_barra():
    """IV Rank vem de DADOS_ATIVOS; ativo com IV Rank baixo é barrado."""
    scanner = pd.DataFrame([
        _scan_full(OPTION_TICKER="VALEX76", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00"),
        _scan_full(OPTION_TICKER="VALEX72", TICKER="VALE3", STRIKE="72,00", CLOSE="1,00"),
    ])
    dados = pd.DataFrame([dict(TICKER="VALE3", HAS_OPTIONS="TRUE", IV_RANK="20")])
    cfg = config.RadarCfg()                                   # iv_rank_min=50, whitelist on
    audit: dict = {}
    opps = radar.scan_scanner(scanner, df_dados_ativos=dados, cfg=cfg, audit=audit)
    assert opps == [] and audit["iv_rank_ok"] == 0


def test_scan_scanner_poe_da_planilha_filtra():
    """Sem Monte Carlo, a POE da própria planilha (OpLab) serve de porteiro."""
    scanner = pd.DataFrame([
        _scan_full(OPTION_TICKER="SEGURA", TICKER="VALE3", STRIKE="76,00", CLOSE="2,00", POE="0,10"),
        _scan_full(OPTION_TICKER="ARRISCADA", TICKER="VALE3", STRIKE="74,00", CLOSE="1,40", POE="0,40"),
        _scan_full(OPTION_TICKER="VALEX72", TICKER="VALE3", STRIKE="72,00", CLOSE="1,00", POE="0,05"),
    ])
    cfg = config.RadarCfg(use_dados_ativos_whitelist=False)
    opps = radar.scan_scanner(scanner, cfg=cfg, poe_max=0.25)
    tickers = [o["option_ticker"] for o in opps]
    assert "ARRISCADA" not in tickers                        # POE 0,40 > 0,25
    assert "SEGURA" in tickers
