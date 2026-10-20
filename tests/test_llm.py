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


def test_complete_omits_empty_tools():
    with patch("llm.client.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok", "role": "assistant"}, "finish_reason": "stop"}]
        }
        mock_post.return_value = mock_response

        LLMClient(model="small-model").complete(system="s", messages=[{"role": "user", "content": "Hi"}], tools=[])

        payload = mock_post.call_args.kwargs["json"]
        assert payload["model"] == "small-model"
        assert "tools" not in payload and "tool_choice" not in payload


def test_parse_json_text_strips_fences():
    from llm.client import parse_json_text
    assert parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
