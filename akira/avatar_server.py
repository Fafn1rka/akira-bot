"""Локальный сервер аватара: страница + поток событий (SSE) без внешних зависимостей."""
import json
import queue
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .emotion import EmotionFilter
from .security import local_request_ok, token_ok


class NullBus:
    def emit(self, type_, **data):
        pass

    def new_confirm(self, text):
        return None

    def get_confirm(self, cid):
        return None


class AvatarServer:
    def __init__(self, cfg: dict, base_dir: Path, brain=None):
        a = cfg["avatar"]
        self.port, self.open_browser = a["port"], a["open_browser"]
        self.web = base_dir / "web"
        self.model = base_dir / a["model"]
        self.three_v, self.vrm_v = a["three_version"], a["vrm_version"]
        self.clients: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.snapshot = {"state": "idle", "emotion": "neutral"}
        self.httpd = None
        self.confirms: dict[str, bool | None] = {}
        self._cid = 0
        self.token = secrets.token_urlsafe(24)   # секрет сессии: без него «да» принять нельзя
        self.brain = brain

    # --- подтверждения (кнопки на странице) ---
    def new_confirm(self, text):
        self._cid += 1
        cid = str(self._cid)
        self.confirms[cid] = None
        self.emit("confirm", id=cid, text=text)
        return cid

    def get_confirm(self, cid):
        return self.confirms.get(cid)

    # --- события ---
    def emit(self, type_, **data):
        evt = {"type": type_, **data}
        if type_ in ("state", "emotion"):
            self.snapshot[type_] = data.get(type_)
        with self.lock:
            for q in self.clients:
                q.put(evt)

    # --- страница ---
    def importmap(self) -> str:
        v = self.web / "vendor"
        local = all((v / p).exists() for p in (
            "three/build/three.module.js",
            "three/examples/jsm/loaders/GLTFLoader.js",
            "three/examples/jsm/utils/BufferGeometryUtils.js",
            "three-vrm/three-vrm.module.js"))
        if local:
            t, addons, vrm = "/web/vendor/three/build/three.module.js", "/web/vendor/three/examples/jsm/", "/web/vendor/three-vrm/three-vrm.module.js"
        else:
            base = f"https://cdn.jsdelivr.net/npm/three@{self.three_v}"
            t, addons = f"{base}/build/three.module.js", f"{base}/examples/jsm/"
            vrm = f"https://cdn.jsdelivr.net/npm/@pixiv/three-vrm@{self.vrm_v}/lib/three-vrm.module.js"
        return json.dumps({"imports": {"three": t, "three/addons/": addons,
                                       "three/examples/jsm/": addons, "@pixiv/three-vrm": vrm}})

    def start(self) -> bool:
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body: bytes, ctype="text/plain; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not local_request_ok(self.headers, srv.port):
                    return self._send(403, b"forbidden")
                path = self.path.split("?")[0]
                if path in ("/", "/index.html"):
                    html = (srv.web / "index.html").read_text(encoding="utf-8")
                    return self._send(200, html.replace("{{IMPORTMAP}}", srv.importmap()).replace("{{TOKEN}}", srv.token).encode("utf-8"),
                                      "text/html; charset=utf-8")
                if path == "/has_model":
                    return self._send(200, json.dumps({"vrm": srv.model.exists()}).encode(), "application/json")
                if path == "/model.vrm":
                    if srv.model.exists():
                        return self._send(200, srv.model.read_bytes(), "application/octet-stream")
                    return self._send(404, b"no model")
                if path == "/events":
                    return self._events()
                if path.startswith("/web/"):
                    f = (srv.web / path[5:]).resolve()
                    if f.is_file() and f.is_relative_to(srv.web.resolve()):
                        ctype = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}.get(f.suffix, "application/octet-stream")
                        return self._send(200, f.read_bytes(), ctype + "; charset=utf-8" if ctype.startswith("text") else ctype)
                self._send(404, b"not found")

            def do_POST(self):
                if not local_request_ok(self.headers, srv.port):
                    return self._send(403, b"forbidden")
                if not token_ok(self.headers.get("X-Akira-Token", ""), srv.token):
                    return self._send(403, b"forbidden")
                path = self.path.split("?")[0]
                if path == "/confirm":
                    try:
                        n = min(int(self.headers.get("Content-Length", 0)), 1024)
                        data = json.loads(self.rfile.read(n) or b"{}")
                        cid = str(data.get("id"))
                        if cid in srv.confirms and srv.confirms[cid] is None:
                            srv.confirms[cid] = bool(data.get("approved"))
                        return self._send(200, b"ok")
                    except (ValueError, OSError):
                        return self._send(400, b"bad request")
                if path == "/chat":
                    if not srv.brain:
                        return self._send(503, json.dumps({"error": "Brain не подключен"}).encode(), "application/json")
                    try:
                        n = min(int(self.headers.get("Content-Length", 0)), 8192)
                        data = json.loads(self.rfile.read(n) or b"{}")
                        text = str(data.get("text", "")).strip()
                        if not text:
                            return self._send(400, b"empty text")

                        def _process(t=text):
                            srv.emit("user", text=t)
                            srv.emit("state", state="thinking")
                            srv.emit("reply_start")
                            try:
                                flt = EmotionFilter(on_emotion=lambda e: srv.emit("emotion", emotion=e))
                                def _on_tok(tok):
                                    cleaned = flt.feed(tok)
                                    if cleaned:
                                        srv.emit("token", text=cleaned)
                                        srv.emit("word", len=len(cleaned))
                                srv.emit("state", state="speaking")
                                ans, label = srv.brain.reply(
                                    t,
                                    emotions=True,
                                    on_event=lambda k, **d: srv.emit("tool", name=d.get("name", "")) if k == "tool" else None,
                                    on_token=_on_tok,
                                )
                                rest = flt.flush()
                                if rest:
                                    srv.emit("token", text=rest)
                                srv.emit("state", state="idle")
                            except Exception as ex:
                                srv.emit("state", state="idle")
                                srv.emit("token", text=f" [Ошибка: {ex}]")

                        threading.Thread(target=_process, daemon=True).start()
                        return self._send(200, json.dumps({"ok": True}).encode(), "application/json")
                    except Exception as e:
                        return self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
                self._send(404, b"not found")

            def _events(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                q: queue.Queue = queue.Queue()
                q.put({"type": "state", "state": srv.snapshot["state"]})
                q.put({"type": "emotion", "emotion": srv.snapshot["emotion"]})
                with srv.lock:
                    srv.clients.append(q)
                try:
                    while True:
                        try:
                            evt = q.get(timeout=15)
                            self.wfile.write(f"data: {json.dumps(evt, ensure_ascii=False)}\n\n".encode("utf-8"))
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with srv.lock:
                        if q in srv.clients:
                            srv.clients.remove(q)

        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError as e:
            print(f"  [!] Аватар не запущен (порт {self.port} занят?): {e}")
            return False
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        url = f"http://localhost:{self.port}"
        print(f"  Аватар: {url}  ({'VRM-модель' if self.model.exists() else 'встроенный персонаж'})")
        if self.open_browser:
            webbrowser.open(url)
        return True


def attach_speaker(speaker, bus):
    """Связывает озвучку с аватаром: состояние «говорит» и движение рта по словам."""
    speaker.on_start = lambda: bus.emit("state", state="speaking")
    speaker.on_end = lambda: bus.emit("state", state="idle")
    speaker.on_word = lambda n: bus.emit("word", len=n)
