# Author: Stian Skogbrott
# License: Apache-2.0
"""Azure OpenAI adapter for REMORA.

Connects to Azure-hosted OpenAI models via private endpoint or public endpoint.
Supports both API key and Managed Identity (Entra ID) authentication.

Requirements:
    pip install openai
"""
from __future__ import annotations

from remora.adapters.llm import LLMAdapter, LLMResponse


class AzureOpenAIAdapter(LLMAdapter):
    """Adapter for Azure OpenAI Service.

    Parameters
    ----------
    endpoint:
        Azure OpenAI resource endpoint (e.g. https://your-resource.openai.azure.com).
    deployment:
        Deployment name (e.g. 'gpt-4o').
    api_key:
        API key. If None, uses DefaultAzureCredential (Managed Identity).
    api_version:
        Azure OpenAI API version.
    """

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_key: str | None = None,
        api_version: str = "2024-08-01-preview",
    ):
        self._endpoint = endpoint
        self._deployment = deployment
        self._api_key = api_key
        self._api_version = api_version

    def complete(self, prompt: str, *, max_tokens: int = 512, temperature: float = 0.0) -> LLMResponse:
        import openai

        if self._api_key:
            client = openai.AzureOpenAI(
                azure_endpoint=self._endpoint,
                api_key=self._api_key,
                api_version=self._api_version,
            )
        else:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            client = openai.AzureOpenAI(
                azure_endpoint=self._endpoint,
                azure_ad_token=token.token,
                api_version=self._api_version,
            )

        resp = client.chat.completions.create(
            model=self._deployment,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            text=choice.message.content or "",
            model=f"azure/{self._deployment}",
            usage_prompt_tokens=usage.prompt_tokens if usage else 0,
            usage_completion_tokens=usage.completion_tokens if usage else 0,
        )

    def model_id(self) -> str:
        return f"azure-openai/{self._deployment}"
