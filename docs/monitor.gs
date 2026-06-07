/**
 * Observabilidade do motor ResearchDeOpcoes (Google Apps Script).
 *
 * Lê a aba MONITOR (heartbeat) + LOGS + RADAR_HISTORICO + COMENTARIOS e oferece:
 *   1) doGet  -> painel web (status 🟢/🟡/🔴, resumo, recomendações, anotações
 *      e tabela de LOGS) para abrir no navegador/celular.
 *   2) verificarHeartbeat -> "dead-man's switch": e-mail se o motor não rodar no pregão.
 *
 * COMO USAR:
 *   1. Planilha > Extensões > Apps Script. Cole este arquivo.
 *   2. Painel: Implantar > Nova implantação > App da Web > Executar como "Eu"
 *      > Acesso "Somente eu" > Implantar. Abra/salve a URL (bookmark no celular).
 *   3. Vigia: ícone de relógio (Acionadores) > verificarHeartbeat > a cada 30 min.
 */

const SHEET_ID = '1zuYr3lTOSsVJzvrBJezZ5hFMIM3jpt2jDfR8uCapKds';
const EMAIL_ALERTA = 'brunotrolo@gmail.com';
const ABA_MONITOR = 'MONITOR', ABA_LOGS = 'LOGS', ABA_RADAR = 'RADAR_HISTORICO', ABA_COMENT = 'COMENTARIOS';
const LIMITE_MIN = 75;
const PREGAO_INI = 10, PREGAO_FIM = 18;

function _planilha() { return SpreadsheetApp.openById(SHEET_ID); }

function _heartbeat() {
  const sh = _planilha().getSheetByName(ABA_MONITOR);
  if (!sh || sh.getLastRow() < 2) return null;
  const r = sh.getRange(2, 1, 1, 8).getValues()[0];
  return { updatedAt: r[0], status: r[1], market: r[2], dur: r[3],
           escudo: r[4], radar: r[5], runUrl: r[6], notes: r[7] };
}

function _idadeMin(updatedAt) {
  let ts = (updatedAt instanceof Date) ? updatedAt
           : new Date(String(updatedAt).replace(' ', 'T') + '-03:00');
  return isNaN(ts.getTime()) ? null : (Date.now() - ts.getTime()) / 60000;
}

function _ehPregao() {
  const tz = 'America/Sao_Paulo', a = new Date();
  const dia = parseInt(Utilities.formatDate(a, tz, 'u'), 10);
  const hora = parseInt(Utilities.formatDate(a, tz, 'H'), 10);
  return dia >= 1 && dia <= 5 && hora >= PREGAO_INI && hora < PREGAO_FIM;
}

function _avaliar() {
  const hb = _heartbeat();
  if (!hb) return { cor: '#6b7280', emoji: '⚪', titulo: 'SEM DADOS', hb: null, idade: null, pregao: _ehPregao() };
  const idade = _idadeMin(hb.updatedAt), pregao = _ehPregao();
  let cor = '#16a34a', emoji = '🟢', titulo = 'NO AR';
  if (String(hb.status).indexOf('ERRO') === 0 || String(hb.status) === 'ERROR') {
    cor = '#dc2626'; emoji = '🔴'; titulo = 'ERRO NA ÚLTIMA EXECUÇÃO';
  } else if (idade !== null && pregao && idade > LIMITE_MIN) {
    cor = '#dc2626'; emoji = '🔴'; titulo = 'ATRASADO (motor pode estar parado)';
  } else if (!pregao) {
    cor = '#ca8a04'; emoji = '🟡'; titulo = 'FORA DO PREGÃO';
  }
  return { cor, emoji, titulo, hb, idade, pregao };
}

function _ultimas(aba, n, ncols) {
  const sh = _planilha().getSheetByName(aba);
  if (!sh || sh.getLastRow() < 2) return [];
  const last = sh.getLastRow(), start = Math.max(2, last - n + 1);
  return sh.getRange(start, 1, last - start + 1, ncols).getValues();
}

function _card(titulo, conteudo) {
  return "<div style='background:#fff;border:1px solid #e5e7eb;border-radius:10px;margin:12px 0;overflow:hidden'>"
    + (titulo ? "<div style='padding:10px 14px;font-weight:700;border-bottom:1px solid #f0f0f0'>" + titulo + "</div>" : "")
    + "<div style='padding:6px 0'>" + conteudo + "</div></div>";
}

function _corStatus(s) {
  s = String(s);
  if (s.indexOf('ERR') === 0 || s === 'FAIL') return '#dc2626';
  if (s.indexOf('WARN') === 0) return '#ca8a04';
  return '#16a34a';
}

