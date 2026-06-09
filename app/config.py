"""Configuração central do motor ResearchDeOpcoes.

Princípios:
    - Segredos e parâmetros de ambiente vêm do .env (nunca hard-coded).
    - O "mapa de colunas" das abas-espelho fica TODO aqui (TABS + COLUMN_MAP),
      para reconciliar num único lugar quando os schemas reais forem confirmados.
    - Thresholds de negócio (Escudo/Radar) têm defaults sensatos, mas são
      sobrescrevíveis pelo .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Caminhos base e carregamento do .env
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key)
    return val if val not in (None, "") else default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(_env(key, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = _env(key, str(default))
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "sim", "on"}


def _env_list(key: str, default: str = "") -> list[str]:
    raw = _env(key, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Google / OpLab / E-mail / Runtime
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Google:
    credentials_file: str = _env("GOOGLE_CREDENTIALS_FILE", str(BASE_DIR / "credenciais.json"))
    spreadsheet_id: str = _env("SPREADSHEET_ID", "")


@dataclass(frozen=True)
class OpLab:
    base_url: str = _env("OPLAB_BASE_URL", "https://api.oplab.com.br/v3")
    token: str = _env("OPLAB_TOKEN", "")
    market_status_path: str = _env("OPLAB_MARKET_STATUS_PATH", "/market/status")
    open_status_code: str = _env("OPLAB_OPEN_STATUS", "A")  # "A" = Aberto
    timeout_seconds: int = _env_int("OPLAB_TIMEOUT", 15)


@dataclass(frozen=True)
class Email:
    enabled: bool = _env_bool("EMAIL_ENABLED", True)
    smtp_host: str = _env("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = _env_int("SMTP_PORT", 465)
    user: str = _env("EMAIL_USER", "")
    app_password: str = _env("EMAIL_APP_PASSWORD", "")
    sender: str = _env("EMAIL_SENDER", _env("EMAIL_USER", ""))
    recipients: list[str] = field(
        default_factory=lambda: _env_list("ALERT_RECIPIENTS", "brunotrolo@gmail.com")
    )


@dataclass(frozen=True)
class Runtime:
    timezone: str = _env("MARKET_TZ", "America/Sao_Paulo")
    dry_run: bool = _env_bool("DRY_RUN", False)        # True = não envia e-mail, não grava planilha
    force_run: bool = _env_bool("FORCE_RUN", False)    # True = roda mesmo com mercado fechado (homologação)
    email_test_only: bool = _env_bool("EMAIL_TEST_ONLY", False)  # True = só manda um e-mail de teste
    # Portão de mercado: "clock" (padrão — dias úteis dentro do horário, SEM depender
    # de API) ou "oplab" (consulta /market/status). A API de status do mercado se
    # mostrou instável e derrubava o motor durante o pregão; o relógio é determinístico.
    market_gate_mode: str = _env("MARKET_GATE_MODE", "clock")
    trading_start: str = _env("TRADING_START", "10:00")   # HH:MM no fuso MARKET_TZ
    trading_end: str = _env("TRADING_END", "16:30")       # HH:MM no fuso MARKET_TZ
    state_dir: Path = BASE_DIR / "state"
    log_file: Path = BASE_DIR / "logs" / "motor.log"
    lock_file: Path = BASE_DIR / "state" / "motor.lock"
    state_file: Path = BASE_DIR / "state" / "last_run.json"


# ---------------------------------------------------------------------------
# Abas (worksheets) das planilhas-espelho
#   header_row = nº da linha (1-based) onde está o cabeçalho real.
#   COCKPIT/Painel_Ativas costuma ter linhas de preâmbulo -> ajuste aqui.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TabSpec:
    title: str
    header_row: int = 1
    decimal_sep: str = "."   # "." = US/ISO ; "," = pt-BR (vírgula decimal)


TABS: dict[str, TabSpec] = {
    # A planilha-espelho inteira está em pt-BR (vírgula decimal, ponto de milhar).
    "ativas":       TabSpec(_env("TAB_ATIVAS", "PAINEL_ATIVAS"),                 _env_int("TAB_ATIVAS_HEADER_ROW", 1),       _env("TAB_ATIVAS_DECIMAL", ",")),
    "lucros":       TabSpec(_env("TAB_LUCROS", "SELECAO_OPCOES_MAIORES_LUCROS"), _env_int("TAB_LUCROS_HEADER_ROW", 1),       _env("TAB_LUCROS_DECIMAL", ",")),
    "volumes":      TabSpec(_env("TAB_VOLUMES", "SELECAO_MAIORES_VOLUMES"),     _env_int("TAB_VOLUMES_HEADER_ROW", 1),       _env("TAB_VOLUMES_DECIMAL", ",")),
    "m9m21":        TabSpec(_env("TAB_M9M21", "RANKING_TENDENCIA_M9M21"),       _env_int("TAB_M9M21_HEADER_ROW", 1),         _env("TAB_M9M21_DECIMAL", ",")),
    "correl":       TabSpec(_env("TAB_CORREL", "RANKING_CORREL_IBOV"),          _env_int("TAB_CORREL_HEADER_ROW", 1),        _env("TAB_CORREL_DECIMAL", ",")),
    "dados_ativos": TabSpec(_env("TAB_DADOS_ATIVOS", "DADOS_ATIVOS"),           _env_int("TAB_DADOS_ATIVOS_HEADER_ROW", 1), _env("TAB_DADOS_ATIVOS_DECIMAL", ",")),
    "config":       TabSpec(_env("TAB_CONFIG", "CONFIG"),                       _env_int("TAB_CONFIG_HEADER_ROW", 1),       _env("TAB_CONFIG_DECIMAL", ",")),
    "scanner":      TabSpec(_env("TAB_SCANNER", "SCANNER_OPCOES"),              _env_int("TAB_SCANNER_HEADER_ROW", 1),      _env("TAB_SCANNER_DECIMAL", "auto")),
}

# Abas de escrita (logs + histórico). Criadas automaticamente se não existirem.
TAB_LOGS = _env("TAB_LOGS", "LOGS")
TAB_HIST_ESCUDO = _env("TAB_HIST_ESCUDO", "ESCUDO_HISTORICO")
TAB_HIST_RADAR = _env("TAB_HIST_RADAR", "RADAR_HISTORICO")
TAB_MONITOR = _env("TAB_MONITOR", "MONITOR")
TAB_CONFIG = _env("TAB_CONFIG", "CONFIG")
TAB_PAINEL_ESCUDO = _env("TAB_PAINEL_ESCUDO", "PAINEL_ESCUDO")
TAB_PAINEL_RADAR = _env("TAB_PAINEL_RADAR", "PAINEL_RADAR")
TAB_DIAGNOSTICO = _env("TAB_RADAR_DIAGNOSTICO", "RADAR_DIAGNOSTICO")

# Aba CONFIG (CHAVE/VALOR) — botões do projeto, controláveis pelo celular.
CONFIG_HEADER = ["CHAVE", "VALOR", "DESCRICAO"]
DEFAULT_CONFIG = [
    # --- E-mail ---
    ["ENVIAR_EMAIL", "TRUE", "Liga/desliga TODOS os e-mails (TRUE/FALSE)"],
    ["ENVIAR_EMAIL_ESCUDO", "TRUE", "E-mail de defesa de posicoes (TRUE/FALSE)"],
    ["ENVIAR_EMAIL_RADAR", "TRUE", "E-mail de oportunidades do Radar (TRUE/FALSE)"],
    ["ESCUDO_NIVEL_MINIMO_EMAIL", "ALERTA", "Nivel minimo p/ e-mail de Escudo (ALERTA ou CRITICO)"],
    # --- Monte Carlo (probabilidade de exercicio) ---
    ["USAR_MONTECARLO", "TRUE", "Filtrar Radar por prob. de exercicio (TRUE/FALSE)"],
    ["POE_MAXIMA", "25", "Prob. maxima de exercicio (%) para recomendar uma PUT"],
    ["MC_CENARIOS", "10000", "Numero de simulacoes do Monte Carlo"],
    ["MC_DRIFT", "0", "Tendencia do GBM (0 = sem vies; ex.: 0.05 = juros)"],
    # --- Radar (filtros de prospeccao) ---
    ["RADAR_FONTE", "auto", "Fonte das oportunidades: scanner / lucros / auto"],
    ["RADAR_IV_RANK_MIN", "50", "IV Rank minimo (premio gordo)"],
    ["RADAR_RATIO_MIN", "1.02", "Distancia minima spot/strike (1.02 = 2% OTM)"],
    ["RADAR_DTE_MIN", "21", "DTE minimo (dias)"],
    ["RADAR_DTE_MAX", "45", "DTE maximo (dias)"],
    ["RADAR_TOP_N", "5", "Quantas oportunidades no e-mail"],
    ["RADAR_MAX_POR_ATIVO", "2", "Maximo de oportunidades por ativo-mae (diversificacao)"],
    ["RADAR_EXIGIR_TENDENCIA_ALTA", "FALSE", "So recomenda se a acao estiver em alta M9>M21 (TRUE/FALSE)"],
    ["RADAR_EVITAR_TENDENCIA_BAIXA", "TRUE", "Descarta venda de PUT/Trava em acao em baixa M9<M21 (estrategia e altista) (TRUE/FALSE)"],
    ["RADAR_TREND_GATE", "medio", "Bloqueio de entrada em ticker baixista (curto/medio/M9M21): off / medio / estrito"],
    ["RADAR_USAR_TRAVA", "TRUE", "Montar Trava de Alta com PUT (risco limitado) em vez de PUT a seco (TRUE/FALSE)"],
    ["RADAR_TRAVA_LARGURA_PCT", "5", "Largura da trava: PUT comprada ~N% abaixo do strike vendido (%)"],
    # --- Escudo (gatilhos de defesa) ---
    ["ESCUDO_RECOMPRA_OTM", "2.0", "Alerta quando custo de recompra >= Nx o premio (OTM)"],
    ["ESCUDO_RECOMPRA_OTM_CRIT", "3.0", "Critico quando recompra >= Nx (OTM)"],
    ["ESCUDO_RECOMPRA_ATM", "1.5", "Alerta quando recompra >= Nx (ATM/ITM)"],
    ["ESCUDO_DELTA_ALERTA", "0.30", "Banda de |Delta| p/ alerta (zona OTM)"],
    ["ESCUDO_DELTA_URGENTE", "0.35", "Banda de |Delta| p/ critico (zona OTM)"],
    ["ESCUDO_DTE_CRITICO", "15", "DTE (dias) que torna ITM/ATM critico"],
    ["ESCUDO_PERDA_MAX_PCT", "50", "Perda (% do MAX_LOSS) que vira critico"],
    ["ESCUDO_GAMMA_MAX", "0.05", "Gamma que dispara pre-perigo"],
    ["ESCUDO_TOQUE_AVISO", "50", "Prob. de TOQUE (virar ITM antes de vencer) que vira AVISO numa perna OTM (%)"],
    ["ESCUDO_TOQUE_ALERTA", "70", "Prob. de TOQUE que vira ALERTA numa perna OTM (%)"],
    ["ESCUDO_HHI_MAX", "0.50", "Concentracao setorial maxima (HHI 0..1)"],
    ["ESCUDO_IBOV_EXPOSICAO_MAX", "80", "Exposicao maxima ao IBOV (%)"],
    ["ESCUDO_IBOV_CORREL_MIN", "0.50", "Correlacao minima p/ contar como exposto ao IBOV"],
]
# Painéis sobrescritos a cada execução (alimentam o web app). O web app lê pelo
# NOME do cabeçalho, então a ordem/quantidade pode evoluir sem quebrar o painel.
PAINEL_ESCUDO_HEADER = ["ATUALIZADO_EM", "TICKER", "OPCAO", "SIDE", "TIPO", "NIVEL", "MONEYNESS",
                        "DTE", "EXPIRY", "QTD", "SPOT", "STRIKE", "DIST_PCT",
                        "PREMIO_ENTRADA", "PREMIO_ATUAL", "RECOMPRA_X", "BREAK_EVEN",
                        "DELTA", "GAMMA", "POE", "POE_MC", "PL_VALUE", "PL_PCT",
                        "GANHO_MAX", "LUCRO_MAX_PCT", "NOCIONAL", "ANALISE", "ACAO", "TOQUE"]
PAINEL_RADAR_HEADER = ["ATUALIZADO_EM", "TICKER", "OPCAO", "EXPIRY", "DTE", "STRIKE", "SPOT",
                       "DIST_PCT", "PREMIO", "PREMIO_FONTE", "IV_RANK", "TAXA_RETORNO", "POE_MC",
                       "POE_TENDENCIA", "TREND_LABEL", "TREND_SCORE",
                       "VOLUME_FIN", "TRAVA_VENDE_OPCAO", "TRAVA_VENDE_STRIKE", "TRAVA_VENDE_PREMIO",
                       "TRAVA_COMPRA_OPCAO", "TRAVA_COMPRA_STRIKE", "TRAVA_COMPRA_PREMIO", "TRAVA_CREDITO",
                       "TRAVA_RISCO_MAX", "TRAVA_RETORNO_RISCO", "MOTIVO", "ANALISE", "TOQUE"]
# Raio-X didático do Radar: 1 linha por ticker do DADOS_ATIVOS.
DIAGNOSTICO_HEADER = ["ATUALIZADO_EM", "TICKER", "VEREDITO", "TENDENCIA", "IV_RANK",
                      "SPOT", "STRIKE", "MARGEM", "CHANCE_EXERCICIO", "CHANCE_TOQUE",
                      "CENARIO_30D", "POR_QUE", "COMO_LER"]

# Cabeçalho fixo da aba LOGS (conforme especificado pelo Bruno)
LOGS_HEADER = ["UPDATED_AT", "SERVICE", "STATUS", "SUMMARY", "CONTEXT"]
# A aba LOGS é REESCRITA a cada ciclo (run mais recente no TOPO, sem linhas vazias),
# limitada a este nº de linhas — a auditoria fica visível logo abaixo do cabeçalho.
LOGS_MAX_ROWS = _env_int("LOGS_MAX_ROWS", 4000)

# Cabeçalho da aba MONITOR (heartbeat / observabilidade — 1 linha sobrescrita)
MONITOR_HEADER = ["UPDATED_AT", "STATUS", "MARKET", "DURATION_S",
                  "ESCUDO_ALERTS", "RADAR_OPPS", "RUN_URL", "NOTES"]

# ---------------------------------------------------------------------------
# Mapa de colunas (logical_field -> nome real na aba-espelho)
#   >>> RECONCILIAR AQUI quando os schemas detalhados chegarem. <<<
# ---------------------------------------------------------------------------
COLUMN_MAP: dict[str, dict[str, str]] = {
    "ativas": {
        "id_trade": "ID_TRADE",
        "id_strategy": "ID_STRATEGY",
        "status": "STATUS",                  # ATIVO / EXERCIDA / ENCERRADO
        "ticker": "TICKER",
        "option_ticker": "OPTION_TICKER",
        "side": "SIDE",                      # COMPRA / VENDA
        "option_type": "OPTION_TYPE",        # CALL / PUT
        "quantity": "QUANTITY",
        "strike": "STRIKE",
        "spot": "SPOT",
        "moneyness": "MONEYNESS",            # ITM / ATM / OTM
        "moneyness_ratio": "MONEYNESS_RATIO",  # ~ spot/strike
        "entry_price": "ENTRY_PRICE",
        "last_premium": "LAST_PREMIUM",
        "delta": "DELTA",                    # por perna (confirmado)
        "gamma": "GAMMA",                    # aceleração do delta (pré-perigo)
        "vega": "VEGA",
        "theta": "THETA",
        "poe": "POE",                        # probabilidade de exercício (0..1)
        "sector": "SECTOR",                  # para o HHI setorial
        "expiry": "EXPIRY",                  # dd/mm/aaaa
        "dte_calendar": "DTE_CALENDAR",      # dias corridos até o vencimento
        "iv": "IV",
        "iv_rank": "IV_RANK",
        "pl_value": "PL_VALUE",
        "pl_pct": "PL_PCT",                   # fração: -1,66 = -166%
        "break_even": "BREAK_EVEN",
        "max_gain": "MAX_GAIN",
        "max_profit_pct": "MAX_PROFIT_PCT",   # fração
        "max_loss": "MAX_LOSS",
        "notional": "NOTIONAL",
        "direction_flag": "DIRECTION_FLAG",  # 1 = perna de crédito (risco)
        "control_flag": "CONTROL_FLAG",      # 0 = ignorar linha na análise
    },
    "lucros": {
        "option_ticker": "OPTION_TICKER",
        "ticker": "TICKER",
        "category": "CATEGORY",        # PUT / CALL
        "expiry": "EXPIRY",            # aaaa-mm-dd
        "dte": "DTE_CALENDAR",
        "strike": "STRIKE",
        "spot": "SPOT",
        "spot_strike_ratio": "SPOT_STRIKE_RATIO",
        "iv_rank": "IV_RANK",
        "iv_current": "IV_CURRENT",
        "volume_fin": "VOLUME_FIN",
        "ve_over_strike": "VE_OVER_STRIKE",   # valor extrínseco / strike (% ) -> estima prêmio
        "bid": "BID",                  # opcional (espelhar SCANNER_OPCOES p/ filtro de spread)
        "ask": "ASK",                  # opcional
        "profit_rate": "PROFIT_RATE_IF_EXERCISED",
        "m9m21_trend": "M9M21_TREND",
        "sector": "SECTOR",
        "company": "COMPANY_NAME",
    },
    "scanner": {
        # Cadeia COMPLETA de opções (preço CLOSE, POE, IV, gregas, moneyness).
        # Fonte primária do Radar e do prêmio REAL. A planilha está em pt-BR
        # (vírgula); o leitor auto-detecta o separador decimal.
        "option_ticker": "OPTION_TICKER",
        "ticker": "TICKER",
        "category": "CATEGORY",        # PUT / CALL (algumas exportações usam TYPE)
        "type": "TYPE",                # PUT / CALL (redundante com CATEGORY)
        "strike": "STRIKE",
        "spot": "SPOT",
        "close": "CLOSE",              # PREÇO/prêmio da opção (sempre o CLOSE)
        "price": "PRICE",              # preço teórico/atual (fallback)
        "mid_price": "MID_PRICE",      # meio do book (fallback)
        "bid": "BID",
        "ask": "ASK",
        "dte": "DTE_CALENDAR",
        "expiry": "EXPIRY",
        "poe": "POE",                  # prob. de exercício (0..1) calculada pela OpLab
        "iv_calc": "IV_CALC",          # volatilidade implícita da opção
        "moneyness": "MONEYNESS",      # ITM / ATM / OTM
        "moneyness_ratio": "MONEYNESS_RATIO",  # ~ spot/strike
        "return_on_strike": "RETURN_ON_STRIKE",  # prêmio/strike (retorno da venda)
        "volume_fin": "VOLUME_FIN",
        "delta": "DELTA",
    },
    "volumes": {
        "ticker": "TICKER",
        "volume_call": "VOLUME_CALL",
        "volume_put": "VOLUME_PUT",
        "volume_total": "VOLUME_TOTAL",
    },
    "m9m21": {
        "ticker": "TICKER",
        "trend": "M9M21_TREND",        # 1 = alta, -1 = baixa
        "value": "M9M21_VALUE",
    },
    "dados_ativos": {
        "ticker": "TICKER",
        "company": "COMPANY_NAME",
        "sector": "SECTOR",
        "spot": "SPOT",
        "iv": "IV",
        "iv_rank": "IV_RANK",
        "bid": "BID",
        "ask": "ASK",
        "volume": "VOLUME",
        "financial_volume": "FINANCIAL_VOLUME",
        "has_options": "HAS_OPTIONS",        # TRUE / FALSE
        "beta_ibov": "BETA_IBOV",
        "correl_ibov": "CORREL_IBOV",
        "m9m21_trend": "M9_M21_TREND",       # 1 = alta, -1 = baixa
        "middle_term_trend": "MIDDLE_TERM_TREND",
        "short_term_trend": "SHORT_TERM_TREND",
        "oplab_score": "OPLAB_SCORE",
        "garch_1y": "GARCH11_1Y",            # vol realizada (GARCH), DIÁRIA
        "stdv_1y": "STDV_1Y",                # desvio-padrão histórico, DIÁRIO
    },
    "correl": {
        "ticker": "TICKER",
        "correl_value": "CORREL_VALUE",
    },
    "config": {
        "chave": "CHAVE",
        "valor": "VALOR",
    },
}


# ---------------------------------------------------------------------------
# Thresholds de negócio — ESCUDO (Módulo 1)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EscudoCfg:
    # Múltiplo de recompra (LAST_PREMIUM / ENTRY_PRICE) por moneyness
    buyback_mult_otm: float = _env_float("ESCUDO_BUYBACK_MULT_OTM", 2.0)
    buyback_mult_otm_crit: float = _env_float("ESCUDO_BUYBACK_MULT_OTM_CRIT", 3.0)
    buyback_mult_atm: float = _env_float("ESCUDO_BUYBACK_MULT_ATM", 1.5)
    # Bandas de |Delta| da perna vendida
    delta_warn: float = _env_float("ESCUDO_DELTA_WARN", 0.30)
    delta_urgent: float = _env_float("ESCUDO_DELTA_URGENT", 0.35)
    delta_atm: float = _env_float("ESCUDO_DELTA_ATM", 0.45)
    # DTE (dias corridos) abaixo do qual ITM/ATM vira crítico (risco de exercício)
    dte_critical: int = _env_int("ESCUDO_DTE_CRITICAL", 15)
    # Fração do MAX_LOSS da estratégia que, atingida, força CRÍTICO
    loss_vs_maxloss_pct: float = _env_float("ESCUDO_LOSS_VS_MAXLOSS_PCT", 0.50)
    # Gamma alto = pré-perigo (aceleração do delta na perna vendida)
    gamma_max: float = _env_float("ESCUDO_GAMMA_MAX", 0.05)
    # Gatilho PREDITIVO (Monte Carlo): probabilidade de a perna OTM TOCAR o strike
    # (virar ATM/ITM) antes do vencimento. Avisa ANTES de dar ruim.
    toque_aviso: float = _env_float("ESCUDO_TOQUE_AVISO", 0.50)
    toque_alerta: float = _env_float("ESCUDO_TOQUE_ALERTA", 0.70)
    # Só analisa a perna de risco (vendida) por padrão
    only_short_legs: bool = _env_bool("ESCUDO_ONLY_SHORT_LEGS", True)
    # --- Risco de PORTFÓLIO (visão agregada) ---
    hhi_max: float = _env_float("ESCUDO_HHI_MAX", 0.50)
    ibov_exposure_max: float = _env_float("ESCUDO_IBOV_EXPOSURE_MAX", 0.80)
    ibov_correl_threshold: float = _env_float("ESCUDO_IBOV_CORREL_THRESHOLD", 0.50)


# ---------------------------------------------------------------------------
# Thresholds de negócio — RADAR (Módulo 2)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RadarCfg:
    # Fonte das oportunidades: "scanner" (cadeia completa com CLOSE/POE/IV — prêmio
    # SEMPRE real), "lucros" (aba de maiores lucros) ou "auto" (scanner se houver).
    fonte: str = _env("RADAR_FONTE", "auto")
    option_type: str = _env("RADAR_OPTION_TYPE", "PUT")
    iv_rank_min: float = _env_float("RADAR_IV_RANK_MIN", 50.0)
    spot_strike_ratio_min: float = _env_float("RADAR_SPOT_STRIKE_RATIO_MIN", 1.02)
    # Liquidez: piso de volume financeiro da opção e do ativo-mãe
    min_option_volume_fin: float = _env_float("RADAR_MIN_OPTION_VOLUME_FIN", 1.0)
    min_underlying_volume: float = _env_float("RADAR_MIN_UNDERLYING_VOLUME", 0.0)
    # Exigir tendência de alta da ação-mãe (M9M21_TREND == 1)?
    require_trend_up: bool = _env_bool("RADAR_REQUIRE_TREND_UP", False)
    # Descartar oportunidades em ação com tendência de BAIXA (M9M21_TREND == -1).
    # Padrão TRUE: venda de PUT / Trava de Alta são estratégias ALTISTAS — não faz
    # sentido vendê-las num ativo caindo. Aceita neutro (0) e alta (1); só corta a baixa.
    evitar_tendencia_baixa: bool = _env_bool("RADAR_EVITAR_TENDENCIA_BAIXA", True)
    # Gate de tendência multi-horizonte para NOVAS entradas (curto/médio/M9M21):
    # "off" = legado (só barra M9<M21); "medio" (padrão) = bloqueia BAIXA, REPIQUE
    # em baixa e M9<M21; "estrito" = só passa ALTA confirmada. Vender PUT em ação
    # caindo é apostar contra a maré — por isso o padrão já bloqueia de fato.
    trend_gate: str = _env("RADAR_TREND_GATE", "medio")
    # Diversificação: máximo de oportunidades por ativo-mãe no Top-N (0 = sem limite).
    max_por_ativo: int = _env_int("RADAR_MAX_POR_ATIVO", 2)
    # Restringir ao universo monitorado da aba DADOS_ATIVOS (com HAS_OPTIONS)?
    use_dados_ativos_whitelist: bool = _env_bool("RADAR_USE_WHITELIST", True)
    require_has_options: bool = _env_bool("RADAR_REQUIRE_HAS_OPTIONS", True)
    # Monte Carlo: só recomenda PUT com probabilidade de exercício <= poe_max
    use_montecarlo: bool = _env_bool("RADAR_USE_MONTECARLO", True)
    poe_max: float = _env_float("RADAR_POE_MAX", 0.25)
    # Janela de DTE (dias corridos) — sweet spot de venda de prêmio
    dte_min: int = _env_int("RADAR_DTE_MIN", 21)
    dte_max: int = _env_int("RADAR_DTE_MAX", 45)
    # Filtro de spread bid-ask por opção (precisa de BID/ASK na aba de lucros)
    use_spread_filter: bool = _env_bool("RADAR_USE_SPREAD_FILTER", False)
    bid_ask_spread_max: float = _env_float("RADAR_BID_ASK_SPREAD_MAX", 0.20)
    top_n: int = _env_int("RADAR_TOP_N", 5)
    # Trava de Alta com PUT (Bull Put Spread): em vez de PUT a seco (risco
    # ilimitado abaixo do strike), monta a trava comprando uma PUT mais OTM
    # para LIMITAR o risco. A perna comprada fica ~largura% abaixo do strike
    # vendido (busca o strike disponível mais próximo na cadeia).
    usar_trava: bool = _env_bool("RADAR_USAR_TRAVA", True)
    trava_largura_pct: float = _env_float("RADAR_TRAVA_LARGURA_PCT", 0.05)


# Instâncias prontas para importar
GOOGLE = Google()
OPLAB = OpLab()
EMAIL = Email()
RUNTIME = Runtime()
ESCUDO = EscudoCfg()
RADAR = RadarCfg()

# Dimensionamento de posição (0 = desabilita a sugestão de sizing no Radar)
CAPITAL_DISPONIVEL = _env_float("CAPITAL_DISPONIVEL", 0.0)
RISK_PER_TRADE = _env_float("RISK_PER_TRADE", 0.02)

# Auditoria: True = registra TODOS os passos/leituras/cálculos na aba LOGS.
AUDIT_VERBOSE = _env_bool("AUDIT_VERBOSE", True)

# Monte Carlo (probabilidade de exercício): nº de cenários, semente, drift (0 = sem tendência).
MC_N = _env_int("MC_N", 10000)
MC_SEED = _env_int("MC_SEED", 42)
MC_DRIFT = _env_float("MC_DRIFT", 0.0)


def cols(table: str) -> dict[str, str]:
    """Atalho para o mapa de colunas de uma tabela lógica."""
    return COLUMN_MAP[table]
