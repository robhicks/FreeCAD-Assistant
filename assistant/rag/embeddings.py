# SPDX-License-Identifier: LGPL-2.1-or-later

import json
import urllib.request
import urllib.error


EMBEDDING_DEFAULTS = {
    "openai": {
        "base_url": "https://api.openai.com",
        "model": "text-embedding-3-small",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "text-embedding-004",
    },
    "custom": {
        "base_url": "http://localhost:11434",
        "model": "",
    },
}


class EmbeddingClient:
    """HTTP-based embedding client using urllib. No SDK dependencies."""

    def __init__(self, provider, api_key, base_url, model):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    @classmethod
    def from_preferences(cls):
        """Build an EmbeddingClient from FreeCAD preferences."""
        import FreeCAD

        prefs = FreeCAD.ParamGet(
            "User parameter:BaseApp/Preferences/Mod/Assistant"
        )
        provider = prefs.GetString("Provider", "anthropic")

        if not cls.provider_supports_embeddings(provider):
            return None

        api_key = prefs.GetString("ApiKey", "")
        defaults = EMBEDDING_DEFAULTS.get(provider, EMBEDDING_DEFAULTS["custom"])
        base_url = prefs.GetString("BaseUrl", "") or defaults["base_url"]
        model = defaults["model"]

        return cls(provider, api_key, base_url, model)

    @staticmethod
    def provider_supports_embeddings(provider):
        """Anthropic has no embedding API."""
        return provider != "anthropic"

    def supports_embeddings(self):
        return self.provider_supports_embeddings(self.provider)

    def embed(self, text):
        """Embed a single text string. Returns list[float]."""
        if self.provider == "custom":
            return self._embed_ollama(text)
        return self._embed_openai_compatible([text])[0]

    def embed_batch(self, texts, batch_size=32):
        """Embed multiple texts. Returns list[list[float]]."""
        if self.provider == "custom":
            return [self._embed_ollama(t) for t in texts]

        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            results.extend(self._embed_openai_compatible(batch))
        return results

    def _embed_openai_compatible(self, texts):
        """OpenAI/Gemini compatible embedding endpoint."""
        url = self.base_url + "/v1/embeddings"
        payload = {
            "model": self.model,
            "input": texts,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = self._http_post(url, payload, headers)
        # Sort by index to ensure order matches input
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    def _embed_ollama(self, text):
        """Ollama embedding endpoint."""
        url = self.base_url + "/api/embed"
        payload = {"model": self.model, "input": text}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = self._http_post(url, payload, headers)
        return data["embeddings"][0]

    def _http_post(self, url, payload, headers):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(error_body)
                msg = detail.get("error", {}).get("message", error_body)
            except (json.JSONDecodeError, AttributeError):
                msg = error_body
            raise RuntimeError(f"Embedding API error {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Embedding connection error: {e.reason}") from e
