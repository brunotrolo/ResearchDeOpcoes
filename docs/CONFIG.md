# Aba CONFIG — painel de controle (sem código)

A aba **CONFIG** (colunas `CHAVE` · `VALOR` · `DESCRICAO`) controla **toda a
estratégia pela planilha** — você edita a coluna `VALOR` (pelo celular) e vale na
próxima execução. A aba é criada automaticamente; chaves novas são **anexadas**
sozinhas (sem apagar o que você editou).

Regras gerais:
- `TRUE`/`FALSE` aceitam também `SIM`/`NAO`, `1`/`0` (sem ligar pra maiúscula/acento).
- Números aceitam ponto ou vírgula (`0.30` ou `0,30`).
- Deixar o `VALOR` em branco = usa o padrão do código.

## ✉️ E-mail
| CHAVE | Exemplo | Aceita | O que faz |
|---|---|---|---|
| `ENVIAR_EMAIL` | `TRUE` | TRUE/FALSE | **Mestre**: desliga **todos** os e-mails de uma vez |
| `ENVIAR_EMAIL_ESCUDO` | `TRUE` | TRUE/FALSE | E-mail de **defesa de posições** |
| `ENVIAR_EMAIL_RADAR` | `TRUE` | TRUE/FALSE | E-mail de **oportunidades** |
| `ESCUDO_NIVEL_MINIMO_EMAIL` | `ALERTA` | ALERTA / CRITICO | Só manda e-mail de Escudo deste nível pra cima |

## 🎲 Monte Carlo (probabilidade de exercício)
| CHAVE | Exemplo | Aceita | O que faz |
|---|---|---|---|
| `USAR_MONTECARLO` | `TRUE` | TRUE/FALSE | Liga a simulação Monte Carlo da PoE (vol IV + realizada) |
| `POE_MAXIMA` | `25` | número (%) | PoE **máxima** pra recomendar uma PUT (`35` afrouxa, `10` aperta). **Vale sempre** — mesmo com o Monte Carlo desligado, usando a POE do scanner |
| `MC_CENARIOS` | `10000` | inteiro | Nº de simulações (mais = mais preciso, mais lento) |
| `MC_DRIFT` | `0` | número | Tendência do GBM (`0` = sem viés; `0.05` ≈ juros) |

## 🎯 Radar (filtros de prospecção)
| CHAVE | Exemplo | Aceita | O que faz |
|---|---|---|---|
| `RADAR_FONTE` | `auto` | scanner / lucros / auto | De onde vêm as oportunidades. `scanner` = prêmio CLOSE real + Trava no mesmo vencimento; `lucros` = aba de maiores lucros (prêmio estimado quando não casa); `auto` = scanner se houver, senão lucros |
| `RADAR_IV_RANK_MIN` | `50` | número | IV Rank mínimo (pânico / prêmio gordo) |
| `RADAR_RATIO_MIN` | `1.02` | número | Distância mín. spot/strike (`1.02` = 2% OTM; `1.10` = 10%) |
| `RADAR_DTE_MIN` | `21` | inteiro | DTE mínimo (dias até o vencimento) |
| `RADAR_DTE_MAX` | `45` | inteiro | DTE máximo |
| `RADAR_TOP_N` | `5` | inteiro | Quantas oportunidades no e-mail |
| `RADAR_MAX_POR_ATIVO` | `2` | inteiro | **Diversificação**: máx. de oportunidades do mesmo ativo-mãe no Top-N |
| `RADAR_EXIGIR_TENDENCIA_ALTA` | `FALSE` | TRUE/FALSE | Só recomenda se a ação estiver em alta (M9 > M21) — mais restritivo |
| `RADAR_EVITAR_TENDENCIA_BAIXA` | `TRUE` | TRUE/FALSE | **Padrão TRUE**: descarta venda de PUT/Trava em ação em **baixa** (M9 < M21) — a estratégia é altista. `FALSE` permite (entra só com aviso) |
| `RADAR_USAR_TRAVA` | `TRUE` | TRUE/FALSE | Recomenda **Trava de Alta com PUT** (risco limitado) em vez de PUT a seco |
| `RADAR_TRAVA_LARGURA_PCT` | `5` | número (%) | Largura da trava: compra a PUT de proteção ~N% abaixo do strike vendido |

## 🛡️ Escudo (gatilhos de defesa)
| CHAVE | Exemplo | Aceita | O que faz |
|---|---|---|---|
| `ESCUDO_RECOMPRA_OTM` | `2.0` | número | Alerta quando recompra ≥ Nx o prêmio (OTM) |
| `ESCUDO_RECOMPRA_OTM_CRIT` | `3.0` | número | Crítico quando recompra ≥ Nx (OTM) |
| `ESCUDO_RECOMPRA_ATM` | `1.5` | número | Alerta quando recompra ≥ Nx (ATM/ITM) |
| `ESCUDO_DELTA_ALERTA` | `0.30` | número | Banda de \|Δ\| p/ alerta (zona OTM) |
| `ESCUDO_DELTA_URGENTE` | `0.35` | número | Banda de \|Δ\| p/ crítico (zona OTM) |
| `ESCUDO_DTE_CRITICO` | `15` | inteiro | DTE que torna ITM/ATM crítico (risco de exercício) |
| `ESCUDO_PERDA_MAX_PCT` | `50` | número (%) | Perda (% do MAX_LOSS) que vira crítico |
| `ESCUDO_GAMMA_MAX` | `0.05` | número | Gamma que dispara "pré-perigo" |
| `ESCUDO_TOQUE_AVISO` | `50` | número (%) | Prob. de **TOQUE** (perna OTM virar ITM antes de vencer) que vira AVISO — gatilho preditivo do Monte Carlo |
| `ESCUDO_TOQUE_ALERTA` | `70` | número (%) | Prob. de **TOQUE** que vira ALERTA (te avisa **antes** de dar ruim) |
| `ESCUDO_HHI_MAX` | `0.50` | número (0..1) | Concentração setorial máxima (HHI) |
| `ESCUDO_IBOV_EXPOSICAO_MAX` | `80` | número (%) | Exposição máxima ao IBOV |
| `ESCUDO_IBOV_CORREL_MIN` | `0.50` | número | Correlação mínima p/ contar como "exposto ao IBOV" |

> Os valores acima são os **padrões**. Qualquer um pode ser sobrescrito também por
> variável de ambiente (`.env`), mas a aba CONFIG **tem prioridade** e é o jeito
> recomendado (controle pelo celular, sem código).
