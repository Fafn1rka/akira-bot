"""
Сценарии — несколько действий одной фразой: «Акира, включи рабочий режим».

Сценарии лежат в файле  data/scenes.json  — при первом запуске он создаётся сам с примерами,
дальше правь его как угодно (обычным блокнотом) и добавляй свои. Перезапускать Акиру после правки
не нужно — файл читается при каждом вызове.

Формат:
{
  "рабочий режим": {
    "aliases": ["работа", "работать"],          // другие названия, по которым сценарий тоже находится
    "say": "Включаю рабочий режим.",            // необязательно
    "steps": [
      {"open": "vscode"},                        // открыть программу или сайт (как «открой ...»)
      {"url": "https://github.com"},             // открыть ссылку в браузере
      {"volume": 25},                            // громкость 0..100
      {"media": "pause"},                        // play_pause | pause | play | next | previous
      {"wait": 2}                                // подождать N секунд (не больше 5)
    ]
  }
}

Безопасность: в шагах нет ни консольных команд, ни произвольного кода — только эти пять действий.
Модель выбирает лишь ИМЯ сценария; что именно он делает, определяет твой файл.
"""
from __future__ import annotations

import json
import logging
import os.path
import re
import time
import webbrowser
from pathlib import Path
from typing import Optional

import config
import mediakeys
import system_control

log = logging.getLogger("akira.scenes")

SCENES_FILE = config.DATA_DIR / "scenes.json"
MAX_STEPS = 12
MAX_WAIT_TOTAL = 5.0

DEFAULT_SCENES: dict = {
    "рабочий режим": {
        "aliases": ["работа", "работать", "work"],
        "say": "Включаю рабочий режим.",
        "steps": [{"open": "vscode"}, {"url": "https://github.com"}, {"volume": 25}],
    },
    "игровой режим": {
        "aliases": ["игры", "поиграть", "гейминг", "gaming"],
        "say": "Игровой режим, поехали.",
        "steps": [{"open": "steam"}, {"open": "discord"}, {"volume": 60}],
    },
    "отдых": {
        "aliases": ["расслабиться", "музыка", "relax"],
        "say": "Отдыхаем.",
        "steps": [{"open": "spotify"}, {"volume": 45}],
    },
    "тишина": {
        "aliases": ["тихий режим", "тихо", "silence"],
        "say": "Тишина.",
        "steps": [{"volume": 0}],
    },
}


# ------------------------------------------------------------------ файл
def load_scenes() -> dict:
    """Читает data/scenes.json; если файла нет — создаёт с примерами. Битый файл -> примеры (и предупреждение)."""
    try:
        if not SCENES_FILE.exists():
            SCENES_FILE.parent.mkdir(exist_ok=True)
            SCENES_FILE.write_text(json.dumps(DEFAULT_SCENES, ensure_ascii=False, indent=2), encoding="utf-8")
            return dict(DEFAULT_SCENES)
        data = json.loads(SCENES_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("ожидался объект {...}")
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось прочитать %s (%s) — использую сценарии по умолчанию.", SCENES_FILE, e)
        return dict(DEFAULT_SCENES)


def _norm(text: str) -> str:
    t = re.sub(r"[«»\"'.,!?]", " ", (text or "").lower().replace("ё", "е"))
    t = re.sub(r"\b(включи|запусти|давай|режим|сценарий|мод)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def find_scene(name: str, scenes: Optional[dict] = None) -> Optional[str]:
    """Имя сценария по тому, что сказал человек («рабочий», «включи работу», «игры»...). None — не нашла."""
    scenes = scenes if scenes is not None else load_scenes()
    q = _norm(name)
    if not q:
        return None
    labels: list[tuple[str, str]] = []            # (нормализованное название, настоящее имя сценария)
    for key, sc in scenes.items():
        labels.append((_norm(key), key))
        for alias in sc.get("aliases") or []:
            labels.append((_norm(str(alias)), key))
    for n, key in labels:                          # 1) точное совпадение
        if n and n == q:
            return key
    for n, key in labels:                          # 2) начало слова («работ» -> «работа»)
        if n and len(q) >= 3 and (n.startswith(q) or q.startswith(n)) and len(n) >= 3:
            return key
    for n, key in labels:                          # 3) общий корень слова («работу» ~ «работа», «музыку» ~ «музыка»)
        pre = len(os.path.commonprefix([n, q]))
        if n and pre >= 5 and pre >= min(len(n), len(q)) - 2:
            return key
    for n, key in labels:                          # 4) одно входит в другое
        if n and len(q) >= 3 and len(n) >= 3 and (q in n or n in q):
            return key
    return None


def names(scenes: Optional[dict] = None) -> list[str]:
    return list((scenes if scenes is not None else load_scenes()).keys())


def save_scenes(data: dict) -> None:
    """Сохраняет весь набор сценариев (используется окном редактора в gui.py)."""
    SCENES_FILE.parent.mkdir(exist_ok=True)
    SCENES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ запуск
def _do_step(step: dict, waited: list[float]) -> str:
    if "open" in step:
        return system_control.open_app(str(step["open"]))
    if "url" in step:
        url = str(step["url"]).strip()
        if not re.match(r"^https?://", url, re.I):
            return f"Пропустила ссылку «{url}»: разрешены только http и https."
        webbrowser.open(url)
        return f"Открываю {url}."
    if "volume" in step:
        try:
            level = max(0, min(100, int(step["volume"])))
        except (TypeError, ValueError):
            return "Пропустила шаг громкости: нужно число от 0 до 100."
        return system_control.control_volume("set", level)
    if "media" in step:
        return mediakeys.media_key(str(step["media"]))
    if "wait" in step:
        try:
            sec = max(0.0, float(step["wait"]))
        except (TypeError, ValueError):
            return ""
        sec = min(sec, MAX_WAIT_TOTAL - waited[0])
        if sec > 0:
            waited[0] += sec
            time.sleep(sec)
        return ""
    return f"Пропустила непонятный шаг: {list(step)[:1]}"


def run_scene(name: str) -> str:
    """Выполняет сценарий по имени. Возвращает короткий отчёт для Акиры."""
    scenes = load_scenes()
    key = find_scene(name, scenes)
    if key is None:
        avail = ", ".join(names(scenes)) or "пока ни одного"
        return f"Не знаю такого сценария — «{name}». Есть: {avail}."
    steps = scenes[key].get("steps")
    if not isinstance(steps, list) or not steps:
        return f"В сценарии «{key}» нет шагов — проверь {SCENES_FILE.name}."

    report: list[str] = []
    waited = [0.0]
    for step in steps[:MAX_STEPS]:
        if not isinstance(step, dict):
            continue
        try:
            res = _do_step(step, waited)
        except Exception as e:  # noqa: BLE001
            log.warning("Шаг сценария %s упал: %s", key, e)
            res = f"Шаг не удался ({type(e).__name__})."
        if res:
            report.append(res)
        time.sleep(0.4)                            # не запускать всё одновременно
    if len(steps) > MAX_STEPS:
        report.append(f"(Выполнила только первые {MAX_STEPS} шагов.)")
    say = str(scenes[key].get("say") or "").strip()
    return f"Сценарий «{key}» выполнен. " + " ".join(report) + (f" Скажи: {say}" if say else "")
