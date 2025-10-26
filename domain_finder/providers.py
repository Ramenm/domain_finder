import os
import time
import random
from typing import List, Optional, Dict, Any

import requests
from dotenv import load_dotenv

from .prompt_templates import build_prompt

load_dotenv()


class LLMProviderError(RuntimeError):
    pass


class BaseProvider:
    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        timeout: float = 30.0,
        retries: int = 3,
        backoff_min: float = 1.0,
        backoff_max: float = 3.0,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.retries = retries
        self.backoff_min = backoff_min
        self.backoff_max = backoff_max

    def _post(self, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code == 429:
                    # Rate limited — backoff and retry.
                    delay = random.uniform(self.backoff_min, self.backoff_max) * attempt
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:  # noqa: BLE001
                last_exc = e
                delay = random.uniform(self.backoff_min, self.backoff_max) * attempt
                time.sleep(delay)
        raise LLMProviderError(f"LLM request failed after {self.retries} attempts: {last_exc}")

    def generate_domains(
        self,
        topic: str,
        tlds: List[str],
        count: int,
        language: str = "ru",
        min_len: int = 4,
        max_len: int = 15,
    ) -> str:
        """
        Возвращает сырой текст из LLM (без парсинга доменов).
        """
        prompt = build_prompt(topic, tlds, count, language=language, min_len=min_len, max_len=max_len)
        return self._generate_with_prompt(prompt)

    # To be implemented by subclasses
    def _generate_with_prompt(self, prompt: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class Chat01Provider(BaseProvider):
    """
    Провайдер chat01.ai
    """

    def __init__(
        self,
        model: str = "gpt-5-thinking",
        temperature: float = 0.7,
        timeout: float = 60.0,
        retries: int = 4,
    ) -> None:
        super().__init__(model=model, temperature=temperature, timeout=timeout, retries=retries)
        self.api_key = os.getenv("API_KEY_CHAT01")
        if not self.api_key:
            raise LLMProviderError(
                "Не найден API_KEY_CHAT01 в окружении (.env). Укажите ключ для chat01."
            )
        self.url = "https://chat01.ai/v1/chat/completions"

    def _generate_with_prompt(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }
        data = self._post(self.url, headers, payload)
        # chat01 формат похож на OpenAI: choices[0].message.content
        try:
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            raise LLMProviderError(f"Неожиданный формат ответа chat01: {e}; raw={data!r}")


class OpenRouterProvider(BaseProvider):
    """
    Провайдер openrouter.ai
    """

    def __init__(
        self,
        model: str = "google/gemini-2.0-flash-lite-preview-02-05:free",
        temperature: float = 0.7,
        timeout: float = 30.0,
        retries: int = 3,
    ) -> None:
        super().__init__(model=model, temperature=temperature, timeout=timeout, retries=retries)
        self.api_key = os.getenv("API_KEY_OPENROUTER")
        if not self.api_key:
            raise LLMProviderError(
                "Не найден API_KEY_OPENROUTER в окружении (.env). Укажите ключ для OpenRouter "
                "или используйте провайдера chat01."
            )
        self.url = "https://openrouter.ai/api/v1/chat/completions"

    def _generate_with_prompt(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }
        data = self._post(self.url, headers, payload)
        try:
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            raise LLMProviderError(f"Неожиданный формат ответа OpenRouter: {e}; raw={data!r}")
