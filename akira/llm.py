import json
import os

import requests


class LLMError(Exception):
    pass


class OllamaClient:
    def __init__(self, host: str):
        self.host = host.rstrip("/")

    def chat(self, model, messages, on_token=None, num_ctx=4096, temperature=0.7, timeout=300) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": False,  # отключаем «размышления» у Qwen3
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        try:
            with requests.post(f"{self.host}/api/chat", json=payload, stream=True, timeout=timeout) as r:
                if r.status_code != 200:
                    raise LLMError(f"Ollama {r.status_code}: {r.text[:200]}")
                parts = []
                for line in r.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    tok = data.get("message", {}).get("content", "")
                    if tok:
                        parts.append(tok)
                        if on_token:
                            on_token(tok)
                    if data.get("done"):
                        break
                return "".join(parts)
        except requests.RequestException as e:
            raise LLMError(f"Ollama недоступна: {e}") from e

    def chat_tools(self, model, messages, tools, num_ctx=4096, timeout=300):
        """Один ход с инструментами (без стрима). Возвращает (текст, вызовы, сырые вызовы)."""
        payload = {"model": model, "messages": messages, "tools": tools, "stream": False, "think": False,
                   "options": {"temperature": 0.3, "num_ctx": num_ctx}}
        try:
            r = requests.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
        except requests.RequestException as e:
            raise LLMError(f"Ollama недоступна: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"Ollama {r.status_code}: {r.text[:200]}")
        msg = r.json().get("message", {})
        raw = msg.get("tool_calls") or []
        calls = []
        for tc in raw:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            calls.append({"name": fn.get("name", ""), "arguments": args})
        return msg.get("content", "") or "", calls, raw

    def embed(self, model, text) -> list[float]:
        try:
            r = requests.post(f"{self.host}/api/embed", json={"model": model, "input": text}, timeout=60)
            r.raise_for_status()
            return r.json()["embeddings"][0]
        except (requests.RequestException, KeyError, IndexError) as e:
            raise LLMError(f"Не удалось получить эмбеддинг: {e}") from e

    def is_up(self) -> bool:
        try:
            return requests.get(f"{self.host}/api/tags", timeout=2).status_code == 200
        except requests.RequestException:
            return False


class AnthropicClient:
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str = "claude-sonnet-5-5", max_tokens: int = 1500):
        self.model = model
        self.max_tokens = max_tokens

    @property
    def has_key(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def chat(self, system: str, messages: list[dict], timeout=120) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("Нет ANTHROPIC_API_KEY")
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system, "messages": messages}
        try:
            r = requests.post(self.URL, headers=headers, json=body, timeout=timeout)
        except requests.RequestException as e:
            raise LLMError(f"Облако недоступно: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"Облако {r.status_code}: {r.text[:200]}")
        blocks = r.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    def chat_tools(self, system, messages, tools, timeout=120):
        """Один ход с инструментами. Возвращает список content-блоков ответа."""
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("Нет ANTHROPIC_API_KEY")
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system,
                "messages": messages, "tools": tools}
        try:
            r = requests.post(self.URL, headers=headers, json=body, timeout=timeout)
        except requests.RequestException as e:
            raise LLMError(f"Облако недоступно: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"Облако {r.status_code}: {r.text[:200]}")
        return r.json().get("content", [])


class GeminiClient:
    """Бесплатный облачный мозг Google Gemini через OpenAI-совместимый API."""
    URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    def __init__(self, model: str = "gemini-2.0-flash", max_tokens: int = 2000):
        self.model = model
        self.max_tokens = max_tokens

    @property
    def has_key(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    def chat(self, system: str, messages: list[dict], timeout=60) -> str:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMError("Нет GEMINI_API_KEY")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        formatted = [{"role": "system", "content": system}] + messages
        body = {"model": self.model, "messages": formatted, "max_tokens": self.max_tokens}
        try:
            r = requests.post(self.URL, headers=headers, json=body, timeout=timeout)
        except requests.RequestException as e:
            raise LLMError(f"Gemini недоступен: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"Gemini {r.status_code}: {r.text[:200]}")
        choices = r.json().get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "") or ""
        return ""

    def chat_tools(self, system, messages, tools, timeout=60):
        """Инструменты в формате Anthropic-совместимых блоков для Brain."""
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMError("Нет GEMINI_API_KEY")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        # Преобразуем input_schema Anthropic в parameters OpenAI
        oa_tools = []
        for t in tools:
            oa_tools.append({
                "type": "function",
                "function": {
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                }
            })
        formatted = [{"role": "system", "content": system}] + messages
        body = {"model": self.model, "messages": formatted, "tools": oa_tools, "max_tokens": self.max_tokens}
        try:
            r = requests.post(self.URL, headers=headers, json=body, timeout=timeout)
        except requests.RequestException as e:
            raise LLMError(f"Gemini недоступен: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"Gemini {r.status_code}: {r.text[:200]}")
        msg = r.json().get("choices", [{}])[0].get("message", {})
        blocks = []
        content = msg.get("content")
        if content:
            blocks.append({"type": "text", "text": content})
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            blocks.append({
                "type": "tool_use",
                "id": tc.get("id", f"call_{fn.get('name')}"),
                "name": fn.get("name"),
                "input": args,
            })
        return blocks

