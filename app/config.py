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
    # PAINEL_ATIVAS e DADOS_ATIVOS estão em pt-BR (vírgula decimal, ponto de milhar).
    "ativas":       TabSpec(_env("TAB_ATIVAS", "Painel_Ativas"),                _env_int("TAB_ATIVAS_HEADER_ROW", 1),       _env("TAB_ATIVAS_DECIMAL", ",")),
    "lucros":       TabSpec(_env("TAB_LUCROS", "SELECAO_OPCOES_MAIORES_LUCROS"), _env_int("TAB_LUCROS_HEADER_ROW", 1),       _env("TAB_LUCROS_DECIMAL", ".")),
    "volumes":      TabSpec(_env("TAB_VOLUMES", "SELECAO_MAIORES_VOLUMES"),     _env_int("TAB_VOLUMES_HEADER_ROW", 1),       _env("TAB_VOLUMES_DECIMAL", ".")),
    "m9m21":        TabSpec(_env("TAB_M9M21", "RANKING_TENDENCIA_M9M21"),       _env_int("TAB_M9M21_HEADER_ROW", 1),         _env("TAB_M9M21_DECIMAL", ".")),
    "correl":       TabSpec(_env("TAB_CORREL", "RANKING_CORREL_IBOV"),          _env_int("TAB_CORREL_HEADER_ROW", 1),        _env("TAB_CORREL_DECIMAL", ".")),
    "dados_ativos": TabSpec(_env("TAB_DADOS_ATIVOS", "DADOS_ATIVOS"),           _env_int("TAB_DADOS_ATIVOS_HEADER_ROW", 1), _env("TAB_DADOS_ATIVOS_DECIMAL", ",")),
}

# Abas de escrita (logs + histórico). Criadas automaticamente se não existirem.
TAB_LOGS = _env("TAB_LOGS", "LOGS")
TAB_HIST_ESCUDO = _env("TAB_HIST_ESCUDO", "ESCUDO_HISTORICO")
TAB_HIST_RADAR = _env("TAB_HIST_RADAR", "RADAR_HISTORICO")

# Cabeçalho fixo da aba LOGS (conforme especificado pelo Bruno)
LOGS_HEADER = ["UPDATED_AT", "SERVICE", "STATUS", "SUMMARY", "CONTEXT"]

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
        "pl_pct": "PL_PCT",
        "max_gain": "MAX_GAIN",
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
        "bid": "BID",                  # opcional (espelhar SCANNER_OPCOES p/ filtro de spread)
        "ask": "ASK",                  # opcional
        "profit_rate": "PROFIT_RATE_IF_EXERCISED",
        "m9m21_trend": "M9M21_TREND",
        "sector": "SECTOR",
        "company": "COMPANY_NAME",
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
        "oplab_score": "OPLAB_SCORE",
    },
    "correl": {
        "ticker": "TICKER",
        "correl_value": "CORREL_VALUE",
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
    option_type: str = _env("RADAR_OPTION_TYPE", "PUT")
    iv_rank_min: float = _env_float("RADAR_IV_RANK_MIN", 50.0)
    spot_strike_ratio_min: float = _env_float("RADAR_SPOT_STRIKE_RATIO_MIN", 1.02)
    # Liquidez: piso de volume financeiro da opção e do ativo-mãe
    min_option_volume_fin: float = _env_float("RADAR_MIN_OPTION_VOLUME_FIN", 1.0)
    min_underlying_volume: float = _env_float("RADAR_MIN_UNDERLYING_VOLUME", 0.0)
    # Exigir tendência de alta da ação-mãe (M9M21_TREND == 1)?
    require_trend_up: bool = _env_bool("RADAR_REQUIRE_TREND_UP", False)
    # Restringir ao universo monitorado da aba DADOS_ATIVOS (com HAS_OPTIONS)?
    use_dados_ativos_whitelist: bool = _env_bool("RADAR_USE_WHITELIST", True)
    require_has_options: bool = _env_bool("RADAR_REQUIRE_HAS_OPTIONS", True)
    # Janela de DTE (dias corridos) — sweet spot de venda de prêmio
    dte_min: int = _env_int("RADAR_DTE_MIN", 21)
    dte_max: int = _env_int("RADAR_DTE_MAX", 45)
    # Filtro de spread bid-ask por opção (precisa de BID/ASK na aba de lucros)
    use_spread_filter: bool = _env_bool("RADAR_USE_SPREAD_FILTER", False)
    bid_ask_spread_max: float = _env_float("RADAR_BID_ASK_SPREAD_MAX", 0.20)
    top_n: int = _env_int("RADAR_TOP_N", 5)


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


def cols(table: str) -> dict[str, str]:
    """Atalho para o mapa de colunas de uma tabela lógica."""
    return COLUMN_MAP[table]
