"""The LLM client the agents share: NVIDIA NIM's OpenAI-compatible chat API (Nemotron).

Agents only ever get text back from here. They never get credentials or tools that act: the
code around them reads Confluence, validates what the model returns, and opens pull requests.
"""

import json
import os
import re
from typing import Protocol

from .integrations import IntegrationError, _request

DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"  # the 120b "super" model 404s on NIM's chat API
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


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
