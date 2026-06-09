/**
 * Painel de observabilidade do motor ResearchDeOpcoes (Google Apps Script).
 *
 * Lê MONITOR (heartbeat) + PAINEL_ESCUDO + PAINEL_RADAR + LOGS e entrega um
 * dashboard web responsivo (celular + desktop) com TODAS as informações que
 * vão no e-mail: defesa de posições (Escudo) e oportunidades (Radar, com a
 * Trava de Alta), além de status do motor e logs.
 *
 * Layout:
 *   - Cards em 1 coluna (celular) → 2 (tablet) → 3 (desktop ≥1160px), com
 *     espaçamento generoso para leitura confortável.
 *
 * Embasamento (justificativas):
 *   - Cada card do Escudo/Radar traz um VEREDITO sempre visível + um bloco
 *     "Por que?" expansível, LIDO dos números reais (PoE, PoE-MC, Toque,
 *     recompra, IV Rank, taxa) — não é texto fixo.
 *
 * Funcionalidades:
 *   - LOGS: filtro (Todos/Problemas/Monte Carlo), "ver detalhe" abre o dossiê
 *     completo (coluna CONTEXT) e botão "Limpar logs" (apaga o histórico).
 *
 * Robustez:
 *   - Os painéis são lidos pelo NOME do cabeçalho (não por índice fixo), então
 *     a planilha pode ganhar colunas novas sem quebrar o painel.
 *   - Todo conteúdo dinâmico é ESCAPADO (corrige "Conteúdo HTML inválido").
 *   - Datas e números formatados em pt-BR (corrige strike/data/duração).
 *
 * COMO USAR:
 *   1. Planilha > Extensões > Apps Script. Cole este arquivo (substitua o antigo).
 *   2. Implantar > Nova implantação > App da Web > Executar como "Eu" > Acesso
 *      "Somente eu" > Implantar. Salve a URL (atalho no celular).
 *   3. Acionadores: verificarHeartbeat > a cada 30 min (vigia "dead-man's switch").
 *   OBS.: o botão "Limpar logs" ESCREVE na planilha; na 1ª vez o Google pede uma
 *   autorização extra (editar planilhas). Após colar mudanças, gere uma NOVA
 *   versão da implantação para o web app passar a enxergar a função.
 */

const SHEET_ID = '1zuYr3lTOSsVJzvrBJezZ5hFMIM3jpt2jDfR8uCapKds';
const EMAIL_ALERTA = 'brunotrolo@gmail.com';
const TZ = 'America/Sao_Paulo';
const ABA_MONITOR = 'MONITOR', ABA_LOGS = 'LOGS', ABA_PESC = 'PAINEL_ESCUDO', ABA_PRAD = 'PAINEL_RADAR', ABA_DIAG = 'RADAR_DIAGNOSTICO';
const LIMITE_MIN = 75;
// Janela do pregão (dias úteis, fuso TZ): vigia só alerta dentro dela. Apenas
// pelo relógio — sem depender da API de status do mercado.
const PREGAO_INI_MIN = 10 * 60;        // 10:00
const PREGAO_FIM_MIN = 16 * 60 + 30;   // 16:30
const PREGAO_LABEL = '10h–16h30';
const REFRESH_S = 120;
const GITHUB_ACTIONS = 'https://github.com/brunotrolo/ResearchDeOpcoes/actions';

// ===========================================================================
// Leitura de dados
// ===========================================================================
function _planilha() { return SpreadsheetApp.openById(SHEET_ID); }

function _heartbeat() {
  const sh = _planilha().getSheetByName(ABA_MONITOR);
  if (!sh || sh.getLastRow() < 2) return null;
  const r = sh.getRange(2, 1, 1, 8).getValues()[0];
  return { updatedAt: r[0], status: r[1], market: r[2], dur: r[3],
           escudo: r[4], radar: r[5], runUrl: r[6], notes: r[7] };
}

/** Lê um painel devolvendo { idx: {COLUNA: posição}, rows: [[...]] }. */
function _readPanel(aba) {
  const sh = _planilha().getSheetByName(aba);
  if (!sh || sh.getLastRow() < 2) return { idx: {}, rows: [] };
  const vals = sh.getRange(1, 1, sh.getLastRow(), sh.getLastColumn()).getValues();
  const idx = {};
  vals[0].forEach((h, i) => { idx[String(h).trim().toUpperCase()] = i; });
  return { idx, rows: vals.slice(1) };
}

function _ultimas(aba, n, ncols) {
  const sh = _planilha().getSheetByName(aba);
  if (!sh || sh.getLastRow() < 2) return [];
  const last = sh.getLastRow(), start = Math.max(2, last - n + 1);
  return sh.getRange(start, 1, last - start + 1, ncols).getValues();
}

// ===========================================================================
// Status do motor
// ===========================================================================
function _ehPregao() {
  const a = new Date();
  const dia = parseInt(Utilities.formatDate(a, TZ, 'u'), 10);   // 1=seg ... 7=dom
  const min = parseInt(Utilities.formatDate(a, TZ, 'H'), 10) * 60
            + parseInt(Utilities.formatDate(a, TZ, 'm'), 10);
  return dia >= 1 && dia <= 5 && min >= PREGAO_INI_MIN && min <= PREGAO_FIM_MIN;
}

function _idadeMin(updatedAt) {
  const d = _toDate(updatedAt);
  return d ? (Date.now() - d.getTime()) / 60000 : null;
}

function _avaliar() {
  const hb = _heartbeat(), pregao = _ehPregao();
  if (!hb) return { cor: '#475569', cor2: '#334155', emoji: '⚪', titulo: 'SEM DADOS', hb: null, idade: null, pregao };
  const idade = _idadeMin(hb.updatedAt);
  let cor = '#16a34a', cor2 = '#15803d', emoji = '🟢', titulo = 'NO AR';
  const st = String(hb.status || '').toUpperCase();
  if (st.indexOf('ERR') === 0 || st === 'FAIL') {
    cor = '#dc2626'; cor2 = '#b91c1c'; emoji = '🔴'; titulo = 'ERRO NA ÚLTIMA EXECUÇÃO';
  } else if (idade !== null && pregao && idade > LIMITE_MIN) {
    cor = '#dc2626'; cor2 = '#b91c1c'; emoji = '🔴'; titulo = 'ATRASADO (motor pode estar parado)';
  } else if (!pregao) {
    cor = '#ca8a04'; cor2 = '#a16207'; emoji = '🟡'; titulo = 'FORA DO PREGÃO';
  }
  return { cor, cor2, emoji, titulo, hb, idade, pregao };
}

// ===========================================================================
// Formatação / escape
// ===========================================================================
function esc(v) {
  if (v == null) return '';
  return String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function _isDate(v) { return Object.prototype.toString.call(v) === '[object Date]' && !isNaN(v.getTime()); }

function _toDate(v) {
  if (_isDate(v)) return v;
  if (v == null || v === '') return null;
  const s = String(v).trim();
  const m = s.match(/^(\d{2})\/(\d{2})\/(\d{4})[ T]?(\d{2})?:?(\d{2})?:?(\d{2})?/);
  if (m) return new Date(+m[3], +m[2] - 1, +m[1], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0));
  const d = new Date(s.replace(' ', 'T'));
  return isNaN(d.getTime()) ? null : d;
}
function _num(v) {
  if (v === '' || v == null) return null;
  if (typeof v === 'number') return isNaN(v) ? null : v;
  if (_isDate(v)) return null;
  let s = String(v).trim().replace(/R\$|%|\s/g, '');
  if (s.indexOf(',') >= 0) s = s.replace(/\./g, '').replace(',', '.');
  const n = parseFloat(s);
  return isNaN(n) ? null : n;
}
function _fmtNum(v, dec) {
  const n = _num(v);
  if (n == null) return '—';
  if (dec == null) dec = 2;
  const parts = Math.abs(n).toFixed(dec).split('.');
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return (n < 0 ? '-' : '') + parts[0] + (dec > 0 ? ',' + parts[1] : '');
}
function _fmtMoney(v) { const n = _num(v); return n == null ? '—' : 'R$ ' + _fmtNum(n, 2); }
function _fmtPct(v, dec) { const n = _num(v); return n == null ? '—' : _fmtNum(n, dec == null ? 1 : dec) + '%'; }
function _diasTxt(v) { const n = _num(v); return n == null ? '—' : _fmtNum(n, 0) + 'd'; }
function _fmtDateTime(v) { const d = _toDate(v); return d ? Utilities.formatDate(d, TZ, 'dd/MM HH:mm') : (v ? esc(v) : '—'); }
function _fmtDateFull(v) { const d = _toDate(v); return d ? Utilities.formatDate(d, TZ, "dd/MM/yyyy 'às' HH:mm") : (v ? esc(v) : '—'); }
function _fmtDateOnly(v) { const d = _toDate(v); return d ? Utilities.formatDate(d, TZ, 'dd/MM/yyyy') : (v ? esc(v) : '—'); }

