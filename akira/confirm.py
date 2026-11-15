"""Подтверждение важных действий: голосом, кнопкой на аватаре или в консоли."""
import re
import time

YES = {"да", "подтверждаю", "давай", "ок", "окей", "конечно", "выполняй", "разрешаю", "yes", "yeah", "ok", "okay"}
NO = {"нет", "не", "отмена", "отмени", "стоп", "запрещаю", "no", "cancel", "stop"}


def parse_yes_no(text: str):
    """True / False / None (непонятно). Отказ проверяется первым - так безопаснее."""
    words = set(re.findall(r"[\w-]+", text.lower()))
    if words & NO:
        return False
    if words & YES:
        return True
    return None


class CLIConfirmer:
    def ask(self, text: str) -> bool:
        print(f"\n  ⚠ Подтверждение: {text}")
        try:
            return input("  Разрешить? [y/N] ").strip().lower() in ("y", "yes", "д", "да")
        except (EOFError, KeyboardInterrupt):
            return False


class VoiceConfirmer:
    """Спрашивает голосом, ответ принимает голосом ИЛИ кнопкой на странице аватара."""

    def __init__(self, speaker, listen, bus, timeout=15.0):
        self.speaker, self.listen, self.bus, self.timeout = speaker, listen, bus, timeout

    def ask(self, text: str) -> bool:
        cid = self.bus.new_confirm(text)
        print(f"\n  ⚠ Подтверждение: {text}")
        self.bus.emit("state", state="listening")
        self.speaker.say(f"{text} Скажите «да» или «нет».")
        self.speaker.wait()
        result, deadline = None, time.time() + self.timeout
        while result is None and time.time() < deadline:
            result = self.bus.get_confirm(cid)
            if result is not None:
                break
            heard = self.listen(0.3)
            if heard:
                print(f"  (ответ: {heard})")
                result = parse_yes_no(heard)
                if result is None:
                    self.speaker.say("Скажите «да» или «нет».")
                    self.speaker.wait()
                    deadline = time.time() + self.timeout
        self.bus.emit("confirm_done", id=cid)
        if result is None:
            self.speaker.say("Ответа нет, отменяю.")
            self.speaker.wait()
        self.bus.emit("state", state="working")
        return bool(result)
