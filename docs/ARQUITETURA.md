# Arquitetura — ResearchDeOpcoes

> "Cérebro Local, Painel na Nuvem" — motor Python no Dell, painel no Google Sheets,
> pager por e-mail. Contorna a rede corporativa travada do Porto Bank.

## Visão geral

```
                 ┌──────────────────────────────────────────────┐
                 │            Google Sheets (Painel)            │
                 │  Painel_Ativas · SELECAO_* · RANKING_* ·     │
                 │  DADOS_ATIVOS · LOGS · *_HISTORICO           │
                 └───────────────▲───────────────▲──────────────┘
                                 │ gspread (lê)   │ gspread (grava)
                                 │                │
  OpLab API ──/market/status──►  ┌───────────────┴──────────────┐
  (relógio de ponto)             │      MOTOR (Dell · Python)    │
                                 │  main.py orquestra:          │
                                 │   1. lock  2. market_gate    │
                                 │   3. escudo  4. radar        │
                                 └───────────────┬──────────────┘
                                                 │ smtplib (SSL)
                                                 ▼
                                        E-mail (pager)
```

## Fluxo de uma execução (`main.py`)

1. **Lock-file** (`state.run_lock`) — impede duas instâncias simultâneas.
2. **Relógio de ponto** (`market_gate.check_market`) — `GET /market/status` na OpLab.
   Se `market_status != "A"`, **encerra** (poupa processamento/API). Se a OpLab
   estiver inacessível, **aborta por segurança** (não roda às cegas).
3. **Escudo** (`escudo.analyze`) — lê `Painel_Ativas`, avalia pernas vendidas.
4. **Radar** (`radar.scan`) — lê seleções, filtra oportunidades de PUT.
5. **Histórico + LOGS** — grava resultados nas abas e dá *flush* dos logs.

Erros de um módulo são capturados e logados (aba LOGS) sem derrubar o outro.

## Camadas (pacote `app/`)

| Arquivo | Responsabilidade |
|---|---|
| `config.py` | `.env` + **mapa de colunas** (`COLUMN_MAP`) + thresholds. Ponto único de reconciliação de schema. |
| `parsing.py` | Limpa `R$`, `%`, milhar, parênteses; parse de datas; DTE. |
| `sheets_client.py` | gspread: lê aba → DataFrame (com `header_row`), grava linhas (cria aba se faltar). |
| `frames.py` | Acesso a colunas por nome **lógico**. |
| `logbook.py` | Logs em 3 destinos: aba LOGS, arquivo, stdout. |
| `market_gate.py` | Consulta OpLab `/market/status`. |
| `notifier.py` | E-mail (SMTP/SSL): alerta urgente (Escudo) e oportunidade (Radar). |
| `state.py` | Lock, dedupe de alertas/oportunidades, marca de última execução. |
| `escudo.py` | **Módulo 1** — regra de defesa por moneyness. |
| `radar.py` | **Módulo 2** — filtros de prospecção. |

## Regra do Escudo (perna vendida), por moneyness

Combina 3 sinais — múltiplo de recompra (`LAST_PREMIUM/ENTRY_PRICE`), `|Delta|`
e perda vs. `MAX_LOSS` (+ DTE) — com severidade crescente:

| Zona | ALERTA | CRÍTICO (e-mail) |
|---|---|---|
| OTM | recompra ≥ 2.0× **ou** \|Δ\| ≥ 0.30 | \|Δ\| ≥ 0.35 **ou** recompra ≥ 3.0× |
| ATM | baseline + recompra ≥ 1.5× **ou** \|Δ\| ≥ 0.45 | DTE ≤ 15 **ou** perda ≥ 50% do MAX_LOSS |
| ITM | baseline (sempre) | DTE ≤ 15 **ou** perda ≥ 50% do MAX_LOSS |

Todos os números em `.env` (`ESCUDO_*`). E-mail urgente só em `ALERTA`/`CRÍTICO`;
`AVISO` fica em LOGS/histórico. Dedupe: 1 alerta/opção/dia, re-dispara se escalar.

## Filtros do Radar

`CATEGORY == PUT` · `IV_RANK ≥ 50` · `SPOT_STRIKE_RATIO ≥ 1.02` ·
`VOLUME_FIN > piso` (liquidez) · (opcional) tendência M9M21 = alta ·
(opcional) universo `DADOS_ATIVOS`. Ranqueia por `PROFIT_RATE` e `IV_RANK`,
envia Top-N. Parâmetros em `.env` (`RADAR_*`).

## Resiliência (Windows / Task Scheduler)

- **Catch-up pós-reboot:** trigger horário com `-StartWhenAvailable` roda a
  ocorrência perdida assim que o PC liga; + trigger `AtStartup`.
- **Resiliência a bugs:** `-RestartCount 3` / `-RestartInterval 1min`.
- **Execução única:** lock-file (`-MultipleInstances IgnoreNew` + `filelock`).
- **Idempotência:** dedupe diário evita e-mails repetidos a cada hora.

Ver `scripts/install_tasks.ps1`.
