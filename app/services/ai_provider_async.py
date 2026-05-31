import abc
import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
from openai import AsyncOpenAI

class AIProvider(abc.ABC):
    @abc.abstractmethod
    async def extract_structured_data(self, prompt: str) -> str:
        pass

class OpenAIProviderAsync(AIProvider):
    def __init__(self, model: str = "gpt-4.1-mini"):
        # Pre-configured AsyncOpenAI client
        self.client = AsyncOpenAI()
        self.model = model

    async def extract_structured_data(self, prompt: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

class AICircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "CLOSED" # CLOSED, OPEN, HALF_OPEN

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"
            logging.error("AI Circuit Breaker is now OPEN")

    def record_success(self):
        self.failures = 0
        self.state = "CLOSED"

    def can_execute(self) -> bool:
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        return True

class ResilientAIWrapperAsync:
    def __init__(self, provider: AIProvider):
        self.provider = provider
        self.circuit_breaker = AICircuitBreaker()

    async def extract(self, prompt: str, timeout: float = 10.0, retries: int = 3) -> Optional[str]:
        if not self.circuit_breaker.can_execute():
            logging.warning("AI Circuit Breaker preventing execution")
            return None

        for attempt in range(retries):
            try:
                result = await asyncio.wait_for(
                    self.provider.extract_structured_data(prompt),
                    timeout=timeout
                )
                self.circuit_breaker.record_success()
                return result
            except Exception as e:
                logging.error(f"AI Provider attempt {attempt + 1} failed: {e}")
                if attempt == retries - 1:
                    self.circuit_breaker.record_failure()
                    return None
                # Exponential backoff
                await asyncio.sleep(1.0 * (2 ** attempt))
        return None
