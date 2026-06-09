# 🪟 Premium Glass — Design System

> Sistema de design **glassmorphism** (cards de vidro sobre gradiente escuro) criado para o web app do *Motor ResearchDeOpcoes*. Este documento é **framework-agnóstico** (HTML + CSS puro) e copy-paste — adapte para React/Vue/Svelte trocando só a marcação.

---

## 1. Conceito

**Premium Glass** combina quatro ideias:

| Princípio | Como se manifesta |
|---|---|
| **Profundidade por luz** | Fundo em gradiente escuro com "blobs" de cor desfocados → sensação de espaço/atmosfera. |
| **Vidro fosco (glassmorphism)** | Cards translúcidos (`rgba` baixa opacidade) + `backdrop-filter: blur()` + borda branca translúcida → flutuam sobre o fundo. |
| **Acento vibrante** | Violeta + ciano como gradiente de marca; verde/âmbar/vermelho só para *status*. |
| **Dado em foco** | Números grandes com fonte display e *tabular-nums*; texto de apoio em cinza-azulado de baixo contraste. |

**Quando usar:** dashboards, cockpits de dados, fintech, painéis "premium". **Quando evitar:** telas com muito texto corrido longo (o contraste reduzido cansa) — nesses casos suba o contraste do corpo ou use tema claro (ver §10).

---

## 2. Tokens (a base de tudo)

Tudo deriva destas variáveis. Mude-as e o tema inteiro muda.

```css
:root{
  /* Acentos de marca */
  --violet:#8B5CF6;  --violet2:#A78BFA;  --cyan:#22D3EE;  --blue:#60A5FA;
  /* Status (semânticos) */
  --green:#34D399;   --amber:#FBBF24;    --red:#F87171;
  /* Texto */
  --text:#EAF0FB;    --muted:#97A3BD;    --faint:#6B7796;
  /* Superfícies de vidro */
  --glass:rgba(255,255,255,.055);   /* card padrão  */
  --glass2:rgba(255,255,255,.09);   /* chip / hover */
  --stroke:rgba(255,255,255,.12);   /* borda padrão */
  --stroke2:rgba(255,255,255,.18);  /* borda forte  */
  /* Raios */
  --r-card:18px; --r-hero:22px; --r-tabs:16px; --r-chip:999px; --r-sm:11px;
  /* Sombras */
  --sh-card:0 12px 34px rgba(3,6,20,.32);
  --sh-hover:0 18px 44px rgba(3,6,20,.45);
  --sh-hero:0 18px 50px rgba(3,6,20,.5);
  /* Blur do vidro */
  --blur:16px; --blur-strong:18px;
}
```

### Paleta visual

| Token | Hex / valor | Uso |
|---|---|---|
| `--violet` / `--violet2` | `#8B5CF6` / `#A78BFA` | Gradiente de marca, marcador de strike, tabs ativas |
| `--cyan` | `#22D3EE` | Gradiente de marca, links, marcador "hoje/spot" |
| `--green` | `#34D399` | Indicado / risco baixo / sucesso |
| `--amber` | `#FBBF24` | Atenção / risco moderado |
| `--red` | `#F87171` | Crítico / risco alto / rejeitado |
| `--text` | `#EAF0FB` | Texto principal (quase branco azulado) |
| `--muted` | `#97A3BD` | Rótulos, legendas |
| `--faint` | `#6B7796` | Texto terciário, descrições |

**Regra de ouro:** acentos de marca (violeta/ciano) para *identidade e navegação*; cores semânticas (verde/âmbar/vermelho) **só** para comunicar *estado*. Não use vermelho como decoração.

---

## 3. Fundação

### 3.1 Fundo (gradiente + blobs de luz)

O efeito de profundidade vem de **3 radiais coloridos** sobre um **linear escuro**, todos em uma única propriedade `background` (sem elementos extras), fixado no scroll:

