"""Unit tests for OllamaBackend — mock HTTP, never touches a real server."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
import requests

from kylinbootlab.agent.backend import ModelUnavailableError, OllamaBackend

# -- Helpers -------------------------------------------------------------------


def _mock_response(json_data: dict[str, Any], status_code: int = 200) -> requests.Response:
    """Build a synthetic ``requests.Response`` with a ``.json()`` method."""
    response = requests.Response()
    response.status_code = status_code
    response._content = b""  # noqa: SLF001
    # Patch .json() onto the instance so it returns our data.
    # requests.Response is a C extension whose json attribute cannot be
    # assigned with normal property access, so we use object.__setattr__.
    object.__setattr__(response, "json", lambda **kwargs: json_data)
    return response


# -- Tests ---------------------------------------------------------------------


def test_chat_returns_content() -> None:
    """A successful /api/chat call returns the message content string."""
    backend = OllamaBackend(model="test-model", base_url="http://127.0.0.1:9999")
    expected = "Hello from the model!"

    with patch("requests.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"message": {"content": expected}}
        )

        result = backend.chat("system", "user")

    assert result == expected
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["model"] == "test-model"
    assert kwargs["json"]["stream"] is False


def test_chat_passes_temperature() -> None:
    """Temperature is forwarded in the options dict."""
    backend = OllamaBackend()

    with patch("requests.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"message": {"content": "ok"}}
        )

        backend.chat("sys", "user", temperature=0.7)

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["options"]["temperature"] == 0.7


def test_default_model_is_qwen() -> None:
    """The default constructor uses the expected Qwen model."""
    backend = OllamaBackend()
    assert backend.model == "qwen2.5-coder:7b-instruct-q4_k_m"
    assert backend.base_url == "http://localhost:11434"


def test_connection_error_wraps_to_model_unavailable() -> None:
    """Any requests.RequestException becomes ModelUnavailableError."""
    backend = OllamaBackend()

    with patch("requests.post") as mock_post:
        mock_post.side_effect = requests.ConnectionError("refused")

        with pytest.raises(ModelUnavailableError, match="unreachable"):
            backend.chat("sys", "user")


def test_malformed_response_raises_model_unavailable() -> None:
    """A response missing the 'message'/'content' keys raises ModelUnavailableError."""
    backend = OllamaBackend()

    with patch("requests.post") as mock_post:
        mock_post.return_value = _mock_response({"unexpected": "shape"})

        with pytest.raises(ModelUnavailableError, match="Unexpected response shape"):
            backend.chat("sys", "user")
