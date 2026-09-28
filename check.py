#!/usr/bin/env python3
"""
Диагностика Акиры: почему она не слышит голос и почему не переключается на Ollama.

Запуск:  check.bat (Windows)  или  ./check.sh (Linux).
Ключи и токены НЕ печатаются — результат можно спокойно показывать.
Что проверяется: файл .env, микрофон (с живой записью и распознаванием), подключённые AI и Ollama.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

problems: list[str] = []

# Настройки, значения которых безопасно показывать (никаких ключей и токенов)
SAFE_KEYS = [
    "VOICE_INPUT_ENABLED", "VOICE_WAKE_WORD_REQUIRED", "VOICE_ENERGY_THRESHOLD", "VOICE_MIC_DEVICE",
    "STT_ENGINE", "WAKE_WORDS", "AI_PROVIDERS", "OLLAMA_MODELS", "OLLAMA_BASE_URL",
    "GEMINI_MODEL", "GEMINI_MODELS", "IDLE_CHAT_ENABLED", "MORNING_BRIEFING",
]


def head(text: str) -> None:
    print(f"\n=== {text} ===")


def ok(text: str) -> None:
    print(f"  [ OK ] {text}")


def info(text: str) -> None:
    print(f"  [ .. ] {text}")


def bad(text: str, fix: str = "") -> None:
    print(f"  [ !! ] {text}")
    if fix:
        print(f"         -> {fix}")
    problems.append(text)


def has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def parse_env(path: Path) -> tuple[dict[str, str], set[str]]:
    """(включённые настройки, закомментированные настройки) — прямо из текста файла .env."""
    active: dict[str, str] = {}
    commented: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            body = line.lstrip("# ").strip()
            if "=" in body:
                commented.add(body.split("=", 1)[0].strip())
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            active[k.strip()] = v.strip().strip("'\"")
    return active, commented


# --------------------------------------------------------------------- .env
def check_env() -> dict[str, str]:
    head("1. Файл .env")
    env_path = HERE / ".env"
    if (HERE / ".env.txt").exists():
        bad("Найден файл .env.txt — Блокнот добавил .txt к имени, Акира его не читает.",
            "Переименуй .env.txt в .env (включи в Проводнике Вид -> Показать -> Расширения имён файлов).")
    if not env_path.exists():
        bad(f"Файла .env нет в {HERE}", "Скопируй .env.example в .env и впиши свои ключи.")
        return {}
    active, commented = parse_env(env_path)
    ok(f"Файл найден: {env_path}")
    print("  Важные настройки (как записано в файле):")
    for key in SAFE_KEYS:
        if key in active:
            print(f"     {key}={active[key]}")
        elif key in commented:
            print(f"     {key}  <- строка ЗАКОММЕНТИРОВАНА (стоит # в начале), не действует")
        else:
            print(f"     {key}  <- нет в файле (используется значение по умолчанию)")
    return active


# --------------------------------------------------------------------- голос
def check_voice(active: dict[str, str]) -> None:
    head("2. Голос: слышит ли Акира тебя")
    try:
        import config
    except Exception as e:  # noqa: BLE001
        bad(f"Не удалось загрузить настройки: {e}", "Запусти установку заново: install.bat")
        return

    if not config.VOICE_INPUT_ENABLED:
        bad("Голосовой ввод ВЫКЛЮЧЕН: в .env стоит VOICE_INPUT_ENABLED=false.",
            "Открой .env, поставь VOICE_INPUT_ENABLED=true, сохрани и перезапусти Акиру.")
    else:
        ok("VOICE_INPUT_ENABLED=true")

    thr = config.VOICE_ENERGY_THRESHOLD
    if thr > 0:
        info(f"Порог громкости задан вручную: {thr:.0f}")
        if thr >= 500:
            bad(f"Порог громкости {thr:.0f} слишком высокий для тихого микрофона — тебя могут «не слышать».",
                "Поставь VOICE_ENERGY_THRESHOLD=0 (порог подберётся сам).")
    else:
        ok("Порог громкости подбирается автоматически")

    for module, hint in (("numpy", "numpy"), ("sounddevice", "sounddevice")):
        if has(module):
            ok(f"Пакет {module} установлен")
        else:
            bad(f"Не установлен пакет {module}.", f"Выполни: .venv\\Scripts\\pip install {hint}   (Linux: .venv/bin/pip)")
    if has("speech_recognition") or has("faster_whisper"):
        ok("Есть пакет для распознавания речи (" + ", ".join(
            m for m, p in (("Google/SpeechRecognition", "speech_recognition"), ("Whisper", "faster_whisper")) if has(p)) + ")")
    else:
        bad("Нет ни SpeechRecognition, ни faster-whisper — нечем распознавать речь.",
            "Выполни: .venv\\Scripts\\pip install SpeechRecognition")
    if not (has("numpy") and has("sounddevice")):
        return

    import numpy as np
    import sounddevice as sd

    try:
        devices = [(i, d) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    except Exception as e:  # noqa: BLE001
        bad(f"Не удалось получить список микрофонов: {e}")
        return
    if not devices:
        bad("Система не видит ни одного микрофона.",
            "Подключи микрофон / проверь Параметры -> Система -> Звук -> Ввод.")
        return
    try:
        default_in = sd.default.device[0]
    except Exception:  # noqa: BLE001
        default_in = None
    print("  Микрофоны (номер можно вписать в .env как VOICE_MIC_DEVICE=НОМЕР):")
    for i, d in devices:
        print(f"     {i}: {d['name']}{'   <- по умолчанию' if i == default_in else ''}")

    spec = active.get("VOICE_MIC_DEVICE", "")
    device = int(spec) if spec.isdigit() else None
    if spec and not spec.isdigit():
        match = [i for i, d in devices if spec.lower() in d["name"].lower()]
        device = match[0] if match else None
        if not match:
            bad(f"VOICE_MIC_DEVICE={spec}: микрофона с таким названием нет.", "Оставь VOICE_MIC_DEVICE пустым или впиши номер из списка.")

    print("\n  >>> Сейчас 4 секунды идёт запись. Скажи что-нибудь ВСЛУХ: «Акира, привет». <<<", flush=True)
    sr, block = 16000, 512
    chunks: list = []
    try:
        with sd.InputStream(samplerate=sr, channels=1, dtype="int16", blocksize=block, device=device) as stream:
            for _ in range(int(4 * sr / block)):
                chunks.append(stream.read(block)[0][:, 0].copy())
    except Exception as e:  # noqa: BLE001
        bad(f"Не удалось открыть микрофон: {e}",
            "Windows: Параметры -> Конфиденциальность -> Микрофон -> включи доступ, в том числе для классических приложений.")
        return

    levels = [float(np.sqrt(np.mean(c.astype(np.float32) ** 2))) for c in chunks]
    noise, peak = float(np.median(levels)), max(levels)
    threshold = thr if thr > 0 else max(150.0, noise * 3.0)
    print(f"  Уровень: фон {noise:.0f}, самый громкий момент {peak:.0f}, порог речи {threshold:.0f}")
    if peak < 3:
        bad("С микрофона идёт полная тишина (нули) — он выключен или Windows не даёт к нему доступ.",
            "Параметры -> Конфиденциальность -> Микрофон -> включить; проверь, что микрофон не выключен кнопкой/переключателем.")
        return
    if peak < threshold:
        bad(f"Ты говорил(а), но самый громкий момент ({peak:.0f}) ниже порога ({threshold:.0f}).",
            "Сделай микрофон громче в настройках Windows (Звук -> Ввод -> Громкость) и поставь VOICE_ENERGY_THRESHOLD=0.")
        return
    ok("Речь на микрофоне слышна")

    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
    try:
        import stt
        engine = stt.get_engine()
        if engine is None:
            bad("Нет рабочего движка распознавания речи.", "pip install SpeechRecognition")
            return
        print(f"  Распознаю (движок: {engine.name})...", flush=True)
        text = engine.transcribe(audio)
    except Exception as e:  # noqa: BLE001
        bad(f"Распознавание речи упало: {e}")
        return
    if text:
        ok(f"Распознала: «{text}»")
        if not any(w in text.lower().replace("ё", "е") for w in config.WAKE_WORDS):
            info("Слова «Акира» в этой фразе не было — в обычной работе Акира откликается именно на него.")
    else:
        bad("Речь на микрофоне есть, но распознать её не удалось.",
            "Режим google нужен интернет; проверь его. Либо поставь локальный Whisper: pip install -r requirements-whisper.txt")


# ------------------------------------------------------------------------ AI
def _get_json(url: str, timeout: float = 4.0):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def check_ai(active: dict[str, str]) -> None:
    head("3. AI и Ollama")
    try:
        import config
        import providers
    except Exception as e:  # noqa: BLE001
        bad(f"Не удалось загрузить модуль AI: {e}")
        return

    if has("httpx"):
        ok("Пакет httpx установлен (нужен для Ollama, Groq, OpenAI, Claude)")
    else:
        bad("Не установлен пакет httpx — без него Ollama и другие не-Gemini провайдеры отключены.",
            "Выполни: .venv\\Scripts\\pip install httpx")

    routes = providers.load_routes(config, True)
    if routes:
        print("  Подключено к Акире (в порядке приоритета):")
        seen: list[str] = []
        for r in routes:
            if r.provider not in seen:
                seen.append(r.provider)
        for prov in seen:
            rs = [r for r in routes if r.provider == prov]
            keys = len({r.api_key for r in rs})
            models = ", ".join(dict.fromkeys(r.model for r in rs))
            print(f"     {prov}: ключей {keys}, модели: {models}")
    else:
        bad("Не подключен НИ ОДИН AI.", "Впиши GEMINI_API_KEY (или ключи другого провайдера) в .env.")

    providers_env = active.get("AI_PROVIDERS", "")
    if providers_env and "ollama" not in [p.strip().lower() for p in providers_env.split(",")]:
        bad(f"AI_PROVIDERS={providers_env} — в этом списке НЕТ ollama, поэтому Акира её не использует.",
            "Допиши ollama: AI_PROVIDERS=gemini,ollama (или удали строку AI_PROVIDERS совсем).")

    wanted = [m.strip() for m in (active.get("OLLAMA_MODELS", "") or active.get("OLLAMA_MODEL", "")).replace(";", ",").split(",") if m.strip()]
    if not wanted:
        bad("OLLAMA_MODELS не задан в .env — ИЗ-ЗА ЭТОГО Акира и не переключается на Ollama.",
            "Впиши строку OLLAMA_MODELS=llama3.1 (имя должно совпадать с тем, что показывает `ollama list`), без # в начале.")
    else:
        ok(f"OLLAMA_MODELS={', '.join(wanted)}")

    base = (active.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1").rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    try:
        tags = _get_json(root + "/api/tags")
    except (urllib.error.URLError, OSError, ValueError) as e:
        bad(f"Ollama не отвечает по адресу {root} ({type(e).__name__}).",
            "Запусти приложение Ollama (значок в трее рядом с часами) или в командной строке: ollama serve")
        return
    installed = [m.get("name", "") for m in tags.get("models", [])]
    ok(f"Ollama запущена, моделей скачано: {len(installed)}")
    for name in installed:
        print(f"     {name}" + ("   <- ОБЛАЧНАЯ (нужен платный тариф Ollama)" if name.endswith(":cloud") else ""))
    if not wanted:
        return

    for model in wanted:
        present = model in installed or f"{model}:latest" in installed
        if model.endswith(":cloud"):
            bad(f"{model} — облачная модель, для неё нужен платный тариф Ollama.", "Возьми локальную: ollama pull llama3.1")
        elif not present:
            bad(f"Модели «{model}» нет среди скачанных.",
                f"Скачай: ollama pull {model}   — или впиши в OLLAMA_MODELS имя из списка выше.")

    local = [m for m in wanted if not m.endswith(":cloud") and (m in installed or f"{m}:latest" in installed)]
    if local:
        model = local[0]
        print(f"\n  Проверяю ответ модели {model} (в первый раз может занять до пары минут)...", flush=True)
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": "Ответь одним словом: привет"}]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, headers={"Content-Type": "application/json"})
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=240) as r:  # noqa: S310
                answer = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"].strip()
            ok(f"Ollama ответила за {time.time() - started:.0f} с: «{answer[:80]}»")
        except Exception as e:  # noqa: BLE001
            bad(f"Ollama не смогла ответить: {type(e).__name__}: {str(e)[:150]}",
                "Проверь, что модель скачана целиком (ollama list) и хватает оперативной памяти.")


def main() -> None:
    print("Диагностика Акиры. Ключи и токены не печатаются.")
    active = check_env()
    for section in (check_voice, check_ai):
        try:
            section(active)
        except KeyboardInterrupt:
            print("\n  (прервано)")
            break
        except Exception as e:  # noqa: BLE001
            bad(f"Проверка «{section.__name__}» сама упала: {type(e).__name__}: {e}")
    head("Итог")
    if problems:
        print(f"  Найдено проблем: {len(problems)}. Исправь пункты [ !! ] выше, сохрани .env,")
        print("  перезапусти Акиру и запусти эту проверку ещё раз.")
    else:
        print("  Всё в порядке. Если Акира всё равно молчит — пришли этот вывод целиком.")


if __name__ == "__main__":
    main()
