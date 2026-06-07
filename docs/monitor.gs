/**
 * Painel de observabilidade do motor ResearchDeOpcoes (Google Apps Script).
 *
 * Lê MONITOR (heartbeat) + PAINEL_ESCUDO + PAINEL_RADAR + LOGS e entrega um
 * dashboard web responsivo (celular + desktop) com TODAS as informações que
 * vão no e-mail: defesa de posições (Escudo) e oportunidades (Radar, com a
 * Trava de Alta), além de status do motor e logs.
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
 */

const SHEET_ID = '1zuYr3lTOSsVJzvrBJezZ5hFMIM3jpt2jDfR8uCapKds';
const EMAIL_ALERTA = 'brunotrolo@gmail.com';
const TZ = 'America/Sao_Paulo';
const ABA_MONITOR = 'MONITOR', ABA_LOGS = 'LOGS', ABA_PESC = 'PAINEL_ESCUDO', ABA_PRAD = 'PAINEL_RADAR';
const LIMITE_MIN = 75;
const PREGAO_INI = 10, PREGAO_FIM = 18;
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
  const dia = parseInt(Utilities.formatDate(a, TZ, 'u'), 10);
  const hora = parseInt(Utilities.formatDate(a, TZ, 'H'), 10);
  return dia >= 1 && dia <= 5 && hora >= PREGAO_INI && hora < PREGAO_FIM;
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

