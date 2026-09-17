import pytest
from unittest.mock import MagicMock, patch
from llm.client import LLMClient

def test_llm_client_complete_success():
    # Mock the LLMClient and the requests response
    with patch("llm.client.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "Hello world!",
                        "role": "assistant"
                    },
                    "finish_reason": "stop"
                }
            ]
        }
        mock_post.return_value = mock_response

        client = LLMClient()
        # Note: we need to mock LLM_API_KEY if it's not set
        with patch("llm.client.LLM_API_KEY", "test_key"):
            result = client.complete(
                system="You are a helper.",
                messages=[{"role": "user", "content": "Hi"}],
                tools=[]
            )

        assert result["text"] == "Hello world!"
        assert result["stop_reason"] == "end_turn"
        assert result["tool_calls"] == []

def test_llm_client_complete_json_success():
    with patch("llm.client.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"decision": "execute"}',
                        "role": "assistant"
                    },
                    "finish_reason": "stop"
                }
            ]
        }
        mock_post.return_value = mock_response

        client = LLMClient()
        with patch("llm.client.LLM_API_KEY", "test_key"):
            result = client.complete_json(
                system="JSON mode",
                messages=[{"role": "user", "content": "Test"}]
            )

        assert result == {"decision": "execute"}
