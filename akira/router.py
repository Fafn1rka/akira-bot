import socket
import time
from dataclasses import dataclass


@dataclass
class Route:
    kind: str    # "local_fast" | "local_main" | "cloud"
    reason: str


class Router:
    def __init__(self, cfg: dict, cloud_ready):
        self.r = cfg["router"]
        self.cloud_enabled = cfg["cloud"]["enabled"]
        self.cloud_ready = cloud_ready  # функция -> bool (есть ключ)
        self._net = (0.0, False)

    def online(self) -> bool:
        ts, val = self._net
        if time.time() - ts < 30:
            return val
        try:
            socket.create_connection(("1.1.1.1", 443), timeout=1.5).close()
            val = True
        except OSError:
            val = False
        self._net = (time.time(), val)
        return val

    def cloud_available(self) -> bool:
        return self.cloud_enabled and self.cloud_ready() and self.online()

    def decide(self, text: str, force: str | None = None) -> Route:
        if force == "local":
            return Route("local_main", "вручную")
        if force == "cloud":
            if self.cloud_available():
                return Route("cloud", "вручную")
            return Route("local_main", "облако недоступно")
        low = text.lower()
        wants_cloud = len(text) >= self.r["cloud_min_chars"] or any(k in low for k in self.r["cloud_keywords"])
        if wants_cloud:
            if self.cloud_available():
                return Route("cloud", "сложная задача")
            return Route("local_main", "облако недоступно")
        if len(text) <= self.r["fast_max_chars"]:
            return Route("local_fast", "короткий запрос")
        return Route("local_main", "обычный диалог")
