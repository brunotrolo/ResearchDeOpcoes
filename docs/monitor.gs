/**
 * Painel de observabilidade do motor ResearchDeOpcoes (Google Apps Script).
 *
 * Lê as abas MONITOR (heartbeat) + PAINEL_ESCUDO + PAINEL_RADAR + LOGS e entrega:
 *   1) doGet -> dashboard web responsivo (celular + desktop) com status do
 *      motor, resumo da última execução, posições em atenção (Escudo),
 *      oportunidades (Radar, com a Trava de Alta) e os logs recentes.
 *   2) verificarHeartbeat -> "dead-man's switch": e-mail se o motor não rodar
 *      durante o pregão.
 *
 * Robustez: todo conteúdo dinâmico é ESCAPADO (corrige o erro "Conteúdo HTML
 * inválido" que vinha de textos com '<'/'>' como "M9<M21"); datas e números
 * são formatados em pt-BR (corrige strike/duração aparecendo como data).
 *
 * COMO USAR:
 *   1. Planilha > Extensões > Apps Script. Cole este arquivo (substitua o antigo).
 *   2. Painel: Implantar > Nova implantação > App da Web > Executar como "Eu"
 *      > Acesso "Somente eu" > Implantar. Salve a URL (atalho no celular).
 *   3. Vigia: ícone de relógio (Acionadores) > verificarHeartbeat > a cada 30 min.
 */

const SHEET_ID = '1zuYr3lTOSsVJzvrBJezZ5hFMIM3jpt2jDfR8uCapKds';
const EMAIL_ALERTA = 'brunotrolo@gmail.com';
const TZ = 'America/Sao_Paulo';
const ABA_MONITOR = 'MONITOR', ABA_LOGS = 'LOGS', ABA_PESC = 'PAINEL_ESCUDO', ABA_PRAD = 'PAINEL_RADAR';
const LIMITE_MIN = 75;            // atraso (min) que liga o alerta no pregão
const PREGAO_INI = 10, PREGAO_FIM = 18;
const REFRESH_S = 120;            // auto-atualização do painel
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

function _ultimas(aba, n, ncols) {
  const sh = _planilha().getSheetByName(aba);
  if (!sh || sh.getLastRow() < 2) return [];
  const last = sh.getLastRow(), start = Math.max(2, last - n + 1);
  return sh.getRange(start, 1, last - start + 1, ncols).getValues();
}

function _todas(aba, ncols) {
  const sh = _planilha().getSheetByName(aba);
  if (!sh || sh.getLastRow() < 2) return [];
  return sh.getRange(2, 1, sh.getLastRow() - 1, ncols).getValues();
}

// ===========================================================================
// Avaliação de status
// ===========================================================================
function _ehPregao() {
  const a = new Date();
  const dia = parseInt(Utilities.formatDate(a, TZ, 'u'), 10);   // 1=seg ... 7=dom
  const hora = parseInt(Utilities.formatDate(a, TZ, 'H'), 10);
  return dia >= 1 && dia <= 5 && hora >= PREGAO_INI && hora < PREGAO_FIM;
}

function _idadeMin(updatedAt) {
  const d = _toDate(updatedAt);
  return d ? (Date.now() - d.getTime()) / 60000 : null;
}

