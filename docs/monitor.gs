/**
 * Observabilidade do motor ResearchDeOpcoes (Google Apps Script).
 *
 * O motor (GitHub Actions) escreve um "heartbeat" na aba MONITOR a cada execução
 * (linha 2: UPDATED_AT, STATUS, MARKET, DURATION_S, ESCUDO_ALERTS, RADAR_OPPS,
 * RUN_URL, NOTES). Este script oferece:
 *   1) doGet  -> página de status (🟢/🟡/🔴) para abrir no navegador/celular.
 *   2) verificarHeartbeat -> "dead-man's switch": gatilho de tempo que te manda
 *      e-mail se o motor NÃO bater ponto durante o pregão (ou seja, parou).
 *
 * COMO USAR:
 *   1. Na planilha: Extensões > Apps Script. Cole este arquivo.
 *   2. Status no celular: Implantar > Nova implantação > Tipo "App da Web"
 *      > Executar como "Eu" > Acesso "Somente eu" > Implantar. Abra/salve a URL.
 *   3. Vigia automático: Acionadores (ícone de relógio) > Adicionar acionador
 *      > função "verificarHeartbeat" > Baseado em tempo > a cada 30 minutos.
 */

const SHEET_ID = '1zuYr3lTOSsVJzvrBJezZ5hFMIM3jpt2jDfR8uCapKds';
const ABA_MONITOR = 'MONITOR';
const EMAIL_ALERTA = 'brunotrolo@gmail.com';
const LIMITE_MIN = 75;                    // motor roda de hora em hora -> 75 min = atraso
const PREGAO_INI = 10, PREGAO_FIM = 18;   // horário BRT (America/Sao_Paulo)

function _planilha() { return SpreadsheetApp.openById(SHEET_ID); }

function _heartbeat() {
  const sh = _planilha().getSheetByName(ABA_MONITOR);
  if (!sh || sh.getLastRow() < 2) return null;
  const r = sh.getRange(2, 1, 1, 8).getValues()[0];
  return { updatedAt: r[0], status: r[1], market: r[2], dur: r[3],
           escudo: r[4], radar: r[5], runUrl: r[6], notes: r[7] };
}

function _idadeMin(updatedAt) {
  let ts;
  if (updatedAt instanceof Date) ts = updatedAt;
  else ts = new Date(String(updatedAt).replace(' ', 'T') + '-03:00');  // BRT
  if (isNaN(ts.getTime())) return null;
  return (Date.now() - ts.getTime()) / 60000;
}

function _ehPregao() {
  const tz = 'America/Sao_Paulo', agora = new Date();
  const dia = parseInt(Utilities.formatDate(agora, tz, 'u'), 10);   // 1=seg..7=dom
  const hora = parseInt(Utilities.formatDate(agora, tz, 'H'), 10);
  return dia >= 1 && dia <= 5 && hora >= PREGAO_INI && hora < PREGAO_FIM;
}

function _avaliar() {
  const hb = _heartbeat();
  if (!hb) return { cor: '#999', emoji: '⚪', titulo: 'SEM DADOS', hb: null, idade: null, pregao: _ehPregao() };
  const idade = _idadeMin(hb.updatedAt);
  const pregao = _ehPregao();
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

function _linha(k, v) {
  return '<tr><td style="text-align:right;color:#666;padding:3px 8px">' + k +
         '</td><td style="text-align:left;padding:3px 8px"><b>' +
         (v === '' || v == null ? '—' : v) + '</b></td></tr>';
}

function doGet(e) {
  const a = _avaliar();
  const hb = a.hb || {};
  const idadeTxt = a.idade == null ? '—' : Math.round(a.idade) + ' min atrás';
  const html =
    '<html><head><meta name="viewport" content="width=device-width, initial-scale=1">' +
    '<meta http-equiv="refresh" content="120"></head>' +
    '<body style="font-family:Segoe UI,Arial;text-align:center;padding:24px">' +
    '<div style="font-size:64px">' + a.emoji + '</div>' +
    '<h1 style="color:' + a.cor + ';margin:8px">' + a.titulo + '</h1>' +
    '<p style="font-size:18px">Última execução: <b>' + idadeTxt + '</b></p>' +
    '<table style="margin:16px auto;border-collapse:collapse;font-size:15px">' +
    _linha('Horário', hb.updatedAt) + _linha('Status', hb.status) +
    _linha('Mercado', hb.market) + _linha('Duração (s)', hb.dur) +
    _linha('Alertas Escudo', hb.escudo) + _linha('Oportunidades Radar', hb.radar) +
    _linha('Observação', hb.notes) + '</table>' +
    (hb.runUrl ? '<p><a href="' + hb.runUrl + '">ver execução no GitHub</a></p>' : '') +
    '<p style="color:#999;font-size:12px">atualiza sozinho a cada 2 min</p>' +
    '</body></html>';
  return HtmlService.createHtmlOutput(html).setTitle('Motor ResearchDeOpcoes');
}

/** Gatilho de tempo (~30 min): avisa por e-mail se o motor parou durante o pregão. */
function verificarHeartbeat() {
  const a = _avaliar();
  const critico = a.titulo.indexOf('ATRASADO') === 0 ||
                  a.titulo.indexOf('ERRO') === 0 || a.titulo === 'SEM DADOS';
  if (a.pregao && critico) {
    const idadeTxt = a.idade == null ? 'desconhecida' : Math.round(a.idade) + ' min';
    MailApp.sendEmail(EMAIL_ALERTA, '🔴 Motor ResearchDeOpcoes — ' + a.titulo,
      'O vigia detectou um problema durante o pregão.\n\n' +
      'Situação: ' + a.titulo + '\n' +
      'Última execução: ' + idadeTxt + ' atrás\n' +
      (a.hb ? 'Status: ' + a.hb.status + ' | Mercado: ' + a.hb.market + '\n' : '') +
      (a.hb && a.hb.runUrl ? 'GitHub: ' + a.hb.runUrl + '\n' : '') +
      '\nVerifique a aba Actions do GitHub: ' +
      'https://github.com/brunotrolo/ResearchDeOpcoes/actions');
  }
}
