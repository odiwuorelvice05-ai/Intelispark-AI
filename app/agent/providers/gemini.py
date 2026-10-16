"""Google Gemini implementation of the provider-neutral AIProvider interface."""
from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.agent.providers.base import AIProvider, ProviderError, ProviderUnavailable
from app.agent.types import AssistantTurn, ToolCall


class GeminiProvider(AIProvider):
    name = "gemini"
    API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str = "", model: str = "gemini-2.5-flash", client: Any = None) -> None:
        self.api_key = api_key.strip()
        self.model = model or "gemini-2.5-flash"
        # client is an optional injectable callable used by unit tests.
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self.api_key or self._client)

    @staticmethod
    def _schema(value: Any) -> Any:
        """Remove JSON Schema keys that Gemini's function declaration schema rejects."""
        if isinstance(value, list):
            return [GeminiProvider._schema(v) for v in value]
        if not isinstance(value, dict):
            return value
        unsupported = {"additionalProperties", "$schema", "$defs", "definitions", "title", "default"}
        return {
            k: (v.upper() if k == "type" and isinstance(v, str) else GeminiProvider._schema(v))
            for k, v in value.items() if k not in unsupported
        }

    @classmethod
    def _wire_tools(cls, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        declarations = []
        for tool in tools:
            declarations.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": cls._schema(tool.get("parameters") or {"type": "object", "properties": {}}),
            })
        return [{"functionDeclarations": declarations}] if declarations else []

    @staticmethod
    def _wire_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []

        def append_turn(role: str, parts: list[dict[str, Any]]) -> None:
            # Gemini expects one user turn containing all function responses for
            # a model turn; merge adjacent same-role content parts accordingly.
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": role, "parts": parts})

        for message in messages:
            role = message.get("role", "user")
            content = message.get("content") or ""
            if role == "system":
                if content:
                    system_parts.append(str(content))
                continue
            if role == "tool":
                try:
                    response = json.loads(content) if isinstance(content, str) else content
                except (json.JSONDecodeError, TypeError):
                    response = {"result": str(content)}
                if not isinstance(response, dict):
                    response = {"result": response}
                append_turn("user", [{"functionResponse": {
                    "name": message.get("name", "tool"), "response": response
                }}])
                continue
            parts: list[dict[str, Any]] = []
            for call in message.get("tool_calls") or []:
                parts.append({"functionCall": {
                    "name": call["name"],
                    "args": call.get("arguments") or {},
                }})
            if content:
                parts.insert(0, {"text": str(content)})
            if parts:
                append_turn("model" if role == "assistant" else "user", parts)
        return "\n\n".join(system_parts), contents

    @staticmethod
    def _parse(response: dict[str, Any], model: str, latency_ms: int) -> AssistantTurn:
        candidates = response.get("candidates") or []
        if not candidates:
            prompt_feedback = response.get("promptFeedback") or {}
            reason = prompt_feedback.get("blockReason") or "no candidates returned"
            raise ProviderError(f"Gemini returned no response: {reason}")
        candidate = candidates[0]
        parts = ((candidate.get("content") or {}).get("parts") or [])
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for index, part in enumerate(parts):
            if isinstance(part.get("text"), str):
                text_parts.append(part["text"])
            function_call = part.get("functionCall")
            if isinstance(function_call, dict) and function_call.get("name"):
                args = function_call.get("args") or {}
                err = None
                if not isinstance(args, dict):
                    args, err = {}, "arguments were not a JSON object"
                calls.append(ToolCall(
                    id=f"gemini-call-{index}-{function_call['name']}",
                    name=function_call["name"],
                    arguments=args,
                    arguments_error=err,
                ))
        usage = response.get("usageMetadata") or {}
        return AssistantTurn(
            content="".join(text_parts),
            tool_calls=calls,
            finish_reason=str(candidate.get("finishReason") or ""),
            usage={
                "prompt_tokens": int(usage.get("promptTokenCount") or 0),
                "completion_tokens": int(usage.get("candidatesTokenCount") or 0),
            },
            model=model,
            latency_ms=latency_ms,
        )

    def chat(self, messages, tools=None, *, tool_choice="auto", json_mode=False,
             max_tokens=700, temperature=0.2, timeout_s=15.0) -> AssistantTurn:
        if not self.enabled:
            raise ProviderUnavailable("Gemini is not configured")
        system, contents = self._wire_messages(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = self._wire_tools(tools)
            mode = {"auto": "AUTO", "any": "ANY", "none": "NONE"}.get(tool_choice, "AUTO")
            payload["toolConfig"] = {"functionCallingConfig": {"mode": mode}}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        started = time.monotonic()
        try:
            if self._client:
                response = self._client(payload=payload, timeout_s=timeout_s)
            else:
                url = f"{self.API_ROOT}/{quote(self.model, safe='')}:generateContent?key={quote(self.api_key, safe='')}"
                request = Request(url, data=json.dumps(payload).encode("utf-8"),
                                  headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(request, timeout=timeout_s) as result:
                    response = json.loads(result.read().decode("utf-8"))
        except HTTPError as exc:
            # Do not log request URLs or credentials; API keys are URL query parameters.
            raise ProviderError(f"Gemini request failed: HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Gemini request failed: {type(exc).__name__}") from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gemini request failed: {type(exc).__name__}") from exc
        return self._parse(response, self.model, int((time.monotonic() - started) * 1000))