function _avaliar() {
  const hb = _heartbeat(), pregao = _ehPregao();
  if (!hb) {
    return { cor: '#475569', cor2: '#334155', emoji: '⚪', titulo: 'SEM DADOS',
             hb: null, idade: null, pregao: pregao };
  }
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
// Formatação / escape (à prova de HTML inválido e de coerção de data)
// ===========================================================================
function _esc(v) {
  if (v == null) return '';
  return String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _isDate(v) {
  return Object.prototype.toString.call(v) === '[object Date]' && !isNaN(v.getTime());
}

function _toDate(v) {
  if (_isDate(v)) return v;
  if (v == null || v === '') return null;
  const s = String(v).trim();
  const m = s.match(/^(\d{2})\/(\d{2})\/(\d{4})[ T]?(\d{2})?:?(\d{2})?:?(\d{2})?/);
  if (m) return new Date(+m[3], +m[2] - 1, +m[1], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0));
  const d = new Date(s.replace(' ', 'T'));
  return isNaN(d.getTime()) ? null : d;
}

function _toNum(v) {
  if (v === '' || v == null) return null;
  if (typeof v === 'number') return isNaN(v) ? null : v;
  if (_isDate(v)) return null;                 // valor corrompido por coerção -> sem número
  let s = String(v).trim().replace(/R\$|%|\s/g, '');
  if (s.indexOf(',') >= 0) s = s.replace(/\./g, '').replace(',', '.');   // pt-BR
  const n = parseFloat(s);
  return isNaN(n) ? null : n;
}

function _fmtNum(v, dec) {
  const n = _toNum(v);
  if (n == null) return '—';
  if (dec == null) dec = 2;
  let s = Math.abs(n).toFixed(dec);
  const parts = s.split('.');
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');   // ponto de milhar
  return (n < 0 ? '-' : '') + parts[0] + (dec > 0 ? ',' + parts[1] : '');
}

function _fmtMoney(v) { const n = _toNum(v); return n == null ? '—' : 'R$ ' + _fmtNum(n, 2); }
function _fmtPct(v, dec) { const n = _toNum(v); return n == null ? '—' : _fmtNum(n, dec == null ? 1 : dec) + '%'; }

function _fmtDateTime(v) {
  const d = _toDate(v);
  return d ? Utilities.formatDate(d, TZ, 'dd/MM HH:mm') : (v ? _esc(v) : '—');
}
function _fmtDateFull(v) {
  const d = _toDate(v);
  return d ? Utilities.formatDate(d, TZ, "dd/MM/yyyy 'às' HH:mm") : (v ? _esc(v) : '—');
}

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
  if (s === '') return '—';
  return _esc(s);
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
// Componentes HTML
// ===========================================================================
function _chip(label, value) {
  return "<span class='chip'>" + _esc(label) + " <b>" + value + "</b></span>";
}

function _cardEscudo(rows) {
  if (!rows.length) {
    return _card('🛡️ Posições em atenção', '', "<div class='empty'>Tudo tranquilo por aqui. 🎉<br>Nenhuma posição precisa de defesa agora.</div>");
  }
  const c = { CRITICO: 0, ALERTA: 0, AVISO: 0 };
  rows.forEach(r => { const n = String(r[3]).toUpperCase(); if (c[n] != null) c[n]++; });
  const badge = "🔴 " + c.CRITICO + " · 🟠 " + c.ALERTA + " · 🟡 " + c.AVISO;
  let body = '';
  rows.forEach(r => {
    const cor = _corNivel(r[3]);
    const chips = _chip('', _esc(r[4]))                       // moneyness
      + _chip('DTE', _esc(r[5]) + 'd')
      + _chip('Δ', _fmtNum(r[6], 2))
      + _chip('PoE', _fmtPct(_toNum(r[7]) == null ? null : _toNum(r[7]) * 100, 0))
      + _chip('P/L', _fmtMoney(r[8]));
    body += "<div class='item' style='border-left-color:" + cor + "'>"
      + "<div class='row1'><span class='tk'>" + _esc(r[1]) + "</span>"
      + "<span class='op'>" + _esc(r[2]) + "</span>"
      + "<span class='nivel' style='background:" + cor + "'>" + _esc(r[3]) + "</span></div>"
      + "<div class='chips'>" + chips + "</div>"
      + (r[9] ? "<div class='analise'>" + _esc(r[9]) + "</div>" : '')
      + (r[10] ? "<div class='acao'>👉 " + _esc(r[10]) + "</div>" : '')
      + "</div>";
  });
  return _card('🛡️ Posições em atenção', badge, body);
}

function _cardRadar(rows) {
  if (!rows.length) {
    return _card('📡 Oportunidades', '', "<div class='empty'>Sem oportunidades no filtro agora.<br>O Radar reavalia a cada execução.</div>");
  }
  let body = '';
  rows.forEach(r => {
    const dist = _toNum(r[5]);
    const distTxt = dist == null ? '—' : (dist >= 0 ? '+' : '') + _fmtNum(dist, 1) + '%';
    const chips = _chip('Strike', _fmtMoney(r[3]))
      + _chip('Spot', _fmtMoney(r[4]))
      + _chip('Dist', distTxt)
      + _chip('IV', _fmtNum(r[6], 0))
      + _chip('DTE', _esc(r[7]) + 'd');
    body += "<div class='item' style='border-left-color:#16a34a'>"
      + "<div class='row1'><span class='tk'>" + _esc(r[1]) + "</span>"
      + "<span class='op'>" + _esc(r[2]) + "</span></div>"
      + "<div class='chips'>" + chips + "</div>"
      + (r[8] ? "<div class='analise'>" + _esc(r[8]) + "</div>" : '')
      + "</div>";
  });
  return _card('📡 Oportunidades', rows.length + (rows.length === 1 ? ' ideia' : ' ideias'), body);
}

function _cardLogs(rows) {
  if (!rows.length) return '';
  let body = "<div class='logs'>";
  rows.forEach(l => {
    body += "<div class='log'>"
      + "<span class='dot' style='background:" + _corStatus(l[2]) + "'></span>"
      + "<span class='t'>" + _fmtDateTime(l[0]) + "</span>"
      + "<span class='s'>" + _esc(l[1]) + "</span>"
      + "<span class='msg'>" + _esc(l[3]) + "</span></div>";
  });
  return _card('🧾 Logs recentes', rows.length + ' eventos', body + "</div>");
}

function _card(titulo, badge, body) {
  return "<div class='card'><div class='head'><span>" + titulo + "</span>"
    + (badge ? "<span class='badge'>" + badge + "</span>" : '')
    + "</div>" + body + "</div>";
}

function _metric(label, value) {
  return "<div class='metric'><div class='l'>" + _esc(label) + "</div><div class='v'>" + value + "</div></div>";
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
    const safe = "<html><head><meta charset='utf-8'></head>"
      + "<body style='font-family:Arial,sans-serif;padding:24px;color:#0f172a'>"
      + "<h2>⚠️ Painel indisponível no momento</h2>"
      + "<p>O painel encontrou um erro ao montar a página, mas o motor segue rodando.</p>"
      + "<pre style='background:#f1f5f9;padding:12px;border-radius:8px;white-space:pre-wrap'>"
      + _esc(err && err.message ? err.message : err) + "</pre>"
      + "<p><a href='" + GITHUB_ACTIONS + "'>Ver execuções no GitHub »</a></p>"
      + "</body></html>";
    return HtmlService.createHtmlOutput(safe).setTitle('Motor ResearchDeOpcoes');
  }
}

