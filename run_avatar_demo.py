"""Проверка аватара без микрофона и моделей: перебирает состояния и эмоции."""
import random
import sys
import time

from akira.avatar_server import AvatarServer
from akira.config import BASE_DIR, load_config


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    if "--no-browser" in sys.argv:
        cfg["avatar"]["open_browser"] = False
    srv = AvatarServer(cfg, BASE_DIR)
    if not srv.start():
        return
    print("Демо запущено. Ctrl+C - выход.")
    phrases = {
        "neutral": "Привет! Я Акира, твой ассистент.",
        "happy": "Отлично, у нас всё получилось!",
        "sad": "К сожалению, не получилось найти файл.",
        "surprised": "Ого, это неожиданно!",
        "angry": "Это недопустимая ошибка.",
        "thinking": "Хм, дай подумать над этим.",
    }
    time.sleep(2)
    try:
        while True:
            for emo, text in phrases.items():
                srv.emit("user", text=f"(демо: {emo})")
                srv.emit("state", state="listening"); time.sleep(1.2)
                srv.emit("state", state="thinking"); srv.emit("emotion", emotion="thinking"); time.sleep(1.2)
                srv.emit("reply_start"); srv.emit("emotion", emotion=emo); srv.emit("state", state="speaking")
                for w in text.split():
                    srv.emit("token", text=w + " ")
                    srv.emit("word", len=len(w))
                    time.sleep(0.12 + 0.04 * len(w))
                srv.emit("state", state="idle")
                time.sleep(2.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
