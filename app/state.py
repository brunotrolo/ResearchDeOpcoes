"""Estado e resiliência — lock, dedupe de alertas e marca de última execução.

Peças de robustez (essenciais rodando durante o pregão num notebook Windows):

    - run_lock(): lock-file (filelock) para impedir duas execuções simultâneas
      (ex.: Task Scheduler dispara o catch-up e a tarefa horária ao mesmo tempo).
    - dedupe de alertas: evita reenviar o MESMO alerta de hora em hora. Um
      alerta só re-dispara se ESCALAR de nível (ex.: ALERTA -> CRITICO) no dia.
    - last_run: timestamp da última execução OK, base para diagnósticos/catch-up.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from filelock import FileLock, Timeout

from app import config

_NIVEL_RANK = {"AVISO": 1, "ALERTA": 2, "CRITICO": 3}


def _ensure_dirs() -> None:
    config.RUNTIME.state_dir.mkdir(parents=True, exist_ok=True)


@contextmanager
def run_lock(timeout: float = 1.0):
    """Garante execução única. Lança Timeout se outra instância está rodando."""
    _ensure_dirs()
    lock = FileLock(str(config.RUNTIME.lock_file), timeout=timeout)
    try:
        with lock:
            yield
    except Timeout as exc:
        raise RuntimeError("Outra execução do motor já está em andamento (lock ativo).") from exc


def _load() -> dict:
    _ensure_dirs()
    path = config.RUNTIME.state_file
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict) -> None:
    _ensure_dirs()
    config.RUNTIME.state_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _today_str() -> str:
    return datetime.now(ZoneInfo(config.RUNTIME.timezone)).strftime("%Y-%m-%d")


def filter_new_alerts(alerts: list[dict]) -> list[dict]:
    """Devolve só os alertas inéditos do dia OU que escalaram de nível.

    Cada alerta precisa de 'option_ticker' e 'nivel'. O estado guarda, por dia,
    o maior nível já notificado por opção.
    """
    state = _load()
    today = _today_str()
    seen: dict = state.get("alertas", {})
    if seen.get("_date") != today:
        seen = {"_date": today}  # reseta o dedupe a cada novo dia

    fresh: list[dict] = []
    for a in alerts:
        key = a.get("option_ticker") or a.get("id_trade") or ""
        nivel = a.get("nivel", "AVISO")
        rank = _NIVEL_RANK.get(nivel, 0)
        if rank > seen.get(key, 0):
            fresh.append(a)
            seen[key] = rank

    state["alertas"] = seen
    _save(state)
    return fresh


def filter_new_opportunities(opps: list[dict]) -> list[dict]:
    """Dedupe do Radar: uma oportunidade (option_ticker) só dispara e-mail
    uma vez por dia, mesmo que continue no Top-N nas execuções seguintes.
    """
    state = _load()
    today = _today_str()
    seen: dict = state.get("radar", {})
    if seen.get("_date") != today:
        seen = {"_date": today}

    fresh: list[dict] = []
    for o in opps:
        key = o.get("option_ticker") or ""
        if key and key not in seen:
            fresh.append(o)
            seen[key] = True

    state["radar"] = seen
    _save(state)
    return fresh


def mark_run_ok(summary: dict | None = None) -> None:
    state = _load()
    state["last_run_ok"] = datetime.now(ZoneInfo(config.RUNTIME.timezone)).isoformat()
    if summary:
        state["last_summary"] = summary
    _save(state)


def get_last_run_ok() -> str | None:
    return _load().get("last_run_ok")
