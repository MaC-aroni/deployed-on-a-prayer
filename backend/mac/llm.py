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

    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str:
        body = {"model": self.model, "temperature": 0.2, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        # A chat completion changes nothing, so a timeout or 5xx is simply asked again.
        reply = _request(self.url, self.headers, method="POST", body=body, timeout=self.timeout, retries=2)
        try:
            text = reply["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise IntegrationError(f"unexpected LLM response: {json.dumps(reply)[:300]}") from e
        if not text or not text.strip():
            raise IntegrationError("the LLM returned an empty response")
        return strip_reasoning(text)


    def chat(self, messages: list[dict], tools: list[dict] | None = None, *, max_tokens: int = 2048) -> dict:
        """One turn of an OpenAI-style conversation with function calling. Returns the assistant
        message: {"content": str | None, "tool_calls": [{"id", "function": {"name", "arguments"}}]}."""
        body = {"model": self.model, "temperature": 0.2, "max_tokens": max_tokens, "messages": messages}
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        reply = _request(self.url, self.headers, method="POST", body=body, timeout=self.timeout, retries=2)
        try:
            message = reply["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise IntegrationError(f"unexpected LLM response: {json.dumps(reply)[:300]}") from e
        if message.get("content"):
            message["content"] = strip_reasoning(message["content"])
        return message


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