function _idadeTxt(m) {
  if (m == null) return '—';
  m = Math.round(m);
  if (m < 1) return 'agora há pouco';
  if (m < 60) return 'há ' + m + ' min';
  const h = Math.floor(m / 60), r = m % 60;
  return 'há ' + h + 'h' + (r ? ' ' + r + 'min' : '');
}
function _mercadoLabel(m) {
  const s = String(m == null ? '' : m).trim().toUpperCase();
  if (s === 'A' || s === 'ABERTO') return '🟢 Aberto';
  if (s === 'F' || s === 'FECHADO') return '🔴 Fechado';
  return s === '' ? '—' : esc(s);
}
function _corNivel(n) {
  n = String(n).toUpperCase();
  if (n === 'CRITICO') return '#dc2626';
  if (n === 'ALERTA') return '#ea580c';
  if (n === 'AVISO') return '#ca8a04';
  return '#16a34a';
}
function _corStatus(s) {
  s = String(s).toUpperCase();
  if (s.indexOf('ERR') === 0 || s === 'FAIL') return '#dc2626';
  if (s.indexOf('WARN') === 0) return '#ca8a04';
  return '#16a34a';
}

// ===========================================================================
// Componentes
// ===========================================================================
function _chip(label, value) {
  const l = label ? esc(label) + ' ' : '';
  return "<span class='chip'>" + l + "<b>" + value + "</b></span>";
}
function _grid(pairs) {
  let c = '';
  pairs.forEach(p => {
    if (p[1] === '—' || p[1] == null) return;
    c += "<div class='m'><div class='ml'>" + esc(p[0]) + "</div><div class='mv'>" + p[1] + "</div></div>";
  });
  return c ? "<div class='mgrid'>" + c + "</div>" : '';
}
function _section(titulo, badge, body) {
  return "<div class='sec'><div class='sechead'><span>" + titulo + "</span>"
    + (badge ? "<span class='badge'>" + badge + "</span>" : '') + "</div>" + body + "</div>";
}

// ===========================================================================
// Justificativa embasada — LIDA dos números de cada posição/ideia (não é texto
// fixo). Entrega um VEREDITO sempre visível + um detalhamento "Por que?" que o
// usuário expande para ver a leitura métrica a métrica.
// ===========================================================================
function _pct100(v) { const n = _num(v); return n == null ? null : n * 100; } // fração → %

function _reasons(lis) {
  let out = '';
  lis.forEach(t => { if (t) out += "<li>" + t + "</li>"; });
  return out ? "<ul class='reasons'>" + out + "</ul>" : '';
}

/** Caixa com VEREDITO (sempre visível) + detalhamento expansível ("Por que?"). */
function _why(titulo, corpo, veredito) {
  if (!corpo && !veredito) return '';
  const v = veredito ? "<div class='verdict'>" + veredito + "</div>" : '';
  const d = corpo ? "<details class='why'><summary>" + esc(titulo) + "</summary>" + corpo + "</details>" : '';
  return "<div class='whybox'>" + v + d + "</div>";
}

/** Leitura embasada de uma posição do ESCUDO (defesa). */
function _porQueEscudo(g, nivel) {
  const poeMc = _pct100(g('POE_MC')), poe = _pct100(g('POE')), toque = _pct100(g('TOQUE'));
  const rec = _num(g('RECOMPRA_X')), plPct = _num(g('PL_PCT')), plVal = _num(g('PL_VALUE'));
  const dist = _num(g('DIST_PCT')), dte = _num(g('DTE')), money = String(g('MONEYNESS') || '').toUpperCase();
  const L = [];
  const pRef = poeMc != null ? poeMc : poe;
  if (pRef != null) {
    const lab = pRef >= 85 ? 'Exercício quase certo' : pRef >= 60 ? 'Exercício provável'
      : pRef >= 40 ? 'Risco real de exercício' : 'Exercício pouco provável';
    let src = poeMc != null ? 'PoE-MC ' + _fmtNum(poeMc, 0) + '% (Monte Carlo na vol. máxima — leitura conservadora)'
      : 'PoE ' + _fmtNum(poe, 0) + '%';
    if (poe != null && poeMc != null) src += '; fórmula fechada ' + _fmtNum(poe, 0) + '%';
    L.push("<b>" + lab + "</b> — " + src + ".");
  }
  if (toque != null) {
    const tl = toque >= 90 ? 'deve tocar o strike antes de vencer' : toque >= 70 ? 'alta chance de tocar o strike antes de vencer'
      : toque >= 40 ? 'chance moderada de encostar no strike no caminho' : 'baixa chance de encostar no strike no caminho';
    L.push("<b>Toque " + _fmtNum(toque, 0) + "%</b> — " + tl + " (em qualquer dia até o vencimento; por isso vem ≥ PoE).");
  }
  if (rec != null) {
    const rl = rec >= 2 ? 'cara: recomprar custa ' + _fmtNum(rec, 1) + '× o prêmio recebido — fechar agora cristaliza o prejuízo, mas trava a perda'
      : rec >= 1.5 ? 'a ' + _fmtNum(rec, 1) + '× o prêmio — ainda administrável' : 'barata (' + _fmtNum(rec, 1) + '× o prêmio) — dá para zerar com folga';
    L.push("<b>Recompra</b> " + rl + ".");
  }
  if (plPct != null) {
    L.push("<b>P/L aberto " + _fmtNum(plPct, 0) + "%</b>" + (plVal != null ? ' (' + _fmtMoney(plVal) + ')' : '')
      + (plPct <= -50 ? ' — perda relevante já marcada' : '') + ".");
  }
  const pos = [];
  if (dist != null) pos.push('strike a ' + (dist >= 0 ? '+' : '') + _fmtNum(dist, 1) + '% do spot');
  if (money) pos.push(esc(money));
  if (dte != null) pos.push('faltam ' + _fmtNum(dte, 0) + 'd');
  if (pos.length) L.push("<b>Posição</b>: " + pos.join(' · ') + ".");

  // Veredito: recomendação amarrada aos números que mais pesam.
  const drv = [];
  if (poeMc != null && poeMc >= 60) drv.push('exercício provável (PoE-MC ' + _fmtNum(poeMc, 0) + '%)');
  if (rec != null && rec >= 2) drv.push('recompra cara (' + _fmtNum(rec, 1) + '×)');
  if (plPct != null && plPct <= -50) drv.push('P/L ' + _fmtNum(plPct, 0) + '%');
  let ver = '';
  if (nivel === 'CRITICO') {
    ver = "🔴 <b>Agir agora</b>" + (drv.length ? " — " + drv.slice(0, 2).join(' e ') : '')
      + ": encerrar ou rolar limita o dano.";
  } else if (nivel === 'ALERTA') {
    ver = "🟠 <b>Preparar defesa</b> — " + ((toque != null && toque >= 70)
      ? 'o preço deve encostar no strike (Toque ' + _fmtNum(toque, 0) + '%)' : 'risco subindo')
      + "; deixe a rolagem pronta antes de virar crítico.";
  } else {
    ver = "🟡 <b>Só acompanhar</b> — risco sob controle"
      + (poeMc != null || toque != null ? ' (' + [poeMc != null ? 'PoE-MC ' + _fmtNum(poeMc, 0) + '%' : '', toque != null ? 'Toque ' + _fmtNum(toque, 0) + '%' : ''].filter(Boolean).join(', ') + ')' : '')
      + "; agir só se piorar ou o prêmio dobrar.";
  }
  return _why('🔬 Por que este nível?', _reasons(L), ver);
}

