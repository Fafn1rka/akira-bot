"""Цикл агента: модель вызывает инструменты, результаты возвращаются ей, пока не будет финальный ответ."""
import re

ACTION_RE = re.compile(
    r"(открой|открыть|запусти|закрой|закрыть|найди|найти|поищи|создай|создать|удали|удалить|перемести|"
    r"переименуй|скопируй|прочитай|прочти|покажи (?:мне )?(?:файлы|папк|содержим)|скриншот|снимок экрана|"
    r"сохрани в файл|запиши в файл|загугли|\bopen\b|\blaunch\b|\bclose\b|\bdelete\b|\bmove\b|\bcopy\b|"
    r"screenshot|search for|\bgoogle\b|read (?:the )?file|create (?:a )?(?:file|folder)|"
    r"погод|новост|в интернете|в сети\b|курс валют|что нового|\bweather\b|\bnews\b|напомни|таймер|заметк)", re.I)


def looks_like_action(text: str, extra=()) -> bool:
    if ACTION_RE.search(text):
        return True
    low = text.lower()
    return any(k in low for k in extra)


class Agent:
    def __init__(self, cfg, local, cloud, toolbox):
        self.cfg, self.local, self.cloud, self.tb = cfg, local, cloud, toolbox

    def run(self, system, msgs, confirmer=None, on_event=None, use_cloud=False, allowed=None) -> str:
        ev = on_event or (lambda *a, **k: None)
        return (self._cloud if use_cloud else self._local)(system, msgs, confirmer, ev, allowed)

    def _call(self, name, args, confirmer, ev, allowed=None):
        ev("tool", name=name, args=args)
        return self.tb.run(name, args, confirmer, allowed)

    def _local(self, system, msgs, confirmer, ev, allowed=None):
        loc = self.cfg["local"]
        conv = [{"role": "system", "content": system}] + list(msgs)
        tools = self.tb.schemas_ollama(allowed)
        for _ in range(self.tb.max_steps):
            text, calls, raw = self.local.chat_tools(loc["main_model"], conv, tools, num_ctx=loc.get("agent_ctx", loc["num_ctx"]))
            if not calls:
                return text
            conv.append({"role": "assistant", "content": text or "", "tool_calls": raw})
            for c in calls:
                conv.append({"role": "tool", "tool_name": c["name"],
                             "content": self._call(c["name"], c["arguments"], confirmer, ev, allowed)})
        return "Я выполнила несколько шагов, но не уверена, что закончила. Проверьте результат."

    def _cloud(self, system, msgs, confirmer, ev, allowed=None):
        conv = list(msgs)
        tools = self.tb.schemas_anthropic(allowed)
        for _ in range(self.tb.max_steps):
            blocks = self.cloud.chat_tools(system, conv, tools)
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            if not uses:
                return text
            conv.append({"role": "assistant", "content": blocks})
            conv.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": u["id"],
                 "content": self._call(u["name"], u.get("input", {}), confirmer, ev, allowed)} for u in uses]})
        return "Я выполнила несколько шагов, но не уверена, что закончила. Проверьте результат."
