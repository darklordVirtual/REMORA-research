import json
import os
from unittest import mock

from remora.oracles.cloudflare import CloudflareOracle

def test_cloudflare_oracle_name_and_lora():
    oracle_no_lora = CloudflareOracle(model="@cf/meta/llama-3.3")
    assert oracle_no_lora.name == "cf/llama-3.3"

    oracle_lora = CloudflareOracle(model="@cf/meta/llama-3.3", lora="1234-abcd")
    assert oracle_lora.name == "cf/llama-3.3-lora"


@mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "mock_token", "CLOUDFLARE_ACCOUNT_ID": "mock_account"}, clear=True)
@mock.patch("urllib.request.urlopen")
def test_cloudflare_oracle_call(mock_urlopen):
    # Setup mock response
    mock_response = mock.MagicMock()
    mock_response.read.return_value = json.dumps({
        "choices": [{"message": {"content": "This is a CF response."}}]
    }).encode("utf-8")
    # Must enter context manager
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    oracle = CloudflareOracle(model="@cf/meta/test-model", lora="test-lora")

    response = oracle.ask("Test prompt")

    assert response.raw_text == "This is a CF response."
    assert response.cost_usd == 0.0
    assert response.latency_ms > 0

    # Ensure Lora was in payload
    req = mock_urlopen.call_args[0][0]
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["lora"] == "test-lora"
    assert payload["model"] == "@cf/meta/test-model"
