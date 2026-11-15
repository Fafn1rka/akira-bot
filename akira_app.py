"""Акира - единая точка входа.   python akira_app.py [--text] [--no-avatar] [--no-phone] [--doctor]"""
import argparse
import sys

from akira.config import BASE_DIR, load_config, version


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Акира")
    ap.add_argument("--text", action="store_true", help="текстовый режим вместо голоса")
    ap.add_argument("--no-avatar", action="store_true")
    ap.add_argument("--no-phone", action="store_true")
    ap.add_argument("--doctor", action="store_true", help="только проверить готовность и выйти")
    args = ap.parse_args()
    cfg = load_config()
    print(f"=== Акира {version()} ===")
    if args.doctor:
        import manage
        return manage.cmd_doctor(cfg, args)

    from akira.app import Services, run_text, run_voice
    sv = Services(cfg, args)
    if args.text:
        run_text(sv)
    else:
        try:
            run_voice(sv)
        except ImportError as e:
            print(f"\n[!] Голосовой ввод недоступен ({e}). Переключаюсь в текстовый режим...")
            print("[i] Для работы микрофона можно установить: pip install faster-whisper\n")
            run_text(sv)
    print("До встречи.")


if __name__ == "__main__":
    main()
