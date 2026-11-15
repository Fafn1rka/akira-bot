"""Доступ с телефона: веб-страница /phone + API под токеном. По умолчанию - только интернет и навыки."""
import json
import os
import queue
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .llm import LLMError
from .security import RateLimiter, token_ok


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))     # пакеты не отправляются, нужен только выбор интерфейса
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def load_token(base_dir: Path, reset: bool = False) -> str:
    p = base_dir / "data" / "phone_token"
    p.parent.mkdir(parents=True, exist_ok=True)
    if reset or not p.exists():
        p.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    return p.read_text(encoding="utf-8").strip()


class PhoneConfirmer:
    """Подтверждение действий кнопкой на телефоне."""

    def __init__(self, server, timeout):
        self.server, self.timeout = server, timeout

    def ask(self, text: str) -> bool:
        cid = self.server.new_confirm(text)
        import time
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            r = self.server.confirms.get(cid)
            if r is not None:
                break
            time.sleep(0.2)
        r = self.server.confirms.pop(cid, None)
        self.server.push({"type": "confirm_done", "id": cid})
        return bool(r)


class PhoneServer:
    def __init__(self, cfg: dict, brain, base_dir: Path):
        p = cfg["phone"]
        self.cfg, self.brain, self.base = cfg, brain, base_dir
        self.bind, self.port = p["bind"], p["port"]
        self.allow_actions, self.confirm_timeout = p["allow_actions"], p["confirm_timeout"]
        self.token = load_token(base_dir)
        self.limiter = RateLimiter()
        self.clients: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.confirms: dict[str, bool | None] = {}
        self._cid = 0
        self.page = (base_dir / "web" / "phone.html").read_text(encoding="utf-8")
        self.httpd = None

    def url(self) -> str:
        host = lan_ip() if self.bind == "0.0.0.0" else self.bind
        return f"http://{host}:{self.port}/phone#t={self.token}"

    def push(self, evt: dict):
        with self.lock:
            for q in self.clients:
                q.put(evt)

    def new_confirm(self, text: str) -> str:
        with self.lock:
            self._cid += 1
            cid = str(self._cid)
            self.confirms[cid] = None
        self.push({"type": "confirm", "id": cid, "text": text})
        return cid

    def allowed_tools(self):
        if self.allow_actions or not self.brain.toolbox:
            return None
        return self.brain.toolbox.names_in_groups({"internet", "skill"})

    def start(self) -> bool:
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json; charset=utf-8"):
                if isinstance(body, (dict, list)):
                    body = json.dumps(body, ensure_ascii=False)
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _auth(self) -> bool:
                ip = self.client_address[0]
                if srv.limiter.blocked(ip):
                    self._send(429, {"error": "слишком много попыток, подождите"})
                    return False
                auth = self.headers.get("Authorization", "")
                if auth.startswith("Bearer ") and token_ok(auth[7:], srv.token):
                    srv.limiter.ok(ip)
                    return True
                srv.limiter.fail(ip)
                self._send(401, {"error": "нет доступа"})
                return False

            def do_GET(self):
                path = self.path.split("?")[0]
                if path in ("/", "/phone"):
                    return self._send(200, srv.page, "text/html; charset=utf-8")
                if not self._auth():
                    return
                if path == "/api/ping":
                    return self._send(200, {"ok": True, "actions": srv.allow_actions})
                if path == "/api/events":
                    return self._events()
                self._send(404, {"error": "not found"})

            def do_POST(self):
                path = self.path.split("?")[0]
                if not self._auth():
                    return
                try:
                    n = min(int(self.headers.get("Content-Length", 0)), 8192)
                    data = json.loads(self.rfile.read(n) or b"{}")
                except (ValueError, OSError):
                    return self._send(400, {"error": "bad request"})
                if path == "/api/confirm":
                    cid = str(data.get("id"))
                    if srv.confirms.get(cid, True) is None:
                        srv.confirms[cid] = bool(data.get("approved"))
                    return self._send(200, {"ok": True})
                if path == "/api/chat":
                    text = str(data.get("text", "")).strip()[:2000]
                    if not text:
                        return self._send(400, {"error": "пустой запрос"})
                    try:
                        answer, label = srv.brain.reply(
                            text, confirmer=PhoneConfirmer(srv, srv.confirm_timeout),
                            on_event=lambda k, **d: srv.push({"type": "tool", "name": d["name"]}) if k == "tool" else None,
                            allowed_tools=srv.allowed_tools())
                        return self._send(200, {"answer": answer, "label": label})
                    except LLMError as e:
                        return self._send(502, {"error": f"модель недоступна: {e}"})
                    except Exception:  # noqa: BLE001 - не показываем внутренности на телефоне
                        return self._send(500, {"error": "внутренняя ошибка, см. консоль ПК"})
                self._send(404, {"error": "not found"})

            def _events(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                q: queue.Queue = queue.Queue()
                with srv.lock:
                    srv.clients.append(q)
                try:
                    while True:
                        try:
                            self.wfile.write(f"data: {json.dumps(q.get(timeout=15), ensure_ascii=False)}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except OSError:
                    pass
                finally:
                    with srv.lock:
                        if q in srv.clients:
                            srv.clients.remove(q)

        try:
            self.httpd = ThreadingHTTPServer((self.bind, self.port), H)
        except OSError as e:
            print(f"  [!] Сервер телефона не запущен (порт {self.port} занят?): {e}")
            return False
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return True
