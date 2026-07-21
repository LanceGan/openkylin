"""Ollama HTTP API backend for local LLM inference."""

from __future__ import annotations


class ModelUnavailableError(RuntimeError):
    """Raised when the Ollama backend cannot be reached or returns an error."""


class OllamaBackend:
    """Local inference backend that communicates with Ollama's HTTP API.

    Uses the ``/api/chat`` endpoint with ``stream=False`` and a configurable
    temperature.  Connection errors are wrapped in ``ModelUnavailableError``.
    """

    def __init__(
        self,
        model: str = "qwen2.5-coder:7b-instruct-q4_k_m",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.base_url = base_url

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.0,
    ) -> str:
        """Send a chat completion request and return the model's text reply.

        Args:
            system_prompt: System-level instruction for the model.
            user_message: The user query / pre-loaded data.
            temperature: Sampling temperature (0.0 = deterministic).

        Returns:
            The ``content`` field from the assistant message.

        Raises:
            ModelUnavailableError: If the HTTP request fails or the response
                is malformed.
        """
        import json as _json
        from typing import Any

        import requests

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }

        try:
            r = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120,
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            raise ModelUnavailableError(
                f"Ollama backend unreachable at {self.base_url}: {exc}"
            ) from exc

        try:
            body: dict[str, Any] = r.json()
            return str(body["message"]["content"])
        except (KeyError, TypeError, ValueError, _json.JSONDecodeError) as exc:
            raise ModelUnavailableError(
                f"Unexpected response shape from Ollama: {exc}"
            ) from exc