```css
body{
  margin:0; min-height:100vh; color:var(--text);
  font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  line-height:1.5; -webkit-font-smoothing:antialiased;
  background:
    radial-gradient(1200px 700px at 12% -8%,  rgba(139,92,246,.30), transparent 60%),
    radial-gradient(1000px 680px at 100% 0%,  rgba(34,211,238,.20), transparent 55%),
    radial-gradient(900px  700px at 50% 120%, rgba(96,165,250,.16), transparent 60%),
    linear-gradient(160deg,#0A0E1C 0%,#10132C 45%,#1B1740 100%);
  background-attachment:fixed;   /* o gradiente não rola junto */
}
```

> 💡 Cada radial é um "blob": `tamanho at posição, cor, transparent`. Mexa nas posições (`12% -8%`, `100% 0%`…) para reposicionar a luz.

### 3.2 Container

```css
.wrap{max-width:1180px; margin:0 auto; padding:20px 15px 60px}
```

---

## 4. Tipografia

Duas famílias do Google Fonts: **Inter** (corpo) e **Sora** (títulos e números de destaque).

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Sora:wght@600;700;800&display=swap" rel="stylesheet">
```

```css
.font-display{font-family:'Sora','Inter',sans-serif}   /* títulos, KPIs, tickers */
/* Números sempre com largura fixa para não "dançar" ao atualizar: */
.tabular{font-variant-numeric:tabular-nums}
```

| Papel | Família | Peso | Tamanho |
|---|---|---|---|
| Título de marca / ticker | Sora | 800 | 18px |
| KPI / número grande | Sora | 800 | 23px |
| Título de seção | Sora | 700 | 16px |
| Corpo | Inter | 400–600 | 13–14px |
| Rótulo / legenda | Inter | 600 | 11–12px (uppercase, `letter-spacing:.5px`) |

**Fallback:** se as fontes não carregarem, `system-ui` assume — o layout não quebra.

---

## 5. Responsividade (desktop ↔ mobile)

### 5.1 Estratégia

- **Mobile-first fluido:** larguras em `%`/`fr`, container com `max-width`. Nada de largura fixa.
- **Toque confortável:** alvos ≥ 38px de altura; chips e tabs com bom *padding*.
- **3 faixas** controladas por 2 breakpoints.

### 5.2 Breakpoints

| Faixa | Largura | Comportamento |
|---|---|---|
| 📱 **Mobile** | `≤ 720px` | KPIs em **2 colunas**; cards **1 coluna**; linhas de log **empilham** (data/badge/msg uma sob a outra); tabs **rolam na horizontal**. |
| 💻 **Tablet** | `721–979px` | KPIs em **4 colunas**; cards ainda **1 coluna** (conteúdo largo respira). |
| 🖥️ **Desktop** | `≥ 980px` | Cards em **2 colunas**; resto fluido. |

```css
/* base = mobile */
.kpis{display:grid; grid-template-columns:repeat(4,1fr); gap:11px}
.cards{display:grid; grid-template-columns:1fr; gap:13px; align-items:start}

