"""Model providers for the eval tool: HarnessRouter (main) and TokenRouter (fallback).

Keys come from an environment variable or ~/.config/<provider>/key and are never printed or saved.
Redirects are refused so the Authorization header is never forwarded to another host.
Standard library only.
"""
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

RETRYABLE = (429, 500, 502, 503, 504)
TERMINAL = ("completed", "done", "failed", "incomplete", "cancelled")


class ProviderError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def read_key(env_name, provider_dir):
    key = os.getenv(env_name, "").strip()
    path = Path.home() / ".config" / provider_dir / "key"
    if not key and path.is_file():
        key = path.read_text().strip()
    return key or None


def http_json(url, key=None, payload=None, headers=None, timeout=180, attempts=3):
    data = json.dumps(payload).encode() if payload is not None else None
    base = {"Accept": "application/json", "User-Agent": "approval-gate-eval/1.0"}
    if key:
        base["Authorization"] = f"Bearer {key}"
    if data is not None:
        base["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                     headers={**base, **(headers or {})})
    for attempt in range(1, attempts + 1):
        try:
            with _OPENER.open(request, timeout=timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode(errors="replace")
            if e.code in RETRYABLE and attempt < attempts:
                time.sleep(2 * attempt)
                continue
            raise ProviderError(f"HTTP {e.code} from {url.split('?')[0]}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < attempts:
                time.sleep(2 * attempt)
                continue
            raise ProviderError(f"{url.split('?')[0]} unreachable: {e}") from None


def _items(body, *keys):
    if isinstance(body, list):
        return body
    for key in keys:
        if isinstance(body.get(key), list):
            return body[key]
    return []


def response_text(body):
    if isinstance(body.get("output_text"), str) and body["output_text"].strip():
        return body["output_text"]
    parts = []
    for item in body.get("output") or []:
        for content in (item.get("content") or []) if isinstance(item, dict) else []:
            if isinstance(content, dict) and content.get("type") in ("output_text", "text") and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts)


class HarnessRouter:
    label = "HarnessRouter"

    def __init__(self, key, harness_id=None):
        self.key = key
        self.base = os.getenv("HR_BASE_URL", "https://api.harnessrouter.ai").rstrip("/")
        self.harness_id = harness_id or os.getenv("HR_HARNESS_ID")
        self.version = None

    def discover(self):
        body = http_json(f"{self.base}/v1/uhp", attempts=2, timeout=15)
        self.version = body.get("default_version")
        return self.version

    def harnesses(self):
        return _items(http_json(f"{self.base}/v1/harnesses", self.key, timeout=30), "data", "harnesses", "items")

    def choose_harness(self):
        if self.harness_id:
            return self.harness_id
        listed = [h for h in self.harnesses() if isinstance(h, dict) and (h.get("id") or h.get("harness_id"))]
        if not listed:
            raise ProviderError("No Harness in this Workspace. Create one in the HarnessRouter dashboard or pass --harness <id>.")
        preferred = next((h for h in listed if "claude" in json.dumps(h).lower()), listed[0])
        self.harness_id = preferred.get("id") or preferred.get("harness_id")
        return self.harness_id

    def ask(self, prompt, timeout=900):
        harness = self.choose_harness()
        if self.version is None:
            self.discover()
        headers = {"Idempotency-Key": str(uuid.uuid4()), "UHP-Version": self.version}
        body = http_json(f"{self.base}/v1/responses", self.key,
                         {"input": prompt, "metadata": {"harness_id": harness}, "stream": False},
                         headers=headers, timeout=timeout, attempts=1)
        deadline = time.monotonic() + timeout
        while body.get("status") not in (None, *TERMINAL) and time.monotonic() < deadline:
            time.sleep(5)
            body = http_json(f"{self.base}/v1/responses/{body['id']}", self.key,
                             headers={"UHP-Version": self.version}, timeout=60)
        if body.get("status") in ("failed", "cancelled"):
            raise ProviderError(f"HarnessRouter response {body.get('status')}: {str(body.get('error'))[:300]}")
        text = response_text(body)
        if not text:
            raise ProviderError(f"HarnessRouter returned no text (status {body.get('status')}).")
        return text


class TokenRouter:
    label = "TokenRouter"

    def __init__(self, key, model=None):
        self.key = key
        self.base = os.getenv("TOKENROUTER_BASE_URL", "https://api.tokenrouter.com/v1").rstrip("/")
        self.model = model or os.getenv("TOKENROUTER_MODEL")

    def models(self):
        return sorted(m["id"] for m in _items(http_json(f"{self.base}/models", self.key, timeout=30), "data")
                      if isinstance(m, dict) and m.get("id"))

    def choose_model(self):
        if not self.model:
            ids = self.models()
            for prefix in ("claude-opus", "claude-sonnet", "claude", "gpt-5", "gemini", "deepseek"):
                self.model = next((i for i in ids if prefix in i.lower()), None)
                if self.model:
                    break
            self.model = self.model or (ids[0] if ids else None)
        if not self.model:
            raise ProviderError("TokenRouter returned no models for this key.")
        return self.model

    def ask(self, prompt, timeout=300):
        body = http_json(f"{self.base}/chat/completions", self.key, {
            "model": self.choose_model(), "max_tokens": 8000, "temperature": 0.7,
            "messages": [{"role": "user", "content": prompt}],
        }, timeout=timeout)
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"Unexpected TokenRouter response: {str(body)[:300]}") from None