function _render() {
  const a = _avaliar(), hb = a.hb || {};
  const esc = _todas(ABA_PESC, 11);
  const rad = _todas(ABA_PRAD, 9);
  const logs = _ultimas(ABA_LOGS, 30, 4).reverse();

  const hero = "<div class='hero' style='background:linear-gradient(135deg," + a.cor + "," + a.cor2 + ")'>"
    + "<div class='emoji'>" + a.emoji + "</div>"
    + "<h1>" + _esc(a.titulo) + "</h1>"
    + "<div class='sub'>Última execução " + _idadeTxt(a.idade)
    + " · " + _fmtDateFull(hb.updatedAt) + "</div>"
    + "<div class='hstats'>"
    + "<div class='hstat'><div class='l'>Mercado</div><div class='v'>" + _mercadoLabel(hb.market) + "</div></div>"
    + "<div class='hstat'><div class='l'>Escudo</div><div class='v'>" + _fmtNum(hb.escudo, 0) + "</div></div>"
    + "<div class='hstat'><div class='l'>Oportunidades</div><div class='v'>" + _fmtNum(hb.radar, 0) + "</div></div>"
    + "<div class='hstat'><div class='l'>Duração</div><div class='v'>" + _fmtNum(hb.dur, 1) + "s</div></div>"
    + "</div></div>";

  const toolbar = "<div class='toolbar'>"
    + "<button class='btn' onclick='location.reload()'>↻ Atualizar agora</button>"
    + "<span class='muted'>atualiza sozinho a cada " + Math.round(REFRESH_S / 60) + " min</span></div>";

  const resumo = _card('Resumo da última execução',
    (hb.runUrl ? "<a href='" + _esc(hb.runUrl) + "'>GitHub »</a>" : ''),
    "<div class='metrics'>"
    + _metric('Horário', _fmtDateFull(hb.updatedAt))
    + _metric('Status', "<span style='color:" + _corStatus(hb.status) + "'>" + _esc(hb.status || '—') + "</span>")
    + _metric('Mercado', _mercadoLabel(hb.market))
    + _metric('Alertas Escudo', _fmtNum(hb.escudo, 0))
    + _metric('Oportunidades', _fmtNum(hb.radar, 0))
    + _metric('Duração (s)', _fmtNum(hb.dur, 1))
    + "</div>"
    + (hb.notes ? "<div class='acao' style='padding:4px 16px 12px'>" + _esc(hb.notes) + "</div>" : ''));

  const foot = "<div class='foot'>"
    + "Pregão " + PREGAO_INI + "h–" + PREGAO_FIM + "h (seg–sex) · vigia avisa por e-mail se o motor parar"
    + " · <a href='" + GITHUB_ACTIONS + "'>Actions</a><br>motor ResearchDeOpcoes</div>";

  const script = "<script>setTimeout(function(){location.reload();}," + (REFRESH_S * 1000) + ");</script>";

  return "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'>"
    + "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    + "<style>" + _css() + "</style></head><body><div class='wrap'>"
    + hero + toolbar + resumo
    + _cardEscudo(esc) + _cardRadar(rad) + _cardLogs(logs)
    + foot + "</div>" + script + "</body></html>";
}

