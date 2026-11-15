import sys

from akira.brain import Brain
from akira.config import BASE_DIR, load_config


def beep():
    try:
        import winsound
        winsound.Beep(880, 120)
    except Exception:
        pass


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--devices" in sys.argv:
        from akira.audio import list_devices
        list_devices()
        return

    from akira.audio import Mic
    from akira.stt import STT
    from akira.confirm import VoiceConfirmer
    from akira.avatar_server import AvatarServer, NullBus, attach_speaker
    from akira.tts import Speaker
    from akira.voice_loop import VoiceSession

    cfg = load_config()
    v = cfg["voice"]
    brain = Brain(cfg, BASE_DIR / "data" / "akira.db", BASE_DIR)
    speaker = Speaker(v["tts_rate"], v["tts_voice_hint"], v["tts_enabled"])

    avatar, emotions = NullBus(), False
    if cfg["avatar"]["enabled"]:
        srv = AvatarServer(cfg, BASE_DIR)
        if srv.start():
            avatar, emotions = srv, True
            attach_speaker(speaker, avatar)
    stt = STT(v["stt_model"], v["language"], prompt=v["wake_prompt"])

    print(f"Загружаю модель распознавания ({v['stt_model']})... первый раз скачается из интернета.")
    stt.load()

    dev = v["mic_device"]
    dev = int(dev) if str(dev).isdigit() else None
    mic = Mic(speaker.busy, device=dev)

    def listen(timeout):
        audio = mic.next_utterance(timeout)
        return stt.transcribe(audio) if audio is not None else None

    confirmer = VoiceConfirmer(speaker, listen, avatar, cfg["tools"]["confirm_timeout"])
    session = VoiceSession(brain, speaker, v["wake_window_sec"], beep, v["debug"], avatar, emotions, confirmer)

    print("Готова. Скажите: «Акира, привет». Для выхода: «Акира, выключись» или Ctrl+C.")
    print("(Первую секунду микрофон калибруется по шуму - помолчите.)")
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


if __name__ == "__main__":
    main()
