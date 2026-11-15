"""Единый запуск: мозг + память + голос + аватар + телефон + навыки + проверки."""
import threading

from . import updater
from .avatar_server import AvatarServer, NullBus, attach_speaker
from .brain import Brain
from .config import BASE_DIR, load_config, version
from .confirm import CLIConfirmer, VoiceConfirmer
from .emotion import EmotionFilter
from .hub import Hub
from .llm import LLMError
from .phone import PhoneServer
from .security import audit
from .skills import SkillManager

HELP = """Команды:
  /cloud <текст>   /local <текст>   /do <текст>   - принудительный режим
  /remember <факт>  /facts  /forget <id>           - память
  /status  /audit  /exit"""


class Services:
    """Всё, что запущено: общий доступ для голосового и текстового режимов."""

    def __init__(self, cfg, args):
        self.cfg = cfg
        self.hub = Hub()
        self.brain = Brain(cfg, BASE_DIR / "data" / "akira.db", BASE_DIR)
        self.avatar = NullBus()
        self.speaker = None
        self.phone = None
        self.skills = None
        self._start(args)

    def _start(self, args):
        cfg, v = self.cfg, self.cfg["voice"]
        if v["tts_enabled"] and not args.text:
            from .tts import Speaker
            self.speaker = Speaker(v["tts_rate"], v["tts_voice_hint"], True)
        if cfg["avatar"]["enabled"] and not args.no_avatar:
            srv = AvatarServer(cfg, BASE_DIR, self.brain)
            if srv.start():
                self.avatar = srv
                if self.speaker:
                    attach_speaker(self.speaker, srv)
        self.hub.avatar, self.hub.speaker = self.avatar, self.speaker

        if self.brain.toolbox:
            self.skills = SkillManager(BASE_DIR, self.brain.toolbox, self.hub, cfg)
            loaded = self.skills.load_all()
            print(f"  Навыки: {', '.join(loaded) if loaded else 'нет включённых (manage.py skills list)'}")
            print(f"  Инструменты: {len(self.brain.toolbox.tools)}")

        if cfg["phone"]["enabled"] and not args.no_phone:
            ps = PhoneServer(cfg, self.brain, BASE_DIR)
            if ps.start():
                self.phone, self.hub.phone = ps, ps
                mode = "с управлением ПК" if ps.allow_actions else "только интернет и навыки"
                print(f"  Телефон ({mode}): {ps.url()}")

        for lvl, text in audit(cfg, BASE_DIR, self.skills):
            if lvl == "high":
                print(f"  [!!] {text}")
        if cfg["update"]["url"] and cfg["update"]["check_on_start"]:
            threading.Thread(target=self._check_update, daemon=True).start()

    def _check_update(self):
        try:
            u = self.cfg["update"]
            m = updater.check(u["url"], version(), u["allow_insecure"])
            if m:
                self.hub.notify(f"Доступна новая версия {m['version']}. Установка: manage.py update --apply")
        except updater.UpdateError as e:
            print(f"  [обновления] {e}")


def run_text(sv: Services):
    brain, confirmer = sv.brain, CLIConfirmer()
    print(HELP)
    while True:
        try:
            text = input("\nВы: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not text:
            continue
        force, act = None, None
        if text.startswith("/"):
            cmd, _, arg = text.partition(" ")
            arg = arg.strip()
            if cmd == "/exit":
                return
            if cmd == "/help":
                print(HELP)
            elif cmd == "/status":
                print(f"  Ollama: {'работает' if brain.local.is_up() else 'НЕ запущена'}; "
                      f"интернет: {'есть' if brain.router.online() else 'нет'}; "
                      f"облако: {'ключ найден' if brain.cloud.has_key else 'нет ключа'}")
            elif cmd == "/audit":
                for lvl, t in audit(sv.cfg, BASE_DIR, sv.skills):
                    print(f"  [{lvl}] {t}")
            elif cmd == "/facts":
                print("\n".join(f"  {i}: {t}" for i, t in brain.memory.list_facts()) or "  Память пуста.")
            elif cmd == "/remember" and arg:
                print(f"  Запомнила (#{brain.memory.add_fact(arg)}).")
            elif cmd == "/forget" and arg.isdigit():
                print("  Забыла." if brain.memory.delete_fact(int(arg)) else "  Нет такого факта.")
            elif cmd in ("/cloud", "/local") and arg:
                force, text = cmd[1:], arg
            elif cmd == "/do" and arg:
                act, text = True, arg
            else:
                print("  Неизвестная команда. /help")
            if text.startswith("/"):
                continue
        print("Акира: ", end="", flush=True)
        flt = EmotionFilter()
        try:
            _, label = brain.reply(
                text, force=force, act=act, confirmer=confirmer, emotions=True,
                on_event=lambda k, **d: print(f"\n  [инструмент] {d['name']} {d.get('args', '')}") if k == "tool" else None,
                on_token=lambda t: print(flt.feed(t), end="", flush=True))
            print(flt.flush(), end="")
            print(f"\n  [{label}]")
        except LLMError as e:
            print(f"\n  Ошибка: {e}\n  Запустите `python manage.py doctor`.")


def run_voice(sv: Services):
    from .audio import Mic
    from .stt import STT
    from .voice_loop import VoiceSession
    cfg, v = sv.cfg, sv.cfg["voice"]
    stt = STT(v["stt_model"], v["language"], prompt=v["wake_prompt"])
    print(f"Загружаю модель распознавания ({v['stt_model']})...")
    stt.load()
    dev = v["mic_device"]
    mic = Mic(sv.speaker.busy if sv.speaker else (lambda: False), device=int(dev) if str(dev).isdigit() else None)

    def listen(timeout):
        audio = mic.next_utterance(timeout)
        return stt.transcribe(audio) if audio is not None else None

    def beep():
        try:
            import winsound
            winsound.Beep(880, 120)
        except Exception:  # noqa: BLE001
            pass

    confirmer = VoiceConfirmer(sv.speaker, listen, sv.avatar, cfg["tools"]["confirm_timeout"])
    session = VoiceSession(sv.brain, sv.speaker, v["wake_window_sec"], beep, v["debug"], sv.avatar, True, confirmer)
    print("Готова. Скажите: «Акира, привет». Выход: «Акира, выключись» или Ctrl+C.")
    try:
        mic.start()
        while True:
            audio = mic.next_utterance()
            text = stt.transcribe(audio) if audio is not None else ""
            if text and not session.handle_text(text):
                break
    except KeyboardInterrupt:
        pass
    finally:
        mic.stop()