/** Leitura embasada de uma ideia do RADAR (oportunidade). */
function _porQueRadar(g, temTrava) {
  const taxa = _num(g('TAXA_RETORNO')), dte = _num(g('DTE')), poeMc = _pct100(g('POE_MC'));
  const toque = _pct100(g('TOQUE')), iv = _num(g('IV_RANK')), dist = _num(g('DIST_PCT')), vol = _num(g('VOLUME_FIN'));
  const rMax = _num(g('TRAVA_RISCO_MAX')), rr = _pct100(g('TRAVA_RETORNO_RISCO')), cred = _num(g('TRAVA_CREDITO'));
  const L = [];
  if (taxa != null) {
    const mes = (dte != null && dte > 0) ? ' (≈' + _fmtNum(taxa / dte * 30, 1) + '%/mês equivalente)' : '';
    L.push("<b>Prêmio rende " + _fmtNum(taxa, 1) + "%</b> sobre o strike em " + (dte != null ? _fmtNum(dte, 0) + 'd' : '?') + mes + ".");
  }
  if (poeMc != null) {
    const pl = poeMc <= 25 ? 'baixa — ideia confortável' : poeMc <= 45 ? 'moderada' : 'alta — escolha com cautela';
    L.push("<b>Chance de ser exercida: " + _fmtNum(poeMc, 0) + "%</b> (PoE-MC na vol. máxima) — " + pl + ".");
  }
  // Tendência: rótulo multi-horizonte + a PoE se a tendência continuar (o número
  // que diz se você está entrando contra a maré). Baixistas já foram bloqueadas.
  const tlab = String(g('TREND_LABEL') || '').toUpperCase();
  const poeT = _pct100(g('POE_TENDENCIA'));
  if (tlab) {
    const nome = { ALTA: 'tendência de ALTA confirmada (curto/médio/M9-M21)', NEUTRO: 'tendência neutra',
      REPIQUE_BAIXA: '⚠️ repique em tendência de baixa', BAIXA: '⛔ tendência de BAIXA' }[tlab] || tlab;
    let extra = '';
    if (poeT != null && poeMc != null)
      extra = " — PoE " + _fmtNum(poeMc, 0) + "%; " + _fmtNum(poeT, 0) + "% se a "
        + (poeT > poeMc + 0.5 ? 'baixa' : 'alta') + " continuar";
    L.push("<b>Tendência</b>: " + nome + extra + ".");
  }
  if (dist != null) L.push("<b>Margem</b>: strike " + (dist >= 0 ? '+' : '') + _fmtNum(dist, 1) + "% vs spot antes de entrar no prejuízo.");
  if (iv != null) {
    const il = iv >= 70 ? 'alta (prêmio caro — bom momento para vender)' : iv >= 40 ? 'mediana' : 'baixa (prêmio magro)';
    L.push("<b>IV Rank " + _fmtNum(iv, 0) + "</b> — volatilidade " + il + ".");
  }
  if (toque != null) L.push("<b>Toque " + _fmtNum(toque, 0) + "%</b> — chance de encostar no strike antes de vencer (pode pedir ajuste no meio do caminho).");
  if (temTrava && rMax != null) {
    L.push("<b>Risco DEFINIDO pela trava</b>: perda máx " + _fmtMoney(rMax) + (cred != null ? ', crédito ' + _fmtMoney(cred) : '')
      + (rr != null ? ' → retorno/risco ' + _fmtNum(rr, 0) + '%' : '') + ".");
  }
  if (vol != null && vol < 20000) L.push("<b>Liquidez baixa</b> (" + _fmtMoney(vol) + ") — atenção ao spread na hora de executar.");

  let ver = '';
  if (poeMc != null && taxa != null) {
    if (poeMc <= 35 && taxa >= 2) ver = "✅ <b>Boa relação</b>: retorno atrativo (" + _fmtNum(taxa, 1) + "%) com baixa probabilidade de exercício (" + _fmtNum(poeMc, 0) + "%)" + (temTrava ? " e perda limitada pela trava" : "") + ".";
    else if (poeMc >= 60) ver = "⚠️ <b>Retorno vem com risco</b>: PoE elevada (" + _fmtNum(poeMc, 0) + "%) — só com trava ou margem extra.";
    else ver = "➖ <b>Equilibrada</b>: retorno (" + _fmtNum(taxa, 1) + "%) e risco (PoE " + _fmtNum(poeMc, 0) + "%) proporcionais — encaixe conforme seu apetite.";
  }
  return _why('🔬 Por que esta ideia?', _reasons(L), ver);
}

function _nivelPill(n) {
  n = String(n).toUpperCase();
  var m = { CRITICO: ['🔴 CRÍTICO', '#fca5a5', 'rgba(248,113,113,.16)', 'rgba(248,113,113,.45)'],
    ALERTA: ['🟠 ALERTA', '#fde68a', 'rgba(251,191,36,.14)', 'rgba(251,191,36,.4)'],
    AVISO: ['🟡 AVISO', '#a5f3fc', 'rgba(34,211,238,.12)', 'rgba(34,211,238,.35)'] }[n]
    || ['OK', '#b8f5dd', 'rgba(52,211,153,.12)', 'rgba(52,211,153,.35)'];
  return "<span class='nivel' style='color:" + m[1] + ";background:" + m[2] + ";border:1px solid " + m[3] + "'>" + m[0] + "</span>";
}
function _leadCls(n) { n = String(n).toUpperCase(); return n === 'CRITICO' ? 'lead-red' : n === 'ALERTA' ? 'lead-amber' : n === 'AVISO' ? 'lead-cyan' : 'lead-green'; }

function _buildEscudo() {
  const { idx, rows } = _readPanel(ABA_PESC);
  const c = { CRITICO: 0, ALERTA: 0, AVISO: 0 };
  rows.forEach(r => { const n = String(r[idx['NIVEL']]).toUpperCase(); if (c[n] != null) c[n]++; });
  const head = "<div class='sec-head'><h2>🛡️ Posições em atenção</h2><span class='hint'>🔴 " + c.CRITICO + " · 🟠 " + c.ALERTA + " · 🟡 " + c.AVISO + "</span></div>";
  if (!rows.length) return { html: head + "<div class='empty'>Tudo tranquilo por aqui. 🎉<br>Nenhuma posição precisa de defesa agora.</div>", n: 0, c: c };
  let items = '';
  rows.forEach(r => {
    const g = n => (idx[n] == null ? '' : r[idx[n]]);
    const nivel = String(g('NIVEL')).toUpperCase();
    if (String(g('OPCAO')).indexOf('PORTFOLIO') === 0) {
      items += "<div class='card " + _leadCls(nivel) + "'><div class='row1'><span class='tk'>🛡️ Carteira</span>"
        + "<span style='margin-left:auto'>" + _nivelPill(nivel) + "</span></div>"
        + (g('ANALISE') ? "<div class='analise'>" + esc(g('ANALISE')) + "</div>" : '')
        + (g('ACAO') ? "<div class='acao'>👉 " + esc(g('ACAO')) + "</div>" : '') + "</div>";
      return;
    }
    const chips = _chip('', esc(g('MONEYNESS'))) + _chip('DTE', _diasTxt(g('DTE')))
      + _chip('Δ', _fmtNum(g('DELTA'), 2)) + _chip('γ', _fmtNum(g('GAMMA'), 2))
      + _chip('PoE', _fmtPct(_num(g('POE')) == null ? null : _num(g('POE')) * 100, 0))
      + (g('POE_MC') !== '' ? _chip('PoE-MC', _fmtPct(_num(g('POE_MC')) == null ? null : _num(g('POE_MC')) * 100, 0)) : '')
      + (g('TOQUE') !== '' ? _chip('Toque', _fmtPct(_num(g('TOQUE')) == null ? null : _num(g('TOQUE')) * 100, 0)) : '')
      + _chip('Recompra', _fmtNum(g('RECOMPRA_X'), 2) + 'x');
    const pl = _fmtMoney(g('PL_VALUE')) + ' (' + _fmtPct(g('PL_PCT'), 0) + ')';
    const grid = _grid([
      ['Spot', _fmtMoney(g('SPOT'))], ['Strike', _fmtMoney(g('STRIKE'))], ['Dist.', _fmtPct(g('DIST_PCT'), 1)],
      ['Prêmio méd.', _fmtMoney(g('PREMIO_ENTRADA'))], ['Prêmio atual', _fmtMoney(g('PREMIO_ATUAL'))], ['Break-even', _fmtMoney(g('BREAK_EVEN'))],
      ['L/P aberto', pl], ['Ganho máx.', _fmtMoney(g('GANHO_MAX'))], ['Nocional', _fmtMoney(g('NOCIONAL'))],
    ]);
    items += "<div class='card " + _leadCls(nivel) + "'>"
      + "<div class='row1'><span class='tk'>" + esc(g('TICKER')) + "</span> <span class='op'>" + esc(g('OPCAO')) + "</span>"
      + "<span style='margin-left:auto'>" + _nivelPill(nivel) + "</span></div>"
      + "<div class='sub'>" + esc(g('SIDE')) + " " + esc(g('TIPO')) + " · " + esc(g('MONEYNESS'))
      + " · " + _diasTxt(g('DTE')) + " (" + _fmtDateOnly(g('EXPIRY')) + ") · " + esc(g('QTD')) + " contratos</div>"
      + "<div class='chips'>" + chips + "</div>" + grid
      + (g('ANALISE') ? "<div class='analise'>🔎 " + esc(g('ANALISE')) + "</div>" : '')
      + (g('ACAO') ? "<div class='acao'>👉 " + esc(g('ACAO')) + "</div>" : '')
      + _porQueEscudo(g, nivel) + "</div>";
  });
  return { html: head + "<div class='cards'>" + items + "</div>", n: rows.length, c: c };
}

