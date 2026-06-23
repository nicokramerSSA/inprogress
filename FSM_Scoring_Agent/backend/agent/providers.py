"""
providers.py — pluggable LLM provider layer enabling PER-INTERACTION model/API selection.

Every LLM-driven step (requirement scoring, vote synthesis, chat) accepts a `model_id`.
This module resolves that id against models.json, picks the right SDK/endpoint, reads the
API key from the environment (never from disk), and returns the model's text.

Supported providers: Anthropic, OpenAI, Azure OpenAI, and a keyless "mock" engine.
The mock id is handled specially by the engines (scoring/vote/chat) with deterministic,
knowledge-base-grounded logic, so the entire app runs with ZERO API keys for demos.

Design goals:
  * Fail soft: a missing SDK or key returns a clear error string, never crashes the server.
  * Provider-agnostic: callers only pass (system, user, model_id, expect_json).
  * Auditable: every response carries which provider/model produced it.
"""
from __future__ import annotations
import os
import json
import re
import time
from typing import Dict, Any, Tuple, Optional

from .knowledge import get_kb

MOCK_MODEL_ID = "mock"


# --------------------------------------------------------------------------- #
# Model resolution                                                            #
# --------------------------------------------------------------------------- #
def resolve_model(model_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (provider_dict, model_dict) for a model id, or raise ValueError."""
    kb = get_kb()
    for provider in kb.models["providers"]:
        for model in provider["models"]:
            if model["id"] == model_id:
                return provider, model
    raise ValueError(f"Unknown model id: {model_id!r}. See GET /api/models for valid ids.")


def is_mock(model_id: str) -> bool:
    return model_id == MOCK_MODEL_ID


def available_models() -> Dict[str, Any]:
    """
    Expose the registry to the UI, annotating each model with whether its API key is
    actually present in the environment (so the front-end can grey out unusable models).
    """
    kb = get_kb()
    out = {"default_model": kb.models["default_model"],
           "task_defaults": kb.models["task_defaults"], "providers": []}
    for p in kb.models["providers"]:
        key_env = p.get("api_key_env")
        key_present = True if key_env is None else bool(os.environ.get(key_env))
        out["providers"].append({
            "id": p["id"], "name": p["name"], "api_key_env": key_env,
            "key_present": key_present,
            "models": p["models"],
        })
    return out


# --------------------------------------------------------------------------- #
# JSON extraction helper                                                       #
# --------------------------------------------------------------------------- #
def extract_json(text: str) -> Any:
    """
    Robustly pull a JSON object/array out of a model response, tolerating code fences
    or leading prose. Raises ValueError if nothing parseable is found.
    """
    text = text.strip()
    # Strip ```json ... ``` fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced { ... } or [ ... ] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("No parseable JSON found in model response.")


def _is_transient(e: Exception) -> bool:
    """True for errors worth retrying (timeouts, rate limits, 5xx, connection drops)."""
    name = type(e).__name__.lower()
    if any(k in name for k in ("timeout", "connection", "ratelimit", "apiconnection",
                               "internalserver", "serviceunavailable", "overloaded")):
        return True
    status = getattr(e, "status_code", None) or getattr(e, "status", None)
    return status in (408, 409, 429, 500, 502, 503, 504, 529)


# --------------------------------------------------------------------------- #
# The client                                                                  #
# --------------------------------------------------------------------------- #
class LLMClient:
    """Thin wrapper around vendor SDKs. One instance can serve any model id."""

    def generate(self, system: str, user: str, model_id: str,
                 expect_json: bool = False, max_tokens: int = 4096,
                 temperature: float = 0.2) -> Dict[str, Any]:
        """
        Returns {"text": str, "provider": str, "model": str, "ok": bool, "error": str|None}.
        Callers that set expect_json should pass the text through extract_json().
        """
        if is_mock(model_id):
            # The mock is handled by the engines, not here. If something calls generate()
            # with the mock id, return a clear marker rather than hitting a network.
            return {"text": "", "provider": "mock", "model": "mock",
                    "ok": False, "error": "mock model handled by engine, not provider"}

        provider, model = resolve_model(model_id)
        sdk = provider["sdk"]
        last = RuntimeError("generate: no attempt completed")  # defensive: never report NoneType
        for attempt in range(3):  # 1 try + 2 retries
            try:
                if sdk == "anthropic":
                    return self._anthropic(provider, model, system, user, expect_json, max_tokens, temperature)
                if sdk in ("openai", "openai_azure"):
                    return self._openai(provider, model, system, user, expect_json, max_tokens, temperature, azure=(sdk == "openai_azure"))
                return {"text": "", "provider": provider["id"], "model": model_id,
                        "ok": False, "error": f"Unsupported sdk {sdk!r}"}
            except Exception as e:  # fail soft — never take the server down over an API error
                last = e
                if not _is_transient(e) or attempt == 2:
                    break
                time.sleep(0.8 * (2 ** attempt))  # 0.8s, 1.6s
        return {"text": "", "provider": provider["id"], "model": model.get("id", model_id),
                "ok": False, "error": f"{type(last).__name__}: {last}"}

    # ---- Anthropic ---------------------------------------------------------- #
    def _anthropic(self, provider, model, system, user, expect_json, max_tokens, temperature):
        key = os.environ.get(provider["api_key_env"])
        if not key:
            return {"text": "", "provider": "anthropic", "model": model["id"], "ok": False,
                    "error": f"Missing {provider['api_key_env']} in environment."}
        import anthropic  # imported lazily so the app runs without the SDK installed
        client = anthropic.Anthropic(api_key=key)
        if expect_json:
            user = user + "\n\nReturn ONLY valid JSON. No prose, no code fences."
        kwargs = dict(
            model=model["id"],
            system=system,
            max_tokens=min(max_tokens, model.get("max_output_tokens", max_tokens)),
            messages=[{"role": "user", "content": user}],
        )
        # Opus 4.7/4.8 removed sampling params (temperature/top_p/top_k) — sending them 400s.
        # Models flagged sampling_params:false omit temperature and use adaptive thinking so
        # reasoning doesn't leak into the (often JSON) response.
        if model.get("sampling_params", True):
            kwargs["temperature"] = temperature
        else:
            kwargs["thinking"] = {"type": "adaptive"}
        resp = client.messages.create(**kwargs)
        text = "".join(block.text for block in resp.content
                       if getattr(block, "type", "") == "text")
        return {"text": text, "provider": "anthropic", "model": model["id"], "ok": True, "error": None}

    # ---- OpenAI / Azure OpenAI --------------------------------------------- #
    def _openai(self, provider, model, system, user, expect_json, max_tokens, temperature, azure=False):
        key = os.environ.get(provider["api_key_env"])
        if not key:
            return {"text": "", "provider": provider["id"], "model": model["id"], "ok": False,
                    "error": f"Missing {provider['api_key_env']} in environment."}
        if azure:
            from openai import AzureOpenAI
            endpoint = os.environ.get(provider.get("endpoint_env", ""), "")
            if not endpoint:
                return {"text": "", "provider": provider["id"], "model": model["id"], "ok": False,
                        "error": f"Missing {provider.get('endpoint_env')} in environment."}
            client = AzureOpenAI(api_key=key, azure_endpoint=endpoint, api_version="2024-06-01")
        else:
            from openai import OpenAI
            client = OpenAI(api_key=key)
        kwargs = dict(
            model=model["id"],
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=min(max_tokens, model.get("max_output_tokens", max_tokens)),
            temperature=temperature,
        )
        if expect_json:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        return {"text": text, "provider": provider["id"], "model": model["id"], "ok": True, "error": None}


# Module-level singleton client (stateless, safe to share).
client = LLMClient()
