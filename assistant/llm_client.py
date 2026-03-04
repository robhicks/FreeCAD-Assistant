# SPDX-License-Identifier: LGPL-2.1-or-later

import json
import urllib.request
import urllib.error

import FreeCAD

DEFAULTS = {
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-20250514",
    },
    "openai": {
        "base_url": "https://api.openai.com",
        "model": "gpt-4o",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
    },
    "custom": {
        "base_url": "http://localhost:11434",
        "model": "",
    },
}


class LLMClient:
    def __init__(self, provider, api_key, base_url, model):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    @classmethod
    def from_preferences(cls):
        prefs = FreeCAD.ParamGet(
            "User parameter:BaseApp/Preferences/Mod/Assistant"
        )
        provider = prefs.GetString("Provider", "anthropic")
        api_key = prefs.GetString("ApiKey", "")
        defaults = DEFAULTS.get(provider, DEFAULTS["custom"])
        base_url = prefs.GetString("BaseUrl", "") or defaults["base_url"]
        model = prefs.GetString("Model", "") or defaults["model"]

        if not api_key and provider in ("anthropic", "openai", "gemini"):
            raise ValueError(
                "No API key configured. Please set one in "
                "Edit > Preferences > Assistant."
            )

        return cls(provider, api_key, base_url, model)

    def send_message(self, messages, system_prompt=""):
        if self.provider == "anthropic":
            return self._send_anthropic(messages, system_prompt)
        return self._send_openai_compatible(messages, system_prompt)

    def _send_anthropic(self, messages, system_prompt):
        url = self.base_url + "/v1/messages"
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages,
        }
        if system_prompt:
            payload["system"] = system_prompt

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        data = self._http_post(url, payload, headers)
        return data["content"][0]["text"]

    def _send_openai_compatible(self, messages, system_prompt):
        url = self.base_url + "/v1/chat/completions"
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend(messages)

        payload = {
            "model": self.model,
            "messages": msgs,
        }

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = self._http_post(url, payload, headers)
        return data["choices"][0]["message"]["content"]

    def _http_post(self, url, payload, headers):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(error_body)
                msg = detail.get("error", {}).get("message", error_body)
            except (json.JSONDecodeError, AttributeError):
                msg = error_body
            raise RuntimeError(f"API error {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection error: {e.reason}") from e

    def get_embedding(self, text):
        """Get an embedding vector for text using the RAG embedding client.

        Returns list[float] or None if the provider doesn't support embeddings.
        """
        from assistant.rag.embeddings import EmbeddingClient

        client = EmbeddingClient.from_preferences()
        if client is None:
            return None
        return client.embed(text)
