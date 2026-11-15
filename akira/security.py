"""Общие средства защиты: проверка Host/Origin, токены, ограничение подбора, аудит настроек."""
import hmac
import os
import time
from pathlib import Path


class RateLimiter:
    """Блокирует IP после нескольких неудачных попыток авторизации."""

    def __init__(self, max_fail=5, window=60, lock=300):
        self.max_fail, self.window, self.lock = max_fail, window, lock
        self.fails: dict[str, list[float]] = {}
        self.locked: dict[str, float] = {}

    def blocked(self, ip: str) -> bool:
        return self.locked.get(ip, 0) > time.time()

    def fail(self, ip: str):
        now = time.time()
        lst = [t for t in self.fails.get(ip, []) if now - t < self.window] + [now]
        self.fails[ip] = lst
        if len(lst) >= self.max_fail:
            self.locked[ip] = now + self.lock
            self.fails[ip] = []

    def ok(self, ip: str):
        self.fails.pop(ip, None)


def token_ok(supplied: str, expected: str) -> bool:
    return bool(supplied) and hmac.compare_digest(supplied.encode("utf-8", "ignore"), expected.encode("utf-8"))


def local_request_ok(headers, port: int) -> bool:
    """Защита от DNS rebinding и чужих сайтов: Host и Origin должны быть нашими."""
    allowed = {f"localhost:{port}", f"127.0.0.1:{port}"}
    if headers.get("Host", "").lower() not in allowed:
        return False
    origin = headers.get("Origin")
    return not origin or origin.lower() in {f"http://{h}" for h in allowed}


def audit(cfg: dict, base_dir: Path, skills=None) -> list[tuple[str, str]]:
    """Проверка настроек безопасности. Уровни: high / warn / info / ok."""
    out: list[tuple[str, str]] = []
    t = cfg["tools"]
    if t.get("allow_shell"):
        out.append(("high", "Включён терминал (allow_shell): модель сможет запускать команды. Список запретов - лишь страховка."))
    if t.get("allow_input_control"):
        out.append(("warn", "Включён ввод с клавиатуры (allow_input_control): каждое действие требует подтверждения, но риск выше."))
    home = Path.home().resolve()
    risky = []
    for d in t["allowed_dirs"]:
        p = Path(os.path.expanduser(d)).resolve()
        low = str(p).lower()
        if (p == home or p == Path(p.anchor) or low.startswith(("c:\\windows", "c:\\program files", "/etc", "/usr", "/bin"))
                or p in (Path("/"),)):
            risky.append(str(p))
    if risky:
        out.append(("high", f"Слишком широкие разрешённые папки: {', '.join(risky)}. Оставьте только нужные."))
    else:
        out.append(("ok", f"Разрешённые папки ({len(t['allowed_dirs'])}) выглядят безопасно."))
    ph = cfg.get("phone", {})
    if ph.get("enabled"):
        if ph.get("allow_actions"):
            out.append(("high", "Телефон может управлять ПК (phone.allow_actions). При утечке токена это доступ к вашим файлам."))
        else:
            out.append(("ok", "Телефон: только интернет и навыки (allow_actions выключен)."))
        if ph.get("bind") == "0.0.0.0":
            out.append(("info", "Сервер телефона виден в вашей Wi-Fi сети. Защищён токеном; в чужих/публичных сетях выключайте."))
        tok = base_dir / "data" / "phone_token"
        if tok.exists() and os.name != "nt" and (tok.stat().st_mode & 0o077):
            out.append(("warn", "Файл токена телефона доступен другим пользователям ПК (права файла)."))
    if cfg["cloud"]["enabled"] and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        out.append(("info", "Облако активно: сложные запросы (и вспомнившиеся факты о вас) отправляются облачной модели."))
    u = cfg.get("update", {})
    if u.get("url"):
        if not u["url"].startswith("https://") or u.get("allow_insecure"):
            out.append(("high", "Обновления идут не по https - подмена возможна."))
        else:
            out.append(("ok", "Обновления по https с проверкой SHA-256 (автоустановки нет)."))
    if skills is not None:
        for name, status in skills.status():
            lvl = "ok" if status == "ok" else "high"
            out.append((lvl, f"Навык {name}: {'код не менялся с момента утверждения' if status == 'ok' else status}"))
    log = base_dir / "data" / "actions.log"
    if log.exists() and log.stat().st_size > cfg.get("security", {}).get("log_max_kb", 1024) * 1024 * 4:
        out.append(("warn", "Журнал действий очень большой."))
    return out
