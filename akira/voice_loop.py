"""Логика голосового диалога: слово активации, окно разговора, стоп-команды, аватар."""
import time

from .avatar_server import NullBus
from .emotion import EmotionFilter, guess_emotion
from .llm import LLMError
from .wake import find_wake, is_exit, is_stop


class VoiceSession:
    def __init__(self, brain, speaker, window=20.0, beep=None, debug=False, avatar=None, emotions=False,
                 confirmer=None):
        self.brain, self.speaker, self.window = brain, speaker, window
        self.beep = beep or (lambda: None)
        self.debug = debug
        self.avatar = avatar or NullBus()
        self.emotions = emotions
        self.confirmer = confirmer
        self.active_until = 0.0

    def _open_window(self):
        self.active_until = time.time() + self.window

    def handle_text(self, text: str) -> bool:
        """Обрабатывает распознанную фразу. False - пора завершать работу."""
        woke, rem = find_wake(text)
        active = time.time() < self.active_until
        if not woke and not active:
            if self.debug:
                print(f"  (слышу: {text})")
            return True

        command = rem if woke else text.strip()
        if woke and not command:
            self.avatar.emit("state", state="listening")
            self.beep()
            self.speaker.say("Слушаю.")
            self.speaker.wait()
            self.avatar.emit("state", state="listening")
            self._open_window()
            return True

        if is_exit(command):
            self.speaker.say("До встречи.")
            self.speaker.wait()
            return False
        if is_stop(command):
            self.speaker.say("Хорошо, я рядом.")
            self.speaker.wait()
            self.avatar.emit("state", state="idle")
            self.active_until = 0.0
            return True

        print(f"\nВы: {command}")
        print("Акира: ", end="", flush=True)
        self.avatar.emit("user", text=command)
        self.avatar.emit("state", state="thinking")
        self.avatar.emit("emotion", emotion="thinking")
        self.avatar.emit("reply_start")

        parts: list[str] = []
        flt = EmotionFilter(on_emotion=lambda e: self.avatar.emit("emotion", emotion=e))

        def out(t):
            if t:
                parts.append(t)
                print(t, end="", flush=True)
                self.avatar.emit("token", text=t)
                self.speaker.feed(t)

        def on_event(kind, **d):
            if kind == "tool":
                print(f"\n  [инструмент] {d['name']} {d.get('args', '')}")
                self.avatar.emit("state", state="working")
                self.avatar.emit("tool", name=d["name"])
            elif kind == "note":
                print(f"\n  [!] {d['text']}")

        try:
            _, label = self.brain.reply(command, on_token=lambda t: out(flt.feed(t)),
                                        voice=True, emotions=self.emotions,
                                        confirmer=self.confirmer, on_event=on_event)
            out(flt.flush())
            if flt.emotion is None:
                self.avatar.emit("emotion", emotion=guess_emotion("".join(parts)))
            self.speaker.flush()
            print(f"\n  [{label}]")
        except LLMError as e:
            print(f"\n  Ошибка: {e}")
            self.avatar.emit("emotion", emotion="sad")
            self.speaker.say("Не получилось ответить. Проверьте, запущена ли Ollama.")
        self.speaker.wait()
        self.avatar.emit("state", state="idle")
        self._open_window()
        return True
