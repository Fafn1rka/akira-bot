import os
import threading
from datetime import datetime

from .agent import Agent, looks_like_action
from .config import load_persona
from .emotion import EMOTION_PROMPT, strip_tag
from .llm import AnthropicClient, GeminiClient, LLMError, OllamaClient
from .memory import Memory
from .router import Router
from .tools import Toolbox


def _normalize(msgs: list[dict]) -> list[dict]:
    """Облачному API нужно чередование ролей и старт с user."""
    out: list[dict] = []
    for m in msgs:
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n" + m["content"]}
        else:
            out.append(dict(m))
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


class Brain:
    def __init__(self, cfg: dict, db_path, base_dir=None):
        self.cfg = cfg
        self.persona = load_persona()
        self.local = OllamaClient(cfg["local"]["host"])
        cloud_cfg = cfg.get("cloud", {})
        provider = str(cloud_cfg.get("provider", "")).lower()
        if provider == "gemini" or (not provider and os.environ.get("GEMINI_API_KEY")):
            model = cloud_cfg.get("model") or "gemini-2.0-flash"
            if "claude" in model:
                model = "gemini-2.0-flash"
            self.cloud = GeminiClient(model, cloud_cfg.get("max_tokens", 2000))
        else:
            self.cloud = AnthropicClient(cloud_cfg.get("model", "claude-sonnet-5-5"), cloud_cfg.get("max_tokens", 1500))
        embed_model = cfg["local"]["embed_model"]
        self.memory = Memory(db_path, embed_fn=lambda t: self.local.embed(embed_model, t))
        self.router = Router(cfg, cloud_ready=lambda: self.cloud.has_key)
        self.lock = threading.RLock()   # один диалог за раз (голос, телефон, консоль)
        self.toolbox = self.agent = None
        if cfg.get("tools", {}).get("enabled") and base_dir is not None:
            self.toolbox = Toolbox(cfg, base_dir)
            self.agent = Agent(cfg, self.local, self.cloud, self.toolbox)

    def _system_prompt(self, facts: list[str], voice: bool = False, emotions: bool = False) -> str:
        s = self.persona + f"\n\nСейчас: {datetime.now():%Y-%m-%d %H:%M}."
        if facts:
            s += "\n\nЧто ты знаешь о пользователе:\n" + "\n".join(f"- {f}" for f in facts)
        if voice:
            s += ("\n\nТвой ответ будет озвучен голосом: отвечай кратко (1-3 предложения), "
                  "обычной речью, без markdown, списков, эмодзи и ссылок.")
        if emotions:
            s += EMOTION_PROMPT
        return s

    def reply(self, text: str, force: str | None = None, on_token=None, voice: bool = False,
              emotions: bool = False, act: bool | None = None, confirmer=None,
              on_event=None, allowed_tools=None) -> tuple[str, str]:
        with self.lock:
            return self._reply(text, force, on_token, voice, emotions, act, confirmer, on_event, allowed_tools)

    def _reply(self, text, force, on_token, voice, emotions, act, confirmer, on_event, allowed_tools):
        mem = self.cfg["memory"]
        facts = self.memory.recall(text, mem["recall_top_k"], mem["recall_min_score"])
        system = self._system_prompt(facts, voice, emotions)
        history = self.memory.recent_messages(mem["history_turns"])
        msgs = _normalize(history + [{"role": "user", "content": text}])

        answer, label = None, ""
        agent_mode = bool(self.agent) and (act is True or (act is None and looks_like_action(text, self.toolbox.keywords)))
        if agent_mode:
            use_cloud = force == "cloud" and self.router.cloud_available()
            try:
                answer = self.agent.run(system + self.toolbox.environment_prompt(allowed_tools), msgs,
                                        confirmer, on_event, use_cloud, allowed_tools)
                label = "агент · облако" if use_cloud else f"агент · {self.cfg['local']['main_model']}"
                if on_token:
                    on_token(answer)
            except LLMError as e:
                if on_event:
                    on_event("note", text=f"Режим действий недоступен ({e}). Отвечаю обычным чатом.")
                answer = None

        if answer is None:
            route = self.router.decide(text, force)
            label = route.kind
            if route.kind == "cloud":
                try:
                    answer = self.cloud.chat(system, msgs)
                    label = f"облако: {self.cloud.model}"
                    if on_token:
                        on_token(answer)
                except LLMError:
                    route.kind = "local_main"
                    label = "локально (облако не ответило)"
            if answer is None:
                loc = self.cfg["local"]
                model = loc["fast_model"] if route.kind == "local_fast" else loc["main_model"]
                full = [{"role": "system", "content": system}] + msgs
                answer = self.local.chat(model, full, on_token=on_token, num_ctx=loc["num_ctx"])
                if not label.startswith("локально"):
                    label = f"локально: {model}"

        self.memory.add_message("user", text)
        self.memory.add_message("assistant", answer)
        if mem.get("auto_facts"):
            self._auto_facts(text, answer)
        return strip_tag(answer)[1], label

    def _auto_facts(self, user_text: str, answer: str):
        prompt = (
            "Из реплики пользователя выдели устойчивые факты о нём (имя, предпочтения, планы, оборудование). "
            "Верни по одному факту на строку или слово НЕТ.\n\nРеплика: " + user_text
        )
        try:
            out = self.local.chat(self.cfg["local"]["fast_model"], [{"role": "user", "content": prompt}], num_ctx=2048)
        except LLMError:
            return
        for line in out.splitlines():
            line = line.strip("-• \t")
            if line and line.upper() != "НЕТ" and len(line) > 5:
                self.memory.add_fact(line)
