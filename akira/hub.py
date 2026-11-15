"""Центр уведомлений: навыки и события сообщают пользователю через голос, аватар и телефон."""
from .avatar_server import NullBus


class Hub:
    def __init__(self):
        self.speaker = None
        self.avatar = NullBus()
        self.phone = None

    def notify(self, text: str):
        print(f"\n  [уведомление] {text}")
        self.avatar.emit("notice", text=text)
        if self.phone:
            self.phone.push({"type": "notice", "text": text})
        if self.speaker:
            self.speaker.say(text)