function _travaBlock(g) {
  if (g('TRAVA_VENDE_STRIKE') === '' || g('TRAVA_VENDE_STRIKE') == null) return '';
  // Códigos das DUAS pernas (para lançar a ordem direto na corretora).
  var vOpt = g('TRAVA_VENDE_OPCAO'), cOpt = g('TRAVA_COMPRA_OPCAO');
  var vTag = vOpt ? " <span class='opc'>" + esc(vOpt) + "</span>" : '';
  var cTag = cOpt ? " <span class='opc'>" + esc(cOpt) + "</span>" : '';
  // Break-even da trava de alta = strike vendido − crédito líquido recebido.
  var be = (_num(g('TRAVA_VENDE_STRIKE')) != null && _num(g('TRAVA_CREDITO')) != null)
    ? _num(g('TRAVA_VENDE_STRIKE')) - _num(g('TRAVA_CREDITO')) : null;
  return "<div class='trava'><div class='travah'>🛡️ Trava de Alta com PUT <span class='hint'>(risco limitado)</span></div>"
    + "<div class='leg'>🔴 <b>Vende</b> PUT" + vTag + " · strike " + _fmtMoney(g('TRAVA_VENDE_STRIKE')) + " · prêmio " + _fmtMoney(g('TRAVA_VENDE_PREMIO')) + "</div>"
    + "<div class='leg'>🟢 <b>Compra</b> PUT" + cTag + " · strike " + _fmtMoney(g('TRAVA_COMPRA_STRIKE')) + " · prêmio " + _fmtMoney(g('TRAVA_COMPRA_PREMIO')) + "</div>"
    + _grid([
      ['Crédito líq.', _fmtMoney(g('TRAVA_CREDITO'))],
      ['Risco máx.', _fmtMoney(g('TRAVA_RISCO_MAX'))],
      ['Retorno/Risco', _fmtPct(_num(g('TRAVA_RETORNO_RISCO')) == null ? null : _num(g('TRAVA_RETORNO_RISCO')) * 100, 0)],
      ['Break-even', be == null ? '—' : _fmtMoney(be)],
    ]) + "</div>";
}

/** Chip de tendência da ação-mãe (rótulo multi-horizonte do gate de entrada).
 *  Como o motor BLOQUEIA baixistas, o que sobra é ✅ Alta / ➖ Neutro — sinal de
 *  confiança de que você não está entrando contra a maré. */
function _trendChip(label) {
  var m = { ALTA: ['green', '✅ Alta'], NEUTRO: ['', '➖ Neutro'],
    REPIQUE_BAIXA: ['amber', '⚠️ Repique↓'], BAIXA: ['red', '⛔ Baixa'] };
  var c = m[String(label || '').toUpperCase()];
  return c ? "<span class='chip " + c[0] + "'>" + c[1] + "</span>" : '';
}

/** Anel (conic-gradient) com o percentual no centro — leitura visual de chance. */
function _ring(pct, color, label, desc) {
  if (pct == null) return '';
  var p = Math.max(0, Math.min(100, Math.round(pct)));
  return "<div class='gauge'><div class='ring' style='background:conic-gradient(" + color + " " + p + "%,rgba(255,255,255,.08) 0)'><span>" + p + "%</span></div>"
    + "<div><div class='gl'>" + esc(label) + "</div>" + (desc ? "<div class='gd'>" + esc(desc) + "</div>" : '') + "</div></div>";
}
function _ringColor(p) { return p == null ? 'var(--muted)' : p <= 25 ? 'var(--green)' : p <= 50 ? 'var(--amber)' : 'var(--red)'; }
function _toqueColor(p) { return p == null ? 'var(--muted)' : p <= 40 ? 'var(--green)' : p <= 70 ? 'var(--amber)' : 'var(--red)'; }
// O Sheets converte "44%"/"-3,7%" em fração (0.44/-0.037) com formato %. Ao ler o
// valor cru, devolvemos sempre em PERCENTUAL: fração (|v|<=1) vira ×100; texto
// "44%" o _num já resolve; número já em % passa direto.
function _pctVal(v) {
  if (v === '' || v == null) return null;
  if (typeof v === 'number') return (v > -1.0001 && v < 1.0001) ? v * 100 : v;
  return _num(v);
}
function _moneyVal(v) { return (v === '' || v == null) ? '—' : (typeof v === 'number' ? _fmtMoney(v) : esc(v)); }
function _margemTxt(v) { const m = _pctVal(v); return m == null ? esc(v) : (m >= 0 ? '+' : '') + _fmtNum(m, 1) + '%'; }

function _buildRadar() {
  const { idx, rows } = _readPanel(ABA_PRAD);
  const head = "<div class='sec-head'><h2>📡 Oportunidades — Travas de Alta com PUT</h2><span class='hint'>"
    + rows.length + (rows.length === 1 ? ' ideia' : ' ideias') + "</span></div>";
  if (!rows.length) return { html: head + "<div class='empty'>Sem oportunidades no filtro agora.<br>O Radar reavalia a cada execução.</div>", n: 0 };
  let items = '';
  rows.forEach(r => {
    const g = n => (idx[n] == null ? '' : r[idx[n]]);
    const temTrava = g('TRAVA_VENDE_STRIKE') !== '' && g('TRAVA_VENDE_STRIKE') != null;
    const dist = _num(g('DIST_PCT')); const distTxt = dist == null ? '—' : (dist >= 0 ? '+' : '') + _fmtNum(dist, 1) + '%';
    const aprox = String(g('PREMIO_FONTE') || '').indexOf('estim') >= 0 ? '≈ ' : '';
    const poe = _pct100(g('POE_MC')), toque = _pct100(g('TOQUE'));
    const chips = _trendChip(g('TREND_LABEL')) + _chip('IV', _fmtNum(g('IV_RANK'), 0))
      + _chip('Taxa', _fmtPct(g('TAXA_RETORNO'), 1)) + _chip('Prêmio', aprox + _fmtMoney(g('PREMIO')))
      + _chip('Dist', distTxt) + (g('VOLUME_FIN') !== '' ? _chip('Vol', _fmtMoney(g('VOLUME_FIN'))) : '');
    const gauges = (poe != null || toque != null) ? ("<div class='gauges'>"
      + _ring(poe, _ringColor(poe), 'Exercício', 'chance de virar exercida')
      + _ring(toque, _toqueColor(toque), 'Toque', 'tocar o strike no caminho') + "</div>") : '';
    items += "<div class='card lead-green'>"
      + "<div class='row1'><span class='tk'>" + esc(g('TICKER')) + "</span> <span class='op'>" + esc(g('OPCAO')) + "</span>"
      + "<span class='tag'>" + (temTrava ? '🛡️ Trava de Alta' : '📉 Venda de PUT') + "</span></div>"
      + "<div class='sub'>" + _diasTxt(g('DTE')) + " (" + _fmtDateOnly(g('EXPIRY')) + ") · prêmio " + aprox + _fmtMoney(g('PREMIO')) + "/ação</div>"
      + "<div class='chips'>" + chips + "</div>" + gauges + _travaBlock(g)
      + (g('ANALISE') ? "<div class='analise'>💡 " + esc(g('ANALISE')) + "</div>" : '')
      + _porQueRadar(g, temTrava) + "</div>";
  });
  return { html: head + "<div class='cards'>" + items + "</div>", n: rows.length };
}

/** Barra de faixa do cenário: pior 5% ── strike/spot ── melhor 5%, com a zona de
 *  exercício (preço abaixo do strike) hachurada. Mostra VISUALMENTE o porquê da chance. */
