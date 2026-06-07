# ResearchDeOpcoes

Motor quantitativo de análise de opções da **B3**, com dupla função:

- 🛡️ **Escudo** — defesa das posições ativas: alertas por perna (moneyness, Δ,
  POE, recompra, DTE, perda) **e por carteira** (concentração setorial via HHI,
  exposição direcional ao IBOV).
- 🎯 **Radar** — prospecção de prêmios: venda de PUT com IV Rank alto, OTM com
  margem, na janela de DTE certa e líquida.

O motor lê o painel no **Google Sheets**, consulta o **relógio de ponto** na
OpLab e dispara **alertas por e-mail**. Roda de hora em hora no pregão.
Arquitetura detalhada em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

Há **dois jeitos de rodar**: na **nuvem do GitHub** (recomendado, sem depender
de PC ligado) ou **local no Windows**.

---

## ☁️ Rodar na nuvem (GitHub Actions) — recomendado, sem Dell

O motor roda sozinho na infraestrutura do GitHub, de hora em hora durante o
pregão. Você não precisa de PC ligado e controla tudo pelo site do GitHub
(que abre no celular). Os segredos ficam **criptografados** no GitHub.

### Passo 1 — Cadastrar os segredos
No GitHub, vá em **Settings → Secrets and variables → Actions →
New repository secret** e cadastre **6 segredos** (um por vez):

| Nome do segredo | Valor |
|---|---|
| `OPLAB_TOKEN` | seu token da OpLab |
| `SPREADSHEET_ID` | `1zuYr3lTOSsVJzvrBJezZ5hFMIM3jpt2jDfR8uCapKds` |
| `GOOGLE_CREDENTIALS_JSON` | **todo o conteúdo** do `credenciais.json` (abra no Bloco de Notas, Ctrl+A, Ctrl+C, cole) |
| `EMAIL_USER` | seu_email@gmail.com |
| `EMAIL_APP_PASSWORD` | a senha de app de 16 letras do Gmail |
| `ALERT_RECIPIENTS` | brunotrolo@gmail.com |

### Passo 2 — Testar (sem enviar nada)
Aba **Actions** → workflow **"Motor (Escudo + Radar)"** → **Run workflow** →
deixe **"Modo teste?"** marcado → **Run**. Veja os logs do run (ele lê tudo,
mas **não** envia e-mail nem grava). Confira também a aba **LOGS** da planilha.

### Passo 3 — Deixar no ar
Pronto: as execuções **agendadas** (10h–18h, seg–sex) já rodam pra valer
automaticamente. Para um teste real manual, rode pelo **Run workflow** com
**"Modo teste?"** desmarcado.

> 🔐 Depois que estiver rodando, **gere uma chave nova** do Service Account e um
> **token novo** na OpLab (eles passaram pelo chat) e atualize os segredos.

---

---

## 💻 Alternativa: rodar local (Windows)

