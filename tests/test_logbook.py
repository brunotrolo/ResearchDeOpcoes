"""Aba LOGS: a reescrita newest-first mantém a auditoria visível.

O bug do 'nada na aba LOGS' era um `append` que deixava uma faixa de linhas
vazias sob o cabeçalho e empurrava o run mais recente para o fim (fora da vista).
A reescrita coloca o run novo no topo, descarta linhas vazias e limita o tamanho.
"""
from app import config
from app.logbook import Logbook
from app.sheets_client import _merge_logs_newest_first as merge


def test_run_novo_fica_no_topo():
    existing = [["t1", "RUN", "OK", "antigo", ""]]
    novos = [["t2", "RUN", "OK", "novo-1", ""], ["t3", "MONTE_CARLO", "OK", "novo-2", ""]]
    out = merge(existing, novos, max_rows=100)
    assert out[0][3] == "novo-1" and out[1][3] == "novo-2"   # run novo no topo
    assert out[-1][3] == "antigo"                             # histórico abaixo


def test_descarta_linhas_vazias_do_historico():
    existing = [["", "", "", "", ""], ["  ", "", "", "", ""], ["t1", "RUN", "OK", "real", ""]]
    out = merge(existing, [["t2", "RUN", "OK", "novo", ""]], max_rows=100)
    assert out == [["t2", "RUN", "OK", "novo", ""], ["t1", "RUN", "OK", "real", ""]]


def test_limita_tamanho_mantendo_o_run_novo_inteiro():
    existing = [[f"h{i}", "RUN", "OK", "x", ""] for i in range(50)]
    novos = [[f"n{i}", "RUN", "OK", "y", ""] for i in range(5)]
    out = merge(existing, novos, max_rows=10)
    assert len(out) == 10
    assert [r[0] for r in out[:5]] == ["n0", "n1", "n2", "n3", "n4"]   # run novo inteiro
    # o run novo NUNCA é cortado, mesmo se exceder o teto
    big = [[f"n{i}", "RUN", "OK", "y", ""] for i in range(20)]
    assert len(merge(existing, big, max_rows=10)) == 20


class _FakeWS:
    def __init__(self, values, rows=1000, cols=5):
        self._values, self.row_count, self.col_count = values, rows, cols
        self.updated = None

    def get_all_values(self):
        return self._values

    def resize(self, rows, cols):
        self.row_count, self.col_count = rows, cols

    def update(self, values, range_name, value_input_option):
        self.updated = {"values": values, "range": range_name}


class _FakeSS:
    def __init__(self, ws):
        self._ws = ws

    def worksheet(self, title):
        return self._ws


def test_write_log_rows_corrige_o_gap_de_linhas_vazias(monkeypatch):
    """Reproduz o bug 'nada na aba LOGS': a aba existe com cabeçalho + faixa de
    linhas VAZIAS + dados lá no fim. A reescrita coloca o run novo na linha 2
    (logo abaixo do cabeçalho), sem faixa vazia, e encolhe a grade."""
    import app.sheets_client as sc
    header = ["UPDATED_AT", "SERVICE", "STATUS", "SUMMARY", "CONTEXT"]
    existing = ([header]                                   # linha 1: cabeçalho
                + [["", "", "", "", ""]] * 57              # 57 linhas vazias (o gap)
                + [["t-antigo", "RUN", "OK", "ciclo velho", ""]])   # dado lá embaixo
    ws = _FakeWS(values=existing, rows=1000)
    monkeypatch.setattr(sc, "_spreadsheet", lambda: _FakeSS(ws))

    novos = [["t-novo", "RUN", "OK", "Início do ciclo", ""],
             ["t-novo2", "MONTE_CARLO", "OK", "auditada", ""]]
    sc.write_log_rows("LOGS", header, novos, max_rows=4000)

    vals = ws.updated["values"]
    assert ws.updated["range"] == "A1"
    assert vals[0] == header                       # cabeçalho na linha 1
    assert vals[1][3] == "Início do ciclo"         # run NOVO logo abaixo (linha 2)
    assert vals[2][1] == "MONTE_CARLO"             # auditoria MC visível
    assert vals[3][3] == "ciclo velho"             # histórico preservado, abaixo
    assert all(any(c.strip() for c in r) for r in vals)   # SEM linhas vazias
    assert ws.row_count == len(vals)               # grade encolhida ao tamanho real


def _runtime(monkeypatch, **over):
    """RUNTIME (dataclass FROZEN) recriado com overrides e plugado no config."""
    import dataclasses
    import app.config as cfg
    monkeypatch.setattr(cfg, "RUNTIME", dataclasses.replace(cfg.RUNTIME, **over))


def test_flush_dry_run_nao_grava(monkeypatch):
    """Em DRY_RUN, nada é escrito na planilha (write_log_rows não é chamado)."""
    _runtime(monkeypatch, dry_run=True)
    chamou = {"n": 0}
    import app.logbook as lb
    monkeypatch.setattr(lb.sheets_client, "write_log_rows", lambda *a, **k: chamou.__setitem__("n", 1))
    log = Logbook()
    log.info("RUN", "oi")
    log.flush()
    assert chamou["n"] == 0


def test_flush_chama_write_log_rows(monkeypatch):
    """Fora de DRY_RUN, o flush reescreve a aba LOGS via write_log_rows."""
    _runtime(monkeypatch, dry_run=False)
    capt = {}
    import app.logbook as lb

    def fake(tab, header, rows, max_rows):
        capt.update(tab=tab, header=list(header), n=len(rows), max_rows=max_rows)

    monkeypatch.setattr(lb.sheets_client, "write_log_rows", fake)
    log = Logbook()
    log.info("RUN", "a")
    log.warn("MONTE_CARLO", "b")
    log.flush()
    assert capt["tab"] == config.TAB_LOGS and capt["header"] == config.LOGS_HEADER
    assert capt["n"] == 2 and capt["max_rows"] == config.LOGS_MAX_ROWS