function _css() {
  return ""
    + "*{box-sizing:border-box}"
    + "body{margin:0;background:#f1f5f9;color:#0f172a;line-height:1.45;"
    + "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;-webkit-font-smoothing:antialiased}"
    + ".wrap{max-width:880px;margin:0 auto;padding:16px}"
    + ".hero{border-radius:18px;padding:22px 20px;color:#fff;box-shadow:0 10px 30px rgba(2,6,23,.18)}"
    + ".hero .emoji{font-size:42px;line-height:1}"
    + ".hero h1{margin:6px 0 2px;font-size:24px;font-weight:800;letter-spacing:.2px}"
    + ".hero .sub{opacity:.92;font-size:13.5px}"
    + ".hstats{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}"
    + ".hstat{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);border-radius:12px;padding:8px 12px;min-width:92px}"
    + ".hstat .l{font-size:11px;opacity:.85;text-transform:uppercase;letter-spacing:.4px}"
    + ".hstat .v{font-size:17px;font-weight:700;margin-top:2px}"
    + ".toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:14px 2px 0;flex-wrap:wrap}"
    + ".muted{color:#64748b;font-size:13px}"
    + ".btn{appearance:none;border:1px solid #e5e7eb;background:#fff;color:#0f172a;border-radius:10px;"
    + "padding:9px 15px;font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 1px 2px rgba(2,6,23,.06)}"
    + ".btn:active{transform:translateY(1px)}"
    + ".card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;margin:14px 0;overflow:hidden;box-shadow:0 1px 3px rgba(2,6,23,.05)}"
    + ".card .head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:13px 16px;font-weight:700;border-bottom:1px solid #f1f5f9}"
    + ".card .head .badge{font-size:12px;font-weight:700;color:#64748b}"
    + ".metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:2px;padding:6px}"
    + ".metric{padding:10px 12px}"
    + ".metric .l{font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.4px}"
    + ".metric .v{font-size:16px;font-weight:700;margin-top:3px;word-break:break-word}"
    + ".item{padding:12px 16px;border-top:1px solid #f1f5f9;border-left:4px solid transparent}"
    + ".item .row1{display:flex;align-items:center;flex-wrap:wrap;gap:8px}"
    + ".tk{font-weight:800;font-size:15px}"
    + ".op{color:#64748b;font-size:13px}"
    + ".nivel{font-size:11px;font-weight:800;padding:2px 9px;border-radius:999px;color:#fff;text-transform:uppercase;letter-spacing:.3px}"
    + ".chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}"
    + ".chip{font-size:12px;background:#f8fafc;border:1px solid #eef2f7;border-radius:8px;padding:3px 8px;color:#334155;white-space:nowrap}"
    + ".chip b{color:#0f172a}"
    + ".analise{margin-top:8px;color:#334155;font-size:13px}"
    + ".acao{margin-top:6px;color:#64748b;font-size:12.5px}"
    + ".empty{padding:26px 16px;text-align:center;color:#64748b}"
    + ".logs{padding:2px 0}"
    + ".log{display:flex;gap:10px;align-items:flex-start;padding:8px 14px;border-top:1px solid #f4f6f9;font-size:12.5px}"
    + ".log .dot{width:8px;height:8px;border-radius:50%;margin-top:5px;flex:0 0 auto}"
    + ".log .t{color:#94a3b8;white-space:nowrap;font-variant-numeric:tabular-nums;min-width:78px}"
    + ".log .s{font-weight:700;color:#64748b;min-width:84px}"
    + ".log .msg{color:#334155}"
    + ".foot{color:#94a3b8;font-size:12px;text-align:center;margin:18px 4px}"
    + "a{color:#2563eb;text-decoration:none}a:hover{text-decoration:underline}"
    + "@media (max-width:560px){.wrap{padding:12px}.hero{padding:18px 16px}.hero h1{font-size:21px}"
    + ".metric .v{font-size:15px}.log{flex-wrap:wrap;gap:4px 10px}.log .s{min-width:0}.log .msg{flex-basis:100%}}";
}

// ===========================================================================
// Dead-man's switch (gatilho de tempo ~30 min)
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
