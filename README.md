# ResearchDeOpcoes

Motor quantitativo de análise de opções da **B3**, com dupla função:

- 🛡️ **Escudo** — defesa das posições ativas (alertas urgentes de risco).
- 🎯 **Radar** — prospecção de prêmios (oportunidades de venda de PUT).

Arquitetura **"Cérebro Local, Painel na Nuvem"**: o motor Python roda no
notebook de casa (via Windows Task Scheduler, de hora em hora no pregão), lê
o painel no **Google Sheets**, consulta o **relógio de ponto** na OpLab e
dispara **alertas por e-mail**. Detalhes em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

## Instalação (Dell / Windows)

```powershell
git clone https://github.com/brunotrolo/ResearchDeOpcoes.git
cd ResearchDeOpcoes
.\scripts\setup.ps1          # cria .venv, instala deps, gera .env
```

Depois:

1. Edite **`.env`** (`SPREADSHEET_ID`, `OPLAB_TOKEN`, `EMAIL_*`). Veja `.env.example`.
2. Coloque o **`credenciais.json`** (Service Account) na raiz.
3. Compartilhe a planilha-espelho com o e-mail da Service Account (leitura/edição).

## Uso

```powershell
# Execução manual (teste). Use DRY_RUN=true no .env para não enviar e-mail/gravar.
.venv\Scripts\python.exe main.py

# Testes
.venv\Scripts\python.exe -m pytest -q

# Agendar (catch-up pós-reboot + restart em caso de bug)
.\scripts\install_tasks.ps1
```

O motor **só processa com o mercado aberto** (`/market/status == "A"`); fora
disso, encerra na hora. Tudo é registrado na aba **LOGS** para debug.

## Configuração

- Abas lidas: `Painel_Ativas`, `SELECAO_OPCOES_MAIORES_LUCROS`,
  `SELECAO_MAIORES_VOLUMES`, `RANKING_TENDENCIA_M9M21`, `RANKING_CORREL_IBOV`,
  `DADOS_ATIVOS`.
- Abas escritas: `LOGS`, `ESCUDO_HISTORICO`, `RADAR_HISTORICO` (criadas se faltarem).
- Mapa de colunas e thresholds: [`app/config.py`](app/config.py).

> ⚠️ Não versione segredos. `.env`, `credenciais.json` e `state/` estão no `.gitignore`.
> Este software é uma ferramenta de apoio; não constitui recomendação de investimento.
