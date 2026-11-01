"""
Инструменты для разработки: git (статус/лог/diff), запущенные процессы, занятые порты, логи.

Все функции здесь только ЧИТАЮТ — ничего не меняют на диске и не запускают посторонние программы
кроме самого git (фиксированным набором аргументов, без участия shell — поэтому ему нельзя
подсунуть постороннюю команду через текст). Чтобы что-то реально ОСТАНОВИТЬ (например, зависший
процесс) — Акира пользуется уже существующим propose_terminal_command с подтверждением, а не
отдельным путём в обход него; см. ENABLE_TERMINAL_COMMANDS в .env.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import config

log = logging.getLogger("akira.devtools")

MAX_OUTPUT = 4000   # не заваливать модель мегабайтным diff'ом или списком процессов
GIT_TIMEOUT = 15.0
MAX_EDIT_PREVIEW = 1500


# -------------------------------------------------------------- правка кода
def prepare_edit(path: str, old: str, new: str) -> tuple[Optional[str], str]:
    """Проверяет, что правку можно применить однозначно — не трогает файл.
    Возвращает (текст ошибки | None, превью «было/станет» для показа владельцу)."""
    p = Path(path).expanduser()
    if not p.is_file():
        return f"Файл «{p}» не найден.", ""
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"Не удалось прочитать файл: {e}", ""
    count = text.count(old)
    if count == 0:
        return "Не нашла в файле точно такой текст для замены — возможно, он уже другой.", ""
    if count > 1:
        return (f"Такой текст встречается в файле {count} раз(а) — нужен более точный фрагмент, "
                "чтобы однозначно понять, какое место менять."), ""
    preview = (f"Файл: {p}\n--- было ---\n{old[:MAX_EDIT_PREVIEW]}\n--- станет ---\n"
              f"{new[:MAX_EDIT_PREVIEW]}")
    return None, preview


def apply_edit(path: str, old: str, new: str) -> str:
    """Применяет уже подтверждённую правку. Перепроверяет однозначность (файл мог измениться
    между предложением и подтверждением) и на всякий случай оставляет резервную копию .bak."""
    p = Path(path).expanduser()
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"Не удалось прочитать файл перед применением: {e}"
    if text.count(old) != 1:
        return "Файл изменился с момента предложения правки — не стала применять, посмотри заново."
    backup = p.with_suffix(p.suffix + ".bak")
    try:
        shutil.copy2(p, backup)
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
    except OSError as e:
        return f"Не удалось записать файл: {e}"
    return f"Готово — изменила «{p}» (резервная копия рядом: {backup.name})."


def _run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                           timeout=GIT_TIMEOUT, encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout + r.stderr)
    except FileNotFoundError:
        return 127, "Программа git не найдена — установи Git for Windows или git."
    except subprocess.TimeoutExpired:
        return 1, "git выполнялся слишком долго."
    except OSError as e:
        return 1, f"Не удалось запустить git: {e}"


def _resolve_project(path: str) -> Optional[Path]:
    """Путь к проекту: явно переданный, иначе DEV_PROJECT_DIR из .env, иначе None."""
    candidate = (path or "").strip() or getattr(config, "DEV_PROJECT_DIR", "")
    if not candidate:
        return None
    p = Path(candidate).expanduser()
    return p if p.is_dir() else None


def _git_repo(path: str) -> tuple[Optional[Path], str]:
    repo = _resolve_project(path)
    if repo is None:
        return None, ("Не знаю, какой проект смотреть — назови путь или укажи "
                      "DEV_PROJECT_DIR в .env (свой проект по умолчанию).")
    if not (repo / ".git").exists():
        return None, f"В «{repo}» нет git-репозитория (нет папки .git)."
    return repo, ""


# --------------------------------------------------------------------- git
def git_status(path: str = "") -> str:
    repo, err = _git_repo(path)
    if repo is None:
        return err
    code, out = _run_git(["status", "--short", "--branch"], repo)
    if code != 0:
        return f"git status не сработал: {out[:500]}"
    return out.strip() or "Изменений нет — всё закоммичено."


def git_log(path: str = "", limit: int = 10) -> str:
    repo, err = _git_repo(path)
    if repo is None:
        return err
    limit = max(1, min(int(limit), 50))
    code, out = _run_git(["log", f"-{limit}", "--oneline", "--decorate"], repo)
    if code != 0:
        return f"git log не сработал: {out[:500]}"
    return out.strip() or "Коммитов пока нет."


def git_diff(path: str = "") -> str:
    repo, err = _git_repo(path)
    if repo is None:
        return err
    code, out = _run_git(["diff", "HEAD"], repo)
    if code != 0:
        return f"git diff не сработал: {out[:500]}"
    out = out.strip()
    if not out:
        return "Незакоммиченных изменений нет."
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n…(показаны не все изменения, diff большой)"
    return out


# ------------------------------------------------------------- процессы/порты
def list_running_processes(name_filter: str = "") -> str:
    try:
        import psutil
    except ImportError:
        return "Не установлен пакет psutil."
    needle = (name_filter or "").strip().lower()
    rows: list[tuple[int, str, float]] = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = p.info
            name = info.get("name") or ""
            if needle and needle not in name.lower():
                continue
            mi = info.get("memory_info")
            mem = (mi.rss / 1024 / 1024) if mi else 0.0
            rows.append((info["pid"], name, mem))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if not rows:
        return f"Процессов с «{name_filter}» в имени не нашла." if needle else "Процессов не нашла."
    rows.sort(key=lambda r: r[2], reverse=True)
    lines = [f"PID {pid}: {name} ({mem:.0f} МБ)" for pid, name, mem in rows[:20]]
    if len(rows) > 20:
        lines.append(f"…и ещё {len(rows) - 20}")
    return "\n".join(lines)


def check_port(port: int) -> str:
    try:
        import psutil
    except ImportError:
        return "Не установлен пакет psutil."
    try:
        port = int(port)
    except (TypeError, ValueError):
        return "Порт должен быть числом."
    if not (0 < port < 65536):
        return "Это не похоже на настоящий номер порта (1–65535)."
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        return ("Не хватает прав посмотреть список сетевых подключений — на Windows попробуй "
                "запустить Акиру от имени администратора.")
    hits = [c for c in conns if c.laddr and c.laddr.port == port]
    if not hits:
        return f"Порт {port} свободен — никто его не слушает."
    pid = next((c.pid for c in hits if c.pid), None)
    if pid is None:
        return f"Порт {port} занят, но не вижу, каким процессом (нужны права администратора)."
    try:
        name = psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return f"Порт {port} занят процессом PID {pid}."
    return f"Порт {port} занят процессом «{name}» (PID {pid})."


# ------------------------------------------------------------------- логи
def read_log(path: str = "", lines: int = 50) -> str:
    """path пустой -> собственный лог Акиры (logs/akira.log)."""
    target = Path(path).expanduser() if (path or "").strip() else (config.LOGS_DIR / "akira.log")
    if not target.is_file():
        return f"Файл «{target}» не найден."
    lines = max(1, min(int(lines), 300))
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Не удалось прочитать файл: {e}"
    tail = text.splitlines()[-lines:]
    return "\n".join(tail) if tail else "Файл пустой."