function _scnBar(p5, p50, p95, strike, spot) {
  if (p5 == null || p95 == null || p95 <= p5) return '';
  const pos = x => Math.max(0, Math.min(100, (x - p5) / (p95 - p5) * 100));
  const sk = strike == null ? null : pos(strike), sp = spot == null ? null : pos(spot);
  let mks = '';
  if (sk != null) mks += "<div class='mk strike' style='left:" + sk.toFixed(1) + "%'><span class='lab'>strike " + _fmtNum(strike, 2) + "</span></div>";
  if (sp != null) mks += "<div class='mk spot' style='left:" + sp.toFixed(1) + "%'><span class='lab'>hoje " + _fmtNum(spot, 2) + "</span></div>";
  return "<div class='scn'><div class='scn-h'><span>Cenário 30 dias</span><span>faixa provável (5%–95%)</span></div>"
    + "<div class='track'><div class='exer' style='width:" + (sk == null ? 0 : sk).toFixed(1) + "%'></div>" + mks + "</div>"
    + "<div class='scn-f'><span>pior 5% <b>" + _fmtMoney(p5) + "</b></span>"
    + (p50 != null ? "<span>provável <b>" + _fmtMoney(p50) + "</b></span>" : '')
    + "<span>melhor 5% <b>" + _fmtMoney(p95) + "</b></span></div></div>";
}
/** Extrai os números do texto CENARIO_30D (pt-BR) p/ desenhar a barra. */
function _parseCen(txt) {
  txt = String(txt || '');
  const gr = re => { const m = txt.match(re); return m ? _num(m[1]) : null; };
  return { p5: gr(/pior 5% R\$ ([\d.,]+)/), p50: gr(/prov[aá]vel R\$ ([\d.,]+)/),
    p95: gr(/melhor 5% R\$ ([\d.,]+)/), spot: gr(/Hoje R\$ ([\d.,]+)/) };
}

function _buildDiag() {
  const { idx, rows } = _readPanel(ABA_DIAG);
  const okOf = v => String(v).toUpperCase().indexOf('INDIC') >= 0;
  let ind = 0; rows.forEach(r => { if (okOf(r[idx['VEREDITO']])) ind++; });
  const head = "<div class='sec-head'><h2>🔬 Raio-X do Radar — ticker a ticker</h2><span class='hint'>"
    + ind + " indicado · " + (rows.length - ind) + " rejeitado · Monte Carlo</span></div>";
  if (!rows.length) return { html: head + "<div class='empty'>Sem diagnóstico ainda.<br>Roda na próxima execução do Radar.</div>", n: 0, ind: 0 };
  let items = '';
  rows.forEach(r => {
    const g = n => (idx[n] == null ? '' : r[idx[n]]);
    const okv = okOf(g('VEREDITO'));
    const exer = _pctVal(g('CHANCE_EXERCICIO')), toque = _pctVal(g('CHANCE_TOQUE'));
    const spotN = _num(g('SPOT')), strikeN = _num(g('STRIKE')), cen = _parseCen(g('CENARIO_30D'));
    const tl = String(g('TENDENCIA') || '').toUpperCase();
    const trendChip = tl ? ("<span class='chip " + (tl === 'ALTA' ? 'green' : tl.indexOf('BAIX') >= 0 ? 'red' : tl.indexOf('REPIQUE') >= 0 ? 'amber' : '') + "'>" + esc(g('TENDENCIA')) + "</span>") : '';
    const verd = okv ? "<span class='verdict ok'>✅ Indicado</span>" : "<span class='verdict no'>⛔ Rejeitado</span>";
    const anchor = "<div class='anchor'><div class='gl'>SPOT · STRIKE · MARGEM</div><div class='av'>"
      + _moneyVal(g('SPOT')) + " · " + _moneyVal(g('STRIKE')) + " · " + _margemTxt(g('MARGEM')) + "</div></div>";
    const gauges = "<div class='gauges'>" + _ring(exer, _ringColor(exer), 'Exercício', 'fecha abaixo do strike')
      + _ring(toque, _toqueColor(toque), 'Toque', 'encosta no strike') + anchor + "</div>";
    const motivo = g('POR_QUE') ? "<div class='motivo'><span class='ic'>" + (okv ? '✅' : '📉') + "</span> " + esc(g('POR_QUE')) + "</div>" : '';
    const bar = _scnBar(cen.p5, cen.p50, cen.p95, strikeN, spotN != null ? spotN : cen.spot);
    const como = g('COMO_LER') ? "<details class='por'" + (okv ? ' open' : '') + "><summary>Como ler estes números</summary><div class='body'>" + esc(g('COMO_LER')) + "</div></details>" : '';
    items += "<div class='card " + (okv ? 'lead-green' : 'lead-red') + "'>"
      + "<div class='row1'><span class='tk'>" + esc(g('TICKER')) + "</span>"
      + (g('IV_RANK') !== '' ? "<span class='chip violet'>IV " + _fmtNum(g('IV_RANK'), 0) + "</span>" : '') + trendChip
      + "<span style='margin-left:auto'>" + verd + "</span></div>"
      + motivo + gauges + bar + como + "</div>";
  });
  return { html: head + "<div class='cards'>" + items + "</div>", n: rows.length, ind: ind };
}

/** Classifica o log para o filtro: 'erro' (problemas), 'mc' (Monte Carlo) ou 'outros'. */
function _logCat(service, status) {
  const st = String(status).toUpperCase(), sv = String(service).toUpperCase();
  if (st.indexOf('ERR') === 0 || st === 'FAIL' || st.indexOf('WARN') === 0) return 'erro';
  if (sv.indexOf('MONTE') >= 0 || sv === 'MC') return 'mc';
  return 'outros';
}

function _buildLogs() {
  const logs = _ultimas(ABA_LOGS, 50, 5).reverse();   // 5 colunas: inclui CONTEXT (dossiê)
  const head = "<div class='sec-head'><h2>🧾 Logs recentes</h2><span class='hint'>" + logs.length + " eventos</span></div>";
  if (!logs.length) return { html: head + "<div class='empty'>Sem logs ainda. O motor grava a auditoria a cada execução.</div>", n: 0 };
  const bar = "<div class='logbar'>"
    + "<button class='lf on' onclick='_flog(this,\"todos\")'>Todos</button>"
    + "<button class='lf' onclick='_flog(this,\"erro\")'>⚠️ Problemas</button>"
    + "<button class='lf' onclick='_flog(this,\"mc\")'>🎲 Monte Carlo</button>"
    + "<button class='lf danger' onclick='_limparLogs()'>🗑️ Limpar</button></div>";
  let body = '';
  logs.forEach(l => {
    const cat = _logCat(l[1], l[2]);
    const ctx = String(l[4] == null ? '' : l[4]).trim();
    const det = ctx ? "<details class='logdet'><summary>ver detalhe »</summary><pre>" + esc(ctx) + "</pre></details>" : '';
    const st = String(l[2]).toUpperCase();
    const bcls = (st.indexOf('ERR') === 0 || st === 'FAIL' || st.indexOf('CRIT') >= 0) ? 'b-crit'
      : (st.indexOf('WARN') === 0 || st.indexOf('AVISO') >= 0) ? 'b-warn' : 'b-ok';
    body += "<div class='log' data-cat='" + cat + "'><span class='t'>" + _fmtDateTime(l[0]) + "</span>"
      + "<span class='badge " + bcls + "'>" + esc(l[1]) + "</span>"
      + "<span class='msg'>" + esc(l[3]) + det + "</span></div>";
  });
  return { html: head + bar + body, n: logs.length };
}

/** Apaga TODO o histórico da aba LOGS (mantém o cabeçalho). Chamado pelo web app
 *  via google.script.run. O motor volta a gravar a auditoria no próximo ciclo. */
function limparLogs() {
  const sh = _planilha().getSheetByName(ABA_LOGS);
  if (!sh) throw new Error('Aba LOGS não encontrada.');
  const last = sh.getLastRow();
  if (last > 1) sh.getRange(2, 1, last - 1, sh.getLastColumn()).clearContent();
  return true;
}

