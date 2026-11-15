"""Навык «таймер»: «Акира, поставь таймер на 10 минут»."""
import threading
import time

MAX_ACTIVE, MAX_SECONDS = 10, 24 * 3600


def register(api):
    timers = {}
    api.keywords("таймер", "напомни")

    @api.tool("set", "Set a countdown timer; Akira will announce when it finishes.",
              {"seconds": {"type": "integer", "description": "Duration in seconds"},
               "label": {"type": "string", "description": "What the timer is for"}},
              required=["seconds"], risk="safe",
              describe=lambda a: f"Таймер на {a.get('seconds')} с")
    def set_timer(seconds, label="таймер"):
        seconds = int(seconds)
        if not 1 <= seconds <= MAX_SECONDS:
            return "Ошибка: длительность от 1 секунды до 24 часов."
        now = time.time()
        for k in [k for k, (t, _) in timers.items() if t < now]:
            timers.pop(k)
        if len(timers) >= MAX_ACTIVE:
            return "Ошибка: слишком много активных таймеров."
        tid = max(timers, default=0) + 1
        timers[tid] = (now + seconds, label)
        th = threading.Timer(seconds, lambda: (timers.pop(tid, None), api.notify(f"Время вышло: {label}.")))
        th.daemon = True
        th.start()
        return f"Таймер «{label}» запущен на {seconds} с."

    @api.tool("list", "List active timers.", risk="safe", describe=lambda a: "Показать таймеры")
    def list_timers():
        now = time.time()
        rows = [f"{lbl}: осталось {int(t - now)} с" for t, lbl in timers.values() if t > now]
        return "\n".join(rows) or "Активных таймеров нет."
