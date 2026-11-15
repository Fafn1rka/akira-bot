"""Управление Акирой: диагностика, безопасность, навыки, телефон, обновления, модели, автозапуск."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from akira.config import BASE_DIR, load_config, version

ICON = {"ok": "[ok] ", "warn": "[!]  ", "fail": "[X]  ", "high": "[!!] ", "info": "[i]  "}


def cmd_doctor(cfg, a):
    from akira.doctor import run_checks
    for st, name, hint in run_checks(cfg, BASE_DIR):
        print(f"{ICON[st]}{name}" + (f"  ->  {hint}" if hint else ""))


def _skills(cfg):
    from akira.skills import SkillManager
    from akira.tools import Toolbox
    return SkillManager(BASE_DIR, Toolbox(cfg, BASE_DIR), None, cfg)


def cmd_audit(cfg, a):
    from akira.security import audit
    for lvl, text in audit(cfg, BASE_DIR, _skills(cfg)):
        print(f"{ICON[lvl]}{text}")


def cmd_skills(cfg, a):
    sm = _skills(cfg)
    if a.action == "list":
        state = dict(sm.status())
        for n in sm.available():
            print(f"{n:15} {'ВКЛЮЧЁН' if state.get(n) == 'ok' else state.get(n, 'выключен')}")
    elif a.action == "enable":
        files = sorted((sm.dir / a.name).rglob("*.py"))
        print(f"Навык {a.name} - это Python-код с полными правами вашего пользователя. Файлы:")
        for f in files:
            print(f"  {f.relative_to(sm.dir)}  ({f.stat().st_size} байт)")
        if not a.yes and input("Вы прочитали код и доверяете ему? [y/N] ").strip().lower() not in ("y", "yes", "д", "да"):
            return print("Отменено.")
        sm.enable(a.name)
        print("Включён. SHA-256 кода сохранён; при любом изменении файлов навык перестанет загружаться.")
    elif a.action == "disable":
        sm.disable(a.name)
        print("Выключен.")


def cmd_phone(cfg, a):
    from akira.phone import PhoneServer, lan_ip, load_token
    if a.action == "reset":
        load_token(BASE_DIR, reset=True)
        print("Токен пересоздан: старые телефоны потеряли доступ.")
    tok = load_token(BASE_DIR)
    host = lan_ip() if cfg["phone"]["bind"] == "0.0.0.0" else cfg["phone"]["bind"]
    url = f"http://{host}:{cfg['phone']['port']}/phone#t={tok}"
    print(f"Откройте на телефоне (та же Wi-Fi сеть): {url}")
    try:
        import qrcode
        q = qrcode.QRCode()
        q.add_data(url)
        q.print_ascii(invert=True)
    except ImportError:
        print("(для QR-кода: pip install qrcode)")
    if not cfg["phone"]["enabled"]:
        print("Телефон выключен: добавьте в config.toml  [phone] enabled = true")


def cmd_update(cfg, a):
    from akira import updater
    u = cfg["update"]
    if not u["url"]:
        return print("Адрес обновлений не задан (config.toml -> [update] url).")
    cur = version()
    if a.rollback:
        return print(updater.rollback(BASE_DIR))
    m = updater.check(u["url"], cur, u["allow_insecure"])
    if not m:
        return print(f"У вас последняя версия ({cur}).")
    print(f"Доступна версия {m['version']} (у вас {cur}). {m.get('notes', '')}")
    if a.apply:
        print(updater.apply(BASE_DIR, m, cur, u["allow_insecure"]))
        print("Перезапустите Акиру. Встроенные навыки могли измениться - включите их заново: manage.py skills enable <имя>")
    else:
        print("Установить: python manage.py update --apply")


def cmd_models(cfg, a):
    loc = cfg["local"]
    for m in dict.fromkeys([loc["main_model"], loc["fast_model"], loc["embed_model"]]):
        print(f"ollama pull {m}")
        subprocess.run(["ollama", "pull", m])


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("Автозапуск поддерживается только в Windows.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def cmd_autostart(cfg, a):
    f = startup_dir() / "Akira.bat"
    if a.action == "on":
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f'@echo off\r\ncd /d "{BASE_DIR}"\r\nstart "Akira" /min python akira_app.py\r\n', encoding="utf-8")
        print(f"Автозапуск включён: {f}")
    elif a.action == "off":
        f.unlink(missing_ok=True)
        print("Автозапуск выключен.")
    else:
        print("включён" if f.exists() else "выключен")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="manage.py", description=f"Акира {version()} - управление")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="проверка готовности").set_defaults(fn=cmd_doctor)
    sub.add_parser("audit", help="проверка настроек безопасности").set_defaults(fn=cmd_audit)
    p = sub.add_parser("skills", help="навыки")
    p.add_argument("action", choices=["list", "enable", "disable"])
    p.add_argument("name", nargs="?")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_skills)
    p = sub.add_parser("phone", help="доступ с телефона")
    p.add_argument("action", nargs="?", default="url", choices=["url", "reset"])
    p.set_defaults(fn=cmd_phone)
    p = sub.add_parser("update", help="обновления")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--rollback", action="store_true")
    p.set_defaults(fn=cmd_update)
    sub.add_parser("models", help="скачать нужные модели Ollama").set_defaults(fn=cmd_models)
    p = sub.add_parser("autostart", help="автозапуск с Windows")
    p.add_argument("action", nargs="?", default="status", choices=["on", "off", "status"])
    p.set_defaults(fn=cmd_autostart)
    a = ap.parse_args(argv)
    if a.cmd == "skills" and a.action in ("enable", "disable") and not a.name:
        ap.error("укажите имя навыка")
    a.fn(load_config(), a)


if __name__ == "__main__":
    main()
