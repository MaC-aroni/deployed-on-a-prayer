"""The LLM client the agents share: NVIDIA NIM's OpenAI-compatible chat API (Nemotron).

Agents only ever get text back from here. They never get credentials or tools that act: the
code around them reads Confluence, validates what the model returns, and opens pull requests.
"""

import json
import os
import re
from pathlib import Path
from typing import Protocol

from .integrations import IntegrationError, _request

DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"  # the 120b "super" model 404s on NIM's chat API
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
GROK_MODEL = "grok-4.7"
GROK_BASE_URL = "https://api.x.ai/v1"
ROOT = Path(__file__).resolve().parents[2]


class LLM(Protocol):
    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str: ...


class NIMChat:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL,
                 timeout: int | None = None):
        # Reasoning models can think for minutes on a long prompt (Grok took >180 s to extract a
        # knowledge page). MAC_LLM_TIMEOUT overrides.
        timeout = timeout or int(os.environ.get("MAC_LLM_TIMEOUT", "300"))
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        self.model = model
        self.timeout = timeout

    def _body(self, messages: list[dict], max_tokens: int, tools: list[dict] | None = None) -> dict:
        body = {"model": self.model, "temperature": 0.2, "max_tokens": max_tokens, "messages": messages}
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        if thinking_off():
            body["chat_template_kwargs"] = {"enable_thinking": False}  # NIM's switch for Nemotron reasoning
        return body

    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        tokens, finish, reasoning = max_tokens, None, 0
        while True:
            # A chat completion changes nothing, so a timeout or 5xx is simply asked again.
            reply = _request(self.url, self.headers, method="POST", body=self._body(messages, tokens),
                             timeout=self.timeout, retries=2)
            try:
                choice = reply["choices"][0]
                text = choice["message"]["content"]
            except (KeyError, IndexError, TypeError) as e:
                raise IntegrationError(f"unexpected LLM response: {json.dumps(reply)[:300]}") from e
            finish = choice.get("finish_reason")
            reasoning = len(choice["message"].get("reasoning_content") or "")
            if text and text.strip() and not _truncated_thinking(text):
                return strip_reasoning(text)
            # A reasoning model that spent its whole budget thinking answers with empty content
            # (finish_reason "length", the thoughts in reasoning_content). Ask again with more room.
            spent = finish == "length" or reasoning > 0 or (text or "").lstrip().startswith("<think>")
            if not spent or tokens >= max_total_tokens():
                break
            tokens = min(tokens * 4, max_total_tokens())
        raise IntegrationError(
            f"the LLM returned an empty response (finish_reason={finish}, {reasoning} chars of reasoning, "
            f"max_tokens={tokens}): the model spent its token budget thinking. Set MAC_LLM_THINKING=off "
            f"or raise MAC_LLM_MAX_TOKENS")

    def chat(self, messages: list[dict], tools: list[dict] | None = None, *, max_tokens: int = 2048) -> dict:
        """One turn of an OpenAI-style conversation with function calling. Returns the assistant
        message: {"content": str | None, "tool_calls": [{"id", "function": {"name", "arguments"}}]}."""
        tokens = max_tokens
        while True:
            reply = _request(self.url, self.headers, method="POST", body=self._body(messages, tokens, tools),
                             timeout=self.timeout, retries=2)
            try:
                choice = reply["choices"][0]
                message = choice["message"]
            except (KeyError, IndexError, TypeError) as e:
                raise IntegrationError(f"unexpected LLM response: {json.dumps(reply)[:300]}") from e
            empty = not (message.get("content") or "").strip() and not message.get("tool_calls")
            if empty and choice.get("finish_reason") == "length" and tokens < max_total_tokens():
                tokens = min(tokens * 4, max_total_tokens())  # it was still thinking
                continue
            if message.get("content"):
                message["content"] = strip_reasoning(message["content"])
            return message


def thinking_off() -> bool:
    """MAC_LLM_THINKING=off asks NIM's Nemotron models not to reason before answering."""
    return os.environ.get("MAC_LLM_THINKING", "").strip().lower() in ("off", "0", "false", "no")


def max_total_tokens() -> int:
    """How far a reply's token budget may grow when the model spent it all thinking."""
    return int(os.environ.get("MAC_LLM_MAX_TOKENS", "32768"))


def _truncated_thinking(text: str) -> bool:
    """A <think> block that never closed: the budget ran out mid-thought."""
    return "<think>" in text and "</think>" not in text


