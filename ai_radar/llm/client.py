"""OpenAI-compatible LLM client with strict JSON + Pydantic validation."""
from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_radar.config import get_config, mask_secret
from ai_radar.llm import prompts
from ai_radar.llm.schemas import (
    ChangePointAnalysis,
    CoverageAssessment,
    ProfileFactExtraction,
)
from ai_radar.models import LlmResponseCache, LlmUsageLog
from ai_radar.utils import dump_json, sha256_hex

log = logging.getLogger(__name__)

T = BaseModel

TModel = TypeVar("TModel", bound=BaseModel)

_MAX_RETRIES = 2


class LlmError(RuntimeError):
    pass


class LlmClient:
    """Unified LLM client (section 十一)."""

    def __init__(self, session: Session | None = None) -> None:
        cfg = get_config().llm
        if not cfg.base_url or not cfg.api_key:
            log.warning(
                "LlmClient initialized with incomplete config (base_url=%s key=%s)",
                cfg.base_url or "<empty>",
                mask_secret(cfg.api_key),
            )
        self.base_url = cfg.base_url
        self.api_key = cfg.api_key
        self.model = cfg.model
        self.timeout = cfg.timeout_seconds
        self.session = session

    # ---------- public API ----------

    def extract_change_points(self, item_payload: dict) -> ChangePointAnalysis:
        prompt = prompts.render_analyze(
            source_name=item_payload["source_name"],
            title=item_payload["title"],
            url=item_payload["url"],
            published_at=item_payload["published_at"],
            content=item_payload["content"],
        )
        return self._call_structured(prompt, ChangePointAnalysis, "analyze_change_point")

    def extract_profile_facts(self, file_path: str, markdown: str) -> ProfileFactExtraction:
        prompt = prompts.render_extract_facts(file_path, markdown)
        return self._call_structured(prompt, ProfileFactExtraction, "extract_profile_facts")

    def assess_coverage(self, payload: dict) -> CoverageAssessment:
        prompt = prompts.render_assess_coverage(
            title=payload["title"],
            summary=payload["summary"],
            why_it_matters=payload["why_it_matters"],
            topic=payload["topic"],
            occurred_at=payload["occurred_at"],
            facts_block=payload["facts_block"],
        )
        return self._call_structured(prompt, CoverageAssessment, "assess_coverage")

    # ---------- internal ----------

    def _call_structured(
        self, prompt: str, model_cls: type[TModel], operation: str
    ) -> TModel:
        cache_key = sha256_hex(f"{operation}\n{self.model}\n{prompt}")
        cached = self._cache_get(cache_key)
        if cached is not None:
            try:
                data = json.loads(cached.response_json)
                result = model_cls.model_validate(data)
                self._record_usage(
                    operation=operation,
                    input_tokens=0,
                    output_tokens=0,
                    input_chars=len(prompt),
                    output_chars=len(cached.response_json),
                    estimated=False,
                    cache_hit=True,
                )
                return result
            except (json.JSONDecodeError, ValidationError):
                log.warning("Ignoring invalid cached LLM response %s", cache_key[:12])

        raw, usage = self._chat(prompt)
        cleaned = _strip_code_fences(raw)
        data = _parse_json_lenient(cleaned)
        if not isinstance(data, dict):
            raise LlmError(f"LLM did not return a JSON object: {cleaned[:200]}")
        result = _validate_structured(model_cls, data)
        self._cache_put(cache_key, operation, result.model_dump())
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        estimated = not bool(input_tokens or output_tokens)
        if estimated:
            # Mixed Chinese/English prompts average roughly two characters per
            # token.  Marking the row as estimated keeps the UI honest.
            input_tokens = max(1, round(len(prompt) / 2))
            output_tokens = max(1, round(len(raw) / 2))
        self._record_usage(
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_chars=len(prompt),
            output_chars=len(raw),
            estimated=estimated,
            cache_hit=False,
        )
        return result

    def _chat(self, user_prompt: str) -> tuple[str, dict]:
        if not self.base_url or not self.api_key:
            raise LlmError("LLM_BASE_URL or LLM_API_KEY is not configured")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompts.SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    raise LlmError(
                        f"LLM HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                data = resp.json()
                return data["choices"][0]["message"]["content"] or "", data.get("usage") or {}
            except (httpx.HTTPError, KeyError, LlmError) as exc:
                last_exc = exc
                log.warning("LLM call failed (attempt %d): %s", attempt + 1, exc)
        raise LlmError(f"LLM call failed after retries: {last_exc}")

    def _cache_get(self, cache_key: str) -> LlmResponseCache | None:
        if self.session is None:
            return None
        return self.session.execute(
            select(LlmResponseCache).where(LlmResponseCache.cache_key == cache_key)
        ).scalar_one_or_none()

    def _cache_put(self, cache_key: str, operation: str, response: dict) -> None:
        if self.session is None:
            return
        if self._cache_get(cache_key) is not None:
            return
        self.session.add(
            LlmResponseCache(
                cache_key=cache_key,
                operation=operation,
                model_name=self.model,
                response_json=dump_json(response),
            )
        )
        self.session.flush()

    def _record_usage(
        self,
        *,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        input_chars: int,
        output_chars: int,
        estimated: bool,
        cache_hit: bool,
    ) -> None:
        if self.session is None:
            return
        self.session.add(
            LlmUsageLog(
                operation=operation,
                model_name=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_chars=input_chars,
                output_chars=output_chars,
                estimated=estimated,
                cache_hit=cache_hit,
            )
        )
        self.session.flush()


# ---------- helpers ----------

def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (with optional language tag) and closing fence.
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_json_lenient(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract the first {...} or [...] block.
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
    return None


def _validate_structured(model_cls: type[TModel], data: dict) -> TModel:
    """Validate once.

    HTTP retries happen in ``_chat``. Re-validating the exact same dictionary
    cannot repair it and previously produced three identical warning blocks.
    """
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        log.warning("LLM JSON validation failed: %s", exc)
        raise LlmError(f"LLM output failed Pydantic validation: {exc}") from exc
