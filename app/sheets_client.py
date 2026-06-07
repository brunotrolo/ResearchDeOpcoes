"""Cliente Google Sheets (gspread) — leitura/escrita das abas-espelho.

Responsabilidades:
    - Autenticar via Service Account (credenciais.json).
    - Ler uma aba inteira como DataFrame, respeitando o header_row (offset de
      preâmbulo) e devolvendo as células como string (parsing fica em parsing.py).
    - Anexar linhas em abas de log/histórico, criando a aba se não existir.

A conexão é preguiçosa e cacheada (a planilha é aberta uma vez por execução).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Sequence

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from tenacity import retry, stop_after_attempt, wait_exponential

from app import config

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


@lru_cache(maxsize=1)
def _client() -> gspread.Client:
    creds = Credentials.from_service_account_file(
        config.GOOGLE.credentials_file, scopes=_SCOPES
    )
    return gspread.authorize(creds)


@lru_cache(maxsize=1)
def _spreadsheet() -> gspread.Spreadsheet:
    if not config.GOOGLE.spreadsheet_id:
        raise RuntimeError("SPREADSHEET_ID não configurado no .env")
    return _client().open_by_key(config.GOOGLE.spreadsheet_id)


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=16))
def read_tab(logical_name: str) -> pd.DataFrame:
    """Lê uma aba lógica (chave de config.TABS) como DataFrame de strings.

    Aplica o header_row configurado: tudo acima dele é descartado; a linha
    do header vira os nomes das colunas; o restante são os dados.
    """
    spec = config.TABS[logical_name]
    ws = _spreadsheet().worksheet(spec.title)
    values = ws.get_all_values()
    if not values or len(values) < spec.header_row:
        return pd.DataFrame()

    header = values[spec.header_row - 1]
    rows = values[spec.header_row:]
    df = pd.DataFrame(rows, columns=header)

    # Remove colunas sem nome e linhas 100% vazias.
    df = df.loc[:, [c for c in df.columns if str(c).strip() != ""]]
    df = df[~(df.apply(lambda r: all(str(v).strip() == "" for v in r), axis=1))]
    return df.reset_index(drop=True)


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=16))
def append_rows(
    tab_title: str,
    rows: Sequence[Sequence],
    header: Sequence[str] | None = None,
) -> None:
    """Anexa linhas a uma aba; cria a aba (com header) se ela não existir."""
    if not rows:
        return
    ss = _spreadsheet()
    try:
        ws = ss.worksheet(tab_title)
    except gspread.WorksheetNotFound:
        n_cols = max(len(header or []), max(len(r) for r in rows))
        ws = ss.add_worksheet(title=tab_title, rows=1000, cols=max(n_cols, 5))
        if header:
            ws.append_row(list(header), value_input_option="USER_ENTERED")

    ws.append_rows(
        [list(map(_cell, r)) for r in rows],
        value_input_option="USER_ENTERED",
    )


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=16))
def upsert_status_row(tab_title: str, header: Sequence[str], row: Sequence) -> None:
    """Escreve `header` na linha 1 e `row` na linha 2, SOBRESCREVENDO (a aba
    mantém só o último estado). Usado pelo heartbeat/MONITOR. Cria a aba se faltar."""
    ss = _spreadsheet()
    try:
        ws = ss.worksheet(tab_title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=tab_title, rows=10, cols=max(len(header), 8))
    ws.update(
        values=[[_cell(c) for c in header], [_cell(c) for c in row]],
        range_name="A1",
        value_input_option="USER_ENTERED",
    )


def _cell(value) -> str:
    return "" if value is None else str(value)


def reset_cache() -> None:
    """Limpa o cache de conexão (útil em testes)."""
    _client.cache_clear()
    _spreadsheet.cache_clear()