@media (min-width:980px){
  .cards{grid-template-columns:repeat(2,1fr)}   /* desktop: 2 colunas */
}
@media (max-width:720px){
  .kpis{grid-template-columns:repeat(2,1fr)}     /* mobile: KPIs 2 col */
  .log{grid-template-columns:1fr; gap:4px}       /* mobile: log empilha */
  .log .t,.log .badge{justify-self:start}
}
```

### 5.3 Padrões que garantem a responsividade

- **Tabs roláveis:** `overflow-x:auto` + `white-space:nowrap` → em telas estreitas vira um carrossel horizontal sem quebrar.
- **Flex que quebra:** `.hero-top`, `.chips`, `.gauges`, `.scn-f` usam `flex-wrap:wrap` → reordenam sozinhos.
- **Grid auto-fit** (em grades de métrica): `repeat(auto-fit,minmax(118px,1fr))` → o número de colunas se ajusta ao espaço.
- **`viewport` obrigatório:** `<meta name="viewport" content="width=device-width, initial-scale=1">`.

---

## 6. Componentes

Cada um traz **anatomia → CSS → HTML**.

### 6.1 Card de vidro (a base)

A peça central. Variantes `lead-*` adicionam uma borda colorida à esquerda para status.

```css
.card{
  background:var(--glass); border:1px solid var(--stroke); border-radius:var(--r-card);
  padding:16px 17px; backdrop-filter:blur(var(--blur)); -webkit-backdrop-filter:blur(var(--blur));
  box-shadow:var(--sh-card); transition:.2s;
}
.card:hover{border-color:var(--stroke2); transform:translateY(-2px); box-shadow:var(--sh-hover)}
.card.lead-green{border-left:3px solid var(--green)}
.card.lead-amber{border-left:3px solid var(--amber)}
.card.lead-red  {border-left:3px solid var(--red)}
.card.lead-cyan {border-left:3px solid var(--cyan)}
```

```html
<div class="card lead-green">…</div>
```

> ⚠️ **Sempre** acompanhe `backdrop-filter` do prefixo `-webkit-backdrop-filter` (Safari).

### 6.2 Hero / cabeçalho de status

```css
.hero{
  position:relative; overflow:hidden; border-radius:var(--r-hero); padding:19px 21px;
  background:linear-gradient(120deg,rgba(139,92,246,.16),rgba(34,211,238,.10));
  border:1px solid var(--stroke2); backdrop-filter:blur(var(--blur-strong)); box-shadow:var(--sh-hero);
}
.hero-top{display:flex; align-items:center; justify-content:space-between; gap:14px; flex-wrap:wrap}
.brand{display:flex; align-items:center; gap:12px}
.logo{width:42px; height:42px; border-radius:13px; display:grid; place-items:center; font-size:22px;
  background:linear-gradient(135deg,var(--violet),var(--cyan)); box-shadow:0 8px 24px rgba(139,92,246,.45)}
