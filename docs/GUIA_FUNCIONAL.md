# Guia Funcional — ResearchDeOpcoes

Este guia explica, **sem código**, o que o motor faz, o que chega no seu e-mail,
o que ele grava na planilha e como interpretar cada número. Para a parte técnica
(módulos, fluxo, deploy) veja [`ARQUITETURA.md`](ARQUITETURA.md); para os
parâmetros da aba CONFIG, veja [`CONFIG.md`](CONFIG.md).

---

## 1. O que o motor faz

A cada execução (manual, pelo GitHub Actions), o motor:

1. Confere se está **dentro do pregão** (relógio de ponto: dias úteis 10:00–16:30).
   Fora do horário, encerra para poupar processamento.
2. Roda a **defesa** das suas posições abertas (🛡️ **Escudo**).
3. Roda a **prospecção** de novas oportunidades de venda de PUT (🎯 **Radar**).
4. Atualiza os **painéis** na planilha, grava o **histórico** e os **LOGS**, e
   manda **e-mail** quando há algo que merece sua atenção.

Você controla tudo pela aba **CONFIG** (pelo celular) — sem mexer em código.

---

## 2. 🛡️ Escudo — defesa das posições abertas

Lê a aba `PAINEL_ATIVAS` (suas pernas vendidas) e classifica cada posição em
**três níveis**:

| Nível | Significa | Vai pro e-mail? |
|---|---|---|
| 🟢 **AVISO** | Vigiar (ex.: gamma alto, vencimento próximo, mas saudável) | Não (só LOGS/painel) |
| 🟡 **ALERTA** | Pede ação: recompra cara, ITM, \|Δ\| subindo | Sim |
| 🔴 **CRÍTICO** | Risco de exercício: muito ITM, perto de vencer, perda grande | Sim |

Cada alerta traz **por que** disparou (os "gatilhos"), a **ação sugerida**
(monitorar, preparar rolagem, encerrar) e uma análise em texto. Também há uma
camada de **risco de carteira**: concentração setorial (HHI) e exposição ao IBOV.

> O Escudo só te incomoda por e-mail no que importa (ALERTA/CRÍTICO). Um mesmo
> alerta não repete no mesmo dia, a não ser que **piore de nível**.

**Aviso ANTES de dar ruim (preditivo):** além de reagir ao que já está ruim, o
Escudo usa o Monte Carlo para calcular a **probabilidade de TOQUE** — a chance de
uma posição **OTM virar ATM/ITM antes do vencimento**. Se essa chance for alta, a
posição (mesmo "saudável" hoje) sobe para AVISO/ALERTA com a ação *"prepare
rolagem/defesa antes"*. Ele também mostra quanto essa chance aumenta **se a
tendência atual continuar**.

---

## 3. 🎯 Radar — prospecção de venda de PUT

Varre a cadeia de opções (`SCANNER_OPCOES`) e devolve as **melhores
oportunidades** de venda de PUT, já como **Trava de Alta** (risco limitado).

### Como uma oportunidade é escolhida (o funil)
1. É uma **PUT** com **prêmio real** (campo `CLOSE` da planilha).
2. **IV Rank alto** (volatilidade cara = prêmio gordo).
3. **OTM com margem** (o spot está acima do strike — distância de segurança).
4. **Líquida** (tem volume financeiro).
5. **Dentro da janela de DTE** (dias até o vencimento) que você definiu.
6. **Probabilidade de exercício (PoE) abaixo do teto** (`POE_MAXIMA`).
7. **Diversificada** (no máximo N por ativo, pra não recomendar 5 do mesmo papel).
8. **Coerente com a direção**: venda de PUT / Trava de Alta são estratégias
   **altistas**, então ações em **tendência de baixa** (M9<M21) são **descartadas
   por padrão** (você pode reativar na CONFIG). Cada oportunidade também mostra a
   **probabilidade de TOQUE** do strike vendido.

### O que é a "Trava de Alta com PUT" (Bull Put Spread)
Em vez de vender uma PUT "a seco" (risco que cresce sem limite se a ação cair
muito), o motor monta a trava:
- **Vende** a PUT da oportunidade (recebe o prêmio).
- **Compra** uma PUT mais barata, com strike ~5% abaixo (paga um prêmio menor).

Você recebe um **crédito líquido** e seu **risco fica limitado** (a perna comprada
funciona como seguro). O e-mail mostra crédito, **risco máximo** e a relação
**retorno/risco**.