def strip_reasoning(text: str) -> str:
    """Reasoning models may prepend their thinking; callers only want the answer."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_block(text: str, language: str) -> str:
    """The body of the first ```<language> fenced block, or the whole text if there isn't one."""
    match = re.search(rf"```(?:{language})?\s*\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else text).strip()


def parse_json(text: str):
    """JSON from a model reply, tolerating a ```json fence around it."""
    try:
        return json.loads(extract_block(text, "json"))
    except json.JSONDecodeError as e:
        raise ValueError(f"not valid JSON: {e}") from e


# ---- Which model: the switch -----------------------------------------------------------------
#
# Two providers can be configured at once: "nemotron" (NVIDIA NIM: NVIDIA_API_KEY, or the generic
# MAC_LLM_API_KEY / MAC_LLM_BASE_URL / MAC_LLM_MODEL) and "grok" (xAI: GROK_API_KEY or XAI_API_KEY,
# GROK_MODEL, GROK_BASE_URL). The console switches between them at run time; the choice is kept in
# MAC_DATA_DIR/settings.json, so it survives a restart and applies to every agent at once.


def providers() -> dict[str, dict]:
    """The providers this deployment has keys for: id -> {id, label, model, base_url, key}."""
    out: dict[str, dict] = {}
    key = os.environ.get("MAC_LLM_API_KEY") or os.environ.get("NVIDIA_API_KEY")
    if key:
        model = os.environ.get("MAC_LLM_MODEL", DEFAULT_MODEL)
        out["nemotron"] = {"id": "nemotron", "label": "Nemotron" if "nemotron" in model.lower() else model.split("/")[-1],
                           "model": model, "base_url": os.environ.get("MAC_LLM_BASE_URL", DEFAULT_BASE_URL), "key": key}
    gkey = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY")
    if gkey:
        out["grok"] = {"id": "grok", "label": "Grok", "model": os.environ.get("GROK_MODEL", GROK_MODEL),
                       "base_url": os.environ.get("GROK_BASE_URL", GROK_BASE_URL), "key": gkey}
    return out


def settings_path() -> Path:
    return Path(os.environ.get("MAC_DATA_DIR", ROOT / ".mac")) / "settings.json"


def _settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def current_provider() -> str | None:
    """The chosen provider when it's configured, else the first configured one (Nemotron first)."""
    available = providers()
    if not available:
        return None
    chosen = _settings().get("llm")
    if chosen in available:
        return chosen
    return "nemotron" if "nemotron" in available else next(iter(available))


def set_provider(provider: str) -> str:
    if provider not in providers():
        raise ValueError(f"no LLM provider {provider!r} is configured here; choose from {sorted(providers())}")
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**_settings(), "llm": provider}, indent=2), encoding="utf-8")
    return provider


def describe_providers() -> dict:
    """For GET /health: no keys, just what can be chosen and what is chosen."""
    current = current_provider()
    return {"llm_provider": current,
            "llm_providers": [{"id": p["id"], "label": p["label"], "model": p["model"], "active": p["id"] == current}
                              for p in providers().values()]}


class RoutedLLM:
    """An LLM that follows the switch: every call goes to whichever provider is chosen now.
    `provider` pins one instead (the CLI's --llm)."""

    def __init__(self, provider: str | None = None):
        self.pinned = provider
        self._clients: dict[tuple, NIMChat] = {}

    def _client(self) -> NIMChat:
        pid = self.pinned or current_provider()
        conf = providers().get(pid or "")
        if conf is None:
            raise IntegrationError("no LLM is configured here (NVIDIA_API_KEY / MAC_LLM_API_KEY or GROK_API_KEY)")
        key = (pid, conf["key"], conf["model"], conf["base_url"])
        if key not in self._clients:
            self._clients[key] = NIMChat(conf["key"], conf["model"], conf["base_url"])
        return self._clients[key]

    @property
    def provider(self) -> str | None:
        return self.pinned or current_provider()

    @property
    def model(self) -> str | None:
        conf = providers().get(self.provider or "")
        return conf["model"] if conf else None

    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str:
        return self._client().complete(system, user, max_tokens=max_tokens)

    def chat(self, messages: list[dict], tools: list[dict] | None = None, *, max_tokens: int = 2048) -> dict:
        return self._client().chat(messages, tools, max_tokens=max_tokens)


def llm_from_env() -> RoutedLLM | None:
    """The agents' LLM, or None when no provider has a key."""
    return RoutedLLM() if providers() else None
