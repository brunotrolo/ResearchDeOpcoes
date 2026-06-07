"""Painéis do web app: o mapeamento linha↔cabeçalho agora é por NOME (não mais
posicional). Estes testes travam isso — em especial que NENHUMA coluna fica de
fora por um erro de digitação na chave (que viraria bug mudo no web app)."""
import main
from app import config


def _esc_full() -> dict:
    return {"ticker": "PRIO3", "option_ticker": "PRIOR660", "side": "VENDA", "option_type": "PUT",
            "nivel": "CRITICO", "moneyness": "ITM", "dte": 12, "expiry": "19/06/2026", "quantity": 300,
            "spot": 60.54, "strike": 66.0, "dist_pct": -8.3, "entry_price": 1.8, "last_premium": 4.79,
            "buyback_mult": 2.66, "break_even": 64.2, "delta": -1.0, "gamma": 0.0, "poe": 1.0,
            "poe_mc_gate": 0.94, "pl_value": -897.0, "pl_pct": -166.0, "max_gain": 150.0,
            "max_profit_pct": 8.0, "notional": 19260.0, "analise": "x", "acao_sugerida": "y",
            "toque_gate": 1.0}


def _rad_full() -> dict:
    return {"ticker": "USIM5", "option_ticker": "USIMS11", "expiry_fmt": "17/07/2026", "dte": 30,
            "strike": 11.04, "spot": 11.46, "dist_pct": 3.8, "premio": 0.62, "premio_fonte": "CLOSE",
            "iv_rank": 88, "profit_rate": 0.056, "poe_mc_gate": 0.44, "volume_fin": 82110,
            "poe_mc_tendencia": 0.51, "trend_label": "ALTA", "trend_score": 3,
            "motivo": "x", "analise": "y", "toque_gate": 0.83,
            "trava": {"sell_opt": "USIMS11", "sell_strike": 11.04, "sell_premio": 0.62,
                      "buy_opt": "USIMS105", "buy_strike": 10.54, "buy_premio": 0.43,
                      "credito": 0.19, "risco_max": 0.31, "retorno_risco": 0.61}}


def _by_name(header, row):
    return lambda nome: row[header.index(nome)]


def test_esc_panel_row_preenche_todas_as_colunas():
    """Input completo ⇒ NENHUMA coluna None: prova que toda chave do mapa casa
    com uma coluna do cabeçalho (um typo deixaria a coluna como None)."""
    row = main._esc_panel_row("2026-06-07 16:28:44", _esc_full())
    h = config.PAINEL_ESCUDO_HEADER
    assert len(row) == len(h)
    assert all(v is not None for v in row), \
        f"colunas vazias: {[h[i] for i, v in enumerate(row) if v is None]}"
    g = _by_name(h, row)
    assert g("OPCAO") == "PRIOR660" and g("NIVEL") == "CRITICO" and g("POE_MC") == 0.94


def test_rad_panel_row_preenche_todas_as_colunas_com_trava():
    row = main._rad_panel_row("2026-06-07 16:28:50", _rad_full())
    h = config.PAINEL_RADAR_HEADER
    assert len(row) == len(h)
    assert all(v is not None for v in row), \
        f"colunas vazias: {[h[i] for i, v in enumerate(row) if v is None]}"
    g = _by_name(h, row)
    assert g("OPCAO") == "USIMS11"
    assert g("TRAVA_VENDE_OPCAO") == "USIMS11" and g("TRAVA_COMPRA_OPCAO") == "USIMS105"


def test_rad_panel_row_sem_trava_deixa_codigos_da_trava_vazios():
    o = {"ticker": "PETR4", "option_ticker": "PETRX30", "strike": 30, "spot": 33,
         "premio": 0.5, "poe_mc_gate": 0.2, "toque_gate": 0.3}
    row = main._rad_panel_row("2026-06-07", o)
    h = config.PAINEL_RADAR_HEADER
    g = _by_name(h, row)
    assert g("TRAVA_VENDE_OPCAO") is None and g("TRAVA_COMPRA_OPCAO") is None
    assert g("OPCAO") == "PETRX30"   # a opção em si continua presente