### O que chega no e-mail do Radar
Para cada oportunidade: ticker e estratégia, **prêmio (CLOSE)**, spot, strike,
distância (margem), IV Rank, taxa de retorno, **PoE** (com a fonte: Monte Carlo
ou OpLab), volume, o bloco da **Trava** (pernas, crédito, risco) e o **porquê**.
Se a ação estiver em **tendência de baixa** (M9<M21), aparece um **aviso
direcional** ⚠️ — vender PUT contra a maré é mais arriscado.

---

## 4. O que o motor grava na planilha

| Aba | Quem escreve | Para quê |
|---|---|---|
| `PAINEL_ESCUDO` | Escudo (sobrescreve) | Estado atual das defesas (alimenta o web app) |
| `PAINEL_RADAR` | Radar (sobrescreve) | Oportunidades atuais (alimenta o web app) |
| `ESCUDO_HISTORICO` | Escudo (anexa) | Histórico de alertas |
| `RADAR_HISTORICO` | Radar (anexa) | Histórico de oportunidades |
| `LOGS` | Sempre | Auditoria passo a passo de cada execução |
| `MONITOR` | Sempre (1 linha) | "Sinal de vida": status, hora, duração da última rodada |

E as abas que ele **lê** (alimentadas pelas suas automações/OpLab):
`PAINEL_ATIVAS`, `SCANNER_OPCOES`, `DADOS_ATIVOS`, `SELECAO_*`, `RANKING_CORREL_IBOV`,
`CONFIG`.

> **Importante sobre o `SCANNER_OPCOES`:** o Radar só enxerga os vencimentos que
> estiverem nessa aba. Se ela só tiver o vencimento da semana (DTE curto) e a sua
> janela for `DTE 21–45`, **nada aparece** — e os LOGS avisam exatamente isso,
> dizendo quais DTEs existem. Alimente o scanner com os vencimentos que você opera.

---

## 5. 📊 Painel web (monitor.gs)

Um web app (Google Apps Script) que mostra os painéis `PAINEL_ESCUDO` e
`PAINEL_RADAR` num visual bonito e responsável (celular e desktop), com cartões,
chips de métricas, o bloco da Trava e a etiqueta de estratégia (📉 Venda de PUT /
🛡️ Trava de Alta). Atualiza ao recarregar. O arquivo fica em `docs/monitor.gs` e
precisa ser **colado no editor do Apps Script** e reimplantado quando muda.

---

## 6. Glossário rápido

| Termo | O que é |
|---|---|
| **Prêmio (CLOSE)** | Quanto o mercado paga pela opção — o preço real de fechamento |
| **IV Rank** | Onde a volatilidade implícita está no ano (0–100). Alto = prêmio caro |
| **DTE** | *Days To Expiry* — dias corridos até o vencimento |
| **Moneyness** | OTM (fora do dinheiro), ATM (no dinheiro), ITM (dentro) |
| **Distância / margem** | Quanto o spot está acima do strike (folga até virar ITM) |
| **PoE** | Probabilidade de exercício — chance de a PUT terminar ITM **no vencimento** (quanto menor, mais seguro) |
| **Toque** | Probabilidade de o preço **tocar o strike** (virar ATM/ITM) em **algum momento** antes de vencer. É sempre ≥ a PoE — mede o risco do caminho, não só do desfecho |
| **Delta (Δ) / Gamma (γ)** | Sensibilidade do preço da opção ao ativo / aceleração dessa sensibilidade |
| **M9 / M21** | Médias móveis de 9 e 21 períodos. M9 > M21 = tendência de alta |
| **Trava de Alta (Bull Put Spread)** | Vender uma PUT + comprar outra mais OTM = crédito com risco limitado |
| **Taxa de retorno** | Prêmio ÷ strike (quanto a venda rende sobre o capital exigido) |

---

## 7. "Não apareceu nada" — o que checar

1. **Mercado fechado?** Fora do pregão o motor encerra (a não ser em homologação).
2. **`SCANNER_OPCOES` alimentado?** E com os **vencimentos** que batem com sua
   janela `RADAR_DTE_MIN/MAX`? Os LOGS dizem quais DTEs existem.
3. **Filtros muito apertados?** IV Rank mínimo, distância OTM, PoE máxima — afrouxe
   na CONFIG e rode de novo.
4. **E-mail desligado?** Veja `ENVIAR_EMAIL` / `ENVIAR_EMAIL_RADAR` na CONFIG.
5. **Olhe os LOGS** — o funil mostra, estágio a estágio, **quantas opções
   sobreviveram a cada filtro** e por que as demais caíram.

> ⚠️ O motor **não é recomendação de investimento** — é uma ferramenta de apoio à
> decisão. A responsabilidade pelas ordens é sempre sua.