// ===========================================================================
// Página
// ===========================================================================
function doGet() {
  try {
    return HtmlService.createHtmlOutput(_render())
      .setTitle('Motor ResearchDeOpcoes')
      .addMetaTag('viewport', 'width=device-width, initial-scale=1');
  } catch (err) {
    const safe = "<html><head><meta charset='utf-8'></head><body style='font-family:Arial;padding:24px'>"
      + "<h2>⚠️ Painel indisponível no momento</h2><p>O motor segue rodando; o painel falhou ao montar.</p>"
      + "<pre style='background:#f1f5f9;padding:12px;border-radius:8px;white-space:pre-wrap'>"
      + esc(err && err.message ? err.message : err) + "</pre>"
      + "<p><a href='" + GITHUB_ACTIONS + "'>Ver execuções no GitHub »</a></p></body></html>";
    return HtmlService.createHtmlOutput(safe).setTitle('Motor ResearchDeOpcoes');
  }
}

// Conteúdo dinâmico do painel (hero + resumo + cards). É re-renderizado a cada
// refresh SEM recarregar a página (ver getPainel/_render).
function _statusPill(a) {
  const t = a.titulo || '';
  const cls = t.indexOf('NO AR') === 0 ? 'ok' : (t.indexOf('FORA') === 0 ? 'warn' : 'bad');
  return "<span class='statuspill " + cls + "'><span class='dot'></span> " + esc(t) + " · " + _idadeTxt(a.idade) + "</span>";
}
function _kpi(l, v, d, cls) {
  return "<div class='kpi'><div class='l'>" + esc(l) + "</div><div class='v sm " + (cls || '') + "'>" + v + "</div><div class='d'>" + esc(d) + "</div></div>";
}
function _tab(id, label, cnt) {
  return "<div class='tab' data-p='" + id + "' onclick=\"_tab('" + id + "')\">" + esc(label) + (cnt ? " <span class='cnt'>" + cnt + "</span>" : '') + "</div>";
}
function _panel(id, body, active) {
  return "<div class='panel" + (active ? ' active' : '') + "' data-panel='" + id + "'>" + body + "</div>";
}
function _resumoBody(a, hb) {
  const grid = _grid([
    ['Horário', _fmtDateFull(hb.updatedAt)],
    ['Status', "<span style='color:" + _corStatus(hb.status) + "'>" + esc(hb.status || '—') + "</span>"],
    ['Mercado', _mercadoLabel(hb.market)], ['Alertas Escudo', _fmtNum(hb.escudo, 0)],
    ['Oportunidades', _fmtNum(hb.radar, 0)], ['Duração (s)', _fmtNum(hb.dur, 1)],
  ]);
  const atalhos = "<div class='sec-head' style='margin-top:18px'><h2>Atalhos</h2></div><div class='card'>"
    + "<div style='display:flex;gap:10px;flex-wrap:wrap'>"
    + "<span class='btn' onclick='_refresh()'>🔄 Atualizar agora</span>"
    + "<a class='btn' href='" + GITHUB_ACTIONS + "' target='_blank'>▶️ Rodar / ver Actions</a>"
    + "<span class='btn' onclick='_limparLogs()'>🧾 Limpar logs</span></div>"
    + "<div class='muted' id='refStatus' style='margin-top:11px'>atualiza sozinho a cada " + Math.round(REFRESH_S / 60) + " min</div></div>";
  return "<div class='sec-head'><h2>Resumo da última execução</h2><span class='hint'>" + _fmtDateTime(hb.updatedAt)
    + (hb.runUrl ? " · <a href='" + esc(hb.runUrl) + "'>GitHub »</a>" : '') + "</span></div>"
    + "<div class='card'>" + grid + (hb.notes ? "<div class='motivo'><span class='ic'>💡</span> " + esc(hb.notes) + "</div>" : '') + "</div>"
    + atalhos;
}

function _inner() {
  const a = _avaliar(), hb = a.hb || {};
  const E = _buildEscudo(), R = _buildRadar(), D = _buildDiag(), L = _buildLogs();
  const hero = "<div class='hero'><div class='hero-top'>"
    + "<div class='brand'><div class='logo'>📡</div><div><h1 class='font-display'>Motor ResearchDeOpcoes</h1>"
    + "<div class='subtitle'>Escudo · Radar · raio-X do Monte Carlo</div></div></div>" + _statusPill(a) + "</div>"
    + "<div class='kpis'>"
    + _kpi('Mercado', _mercadoLabel(hb.market), 'Pregão ' + PREGAO_LABEL, '')
    + _kpi('Escudo', String(E.n), E.c.CRITICO + ' crítico · ' + E.c.ALERTA + ' alerta', E.c.CRITICO > 0 ? 'red' : '')
    + _kpi('Radar', String(R.n), 'oportunidades', 'cyan')
    + _kpi('Diagnóstico', String(D.n), D.ind + ' indicado(s)', '')
    + "</div></div>";
  const tabs = "<div class='tabsbar'><div class='tabs'>"
    + _tab('resumo', 'Resumo', '') + _tab('escudo', 'Escudo', E.n) + _tab('radar', 'Radar', R.n)
    + _tab('diag', 'Diagnóstico', D.n) + _tab('logs', 'Logs', '') + "</div></div>";
  const panels = _panel('resumo', _resumoBody(a, hb), true) + _panel('escudo', E.html)
    + _panel('radar', R.html) + _panel('diag', D.html) + _panel('logs', L.html);
  const foot = "<div class='foot'>Execução manual via <a href='" + GITHUB_ACTIONS + "'>GitHub Actions</a> · pregão " + PREGAO_LABEL
    + "<br>motor ResearchDeOpcoes · não é recomendação de investimento</div>";
  return hero + tabs + panels + foot;
}

// Chamado pelo CLIENTE via google.script.run — devolve só o HTML do painel.
function getPainel() {
  try { return _inner(); }
  catch (e) { return "<div class='sec'><div class='item'>Falha ao atualizar agora: "
    + esc(e && e.message ? e.message : e) + "</div></div>"; }
}

function _render() {
  // Refresh SEM reload: busca o HTML novo via google.script.run e troca o DOM.
  // O estado da aba ativa fica no cliente (window.__tab) e é reaplicado após cada
  // refresh, então o auto-refresh não joga você de volta pro Resumo.
  const script = "<script>"
    + "window.__tab='resumo';"
    + "function _showTab(name){var T=document.querySelectorAll('.tab');for(var i=0;i<T.length;i++)T[i].classList.toggle('active',T[i].getAttribute('data-p')===name);"
    + "var P=document.querySelectorAll('.panel');for(var j=0;j<P.length;j++)P[j].classList.toggle('active',P[j].getAttribute('data-panel')===name);}"
    + "function _tab(name){window.__tab=name;_showTab(name);try{window.scrollTo({top:0,behavior:'smooth'});}catch(e){window.scrollTo(0,0);}}"
    + "function _apply(html){var el=document.getElementById('painel');if(el&&html){el.innerHTML=html;_showTab(window.__tab||'resumo');}}"
    + "function _refresh(){var s=document.getElementById('refStatus');if(s)s.textContent='atualizando…';"
    + "google.script.run.withSuccessHandler(_apply).withFailureHandler(function(){"
    + "var s2=document.getElementById('refStatus');if(s2)s2.textContent='sem conexão — tentando de novo';}).getPainel();}"
    // Filtra os logs no cliente (sem ida ao servidor) por categoria do data-cat.
    + "function _flog(btn,cat){var b=document.querySelectorAll('.lf');for(var i=0;i<b.length;i++)if(!b[i].classList.contains('danger'))b[i].classList.remove('on');"
    + "if(btn)btn.classList.add('on');var L=document.querySelectorAll('.log');"
    + "for(var j=0;j<L.length;j++){var c=L[j].getAttribute('data-cat');L[j].style.display=(cat==='todos'||c===cat)?'':'none';}}"
    // Apaga os logs (com confirmação) e recarrega o painel.
    + "function _limparLogs(){if(!confirm('Apagar TODO o histórico de logs? Não dá para desfazer.\\nO motor volta a gravar no próximo ciclo.'))return;"
    + "var s=document.getElementById('refStatus');if(s)s.textContent='limpando logs…';"
    + "google.script.run.withSuccessHandler(function(){_refresh();}).withFailureHandler(function(e){"
    + "var s2=document.getElementById('refStatus');if(s2)s2.textContent='falha ao limpar: '+(e&&e.message?e.message:e);}).limparLogs();}"
    + "setInterval(_refresh," + (REFRESH_S * 1000) + ");"
    + "</script>";
  return "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'>"
    + "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    + "<link rel='preconnect' href='https://fonts.googleapis.com'>"
    + "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Sora:wght@600;700;800&display=swap' rel='stylesheet'>"
    + "<style>" + _css() + "</style></head>"
    + "<body><div class='wrap' id='painel'>" + _inner() + "</div>" + script + "</body></html>";
}

