"""Синтез речи: голоса Windows (SAPI) через pyttsx3. Работает офлайн, 0 ГБ VRAM."""
import queue
import re
import threading
import time


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", " ссылка ", text)
    text = re.sub(r"[*_#>~|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)  # эмодзи
    return re.sub(r"\s+", " ", text).strip()


def pop_sentences(buf: str):
    """Отделяет законченные предложения от хвоста (для потоковой озвучки)."""
    out, start = [], 0
    for m in re.finditer(r'[.!?…]+["»)]*\s+|\n+', buf):
        s = buf[start:m.end()].strip()
        if s:
            out.append(s)
        start = m.end()
    return out, buf[start:]


class Speaker:
    def __init__(self, rate=190, voice_hint="", enabled=True, grace=0.6):
        self.rate, self.hint, self.enabled, self.grace = rate, voice_hint.lower(), enabled, grace
        self.q: queue.Queue = queue.Queue()
        self._buf = ""
        self._pending = 0
        self._lock = threading.Lock()
        self._last_end = 0.0
        self._talking = False
        self.on_start = self.on_end = self.on_word = None  # хуки для аватара
        if enabled:
            threading.Thread(target=self._run, daemon=True).start()

    # --- API ---
    def feed(self, token: str):
        self._buf += token
        sentences, self._buf = pop_sentences(self._buf)
        for s in sentences:
            self.say(s)

    def flush(self):
        rest, self._buf = self._buf, ""
        self.say(rest)

    def say(self, text: str):
        text = clean_for_speech(text)
        if not text or not self.enabled:
            return
        with self._lock:
            self._pending += 1
        self.q.put(text)

    def busy(self) -> bool:
        return self._pending > 0 or (time.time() - self._last_end) < self.grace

    def wait(self):
        while self._pending > 0:
            time.sleep(0.05)

    # --- поток озвучки ---
    def _pick_voice(self, engine):
        voices = engine.getProperty("voices")
        def txt(v):
            return f"{v.name} {v.id} {getattr(v, 'languages', '')}".lower()
        for v in voices:
            if self.hint and self.hint in txt(v):
                return v
        for v in voices:
            if "russian" in txt(v) or "ru-ru" in txt(v) or "ru_ru" in txt(v):
                return v
        return None

    def _run(self):
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            v = self._pick_voice(engine)
            try:
                engine.connect("started-word", lambda name, location, length: self.on_word and self.on_word(length))
            except Exception:
                pass
            if v:
                engine.setProperty("voice", v.id)
            else:
                print("  [!] Русский голос Windows не найден. Добавьте его: "
                      "Параметры - Время и язык - Речь - Добавить голоса.")
        except Exception as e:
            print(f"  [!] Озвучка отключена: {e}")
            self.enabled = False
            engine = None
        while True:
            text = self.q.get()
            try:
                if not self._talking and self.on_start:
                    self._talking = True
                    self.on_start()
                if engine:
                    engine.say(text)
                    engine.runAndWait()
            except Exception as e:
                print(f"  [!] Ошибка озвучки: {e}")
            finally:
                with self._lock:
                    self._pending -= 1
                    done = self._pending == 0
                self._last_end = time.time()
                if done and self._talking:
                    self._talking = False
                    if self.on_end:
                        self.on_end()