function _cardEscudo() {
  const { idx, rows } = _readPanel(ABA_PESC);
  if (!rows.length) return _section('🛡️ Posições em atenção', '',
    "<div class='empty'>Tudo tranquilo por aqui. 🎉<br>Nenhuma posição precisa de defesa agora.</div>");
  const c = { CRITICO: 0, ALERTA: 0, AVISO: 0 };
  rows.forEach(r => { const n = String(r[idx['NIVEL']]).toUpperCase(); if (c[n] != null) c[n]++; });
  const badge = '🔴 ' + c.CRITICO + ' · 🟠 ' + c.ALERTA + ' · 🟡 ' + c.AVISO;
  let items = '';
  rows.forEach(r => {
    const g = n => (idx[n] == null ? '' : r[idx[n]]);
    const nivel = String(g('NIVEL')).toUpperCase();
    const cor = _corNivel(nivel);
    if (String(g('OPCAO')).indexOf('PORTFOLIO') === 0) {
      items += "<div class='item' style='border-left-color:" + cor + "'>"
        + "<div class='row1'><span class='tk'>🛡️ Carteira</span>"
        + "<span class='nivel' style='background:" + cor + "'>" + esc(nivel) + "</span></div>"
        + (g('ANALISE') ? "<div class='analise'>" + esc(g('ANALISE')) + "</div>" : '')
        + (g('ACAO') ? "<div class='acao'>👉 " + esc(g('ACAO')) + "</div>" : '') + "</div>";
      return;
    }
    const chips = _chip('', esc(g('MONEYNESS')))
      + _chip('DTE', _diasTxt(g('DTE')))
      + _chip('Δ', _fmtNum(g('DELTA'), 2))
      + _chip('γ', _fmtNum(g('GAMMA'), 2))
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
    items += "<div class='item' style='border-left-color:" + cor + "'>"
      + "<div class='row1'><span class='tk'>" + esc(g('TICKER')) + "</span> <span class='op'>" + esc(g('OPCAO')) + "</span>"
      + "<span class='nivel' style='background:" + cor + "'>" + esc(nivel) + "</span></div>"
      + "<div class='sub'>" + esc(g('SIDE')) + " " + esc(g('TIPO')) + " · " + esc(g('MONEYNESS'))
      + " · " + _diasTxt(g('DTE')) + " (" + _fmtDateOnly(g('EXPIRY')) + ") · " + esc(g('QTD')) + " contratos</div>"
      + "<div class='chips'>" + chips + "</div>" + grid
      + (g('ANALISE') ? "<div class='analise'>🔎 " + esc(g('ANALISE')) + "</div>" : '')
      + (g('ACAO') ? "<div class='acao'>👉 " + esc(g('ACAO')) + "</div>" : '') + "</div>";
  });
  return _section('🛡️ Posições em atenção', badge, "<div class='cards'>" + items + "</div>");
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

function _cardRadar() {
  const { idx, rows } = _readPanel(ABA_PRAD);
  if (!rows.length) return _section('📡 Oportunidades', '',
    "<div class='empty'>Sem oportunidades no filtro agora.<br>O Radar reavalia a cada execução.</div>");
  let items = '';
  rows.forEach(r => {
    const g = n => (idx[n] == null ? '' : r[idx[n]]);
    const temTrava = g('TRAVA_VENDE_STRIKE') !== '' && g('TRAVA_VENDE_STRIKE') != null;
    const tag = temTrava ? '🛡️ Trava de Alta com PUT' : '📉 Venda de PUT';
    const dist = _num(g('DIST_PCT'));
    const distTxt = dist == null ? '—' : (dist >= 0 ? '+' : '') + _fmtNum(dist, 1) + '%';
    const aprox = String(g('PREMIO_FONTE') || '').indexOf('estim') >= 0 ? '≈ ' : '';
    const chips = _chip('Strike', _fmtMoney(g('STRIKE')))
      + _chip('Spot', _fmtMoney(g('SPOT')))
      + _chip('Dist', distTxt)
      + _chip('IV', _fmtNum(g('IV_RANK'), 0))
      + _chip('Taxa', _fmtPct(g('TAXA_RETORNO'), 1))
      + _chip('PoE', _fmtPct(_num(g('POE_MC')) == null ? null : _num(g('POE_MC')) * 100, 0))
      + (g('TOQUE') !== '' ? _chip('Toque', _fmtPct(_num(g('TOQUE')) == null ? null : _num(g('TOQUE')) * 100, 0)) : '')
      + _chip('Prêmio', aprox + _fmtMoney(g('PREMIO')))
      + (g('VOLUME_FIN') !== '' ? _chip('Vol', _fmtMoney(g('VOLUME_FIN'))) : '');
    items += "<div class='item' style='border-left-color:#16a34a'>"
      + "<div class='row1'><span class='tk'>" + esc(g('TICKER')) + "</span> <span class='op'>" + esc(g('OPCAO')) + "</span>"
      + "<span class='tag'>" + tag + "</span></div>"
      + "<div class='sub'>" + _diasTxt(g('DTE')) + " (" + _fmtDateOnly(g('EXPIRY')) + ") · prêmio " + aprox + _fmtMoney(g('PREMIO')) + "/ação</div>"
      + "<div class='chips'>" + chips + "</div>" + _travaBlock(g)
      + (g('ANALISE') ? "<div class='analise'>💡 " + esc(g('ANALISE')) + "</div>" : '') + "</div>";
  });
  return _section('📡 Oportunidades', rows.length + (rows.length === 1 ? ' ideia' : ' ideias'),
    "<div class='cards'>" + items + "</div>");
}

function _cardLogs() {
  const logs = _ultimas(ABA_LOGS, 40, 4).reverse();
  if (!logs.length) return '';
  let body = "<div class='logs'>";
  logs.forEach(l => {
    body += "<div class='log'><span class='dot' style='background:" + _corStatus(l[2]) + "'></span>"
      + "<span class='t'>" + _fmtDateTime(l[0]) + "</span>"
      + "<span class='sv'>" + esc(l[1]) + "</span>"
      + "<span class='msg'>" + esc(l[3]) + "</span></div>";
  });
  return _section('🧾 Logs recentes', logs.length + ' eventos', body + "</div>");
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
function _inner() {
  const a = _avaliar(), hb = a.hb || {};
  const hero = "<div class='hero' style='background:linear-gradient(135deg," + a.cor + "," + a.cor2 + ")'>"
    + "<div class='emoji'>" + a.emoji + "</div><h1>" + esc(a.titulo) + "</h1>"
    + "<div class='subh'>Última execução " + _idadeTxt(a.idade) + " · " + _fmtDateFull(hb.updatedAt) + "</div>"
    + "<div class='hstats'>"
    + "<div class='hstat'><div class='l'>Mercado</div><div class='v'>" + _mercadoLabel(hb.market) + "</div></div>"
    + "<div class='hstat'><div class='l'>Escudo</div><div class='v'>" + _fmtNum(hb.escudo, 0) + "</div></div>"
    + "<div class='hstat'><div class='l'>Oportunidades</div><div class='v'>" + _fmtNum(hb.radar, 0) + "</div></div>"
    + "<div class='hstat'><div class='l'>Duração</div><div class='v'>" + _fmtNum(hb.dur, 1) + "s</div></div>"
    + "</div></div>";
  const toolbar = "<div class='toolbar'><button class='btn' onclick='_refresh()'>↻ Atualizar agora</button>"
    + "<span class='muted' id='refStatus'>atualiza sozinho a cada " + Math.round(REFRESH_S / 60) + " min</span></div>";
  const resumo = _section('Resumo da última execução', (hb.runUrl ? "<a href='" + esc(hb.runUrl) + "'>GitHub »</a>" : ''),
    _grid([
      ['Horário', _fmtDateFull(hb.updatedAt)],
      ['Status', "<span style='color:" + _corStatus(hb.status) + "'>" + esc(hb.status || '—') + "</span>"],
      ['Mercado', _mercadoLabel(hb.market)],
      ['Alertas Escudo', _fmtNum(hb.escudo, 0)],
      ['Oportunidades', _fmtNum(hb.radar, 0)],
      ['Duração (s)', _fmtNum(hb.dur, 1)],
    ]) + (hb.notes ? "<div class='acao' style='padding:2px 14px 10px'>" + esc(hb.notes) + "</div>" : ''));
  const foot = "<div class='foot'>Pregão " + PREGAO_INI + "h–" + PREGAO_FIM + "h (seg–sex) · vigia avisa por e-mail se o motor parar"
    + " · <a href='" + GITHUB_ACTIONS + "'>Actions</a><br>motor ResearchDeOpcoes</div>";
  return hero + toolbar + resumo + _cardEscudo() + _cardRadar() + _cardLogs() + foot;
}

// Chamado pelo CLIENTE via google.script.run — devolve só o HTML do painel.
function getPainel() {
  try { return _inner(); }
  catch (e) { return "<div class='sec'><div class='item'>Falha ao atualizar agora: "
    + esc(e && e.message ? e.message : e) + "</div></div>"; }
}

function _render() {
  // Refresh SEM reload: busca o HTML novo via google.script.run e troca o DOM.
  // Evita a navegação do iframe sandbox (que expira o token e zera a tela).
  const script = "<script>"
    + "function _apply(html){var el=document.getElementById('painel');if(el&&html)el.innerHTML=html;}"
    + "function _refresh(){var s=document.getElementById('refStatus');if(s)s.textContent='atualizando…';"
    + "google.script.run.withSuccessHandler(_apply).withFailureHandler(function(){"
    + "var s2=document.getElementById('refStatus');if(s2)s2.textContent='sem conexão — tentando de novo';}).getPainel();}"
    + "setInterval(_refresh," + (REFRESH_S * 1000) + ");"
    + "</script>";
  return "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'>"
    + "<meta name='viewport' content='width=device-width, initial-scale=1'><style>" + _css() + "</style></head>"
    + "<body><div class='wrap' id='painel'>" + _inner() + "</div>" + script + "</body></html>";
}

function _css() {
  return ""
    + "*{box-sizing:border-box}"
    + "body{margin:0;background:#eef1f5;color:#0f172a;line-height:1.45;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;-webkit-font-smoothing:antialiased}"
    + ".wrap{max-width:1040px;margin:0 auto;padding:18px}"
    + ".hero{border-radius:18px;padding:22px 22px;color:#fff;box-shadow:0 12px 34px rgba(2,6,23,.20)}"
    + ".hero .emoji{font-size:42px;line-height:1}"
    + ".hero h1{margin:6px 0 2px;font-size:25px;font-weight:800;letter-spacing:.2px}"
    + ".hero .subh{opacity:.92;font-size:13.5px}"
    + ".hstats{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}"
    + ".hstat{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);border-radius:12px;padding:9px 14px;min-width:104px;flex:1 1 auto}"
    + ".hstat .l{font-size:11px;opacity:.85;text-transform:uppercase;letter-spacing:.4px}"
    + ".hstat .v{font-size:18px;font-weight:700;margin-top:2px}"
    + ".toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:16px 2px 2px;flex-wrap:wrap}"
    + ".muted{color:#64748b;font-size:13px}"
    + ".btn{appearance:none;border:1px solid #d7dde6;background:#fff;color:#0f172a;border-radius:10px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 1px 2px rgba(2,6,23,.06)}"
    + ".btn:active{transform:translateY(1px)}"
    + ".sec{margin:18px 0}"
    + ".sechead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 2px 10px;font-weight:800;font-size:17px}"
    + ".sechead .badge{font-size:12.5px;font-weight:700;color:#64748b}"
    + ".cards{display:grid;grid-template-columns:1fr;gap:14px}"
    + ".item{background:#fff;border:1px solid #e5e7eb;border-left:5px solid #cbd5e1;border-radius:14px;padding:14px 16px;box-shadow:0 1px 3px rgba(2,6,23,.06)}"
    + ".item .row1{display:flex;align-items:center;flex-wrap:wrap;gap:8px}"
    + ".tk{font-weight:800;font-size:16px}"
    + ".op{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:700;color:#0f172a;font-size:13px;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;padding:1px 7px}"
    + ".opc{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:700;color:#0f172a;background:#fff7ed;border:1px solid #fed7aa;border-radius:6px;padding:0 6px}"
    + ".sub{color:#64748b;font-size:12.5px;margin-top:3px}"
    + ".nivel{margin-left:auto;font-size:11px;font-weight:800;padding:3px 10px;border-radius:999px;color:#fff;text-transform:uppercase;letter-spacing:.3px}"
    + ".tag{margin-left:auto;font-size:11.5px;font-weight:700;color:#166534;background:#dcfce7;border:1px solid #bbf7d0;border-radius:999px;padding:3px 10px}"
    + ".chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}"
    + ".chip{font-size:12px;background:#f1f5f9;border:1px solid #e6ebf2;border-radius:8px;padding:3px 9px;color:#334155;white-space:nowrap}"
    + ".chip b{color:#0f172a}"
    + ".mgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:1px;margin-top:11px;background:#eef2f7;border:1px solid #eef2f7;border-radius:10px;overflow:hidden}"
    + ".m{background:#fff;padding:8px 11px}"
    + ".ml{font-size:10.5px;color:#94a3b8;text-transform:uppercase;letter-spacing:.4px}"
    + ".mv{font-size:14.5px;font-weight:700;margin-top:2px}"
    + ".trava{margin-top:11px;background:#ecfdf5;border:1px solid #d1fae5;border-radius:10px;padding:10px 12px}"
    + ".travah{font-weight:700;margin-bottom:4px}"
    + ".travah .hint{color:#64748b;font-weight:400;font-size:12px}"
    + ".leg{font-size:13px;margin:2px 0}"
    + ".analise{margin-top:10px;color:#334155;font-size:13px;background:#f8fafc;border-radius:8px;padding:8px 10px}"
    + ".acao{margin-top:7px;color:#475569;font-size:12.5px}"
    + ".empty{padding:26px 16px;text-align:center;color:#64748b;background:#fff;border:1px solid #e5e7eb;border-radius:14px}"
    + ".logs{background:#fff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden}"
    + ".log{display:flex;gap:10px;align-items:flex-start;padding:8px 14px;border-top:1px solid #f1f5f9;font-size:12.5px}"
    + ".log:first-child{border-top:none}"
    + ".log .dot{width:8px;height:8px;border-radius:50%;margin-top:5px;flex:0 0 auto}"
    + ".log .t{color:#94a3b8;white-space:nowrap;font-variant-numeric:tabular-nums;min-width:82px}"
    + ".log .sv{font-weight:700;color:#64748b;min-width:92px}"
    + ".log .msg{color:#334155}"
    + ".foot{color:#94a3b8;font-size:12px;text-align:center;margin:20px 4px}"
    + "a{color:#2563eb;text-decoration:none}a:hover{text-decoration:underline}"
    + "@media (min-width:820px){.cards{grid-template-columns:1fr 1fr}}"
    + "@media (max-width:560px){.wrap{padding:13px}.hero{padding:18px 16px}.hero h1{font-size:21px}"
    + ".log{flex-wrap:wrap;gap:3px 10px}.log .sv{min-width:0}.log .msg{flex-basis:100%}}";
}

// ===========================================================================
// Dead-man's switch
// ===========================================================================
function verificarHeartbeat() {
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