function _css() {
  // Premium Glass — gradiente + cards de vidro (glassmorphism), abas, anéis e
  // barra de cenário. Tema escuro. Cobre as classes novas e as dos explicadores.
  return `
:root{--violet:#8B5CF6;--violet2:#A78BFA;--cyan:#22D3EE;--green:#34D399;--amber:#FBBF24;--red:#F87171;
--text:#EAF0FB;--muted:#97A3BD;--faint:#6B7796;--glass:rgba(255,255,255,.055);--glass2:rgba(255,255,255,.09);
--stroke:rgba(255,255,255,.12);--stroke2:rgba(255,255,255,.18)}
*{box-sizing:border-box}
body{margin:0;color:var(--text);line-height:1.5;-webkit-font-smoothing:antialiased;
font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;
background:radial-gradient(1200px 700px at 12% -8%,rgba(139,92,246,.30),transparent 60%),
radial-gradient(1000px 680px at 100% 0%,rgba(34,211,238,.20),transparent 55%),
radial-gradient(900px 700px at 50% 120%,rgba(96,165,250,.16),transparent 60%),
linear-gradient(160deg,#0A0E1C 0%,#10132C 45%,#1B1740 100%);background-attachment:fixed;min-height:100vh}
.wrap{max-width:1180px;margin:0 auto;padding:20px 15px 60px}
.font-display{font-family:'Sora','Inter',sans-serif}
a{color:var(--cyan);text-decoration:none}a:hover{text-decoration:underline}
/* HERO */
.hero{position:relative;overflow:hidden;border-radius:22px;padding:19px 21px;
background:linear-gradient(120deg,rgba(139,92,246,.16),rgba(34,211,238,.10));
border:1px solid var(--stroke2);backdrop-filter:blur(18px);box-shadow:0 18px 50px rgba(3,6,20,.5)}
.hero-top{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px}
.logo{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;font-size:22px;
background:linear-gradient(135deg,var(--violet),var(--cyan));box-shadow:0 8px 24px rgba(139,92,246,.45)}
.brand h1{font-size:18px;margin:0;font-weight:800;letter-spacing:.2px}
.brand .subtitle{font-size:12.5px;color:var(--muted);margin-top:1px}
.statuspill{display:inline-flex;align-items:center;gap:9px;padding:9px 15px;border-radius:999px;font-weight:700;font-size:13px;
border:1px solid rgba(52,211,153,.4);background:rgba(52,211,153,.12);color:#b8f5dd}
.statuspill.warn{border-color:rgba(251,191,36,.4);background:rgba(251,191,36,.12);color:#fde68a}
.statuspill.bad{border-color:rgba(248,113,113,.45);background:rgba(248,113,113,.14);color:#fecaca}
.dot{width:9px;height:9px;border-radius:50%;background:currentColor;box-shadow:0 0 0 0 currentColor;animation:pulse 2s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(255,255,255,.35)}70%{box-shadow:0 0 0 9px rgba(255,255,255,0)}100%{box-shadow:0 0 0 0 rgba(255,255,255,0)}}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:11px;margin-top:17px}
.kpi{background:var(--glass);border:1px solid var(--stroke);border-radius:15px;padding:12px 14px}
.kpi .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;font-weight:600}
.kpi .v{font-size:23px;font-weight:800;margin-top:4px;font-variant-numeric:tabular-nums;font-family:'Sora'}
.kpi .v.sm{font-size:18px}.kpi .d{font-size:11.5px;color:var(--faint);margin-top:2px}
.kpi .v.green{color:var(--green)}.kpi .v.cyan{color:var(--cyan)}.kpi .v.amber{color:var(--amber)}.kpi .v.red{color:var(--red)}
/* TABS */
.tabsbar{position:sticky;top:8px;z-index:20;margin:16px 0 14px}
.tabs{display:flex;gap:5px;padding:6px;border-radius:16px;background:rgba(10,14,28,.6);border:1px solid var(--stroke);
backdrop-filter:blur(14px);overflow-x:auto;box-shadow:0 10px 30px rgba(0,0,0,.35)}
.tab{flex:1;min-width:max-content;text-align:center;padding:10px 15px;border-radius:11px;cursor:pointer;
font-weight:600;font-size:13.5px;color:var(--muted);white-space:nowrap;transition:.18s;user-select:none}
.tab:hover{color:var(--text);background:var(--glass)}
.tab.active{color:#0a0e1c;background:linear-gradient(135deg,var(--violet2),var(--cyan));box-shadow:0 8px 22px rgba(139,92,246,.4);font-weight:700}
.tab .cnt{display:inline-block;margin-left:5px;font-size:11px;padding:1px 7px;border-radius:999px;background:rgba(255,255,255,.16);font-weight:700}
.tab.active .cnt{background:rgba(10,14,28,.25)}
.panel{display:none}.panel.active{display:block;animation:fade .35s ease}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
/* SECTIONS + CARDS */
.sec-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin:6px 2px 12px}
.sec-head h2{font-size:16px;margin:0;font-weight:700;font-family:'Sora'}
.sec-head .hint{font-size:12.5px;color:var(--muted)}
.cards{display:grid;grid-template-columns:1fr;gap:13px;align-items:start}
.card{background:var(--glass);border:1px solid var(--stroke);border-radius:18px;padding:16px 17px;
backdrop-filter:blur(16px);box-shadow:0 12px 34px rgba(3,6,20,.32);transition:.2s}
.card:hover{border-color:var(--stroke2);transform:translateY(-2px);box-shadow:0 18px 44px rgba(3,6,20,.45)}
.card.lead-green{border-left:3px solid var(--green)}.card.lead-red{border-left:3px solid var(--red)}
.card.lead-amber{border-left:3px solid var(--amber)}.card.lead-cyan{border-left:3px solid var(--cyan)}
.row1{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.tk{font-size:18px;font-weight:800;font-family:'Sora';letter-spacing:.3px}
.op{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#cdd6ea;background:var(--glass2);border:1px solid var(--stroke);border-radius:6px;padding:1px 7px}
.tag{margin-left:auto;font-size:12px;font-weight:600;color:#b8f5dd;background:rgba(52,211,153,.12);border:1px solid rgba(52,211,153,.3);border-radius:999px;padding:3px 11px}
.nivel{font-size:11.5px;font-weight:800;padding:4px 11px;border-radius:999px;letter-spacing:.3px}
.sub{color:var(--muted);font-size:12.5px;margin-top:5px}
/* chips */
.chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}
.chip{font-size:12px;font-weight:600;border:1px solid var(--stroke);background:var(--glass2);border-radius:999px;padding:4px 11px;color:#cdd6ea;white-space:nowrap}
.chip b{font-weight:800;color:#fff;font-variant-numeric:tabular-nums}
.chip.green{color:#b8f5dd;border-color:rgba(52,211,153,.35);background:rgba(52,211,153,.12)}
.chip.red{color:#fecaca;border-color:rgba(248,113,113,.35);background:rgba(248,113,113,.12)}
.chip.amber{color:#fde68a;border-color:rgba(251,191,36,.35);background:rgba(251,191,36,.12)}
.chip.violet{color:#ddd6fe;border-color:rgba(139,92,246,.4);background:rgba(139,92,246,.15)}
.chip.cyan{color:#a5f3fc;border-color:rgba(34,211,238,.35);background:rgba(34,211,238,.12)}
/* grid de métricas */
.mgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:1px;margin-top:12px;background:var(--stroke);border:1px solid var(--stroke);border-radius:12px;overflow:hidden}
.m{background:rgba(12,16,30,.55);padding:9px 12px}
.ml{font-size:10.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.4px}
.mv{font-size:14.5px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
/* verdict: box (explicador) e pill (diagnóstico) */
.verdict{padding:9px 12px;border-radius:11px;background:rgba(139,92,246,.12);border:1px solid rgba(139,92,246,.28);font-size:12.5px;font-weight:600;color:#e9e6ff}
.verdict.ok,.verdict.no{display:inline-flex;align-items:center;gap:7px;padding:6px 13px;border-radius:999px;font-weight:700;font-size:13px;border:0}
.verdict.ok{color:#0a0e1c;background:linear-gradient(135deg,#34D399,#22D3EE);box-shadow:0 6px 18px rgba(52,211,153,.35)}
.verdict.no{color:#fecaca;background:rgba(248,113,113,.14);border:1px solid rgba(248,113,113,.4)}
/* anéis */
.gauges{display:flex;gap:18px;align-items:center;margin-top:14px;flex-wrap:wrap}
.gauge{display:flex;align-items:center;gap:11px}
.ring{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;position:relative;flex:0 0 auto}
.ring::before{content:"";position:absolute;inset:6px;border-radius:50%;background:#0c1020}
.ring span{position:relative;font-weight:800;font-size:14px;font-variant-numeric:tabular-nums;font-family:'Sora'}
.gl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;font-weight:600}
.gd{font-size:11.5px;color:var(--faint);margin-top:2px;max-width:150px}
.anchor{margin-left:auto;text-align:right}.anchor .av{font-weight:800;font-family:'Sora';font-size:15px;margin-top:3px;font-variant-numeric:tabular-nums}
/* barra de cenário */
.scn{margin-top:15px}
.scn-h{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-bottom:7px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.track{position:relative;height:34px;border-radius:10px;border:1px solid var(--stroke);
background:linear-gradient(90deg,rgba(248,113,113,.18),rgba(251,191,36,.12) 45%,rgba(52,211,153,.18))}
.track .exer{position:absolute;left:0;top:0;bottom:0;border-radius:10px 0 0 10px;border-right:1px dashed rgba(248,113,113,.6);
background:repeating-linear-gradient(45deg,rgba(248,113,113,.22),rgba(248,113,113,.22) 6px,rgba(248,113,113,.10) 6px,rgba(248,113,113,.10) 12px)}
.mk{position:absolute;top:-6px;bottom:-6px;width:2px;background:var(--text);transform:translateX(-1px)}
.mk.strike{background:var(--violet2);box-shadow:0 0 10px rgba(167,139,250,.8)}.mk.spot{background:var(--cyan)}
.mk .lab{position:absolute;top:-19px;left:50%;transform:translateX(-50%);white-space:nowrap;font-size:10px;font-weight:700;
color:var(--violet2);background:rgba(10,14,28,.75);padding:1px 6px;border-radius:6px;border:1px solid rgba(167,139,250,.4)}
.mk.spot .lab{color:var(--cyan);border-color:rgba(34,211,238,.4)}
.scn-f{display:flex;justify-content:space-between;gap:8px;font-size:12px;margin-top:9px;font-variant-numeric:tabular-nums;color:var(--muted);flex-wrap:wrap}
.scn-f b{color:var(--text);font-weight:700}
/* expansível "como ler" + por que */
.por,.why{margin-top:13px;border-top:1px solid var(--stroke);padding-top:11px}
.por>summary,.why>summary{cursor:pointer;font-weight:600;font-size:13px;color:var(--cyan);list-style:none;display:flex;align-items:center;gap:7px}
.por>summary::-webkit-details-marker,.why>summary::-webkit-details-marker{display:none}
.por>summary::before,.why>summary::before{content:"▸";transition:.2s;color:var(--violet2)}
.por[open]>summary::before,.why[open]>summary::before{transform:rotate(90deg)}
.por .body{font-size:13.5px;line-height:1.62;color:#cdd6ea;margin-top:10px}.por .body b{color:#fff}
.whybox{margin-top:13px}
.reasons{margin:10px 0 2px;padding-left:20px}
.reasons li{font-size:13px;color:#cdd6ea;margin-bottom:7px;line-height:1.5}.reasons li b{color:#fff}
.motivo{font-size:13px;color:#cdd6ea;margin-top:12px;line-height:1.55}.motivo .ic{color:var(--violet2)}
/* trava */
.trava{margin-top:13px;background:rgba(34,211,238,.06);border:1px solid rgba(34,211,238,.2);border-radius:13px;padding:12px 14px}
.travah{font-weight:700;margin-bottom:6px}.travah .hint{color:var(--muted);font-weight:400;font-size:12px}
.leg{font-size:13px;margin:3px 0;font-variant-numeric:tabular-nums}
.opc{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#fde68a;background:rgba(251,191,36,.1);border:1px solid rgba(251,191,36,.25);border-radius:6px;padding:0 6px}
/* analise / acao / empty */
.analise{margin-top:11px;color:#cdd6ea;font-size:13px;background:var(--glass);border:1px solid var(--stroke);border-radius:10px;padding:9px 11px}
.acao{margin-top:8px;color:var(--muted);font-size:12.5px}
.empty{text-align:center;color:var(--muted);padding:34px 12px;font-size:14px;background:var(--glass);border:1px solid var(--stroke);border-radius:16px}
/* botões */
.btn{display:inline-flex;align-items:center;gap:7px;padding:9px 15px;border-radius:11px;cursor:pointer;font-weight:600;font-size:13px;color:var(--text);background:var(--glass2);border:1px solid var(--stroke2)}
.btn:hover{background:rgba(255,255,255,.14)}.muted{color:var(--muted);font-size:12.5px}
/* logs */
.logbar{display:flex;gap:7px;margin-bottom:12px;flex-wrap:wrap}
.lf{padding:7px 13px;border-radius:10px;font-size:12.5px;cursor:pointer;border:1px solid var(--stroke);background:var(--glass);color:var(--muted);font-weight:600;appearance:none}
.lf.on{color:#0a0e1c;background:linear-gradient(135deg,var(--violet2),var(--cyan))}
.lf.danger{color:#fecaca;border-color:rgba(248,113,113,.35);background:rgba(248,113,113,.1)}
.log{display:grid;grid-template-columns:104px 96px 1fr;gap:12px;padding:11px 14px;border-radius:12px;background:var(--glass);border:1px solid var(--stroke);margin-bottom:7px;font-size:13px;align-items:center}
.log .t{color:var(--faint);font-size:12px;font-variant-numeric:tabular-nums}
.log .msg{color:#cdd6ea}
.badge{font-size:10.5px;font-weight:800;padding:3px 9px;border-radius:999px;text-align:center;letter-spacing:.4px}
.b-ok{background:rgba(52,211,153,.15);color:#86efac}.b-crit{background:rgba(248,113,113,.18);color:#fca5a5}
.b-warn{background:rgba(251,191,36,.16);color:#fcd34d}.b-info{background:rgba(96,165,250,.15);color:#93c5fd}
.logdet{margin-top:5px}
.logdet>summary{cursor:pointer;color:var(--cyan);font-size:11.5px;list-style:none}
.logdet>summary::-webkit-details-marker{display:none}
.logdet pre{margin:7px 0 2px;padding:10px 12px;background:rgba(2,6,18,.6);color:#cdd6ea;border:1px solid var(--stroke);border-radius:9px;font-size:11px;white-space:pre-wrap;word-break:break-word;max-height:280px;overflow:auto}
.foot{text-align:center;color:var(--faint);font-size:12px;margin-top:26px;line-height:1.7}
@media(min-width:980px){.cards{grid-template-columns:repeat(2,1fr)}}
@media(max-width:720px){.kpis{grid-template-columns:repeat(2,1fr)}.log{grid-template-columns:1fr;gap:4px}.log .t,.badge{justify-self:start}}
`;
}