function doGet(e) {
  const a = _avaliar(), hb = a.hb || {};
  const idadeTxt = a.idade == null ? '—' : Math.round(a.idade) + ' min atrás';
  let html = "<html><head><meta charset='utf-8'>"
    + "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    + "<meta http-equiv='refresh' content='120'></head>"
    + "<body style='font-family:Segoe UI,Arial,sans-serif;background:#f3f4f6;margin:0;padding:14px'>"
    + "<div style='max-width:780px;margin:0 auto'>";

  // Cabeçalho de status
  html += "<div style='background:" + a.cor + ";color:#fff;border-radius:12px;padding:18px;text-align:center'>"
    + "<div style='font-size:40px'>" + a.emoji + "</div>"
    + "<div style='font-size:22px;font-weight:800'>" + a.titulo + "</div>"
    + "<div style='opacity:.9'>Última execução: " + idadeTxt + "</div></div>";

  // Resumo
  html += _card("Resumo da última execução",
    "<table width='100%' style='border-collapse:collapse'><tr>"
    + _kv('Horário', hb.updatedAt) + _kv('Mercado', hb.market) + _kv('Status', hb.status)
    + "</tr><tr>"
    + _kv('Alertas Escudo', hb.escudo) + _kv('Oportunidades', hb.radar) + _kv('Duração (s)', hb.dur)
    + "</tr></table>"
    + (hb.runUrl ? "<div style='padding:6px 14px'><a href='" + hb.runUrl + "'>ver execução no GitHub »</a></div>" : ""));

  // Recomendações recentes (RADAR_HISTORICO)
  const rad = _ultimas(ABA_RADAR, 8, 10).reverse();
  if (rad.length) {
    let t = "<table width='100%' style='border-collapse:collapse;font-size:13px'>"
      + "<tr style='background:#f9fafb;text-align:left'><th style='padding:6px 10px'>Opção</th><th>Ativo</th>"
      + "<th>Strike</th><th>IV Rank</th><th>DTE</th></tr>";
    rad.forEach(r => { t += "<tr><td style='padding:6px 10px;border-top:1px solid #f0f0f0'>" + r[1] + "</td><td>"
      + r[2] + "</td><td>" + r[3] + "</td><td>" + r[6] + "</td><td>" + r[8] + "</td></tr>"; });
    html += _card("📡 Últimas recomendações do Radar", t + "</table>");
  }

  // Suas anotações (COMENTARIOS)
  const com = _ultimas(ABA_COMENT, 30, 3);
  if (com.length) {
    let t = "<table width='100%' style='border-collapse:collapse;font-size:13px'>";
    com.forEach(c => { if (c[0]) t += "<tr><td style='padding:6px 10px;border-top:1px solid #f0f0f0;font-weight:600;white-space:nowrap'>"
      + c[0] + "</td><td style='padding:6px 10px;border-top:1px solid #f0f0f0'>" + c[1] + "</td></tr>"; });
    html += _card("📝 Suas anotações", t + "</table>");
  }

  // Logs recentes
  const logs = _ultimas(ABA_LOGS, 25, 4).reverse();
  let lt = "<table width='100%' style='border-collapse:collapse;font-size:12px'>";
  logs.forEach(l => {
    lt += "<tr><td style='padding:5px 10px;border-top:1px solid #f0f0f0;color:#888;white-space:nowrap'>" + l[0] + "</td>"
      + "<td style='padding:5px 6px;border-top:1px solid #f0f0f0;font-weight:600'>" + l[1] + "</td>"
      + "<td style='padding:5px 6px;border-top:1px solid #f0f0f0;color:" + _corStatus(l[2]) + ";font-weight:700'>" + l[2] + "</td>"
      + "<td style='padding:5px 10px;border-top:1px solid #f0f0f0'>" + l[3] + "</td></tr>";
  });
  html += _card("🧾 Logs recentes", lt + "</table>");

  html += "<p style='color:#9ca3af;font-size:12px;text-align:center'>atualiza sozinho a cada 2 min · motor ResearchDeOpcoes</p>";
  html += "</div></body></html>";
  return HtmlService.createHtmlOutput(html).setTitle('Motor ResearchDeOpcoes');
}

function _kv(k, v) {
  return "<td width='33%' style='padding:8px 14px;vertical-align:top'>"
    + "<div style='font-size:11px;color:#888'>" + k + "</div>"
    + "<div style='font-size:16px;font-weight:700'>" + (v === '' || v == null ? '—' : v) + "</div></td>";
}

/** Gatilho de tempo (~30 min): avisa por e-mail se o motor parou durante o pregão. */
function verificarHeartbeat() {
  const a = _avaliar();
  const critico = a.titulo.indexOf('ATRASADO') === 0 || a.titulo.indexOf('ERRO') === 0 || a.titulo === 'SEM DADOS';
  if (a.pregao && critico) {
    const idadeTxt = a.idade == null ? 'desconhecida' : Math.round(a.idade) + ' min';
    MailApp.sendEmail(EMAIL_ALERTA, '🔴 Motor ResearchDeOpcoes — ' + a.titulo,
      'O vigia detectou um problema durante o pregão.\n\n' +
      'Situação: ' + a.titulo + '\nÚltima execução: ' + idadeTxt + ' atrás\n' +
      (a.hb ? 'Status: ' + a.hb.status + ' | Mercado: ' + a.hb.market + '\n' : '') +
      (a.hb && a.hb.runUrl ? 'GitHub: ' + a.hb.runUrl + '\n' : '') +
      '\nActions: https://github.com/brunotrolo/ResearchDeOpcoes/actions');
  }
}
