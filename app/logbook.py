"""Logbook — registro de TODAS as etapas para debug, em 3 destinos:

    1. Aba LOGS do Google Sheets (colunas: UPDATED_AT, SERVICE, STATUS,
       SUMMARY, CONTEXT) — o painel de debug do Bruno.
    2. Arquivo local (logs/motor.log) — resiliência se a planilha falhar.
    3. stdout — útil ao rodar manualmente.

Os registros são bufferizados em memória e gravados de uma vez no final (flush).
A aba LOGS é REESCRITA a cada ciclo com o run mais recente no TOPO (sem faixas de
linhas vazias e com tamanho limitado) — assim a auditoria fica visível logo abaixo
do cabeçalho, em vez de empurrada para o fim por `append` (causa do 'aba vazia').
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app import config, sheets_client

# --- logger local/arquivo ---------------------------------------------------
config.RUNTIME.log_file.parent.mkdir(parents=True, exist_ok=True)
_logger = logging.getLogger("researchdeopcoes")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
    _fh = logging.FileHandler(config.RUNTIME.log_file, encoding="utf-8")
    _fh.setFormatter(_fmt)
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    _logger.addHandler(_fh)
    _logger.addHandler(_sh)


@dataclass
class LogEntry:
    updated_at: str
    service: str
    status: str
    summary: str
    context: str

    def as_row(self) -> list[str]:
        return [self.updated_at, self.service, self.status, self.summary, self.context]


class Logbook:
    """Acumula entradas e dá flush na aba LOGS no final da execução."""

    def __init__(self) -> None:
        self._entries: list[LogEntry] = []
        self._tz = ZoneInfo(config.RUNTIME.timezone)

    def log(self, service: str, status: str, summary: str, context=None) -> None:
        now = datetime.now(self._tz).strftime("%Y-%m-%d %H:%M:%S")
        ctx = ""
        if context is not None:
            ctx = context if isinstance(context, str) else json.dumps(
                context, ensure_ascii=False, default=str
            )
        entry = LogEntry(now, service, str(status).upper(), summary, ctx[:5000])
        self._entries.append(entry)

        level = logging.ERROR if entry.status in {"ERROR", "FAIL"} else logging.INFO
        _logger.log(level, f"[{service}/{entry.status}] {summary} :: {ctx[:300]}")

    # Atalhos semânticos
    def info(self, service: str, summary: str, context=None) -> None:
        self.log(service, "OK", summary, context)

    def warn(self, service: str, summary: str, context=None) -> None:
        self.log(service, "WARN", summary, context)

    def error(self, service: str, summary: str, context=None) -> None:
        self.log(service, "ERROR", summary, context)

    def flush(self) -> None:
        """Reescreve a aba LOGS com este ciclo no TOPO (a não ser em DRY_RUN).

        Antes era um `append` cego, que deixava uma faixa de linhas vazias sob o
        cabeçalho e empurrava o run mais recente para o fim — a aba PARECIA vazia.
        Agora reescrevemos com o run novo no topo, sem faixas vazias e com tamanho
        limitado, então a auditoria fica visível logo abaixo do cabeçalho."""
        if not self._entries:
            return
        if config.RUNTIME.dry_run:
            _logger.info("[DRY_RUN] %d linhas NÃO gravadas na aba LOGS", len(self._entries))
            return
        try:
            sheets_client.write_log_rows(
                config.TAB_LOGS,
                config.LOGS_HEADER,
                [e.as_row() for e in self._entries],
                max_rows=config.LOGS_MAX_ROWS,
            )
        except Exception as exc:  # nunca deixe o log derrubar a execução
            _logger.error("Falha ao gravar LOGS no Sheets: %s", exc)
        finally:
            self._entries.clear()
