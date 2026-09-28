"""
providers.py — адаптеры разных AI для Brain.

Поддерживается три вида API:
    gemini     — Google Gemini (пакет google-genai)
    openai     — всё, что говорит на языке OpenAI Chat Completions:
                 OpenAI, OpenRouter, Groq, DeepSeek, Mistral, а также ЛОКАЛЬНЫЕ
                 модели через Ollama и LM Studio (бесплатно, без ключа)
    anthropic  — Claude (Messages API)

Для каждого провайдера в .env задаются ключи и модели (префикс = имя большими буквами):
    GEMINI_API_KEYS=k1,k2         GEMINI_MODELS=gemini-2.5-flash,gemini-2.0-flash
    OPENAI_API_KEYS=sk-...        OPENAI_MODELS=gpt-4o-mini
    ANTHROPIC_API_KEYS=sk-ant-... ANTHROPIC_MODELS=claude-haiku-4-5-20251001
    GROQ_API_KEYS=gsk_...         GROQ_MODELS=llama-3.3-70b-versatile
    OLLAMA_MODELS=llama3.1        # ключ не нужен; OLLAMA_BASE_URL — если сервер не на localhost
    AI_PROVIDERS=gemini,groq,ollama   # порядок приоритета (по умолчанию — как в PRESETS)

Провайдер включается, только если для него заданы модели (и ключ, кроме локальных).
Если основной упёрся в лимит — Brain автоматически уходит на следующий.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import os
import types as _pytypes
import typing
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import httpx
except ImportError:  # нужен только для не-Gemini провайдеров
    httpx = None

try:
    from google import genai
    from google.genai import types as gtypes
except ImportError:
    genai = None
    gtypes = None

log = logging.getLogger("akira.providers")

MAX_TOOL_ROUNDS = 5

# имя -> (вид API, base_url по умолчанию, нужен ли ключ)
PRESETS: dict[str, tuple[str, str, bool]] = {
    "gemini":     ("gemini",    "", True),
    "openai":     ("openai",    "https://api.openai.com/v1", True),
    "anthropic":  ("anthropic", "https://api.anthropic.com", True),
    "openrouter": ("openai",    "https://openrouter.ai/api/v1", True),
    "groq":       ("openai",    "https://api.groq.com/openai/v1", True),
    "deepseek":   ("openai",    "https://api.deepseek.com", True),
    "mistral":    ("openai",    "https://api.mistral.ai/v1", True),
    "ollama":     ("openai",    "http://localhost:11434/v1", False),
    "lmstudio":   ("openai",    "http://localhost:1234/v1", False),
    "custom":     ("openai",    "", True),   # любой OpenAI-совместимый: CUSTOM_BASE_URL=...
}

_IMG_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name) or default)
    except ValueError:
        return default


MAX_TOKENS = _env_int("AI_MAX_TOKENS", 1024)


# --------------------------------------------------------------------- типы
class ProviderError(Exception):
    """Ошибка API провайдера. code — HTTP-статус (как у google.genai.errors.APIError)."""

    def __init__(self, code: int, message: str):
        super().__init__(f"{code} {message}")
        self.code = code


@dataclass
class Attach:
    name: str
    mime: str
    data: bytes


@dataclass(frozen=True)
class Route:
    """Одна «дорожка»: провайдер + ключ + модель."""
    provider: str
    kind: str        # gemini | openai | anthropic
    api_key: str
    base_url: str
    model: str
    key_no: int      # номер ключа внутри провайдера (только для логов)

    @property
    def label(self) -> str:
        return f"{self.provider}: ключ #{self.key_no}, модель {self.model}"


# ------------------------------------------------------------- загрузка .env
def split_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.replace(";", ",").replace("\n", ",").split(",") if v.strip()]


def dedupe(items: list[Optional[str]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        it = (it or "").strip()
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def load_routes(cfg=None, prefer_best_model: bool = True) -> list[Route]:
    """Собирает упорядоченный список маршрутов из переменных окружения (и модуля config)."""
    order = [p.lower() for p in split_list(os.getenv("AI_PROVIDERS"))] or list(PRESETS)
    for p in order:
        if p not in PRESETS:
            log.warning("AI_PROVIDERS: неизвестный провайдер «%s» (доступны: %s)", p, ", ".join(PRESETS))
    routes: list[Route] = []

    for name in order:
        if name not in PRESETS:
            continue
        kind, default_url, needs_key = PRESETS[name]
        pfx = name.upper()

        keys = dedupe(
            split_list(os.getenv(f"{pfx}_API_KEYS"))
            + [os.getenv(f"{pfx}_API_KEY") or getattr(cfg, f"{pfx}_API_KEY", None)]
            + [os.getenv(f"{pfx}_API_KEY_{i}") for i in range(1, 21)]
        )
        models = dedupe(split_list(os.getenv(f"{pfx}_MODELS")) + [os.getenv(f"{pfx}_MODEL")])
        if not models:                              # значение по умолчанию из config.py — только если больше ничего нет
            models = dedupe([getattr(cfg, f"{pfx}_MODEL", None)])

        if name == "gemini" and keys and not models:
            models = ["gemini-2.0-flash"]          # запасная модель по умолчанию
        if not needs_key and not keys:
            keys = ["local"]

        if not models:
            if keys and needs_key:
                log.warning("%s: ключ есть, но не задан %s_MODELS — провайдер пропущен", name, pfx)
            continue
        if not keys:
            continue
        if kind == "gemini" and genai is None:
            log.warning("gemini: не установлен пакет google-genai — провайдер пропущен")
            continue
        if kind != "gemini" and httpx is None:
            log.warning("%s: не установлен пакет httpx (pip install httpx) — провайдер пропущен", name)
            continue
        base = (os.getenv(f"{pfx}_BASE_URL") or default_url).rstrip("/")
        if kind != "gemini" and not base:
            log.warning("%s: не задан %s_BASE_URL — провайдер пропущен", name, pfx)
            continue

        nk, nm = len(keys), len(models)
        pairs = ([(k, m) for m in range(nm) for k in range(nk)] if prefer_best_model
                 else [(k, m) for k in range(nk) for m in range(nm)])
        routes += [Route(name, kind, keys[k], base, models[m], k + 1) for k, m in pairs]

    return routes


# ------------------------------------------------------------ инструменты
_PY2JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}


def tool_schema(fn: Callable) -> dict:
    """JSON-схема инструмента из python-функции: имя, докстринг, типы аргументов."""
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001
        hints = {}
    union_types = tuple(t for t in (typing.Union, getattr(_pytypes, "UnionType", None)) if t)
    props: dict[str, dict] = {}
    required: list[str] = []
    for pname, p in sig.parameters.items():
        t = hints.get(pname, str)
        if typing.get_origin(t) in union_types:
            args = [a for a in typing.get_args(t) if a is not type(None)]
            t = args[0] if args else str
        props[pname] = {"type": _PY2JSON.get(t, "string")}
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "name": fn.__name__,
        "description": inspect.getdoc(fn) or fn.__name__,
        "parameters": {"type": "object", "properties": props, "required": required},
    }


async def run_tool(tools: dict[str, Callable], name: str, args) -> str:
    """Запускает инструмент. Обычные функции идут прямо в потоке событий (важно для COM/Windows);
    функции с атрибутом .slow = True — в отдельном потоке."""
    fn = tools.get(name)
    if fn is None:
        return f"Неизвестный инструмент: {name}"
    if not isinstance(args, dict):
        args = {}
    try:
        if getattr(fn, "slow", False):
            out = await asyncio.to_thread(fn, **args)
        else:
            out = fn(**args)
        if inspect.isawaitable(out):
            out = await out
    except Exception as e:  # noqa: BLE001
        log.warning("Инструмент %s упал: %s", name, e)
        return f"Ошибка инструмента: {type(e).__name__}: {e}"
    return str(out)[:4000]


# ----------------------------------------------------------------- HTTP
async def _post(url: str, headers: dict, body: dict, timeout: float = 90.0) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=headers, json=body)
    except httpx.TransportError as e:
        # сеть/сервер недоступны — для Brain это то же, что «перегружен»
        raise ProviderError(503, f"UNAVAILABLE: {type(e).__name__}: {e}") from e
    if r.status_code >= 400:
        raise ProviderError(r.status_code, r.text[:500])
    return r.json()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _role(role: str) -> str:
    return "assistant" if role == "model" else "user"


# --------------------------------------------------------------- Gemini
async def _gemini(client, model: str, system: str, history: list[tuple[str, str]],
                  text: str, atts: list[Attach], tools: list[Callable]) -> str:
    contents = [gtypes.Content(role=r, parts=[gtypes.Part(text=t)]) for r, t in history]
    parts = []
    for a in atts:
        parts.append(gtypes.Part(text=f"[Файл {a.name}]"))
        parts.append(gtypes.Part.from_bytes(data=a.data, mime_type=a.mime))
    parts.append(gtypes.Part(text=text))
    contents.append(gtypes.Content(role="user", parts=parts))

    cfg = gtypes.GenerateContentConfig(system_instruction=system, tools=tools or None)
    res = await client.aio.models.generate_content(model=model, contents=contents, config=cfg)
    try:
        return (res.text or "").strip()
    except Exception:  # noqa: BLE001  (ответ заблокирован фильтрами и т.п.)
        return ""


# ------------------------------------------------- OpenAI-совместимые
async def _openai(route: Route, system: str, history: list[tuple[str, str]],
                  text: str, atts: list[Attach], tools: dict[str, Callable]) -> str:
    messages: list[dict] = [{"role": "system", "content": system}]
    messages += [{"role": _role(r), "content": t} for r, t in history]

    content: list[dict] = []
    unsupported: list[str] = []
    for a in atts:
        if a.mime in _IMG_MIMES:
            content.append({"type": "image_url", "image_url": {"url": f"data:{a.mime};base64,{_b64(a.data)}"}})
        else:
            unsupported.append(a.name)
    prompt = text + (f"\n(Эта модель не читает файлы: {', '.join(unsupported)})" if unsupported else "")
    content.append({"type": "text", "text": prompt})
    messages.append({"role": "user", "content": content if len(content) > 1 else prompt})

    defs = [{"type": "function", "function": tool_schema(fn)} for fn in tools.values()]
    url = f"{route.base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"}

    for _ in range(MAX_TOOL_ROUNDS):
        body: dict = {"model": route.model, "messages": messages}
        if defs:
            body["tools"] = defs
        try:
            data = await _post(url, headers, body)
        except ProviderError as e:
            if defs and e.code == 400 and "tool" in str(e).lower():
                defs = []          # модель не умеет инструменты (часто у локальных) — отвечаем без них
                continue
            raise
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip()
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
        for c in calls:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await run_tool(tools, c["function"]["name"], args)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
    return ""


# ------------------------------------------------------------ Anthropic
async def _anthropic(route: Route, system: str, history: list[tuple[str, str]],
                     text: str, atts: list[Attach], tools: dict[str, Callable]) -> str:
    messages: list[dict] = [{"role": _role(r), "content": t} for r, t in history]

    content: list[dict] = []
    unsupported: list[str] = []
    for a in atts:
        if a.mime in _IMG_MIMES:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": a.mime, "data": _b64(a.data)}})
        elif a.mime == "application/pdf":
            content.append({"type": "document",
                            "source": {"type": "base64", "media_type": a.mime, "data": _b64(a.data)}})
        else:
            unsupported.append(a.name)
    prompt = text + (f"\n(Эта модель не читает файлы: {', '.join(unsupported)})" if unsupported else "")
    content.append({"type": "text", "text": prompt})
    messages.append({"role": "user", "content": content})

    defs = []
    for fn in tools.values():
        s = tool_schema(fn)
        defs.append({"name": s["name"], "description": s["description"], "input_schema": s["parameters"]})

    url = f"{route.base_url}/v1/messages"
    headers = {"x-api-key": route.api_key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}

    for _ in range(MAX_TOOL_ROUNDS):
        body: dict = {"model": route.model, "max_tokens": MAX_TOKENS, "system": system, "messages": messages}
        if defs:
            body["tools"] = defs
        data = await _post(url, headers, body)
        blocks = data.get("content") or []
        uses = [b for b in blocks if b.get("type") == "tool_use"]
        if data.get("stop_reason") != "tool_use" or not uses:
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        messages.append({"role": "assistant", "content": blocks})
        results = []
        for b in uses:
            results.append({"type": "tool_result", "tool_use_id": b["id"],
                            "content": await run_tool(tools, b["name"], b.get("input"))})
        messages.append({"role": "user", "content": results})
    return ""


# ------------------------------------------------------------- вход
async def generate(route: Route, system: str, history: list[tuple[str, str]], text: str,
                   atts: list[Attach], tools: list[Callable], gemini_clients: dict) -> str:
    """Один запрос к выбранному маршруту. Бросает исключение при ошибке (Brain её обработает)."""
    if route.kind == "gemini":
        client = gemini_clients.get(route.api_key)
        if client is None:
            client = gemini_clients[route.api_key] = genai.Client(api_key=route.api_key)
        return await _gemini(client, route.model, system, history, text, atts, tools)

    tool_map = {fn.__name__: fn for fn in tools}
    if route.kind == "openai":
        return await _openai(route, system, history, text, atts, tool_map)
    if route.kind == "anthropic":
        return await _anthropic(route, system, history, text, atts, tool_map)
    raise ValueError(f"Неизвестный вид провайдера: {route.kind}")