### Passo 1 — Pré-requisitos
- **Python 3.11+** ([python.org](https://www.python.org/downloads/) — marque *"Add Python to PATH"* na instalação).
- **Git** ([git-scm.com](https://git-scm.com/download/win)).

### Passo 2 — Clonar e instalar
Abra o **PowerShell** e rode:
```powershell
git clone https://github.com/brunotrolo/ResearchDeOpcoes.git
cd ResearchDeOpcoes
.\scripts\setup.ps1     # cria .venv, instala dependências e gera o .env
```

### Passo 3 — Credenciais do Google (Service Account) 🔑
Esta etapa é **manual no console do Google** (feita uma vez):
1. Acesse [console.cloud.google.com](https://console.cloud.google.com/) e crie um **projeto** (ex.: "ResearchOpcoes").
2. Menu **APIs e Serviços → Biblioteca** → ative **Google Sheets API** e **Google Drive API**.
3. **APIs e Serviços → Credenciais → Criar credenciais → Conta de serviço**. Dê um nome e crie.
4. Na conta de serviço criada → aba **Chaves → Adicionar chave → Criar nova chave → JSON**. Baixa um arquivo `.json`.
5. Renomeie esse arquivo para **`credenciais.json`** e coloque na **raiz** do projeto.
6. Abra o `credenciais.json`, copie o e-mail do campo `client_email`
   (algo como `...@...iam.gserviceaccount.com`).
7. Na sua **planilha-espelho** do Google Sheets, clique em **Compartilhar** e
   adicione esse e-mail como **Editor** (precisa editar para gravar LOGS/histórico).

### Passo 4 — Token da OpLab
Pegue seu token em [oplab.com.br](https://oplab.com.br) (área de conta/API). Ele
é usado só para o `GET /v3/market/status` (o relógio de ponto).

### Passo 5 — Senha de app do Gmail (para enviar e-mail)
1. Ative a **verificação em 2 etapas** na sua conta Google.
2. Vá em [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords),
   gere uma **senha de app** e copie os 16 caracteres. (Não é sua senha normal!)

### Passo 6 — Preencher o `.env`
Abra o arquivo `.env` (criado no passo 2) e preencha:
```dotenv
SPREADSHEET_ID=<id da planilha-espelho — está na URL entre /d/ e /edit>
OPLAB_TOKEN=<token do passo 4>
EMAIL_USER=seu_email@gmail.com
EMAIL_APP_PASSWORD=<senha de app do passo 5>
ALERT_RECIPIENTS=brunotrolo@gmail.com
```
Os demais parâmetros (thresholds do Escudo/Radar) já vêm com defaults sensatos —
veja `.env.example` para a lista completa.

### Passo 7 — Teste seco (DRY-RUN) com a B3 aberta ⚠️
> O maior risco operacional não é o código — é um alerta ilegível no celular às
> 14h30. **Faça o dry-run e confira o e-mail antes de automatizar.**

No `.env`, coloque `DRY_RUN=true` e rode manualmente:
```powershell
.venv\Scripts\python.exe main.py
```
Confira a saída do console e `logs/motor.log`. Depois, com `DRY_RUN=false`,
rode de novo **com o mercado aberto** e verifique se o e-mail chega **formatado e
legível no celular**.

### Passo 8 — Agendar (produção)
```powershell
.\scripts\install_tasks.ps1   # rode o PowerShell como Administrador
```
Cria duas tarefas no **Agendador de Tarefas**: horária (10h–17h, seg–sex, com
**catch-up** se o PC estava desligado) e uma na inicialização (pós-reboot), com
**restart automático** em caso de bug.

---

## 🔭 Observabilidade & Auditoria

**Auditoria completa (aba LOGS):** com `AUDIT_VERBOSE=true` (padrão), cada ciclo
registra TUDO — início/fim, resposta da OpLab, cada leitura de aba (linhas +
colunas), as métricas de carteira calculadas (HHI, exposição IBOV), o **funil**
de filtros do Radar (quantas opções sobraram em cada etapa), os alertas e
oportunidades detalhados e o resultado dos e-mails. O detalhe item-a-item fica
nas abas `ESCUDO_HISTORICO` / `RADAR_HISTORICO`.

**Heartbeat (aba MONITOR):** a cada execução o motor sobrescreve 1 linha com
status, mercado, duração, nº de alertas/oportunidades e o link da execução no
GitHub. É o "sinal de vida".

**Painel de status + vigia (Apps Script):** [`docs/monitor.gs`](docs/monitor.gs)
é um Web App que mostra uma página 🟢/🟡/🔴 (abre no celular) lendo o heartbeat,
e um **dead-man's switch**: um gatilho de tempo que te manda e-mail se o motor
**não bater ponto durante o pregão** (ou seja, parou). Instruções de deploy no
topo do arquivo.

**Testes (sem depender do mercado):** 30 testes cobrem parser, Escudo (por perna
+ carteira), Radar, métricas de risco, o relógio de ponto e o **orquestrador
inteiro** (mercado fechado, OpLab fora do ar, alerta crítico, oportunidade) com
as dependências mockadas. Rode quando quiser:
```bash
python -m pytest -q
```

## Uso no dia a dia
```powershell
.venv\Scripts\python.exe main.py            # rodar agora
.venv\Scripts\python.exe -m pytest -q       # rodar os testes (24)
```
O motor **só processa com o mercado aberto** (`/market/status == "A"`); fora
disso, encerra na hora. Tudo é registrado na aba **LOGS** para debug.

## Configuração
- **Abas lidas:** `Painel_Ativas`, `SELECAO_OPCOES_MAIORES_LUCROS`,
  `SELECAO_MAIORES_VOLUMES`, `RANKING_TENDENCIA_M9M21`, `RANKING_CORREL_IBOV`,
  `DADOS_ATIVOS`.
- **Abas escritas:** `LOGS`, `ESCUDO_HISTORICO`, `RADAR_HISTORICO` (criadas se faltarem).
- **Mapa de colunas e thresholds:** [`app/config.py`](app/config.py) (tudo no `.env`).

## Notas técnicas
- Usamos **`google-auth`** (não o `oauth2client`, que está **descontinuado** pelo Google).
- Agendamos via **Windows Task Scheduler** (não a lib `schedule`), pois o modelo é
  de execução horária — não um processo vivo 24/7. Em Linux/WSL, o equivalente é
  o cron: `0 10-17 * * 1-5 cd /caminho/repo && .venv/bin/python main.py >> logs/cron.log 2>&1`.

> ⚠️ Não versione segredos. `.env`, `credenciais.json` e `state/` estão no `.gitignore`.
> Este software é uma ferramenta de apoio; **não constitui recomendação de investimento**.
