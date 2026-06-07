# Arquitetura — ResearchDeOpcoes

> "Cérebro Local, Painel na Nuvem" — motor Python no Dell, painel no Google Sheets,
> pager por e-mail. Contorna a rede corporativa travada do Porto Bank.

## Visão geral

```
                 ┌──────────────────────────────────────────────┐
                 │            Google Sheets (Painel)            │
                 │  Painel_Ativas · SCANNER_OPCOES · SELECAO_* ·│
                 │  RANKING_* · DADOS_ATIVOS · LOGS · *_HISTORICO│
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
4. **Radar** (`radar.scan_scanner` / `radar.scan`) — lê o `SCANNER_OPCOES` (ou as
   seleções), filtra oportunidades de PUT e monta a Trava de Alta.
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
| `montecarlo.py` | Simulação GBM da probabilidade de exercício (PoE) — vol IV + realizada. |
| `notifier.py` | E-mail (SMTP/SSL): alerta urgente (Escudo) e oportunidade (Radar). |
| `state.py` | Lock, dedupe de alertas/oportunidades, marca de última execução. |
| `risk_metrics.py` | Métricas de carteira (HHI, exposição IBOV, sizing, spread). |
| `escudo.py` | **Módulo 1** — defesa por perna (moneyness) + carteira. |
| `radar.py` | **Módulo 2** — prospecção: `scan_scanner` (scanner) e `scan` (lucros). |

## Regra do Escudo (perna vendida), por moneyness

`DELTA`, `POE` (prob. de exercício) e `DTE_CALENDAR` são lidos direto da
PAINEL_ATIVAS. Combina múltiplo de recompra (`LAST_PREMIUM/ENTRY_PRICE`),
`|Delta|`, perda vs. `MAX_LOSS` e proximidade de vencimento:

| Zona | AVISO (só log) | ALERTA (e-mail) | CRÍTICO (e-mail) |
|---|---|---|---|
| OTM | vence em ≤ 15d (saudável) | recompra ≥ 2.0× **ou** \|Δ\| ≥ 0.30 | \|Δ\| ≥ 0.35 **ou** recompra ≥ 3.0× **ou** perda ≥ 50% |
| ATM | baseline (gamma alto) | recompra ≥ 1.5× **ou** (DTE ≤ 15 **e** perdendo) | perda ≥ 50% do MAX_LOSS |
| ITM | — | baseline (sempre) | DTE ≤ 15 **ou** perda ≥ 50% do MAX_LOSS |

A banda de `|Δ|` atua **só na zona OTM** (early-warning de drift): em ATM/ITM o
`|Δ|` já é alto por natureza e o que manda é moneyness + DTE + perda. `Gamma`
alto (≥ `ESCUDO_GAMMA_MAX`) adiciona um AVISO de "pré-perigo" (aceleração).
Números em `.env` (`ESCUDO_*`). E-mail só em `ALERTA`/`CRÍTICO`; `AVISO` fica em
LOGS/histórico. Dedupe: 1 alerta/opção/dia, re-dispara se escalar de nível.

### Risco de carteira (agregado)
Além da análise por perna, o Escudo avalia a carteira como um todo
(`escudo.analyze_portfolio`, pesos = `NOTIONAL`):
- **HHI setorial** — índice de concentração por setor. `HHI > 0.50` → ALERTA.
- **Exposição ao IBOV** — fração do portfólio em ativos com `|correlação| ≥ 0.50`
  (de `RANKING_CORREL_IBOV`). `> 80%` → ALERTA de risco direcional sistêmico.

## Módulo 2 — Radar (prospecção de PUTs)

### Fonte das oportunidades (`RADAR_FONTE`)
- **`scanner`** — lê a aba **`SCANNER_OPCOES`** (cadeia completa de opções, ~2000
  linhas). O prêmio é **sempre o `CLOSE` real** da planilha e a Trava de Alta usa
  pernas do **mesmo vencimento**. Fonte primária.
- **`lucros`** — lê `SELECAO_OPCOES_MAIORES_LUCROS`. O prêmio vem do scanner
  quando a opção casa; senão é **estimado** (`VE/strike`, marcado com `≈`).
- **`auto`** (padrão) — usa o scanner quando ele tem linhas; senão, a aba de lucros.

### Funil de filtros (estágio a estágio nos LOGS)
`é PUT` (por `CATEGORY` **ou** `TYPE`) · prêmio `CLOSE` válido (`0 < prêmio <
strike`) · `IV_RANK ≥ 50` (cruzado de `DADOS_ATIVOS`; ativo fora do universo não
é barrado) · distância `spot/strike ≥ 1.02` (OTM com margem) · `VOLUME_FIN ≥
piso` (liquidez) · `DTE ∈ [min, max]` · (opcional) descarta tendência de **baixa**
M9<M21 · universo monitorado `DADOS_ATIVOS` (`HAS_OPTIONS = TRUE`).

### Porteiro de risco — PoE (probabilidade de exercício)
O teto `POE_MAXIMA` (padrão 25%) é **sempre** aplicado. A PoE de cada opção vem,
em ordem: do **Monte Carlo** (`montecarlo.poe_resumo`, GBM com vol IV e realizada,
gate = pior caso) quando há vol do ativo em `DADOS_ATIVOS`; senão, da **POE da
planilha** (OpLab, risk-neutral). Cada oportunidade registra a **fonte da PoE**.

### Trava de Alta com PUT (Bull Put Spread)
Em vez de PUT a seco (risco ilimitado abaixo do strike), o motor monta a trava:
**vende** a PUT da oportunidade e **compra** uma PUT mais OTM (~`RADAR_TRAVA_LARGURA_PCT`
abaixo, padrão 5%), escolhendo na cadeia o strike disponível mais próximo do alvo
e do **mesmo vencimento**. Resultado: crédito, **risco máximo limitado** (largura −
crédito) e retorno/risco. Sem perna de proteção, o motivo é explicado nos LOGS.

### Ranking, diversificação e sizing
Ordena por taxa de retorno (`prêmio/strike`) e `IV_RANK`. **Diversificação:**
no máximo `RADAR_MAX_POR_ATIVO` (padrão 2) oportunidades por ativo-mãe, depois
corta no `RADAR_TOP_N`. Se `CAPITAL_DISPONIVEL > 0`, sugere o nº de contratos
(margem-proxy = `strike × 100`, risco de `RISK_PER_TRADE` por trade). Ações em
tendência de **baixa** (M9<M21) levam um **aviso direcional** no e-mail e nos LOGS.

### `EXPIRY` serial do Sheets
O `EXPIRY` do scanner vem como **número serial** (e às vezes com fração de hora,
ex.: `46192.58` = 19/06/2026 ~14h). `_fmt_expiry` auto-detecta o separador e só
converte dentro de uma faixa plausível (40000–60000), evitando overflow de data.

Parâmetros em `.env` / aba `CONFIG` (`RADAR_*`, `POE_MAXIMA`, `USAR_MONTECARLO`).

## Locale numérico por aba

PAINEL_ATIVAS e DADOS_ATIVOS são **pt-BR** (vírgula decimal, ponto de milhar:
`R$ 1.285,00`, `-0,72`); SELECAO_*/RANKING_* são **US/ISO** (`1.0133`). O parser
recebe o separador correto por aba (`TabSpec.decimal_sep`), evitando que `1.000`
vire `1.0`.

## Deploy: nuvem (GitHub Actions) ou local (Windows)

**Nuvem (recomendado, `.github/workflows/motor.yml`):** roda de hora em hora
(cron 13–21 UTC = 10h–18h BRT, seg–sex) na infraestrutura do GitHub. Segredos
em GitHub Secrets (token, credenciais JSON, e-mail). O estado de dedupe é
persistido entre execuções via `actions/cache` (cada run é efêmero). `concurrency`
evita sobreposição (substitui o lock-file). `workflow_dispatch` permite rodar
manualmente com modo dry-run. Não depende de PC ligado.

**Local (Windows / Task Scheduler):** veja abaixo.

## Resiliência (Windows / Task Scheduler)

- **Catch-up pós-reboot:** trigger horário com `-StartWhenAvailable` roda a
  ocorrência perdida assim que o PC liga; + trigger `AtStartup`.
- **Resiliência a bugs:** `-RestartCount 3` / `-RestartInterval 1min`.
- **Execução única:** lock-file (`-MultipleInstances IgnoreNew` + `filelock`).
- **Idempotência:** dedupe diário evita e-mails repetidos a cada hora.

Ver `scripts/install_tasks.ps1`.
