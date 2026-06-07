"""Painéis do web app: o mapeamento POSICIONAL linha↔cabeçalho é frágil, então
trava aqui os campos que alimentam os cards (em especial os CÓDIGOS das pernas
da Trava, que o app usa para a tomada de decisão)."""
import main
from app import config


def test_rad_panel_row_casa_com_o_cabecalho_e_traz_os_codigos_das_pernas():
    o = {
        "ticker": "USIM5", "option_ticker": "USIMS11", "expiry_fmt": "17/07/2026",
        "dte": 30, "strike": 11.04, "spot": 11.46, "dist_pct": 3.8, "premio": 0.62,
        "iv_rank": 88, "profit_rate": 0.056, "poe_mc_gate": 0.44, "volume_fin": 82110,
        "toque_gate": 0.83, "motivo": "x", "analise": "y",
        "trava": {"sell_opt": "USIMS11", "sell_strike": 11.04, "sell_premio": 0.62,
                  "buy_opt": "USIMS105", "buy_strike": 10.54, "buy_premio": 0.43,
                  "credito": 0.19, "risco_max": 0.31, "retorno_risco": 0.61},
    }
    row = main._rad_panel_row("2026-06-07 16:28:50", o)
    h = config.PAINEL_RADAR_HEADER
    assert len(row) == len(h)                       # linha casa com o cabeçalho
    g = lambda nome: row[h.index(nome)]             # acesso por NOME (como o web app)
    # Os DOIS códigos da trava chegam ao painel (o app monta a ordem com eles).
    assert g("OPCAO") == "USIMS11"                  # perna vendida (título do card)
    assert g("TRAVA_VENDE_OPCAO") == "USIMS11"
    assert g("TRAVA_COMPRA_OPCAO") == "USIMS105"    # ANTES faltava no painel
    assert g("TRAVA_VENDE_STRIKE") == 11.04 and g("TRAVA_COMPRA_STRIKE") == 10.54


def test_rad_panel_row_sem_trava_deixa_codigos_da_trava_vazios():
    o = {"ticker": "PETR4", "option_ticker": "PETRX30", "strike": 30, "spot": 33,
         "premio": 0.5, "poe_mc_gate": 0.2, "toque_gate": 0.3}
    row = main._rad_panel_row("2026-06-07", o)
    h = config.PAINEL_RADAR_HEADER
    assert row[h.index("TRAVA_VENDE_OPCAO")] is None
    assert row[h.index("TRAVA_COMPRA_OPCAO")] is None
