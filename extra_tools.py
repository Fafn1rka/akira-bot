"""
extra_tools.py — дополнительные инструменты Акиры (только для владельца).

Что тут есть: время, напоминания, поиск в интернете, управление плеером, СЦЕНАРИИ («рабочий режим»),
ВЗГЛЯД НА ЭКРАН и утренний БРИФИНГ.

Чтобы добавить свой инструмент, просто напиши обычную функцию с типами аргументов и докстрингом —
модель увидит докстринг как описание. Работает со ВСЕМИ провайдерами (Gemini, OpenAI, Claude, Ollama...),
схемы строятся автоматически. Если инструмент долгий (сеть, диск) — поставь ему `.slow = True`.
"""
from __future__ import annotations

import logging
from datetime import datetime

import briefing
import config
import imagegen
import links
import mediakeys
import music
import scenes
import spotify

log = logging.getLogger("akira.tools")

_WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def make_extra_tools(brain, key: str) -> list:
    tools: list = []

    def get_current_time() -> str:
        """Возвращает текущие дату, день недели и время на компьютере владельца."""
        now = datetime.now()
        return f"{now:%d.%m.%Y}, {_WEEKDAYS[now.weekday()]}, {now:%H:%M}"

    def set_reminder(minutes: int, text: str) -> str:
        """Ставит напоминание: через указанное число минут (1..1440) Акира сама напомнит владельцу \
о том, что в text. Напоминания не переживают перезапуск программы."""
        m = max(1, min(int(minutes), 1440))
        if not brain.schedule_reminder(key, text, m * 60):
            return "Напоминания пока не подключены."
        return f"Хорошо, напомню через {m} мин."

    def web_search(query: str) -> str:
        """Ищет в интернете и возвращает несколько верхних результатов (заголовок, ссылка, описание). \
Используй для свежих новостей, погоды, курсов, статей и фактов, которых ты не знаешь наверняка. \
Найденные ссылки сами сохранятся на вкладке «Ссылки» и (если включено) придут владельцу в Telegram/Discord — \
отдельно пересылать их не нужно."""
        try:
            from ddgs import DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS  # старое имя пакета
            except ImportError:
                return "Поиск не установлен: pip install ddgs"
        try:
            results = list(DDGS().text(query, max_results=5))
        except Exception as e:  # noqa: BLE001
            return f"Поиск не удался: {type(e).__name__}"
        if not results:
            return "Ничего не нашлось."

        found = [(r.get("title", "") or r.get("href", ""), r.get("href", "")) for r in results[:3] if r.get("href")]
        for title, url in found:
            links.add_link(url, title, "инфо", source="web_search")
        if found and config.LINKS_NOTIFY:
            brain.notify(key, "\n\n".join(f"🔗 {t}\n{u}" for t, u in found))

        return "\n\n".join(
            f"{r.get('title', '')}\n{r.get('href', '')}\n{r.get('body', '')}" for r in results
        )

    web_search.slow = True  # type: ignore[attr-defined]

    def media_control(action: str) -> str:
        """Управляет уже играющим плеером (музыка, видео в браузере, Spotify и т.д.). \
action: 'play_pause' (пауза/продолжить), 'pause', 'play', 'next' (следующий трек) или 'previous' (предыдущий). \
Чтобы включить КОНКРЕТНУЮ песню или исполнителя — не сюда, вызывай play_music."""
        return mediakeys.media_key(action)

    def play_music(query: str) -> str:
        """Включает конкретную песню или исполнителя по названию — то, что владелец попросил \
(«включи <песня>», «поставь <исполнитель>», «переключи на другую песню/на <что-то>»). Ищет по порядку: \
личная библиотека музыки владельца -> его Spotify (если подключён) -> YouTube. Чтобы просто поставить \
на паузу или переключить трек дальше по очереди — используй media_control, а не эту команду."""
        local = music.find(query, limit=1)
        if local:
            return music.play_track(local[0])          # уже сама пишет в историю прослушанного

        capture: dict = {}
        if spotify.available():
            result = spotify.play(query, capture=capture)
            if capture.get("title"):
                music.record_played(capture["title"], url=capture.get("url", ""), source="Spotify")
        else:
            result = music.play_youtube(query, capture=capture)   # сама пишет в историю (source=YouTube)

        if capture.get("url"):
            links.add_link(capture["url"], capture.get("title") or query, capture.get("kind", "музыка"),
                           source="play_music")
            if config.LINKS_NOTIFY:
                brain.notify(key, f"🎵 {capture.get('title') or query}\n{capture['url']}")
        return result

    play_music.slow = True  # type: ignore[attr-defined]

    def list_music(query: str = "") -> str:
        """Показывает, что есть в личной библиотеке музыки владельца — все треки или по запросу \
(жанр/исполнитель/часть названия). Полезно перед play_music, если владелец не уверен, что выбрать, \
или просит «что у меня есть из ...»."""
        return music.list_library(query)

    list_music.slow = True  # type: ignore[attr-defined]

    # ---------------------------------------------------------- сценарии
    def run_scene(name: str) -> str:
        """Включает сценарий — сразу несколько действий на компьютере (открыть программы, сайты, выставить \
громкость). Вызывай, когда владелец просит «включи рабочий режим», «игровой режим», «тишину» и т.п. \
Доступные сценарии: __NAMES__."""
        return scenes.run_scene(name)

    def list_scenes() -> str:
        """Перечисляет доступные сценарии (режимы), которые можно включить через run_scene."""
        found = scenes.names()
        return ("Доступные сценарии: " + ", ".join(found)) if found else "Сценариев пока нет."

    # имена сценариев — прямо в описание инструмента, чтобы модель знала их, не спрашивая
    run_scene.__doc__ = (run_scene.__doc__ or "").replace("__NAMES__", ", ".join(scenes.names()) or "пока нет")

    # ------------------------------------------------------------ брифинг
    def morning_briefing() -> str:
        """Собирает данные для утреннего приветствия: дата, погода и напоминания на сегодня. Вызывай, когда \
владелец просит утренний брифинг, «что сегодня» или «какая погода». Затем перескажи это живой речью."""
        return briefing.gather_facts(brain)

    morning_briefing.slow = True  # type: ignore[attr-defined]

    def generate_image(prompt: str) -> str:
        """Рисует картинку по описанию и сама отправляет её владельцу — файлом в Telegram/Discord \
(смотря где попросили) или показывает на вкладке «Картинки» в окне. Используй, когда просят \
нарисовать/сгенерировать/создать картинку, иллюстрацию, арт и т.п. prompt — подробное описание того, \
что нарисовать: стиль, детали, настроение (по-английски обычно точнее, но можно и по-русски). \
Готовую картинку в ответе описывать не нужно — просто скажи коротко, что нарисовала."""
        path, caption = imagegen.generate(prompt)
        if path is None:
            return caption
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        delivered = brain.notify_image(key, path.read_bytes(), mime, caption)
        if not delivered:
            return f"{caption} Сохранила: {path}"
        return caption

    generate_image.slow = True  # type: ignore[attr-defined]

    tools += [get_current_time, set_reminder, web_search, media_control, play_music, list_music,
              generate_image, run_scene, list_scenes, morning_briefing]

    # -------------------------------------------------------------- экран
    if config.ENABLE_SCREEN_VISION:
        def look_at_screen() -> str:
            """Делает снимок экрана владельца, чтобы ты его рассмотрела. Вызывай, когда просят посмотреть \
на экран, помочь с тем, что сейчас открыто, или разобраться с ошибкой на экране. После вызова коротко \
скажи, что смотришь; сам снимок ты получишь следующим шагом."""
            return brain.request_screenshot(key)

        tools.append(look_at_screen)

    return tools