.brand h1{font-size:18px; margin:0; font-weight:800}
.brand .subtitle{font-size:12.5px; color:var(--muted); margin-top:1px}
```

### 6.3 Status pill (com pulso)

Pílula de estado com um ponto que pulsa — ótimo para "ao vivo".

```css
.statuspill{display:inline-flex; align-items:center; gap:9px; padding:9px 15px; border-radius:var(--r-chip);
  font-weight:700; font-size:13px; border:1px solid rgba(52,211,153,.4); background:rgba(52,211,153,.12); color:#b8f5dd}
.statuspill.warn{border-color:rgba(251,191,36,.4); background:rgba(251,191,36,.12); color:#fde68a}
.statuspill.bad {border-color:rgba(248,113,113,.45); background:rgba(248,113,113,.14); color:#fecaca}
.dot{width:9px; height:9px; border-radius:50%; background:currentColor; animation:pulse 2s infinite}
@keyframes pulse{
  0%{box-shadow:0 0 0 0 rgba(255,255,255,.35)}
  70%{box-shadow:0 0 0 9px rgba(255,255,255,0)}
  100%{box-shadow:0 0 0 0 rgba(255,255,255,0)}
}
```

```html
<span class="statuspill"><span class="dot"></span> NO AR · há 4 min</span>
```

### 6.4 KPIs

```css
.kpi{background:var(--glass); border:1px solid var(--stroke); border-radius:15px; padding:12px 14px}
.kpi .l{font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.6px; font-weight:600}
.kpi .v{font-size:23px; font-weight:800; margin-top:4px; font-variant-numeric:tabular-nums; font-family:'Sora'}
.kpi .v.sm{font-size:18px}
.kpi .d{font-size:11.5px; color:var(--faint); margin-top:2px}
.kpi .v.green{color:var(--green)} .kpi .v.cyan{color:var(--cyan)}
.kpi .v.amber{color:var(--amber)} .kpi .v.red{color:var(--red)}
```

### 6.5 Tabs (navegação)

Pílula deslizante; aba ativa ganha o gradiente de marca.

```css
.tabsbar{position:sticky; top:8px; z-index:20; margin:16px 0 14px}
.tabs{display:flex; gap:5px; padding:6px; border-radius:var(--r-tabs); background:rgba(10,14,28,.6);
  border:1px solid var(--stroke); backdrop-filter:blur(14px); overflow-x:auto}
.tab{flex:1; min-width:max-content; text-align:center; padding:10px 15px; border-radius:var(--r-sm);
  cursor:pointer; font-weight:600; font-size:13.5px; color:var(--muted); white-space:nowrap; transition:.18s; user-select:none}
.tab:hover{color:var(--text); background:var(--glass)}
.tab.active{color:#0a0e1c; background:linear-gradient(135deg,var(--violet2),var(--cyan));
  box-shadow:0 8px 22px rgba(139,92,246,.4); font-weight:700}
.tab .cnt{display:inline-block; margin-left:5px; font-size:11px; padding:1px 7px; border-radius:999px; background:rgba(255,255,255,.16); font-weight:700}
.tab.active .cnt{background:rgba(10,14,28,.25)}
.panel{display:none} .panel.active{display:block; animation:fade .35s ease}
@keyframes fade{from{opacity:0; transform:translateY(6px)} to{opacity:1; transform:none}}
```

```html
<div class="tabsbar"><div class="tabs">
  <div class="tab active" data-p="a" onclick="showTab('a')">Resumo</div>
  <div class="tab" data-p="b" onclick="showTab('b')">Dados <span class="cnt">25</span></div>
</div></div>
<div class="panel active" data-panel="a">…</div>
<div class="panel"        data-panel="b">…</div>
<script>
function showTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.p===name));
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.dataset.panel===name));
}
</script>
```

> 💡 **Dica de robustez:** se o conteúdo for recarregado via AJAX, guarde a aba ativa numa variável (`window.__tab`) e reaplique após cada atualização — assim o refresh não joga o usuário de volta pra primeira aba.

### 6.6 Chips

```css
.chips{display:flex; gap:7px; flex-wrap:wrap; margin-top:11px}
.chip{font-size:12px; font-weight:600; border:1px solid var(--stroke); background:var(--glass2);
  border-radius:var(--r-chip); padding:4px 11px; color:#cdd6ea; white-space:nowrap}
.chip b{font-weight:800; color:#fff; font-variant-numeric:tabular-nums}
.chip.green {color:#b8f5dd; border-color:rgba(52,211,153,.35); background:rgba(52,211,153,.12)}
.chip.red   {color:#fecaca; border-color:rgba(248,113,113,.35); background:rgba(248,113,113,.12)}
.chip.amber {color:#fde68a; border-color:rgba(251,191,36,.35); background:rgba(251,191,36,.12)}
.chip.violet{color:#ddd6fe; border-color:rgba(139,92,246,.4);  background:rgba(139,92,246,.15)}
.chip.cyan  {color:#a5f3fc; border-color:rgba(34,211,238,.35); background:rgba(34,211,238,.12)}
```

```html
<span class="chip violet">IV <b>83</b></span> <span class="chip green">✅ Alta</span>
```

### 6.7 Verdict pills (decisão)

```css
.verdict.ok,.verdict.no{display:inline-flex; align-items:center; gap:7px; padding:6px 13px; border-radius:var(--r-chip); font-weight:700; font-size:13px}
.verdict.ok{color:#0a0e1c; background:linear-gradient(135deg,var(--green),var(--cyan)); box-shadow:0 6px 18px rgba(52,211,153,.35)}
.verdict.no{color:#fecaca; background:rgba(248,113,113,.14); border:1px solid rgba(248,113,113,.4)}
```

### 6.8 Anéis (gauges com `conic-gradient`)

Mostram um percentual visualmente, sem SVG nem JS — só CSS:

```css
.gauges{display:flex; gap:18px; align-items:center; margin-top:14px; flex-wrap:wrap}
.gauge{display:flex; align-items:center; gap:11px}
.ring{width:56px; height:56px; border-radius:50%; display:grid; place-items:center; position:relative; flex:0 0 auto}
.ring::before{content:""; position:absolute; inset:6px; border-radius:50%; background:#0c1020} /* "furo" */
.ring span{position:relative; font-weight:800; font-size:14px; font-variant-numeric:tabular-nums; font-family:'Sora'}
.gl{font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; font-weight:600}
.gd{font-size:11.5px; color:var(--faint); margin-top:2px; max-width:150px}
```

```html
<!-- O percentual e a cor são inline (gerados no servidor/JS): -->
<div class="gauge">
  <div class="ring" style="background:conic-gradient(var(--amber) 44%, rgba(255,255,255,.08) 0)"><span>44%</span></div>
  <div><div class="gl">Exercício</div><div class="gd">fecha abaixo do strike</div></div>
</div>
```

> 🎨 **Cor por faixa:** ≤25% verde, ≤50% âmbar, senão vermelho (o "perigo" cresce com o número).

### 6.9 ⭐ Barra de cenário (range bar) — o componente estrela

Mostra uma faixa **pior 5% ── marcadores ── melhor 5%**, com a "zona de risco" hachurada e marcadores posicionados em `%`. Comunica *onde um ponto cai dentro de uma faixa provável*.

```css
.scn{margin-top:15px}
.scn-h{display:flex; justify-content:space-between; font-size:11px; color:var(--muted); margin-bottom:7px;
  font-weight:600; text-transform:uppercase; letter-spacing:.5px}
.track{position:relative; height:34px; border-radius:10px; border:1px solid var(--stroke);
  background:linear-gradient(90deg,rgba(248,113,113,.18),rgba(251,191,36,.12) 45%,rgba(52,211,153,.18))}
.track .exer{position:absolute; left:0; top:0; bottom:0; border-radius:10px 0 0 10px;
  border-right:1px dashed rgba(248,113,113,.6);
  background:repeating-linear-gradient(45deg,rgba(248,113,113,.22),rgba(248,113,113,.22) 6px,rgba(248,113,113,.10) 6px,rgba(248,113,113,.10) 12px)}
.mk{position:absolute; top:-6px; bottom:-6px; width:2px; background:var(--text); transform:translateX(-1px)}
.mk.strike{background:var(--violet2); box-shadow:0 0 10px rgba(167,139,250,.8)}
.mk.spot{background:var(--cyan)}
.mk .lab{position:absolute; top:-19px; left:50%; transform:translateX(-50%); white-space:nowrap; font-size:10px; font-weight:700;
  color:var(--violet2); background:rgba(10,14,28,.75); padding:1px 6px; border-radius:6px; border:1px solid rgba(167,139,250,.4)}
.mk.spot .lab{color:var(--cyan); border-color:rgba(34,211,238,.4)}
.scn-f{display:flex; justify-content:space-between; gap:8px; font-size:12px; margin-top:9px;
  font-variant-numeric:tabular-nums; color:var(--muted); flex-wrap:wrap}
.scn-f b{color:var(--text); font-weight:700}
```

```html
<div class="scn">
  <div class="scn-h"><span>Cenário 30 dias</span><span>faixa provável</span></div>
  <div class="track">
    <div class="exer" style="width:38.8%"></div>
    <div class="mk strike" style="left:38.8%"><span class="lab">strike 11,04</span></div>
    <div class="mk spot"   style="left:46.1%"><span class="lab">hoje 11,46</span></div>
  </div>
  <div class="scn-f"><span>pior 5% <b>R$ 8,81</b></span><span>provável <b>R$ 11,33</b></span><span>melhor 5% <b>R$ 14,56</b></span></div>
</div>
```

**Cálculo da posição** (em JS): com a faixa `[min, max]`, a posição de um valor `x` é
`pos = clamp(0, 100, (x - min) / (max - min) * 100)`. A largura da zona hachurada = posição do marcador de risco.

### 6.10 Detalhe expansível (`details`/`summary`)

Esconde leitura longa atrás de um clique, com seta animada.

```css
.por{margin-top:13px; border-top:1px solid var(--stroke); padding-top:11px}
.por>summary{cursor:pointer; font-weight:600; font-size:13px; color:var(--cyan); list-style:none; display:flex; align-items:center; gap:7px}
.por>summary::-webkit-details-marker{display:none}
.por>summary::before{content:"▸"; transition:.2s; color:var(--violet2)}
.por[open]>summary::before{transform:rotate(90deg)}
.por .body{font-size:13.5px; line-height:1.62; color:#cdd6ea; margin-top:10px}
.por .body b{color:#fff}
```

```html
<details class="por" open><summary>Como ler</summary><div class="body">Texto…</div></details>
```

### 6.11 Logs (linha + badge + filtros)

```css
.logbar{display:flex; gap:7px; margin-bottom:12px; flex-wrap:wrap}
.lf{padding:7px 13px; border-radius:10px; font-size:12.5px; cursor:pointer; border:1px solid var(--stroke);
  background:var(--glass); color:var(--muted); font-weight:600}
.lf.on{color:#0a0e1c; background:linear-gradient(135deg,var(--violet2),var(--cyan))}
.lf.danger{color:#fecaca; border-color:rgba(248,113,113,.35); background:rgba(248,113,113,.1)}
.log{display:grid; grid-template-columns:104px 96px 1fr; gap:12px; padding:11px 14px; border-radius:12px;
  background:var(--glass); border:1px solid var(--stroke); margin-bottom:7px; font-size:13px; align-items:center}
.log .t{color:var(--faint); font-size:12px; font-variant-numeric:tabular-nums}
.badge{font-size:10.5px; font-weight:800; padding:3px 9px; border-radius:999px; text-align:center; letter-spacing:.4px}
.b-ok{background:rgba(52,211,153,.15); color:#86efac}
.b-crit{background:rgba(248,113,113,.18); color:#fca5a5}
.b-warn{background:rgba(251,191,36,.16); color:#fcd34d}
.b-info{background:rgba(96,165,250,.15); color:#93c5fd}
```

### 6.12 Botões, links, estados vazios

```css
.btn{display:inline-flex; align-items:center; gap:7px; padding:9px 15px; border-radius:var(--r-sm); cursor:pointer;
  font-weight:600; font-size:13px; color:var(--text); background:var(--glass2); border:1px solid var(--stroke2)}
.btn:hover{background:rgba(255,255,255,.14)}
a{color:var(--cyan); text-decoration:none} a:hover{text-decoration:underline}
.empty{text-align:center; color:var(--muted); padding:34px 12px; font-size:14px;
  background:var(--glass); border:1px solid var(--stroke); border-radius:16px}
```

---

## 7. Sombra & profundidade (a "regra dos vidros")

Para o vidro funcionar, respeite a hierarquia de elevação:

| Camada | Fundo | Borda | Sombra | Blur |
|---|---|---|---|---|
| Fundo | gradiente | — | — | — |
| Card | `--glass` (5,5%) | `--stroke` | `--sh-card` | 16px |
| Chip / hover | `--glass2` (9%) | `--stroke`/`--stroke2` | leve | — |
| Hero / tabs | gradiente leve | `--stroke2` | `--sh-hero` | 18px |

> Quanto **mais na frente**, mais opaco e mais sombra. Nunca empilhe dois `backdrop-filter` translúcidos sem necessidade (custa performance).

---

## 8. Acessibilidade & fallbacks

```css
/* 1) Movimento reduzido: desliga pulso e animações de aba */
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation:none !important; transition:none !important}
}
/* 2) Sem suporte a backdrop-filter (degrada com elegância) */
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){
  .card,.hero,.tabs{background:rgba(18,22,40,.92)}  /* vidro vira sólido escuro */
}
```

- **Contraste:** corpo `#EAF0FB` sobre fundo escuro passa AA. Texto `--faint` é decorativo — **não** use para informação crítica.
- **Fontes:** o `<link>` do Google Fonts é progressivo; `system-ui` é o fallback.
- **Foco:** adicione `:focus-visible{outline:2px solid var(--cyan); outline-offset:2px}` em elementos clicáveis (tabs, botões) para navegação por teclado.
- **`backdrop-filter`** funciona em todos os navegadores modernos (Chrome/Edge/Safari/Firefox recentes); o `@supports` acima cobre os antigos.

---

## 9. Performance

- **Limite o blur:** `backdrop-filter` é caro. Use em **poucas** superfícies grandes (cards, hero, tabs) — não em cada chip.
- **`will-change` com parcimônia:** só em elementos que animam de fato.
- **`background-attachment:fixed`** pode pesar em mobile muito antigo; se notar travada, troque por um fundo fixo via pseudo-elemento `position:fixed`.
- **Anéis e barras são CSS puro** (sem SVG/canvas) → praticamente de graça.

---

## 10. Adaptando para **tema claro** (reuso)

Troque só os tokens — a estrutura é a mesma:

```css
:root{
  --text:#0F172A; --muted:#475569; --faint:#94A3B8;
  --glass:rgba(255,255,255,.7); --glass2:#FFFFFF;
  --stroke:rgba(15,23,42,.08); --stroke2:rgba(15,23,42,.14);
}
body{background:
  radial-gradient(1000px 600px at 10% -10%,rgba(139,92,246,.10),transparent 60%),
  radial-gradient(900px 600px at 100% 0%,rgba(34,211,238,.10),transparent 55%),
  linear-gradient(160deg,#F7F8FC,#EEF1F8)}
.ring::before{background:#fff}   /* o furo do anel acompanha o fundo do card */
```

> Mantenha o `.ring::before` e o gradiente das pills/abas com a **mesma cor do card** que está atrás — é o que dá o efeito de "recorte".

---

## 11. Template starter (copie e rode)

```html
<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Sora:wght@600;700;800&display=swap" rel="stylesheet">
<style>
  /* cole aqui §2 (tokens) + §3.1 (body) + os componentes que usar + §5.2 (breakpoints) + §8 (fallbacks) */
</style></head>
<body>
  <div class="wrap">
    <div class="hero"><div class="hero-top">
      <div class="brand"><div class="logo">📡</div><div>
        <h1 class="font-display">Meu Dashboard</h1><div class="subtitle">subtítulo</div></div></div>
      <span class="statuspill"><span class="dot"></span> NO AR</span>
    </div>
    <div class="kpis" style="margin-top:17px">
      <div class="kpi"><div class="l">Métrica</div><div class="v sm cyan">42</div><div class="d">detalhe</div></div>
    </div></div>

    <div class="tabsbar"><div class="tabs">
      <div class="tab active" data-p="a" onclick="showTab('a')">Aba A</div>
      <div class="tab" data-p="b" onclick="showTab('b')">Aba B</div>
    </div></div>

    <div class="panel active" data-panel="a">
      <div class="card lead-green"><div class="row1"><span class="tk">CARD</span></div>
        <div class="gauges">
          <div class="gauge"><div class="ring" style="background:conic-gradient(var(--green) 44%,rgba(255,255,255,.08) 0)"><span>44%</span></div>
            <div><div class="gl">Rótulo</div></div></div>
        </div></div>
    </div>
    <div class="panel" data-panel="b"><div class="empty">Conteúdo da aba B</div></div>
  </div>
<script>
function showTab(n){document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.p===n));
document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.dataset.panel===n));}
</script>
</body></html>
```

---

## 12. Checklist de implementação

- [ ] `<meta viewport>` presente
- [ ] Tokens (`:root`) no topo do CSS
- [ ] `backdrop-filter` **com** `-webkit-backdrop-filter`
- [ ] Números com `font-variant-numeric:tabular-nums`
- [ ] `--faint` só em texto decorativo
- [ ] Breakpoints 720/980 testados em celular e desktop
- [ ] Fallback `@supports not` + `prefers-reduced-motion`
- [ ] `:focus-visible` nos clicáveis
- [ ] Cor do `.ring::before` = cor do card atrás
- [ ] Estado da aba persistido se houver auto-refresh

---

*Premium Glass · extraído do `docs/monitor.gs` do Motor ResearchDeOpcoes. Framework-agnóstico — leve para onde quiser. 🪟*