// ===========================================================================
// Dead-man's switch (DESLIGADO — motor é manual)
// ===========================================================================
// O motor não tem mais agendamento automático (roda só manualmente via GitHub
// Actions). Sem schedule, o "motor parado durante o pregão" é o estado ESPERADO,
// então o vigia perderia o sentido e inundaria o e-mail de "ATRASADO".
// Para reativar (caso volte a agendar): troque VIGIA_ATIVO para true.
const VIGIA_ATIVO = false;
function verificarHeartbeat() {
  if (!VIGIA_ATIVO) return;   // motor manual: não dispara alerta de "atrasado"
  const a = _avaliar();
  const critico = a.titulo.indexOf('ATRASADO') === 0 || a.titulo.indexOf('ERRO') === 0 || a.titulo === 'SEM DADOS';
  if (a.pregao && critico) {
    const idadeTxt = a.idade == null ? 'desconhecida' : Math.round(a.idade) + ' min';
    MailApp.sendEmail(EMAIL_ALERTA, '🔴 Motor ResearchDeOpcoes — ' + a.titulo,
      'O vigia detectou um problema durante o pregão.\n\n' +
      'Situação: ' + a.titulo + '\nÚltima execução: ' + idadeTxt + ' atrás\n' +
      (a.hb ? 'Status: ' + a.hb.status + ' | Mercado: ' + String(a.hb.market) + '\n' : '') +
      (a.hb && a.hb.runUrl ? 'GitHub: ' + a.hb.runUrl + '\n' : '') +
      '\nActions: ' + GITHUB_ACTIONS);
  }
}
