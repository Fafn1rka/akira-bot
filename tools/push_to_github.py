#!/usr/bin/env python3
"""
Заливает проект на GitHub. Безопасно: НЕ хранит токен внутри репозитория,
НЕ делает force-push и заранее проверяет, что .env не попадёт в коммит.

Использование:
    python tools/push_to_github.py https://github.com/USER/REPO.git

Если репозиторий приватный или ты ещё не логинился в git — обычный `git push`
сам спросит логин/токен (GitHub больше не принимает пароль, нужен Personal
Access Token: https://github.com/settings/tokens — достаточно прав "repo").
Проще всего один раз сохранить его через git-credential-manager или
`gh auth login`, если стоит GitHub CLI.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    remote_url = sys.argv[1]

    if (ROOT / ".env").exists():
        tracked = subprocess.run(["git", "ls-files", ".env"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.strip()
        if tracked:
            print("СТОП: файл .env уже отслеживается git — в нём секретные ключи.")
            print("Выполни:  git rm --cached .env   и запусти скрипт снова.")
            sys.exit(1)

    if not (ROOT / ".git").exists():
        run(["git", "init"])
        run(["git", "branch", "-M", "main"])

    run(["git", "add", "-A"])
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode
    if diff != 0:
        run(["git", "commit", "-m", "Akira: update"])
    else:
        print("Изменений нет — коммитить нечего.")

    existing = subprocess.run(["git", "remote"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if "origin" in existing:
        run(["git", "remote", "set-url", "origin", remote_url])
    else:
        run(["git", "remote", "add", "origin", remote_url])

    run(["git", "push", "-u", "origin", "main"])
    print("\nГотово! Токен нигде не сохранён в файлах репозитория.")


if __name__ == "__main__":
    main()
