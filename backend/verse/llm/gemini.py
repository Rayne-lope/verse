from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from verse.config import LLMConfig
from verse.llm.base import LLMAdapter, LLMResponse
from verse.persistence.keychain import get_api_key


GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_MODEL = "gemini-3.5-flash"


class GeminiAdapter(LLMAdapter):
    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config or LLMConfig(provider="gemini")
        self.model = _effective_gemini_model(self.config)
        self.base_url = _effective_gemini_base_url(self.config)
        self.api_key = api_key
        self._client = client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        return await asyncio.to_thread(self._chat_sync, messages, tools)

    def _chat_sync(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        try:
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "google-genai is required for GeminiAdapter. Install backend dependencies first."
            ) from exc

        system_instruction, contents = _convert_messages(messages)
        config_kwargs: dict[str, Any] = {
            "temperature": self.config.temperature,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        converted_tools = _convert_tools(tools)
        if converted_tools:
            config_kwargs["tools"] = converted_tools

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        text = _extract_text(response)
        tool_calls = _extract_tool_calls(response)
        return LLMResponse(text=text, tool_calls=tool_calls, raw=response)

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:
                raise RuntimeError(
                    "google-genai is required for GeminiAdapter. Install backend dependencies first."
                ) from exc

            api_key = (
                self.api_key
                or os.getenv("GEMINI_API_KEY")
                or get_api_key("gemini")
                or get_api_key("gemini_api_key")
            )
            if not api_key:
                raise RuntimeError("Gemini API key not found in env or Keychain")
            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(base_url=self.base_url),
            )
        return self._client


def _effective_gemini_model(config: LLMConfig) -> str:
    model = (config.model or "").strip()
    if not model or model == LLMConfig.model:
        return GEMINI_DEFAULT_MODEL
    return model


def _effective_gemini_base_url(config: LLMConfig) -> str:
    base_url = (config.base_url or "").strip()
    if not base_url or base_url == LLMConfig.base_url:
        return GEMINI_API_BASE_URL
    return base_url


def _convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[Any]]:
    from google.genai import types

    tool_names_by_id: dict[str, str] = {}
    for message in messages:
        for tool_call in message.get("tool_calls") or []:
            tool_id = tool_call.get("id")
            name = tool_call.get("function", {}).get("name")
            if tool_id and name:
                tool_names_by_id[str(tool_id)] = str(name)

    system_parts: list[str] = []
    contents: list[Any] = []
    for message in messages:
        role = str(message.get("role") or "")
        content = message.get("content")

        if role == "system":
            if content:
                system_parts.append(str(content))
            continue

        if role == "tool":
            tool_id = str(message.get("tool_call_id") or "")
            name = tool_names_by_id.get(tool_id) or "tool_result"
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=tool_id or None,
                                name=name,
                                response={"result": str(content or "")},
                            )
                        )
                    ],
                )
            )
            continue

        gemini_role = "model" if role == "assistant" else "user"
        parts = []
        if content:
            parts.append(types.Part.from_text(text=str(content)))
        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function", {})
            name = function.get("name")
            if not name:
                continue
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(
                        id=tool_call.get("id"),
                        name=str(name),
                        args=_parse_arguments(function.get("arguments")),
                    )
                )
            )
        if parts:
            contents.append(types.Content(role=gemini_role, parts=parts))

    return "\n\n".join(system_parts), contents


def _parse_arguments(raw_arguments: Any) -> dict[str, Any]:
    if raw_arguments is None or raw_arguments == "":
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    try:
        parsed = json.loads(str(raw_arguments))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _convert_tools(tools: list[dict[str, Any]] | None) -> list[Any]:
    if not tools:
        return []
    from google.genai import types

    declarations = []
    for definition in tools:
        function = definition.get("function", {})
        name = function.get("name")
        if not name:
            continue
        parameters = function.get("parameters") or {"type": "object", "properties": {}}
        declarations.append(
            types.FunctionDeclaration(
                name=str(name),
                description=function.get("description", ""),
                parameters=_schema_to_gemini(parameters),
            )
        )
    return [types.Tool(function_declarations=declarations)] if declarations else []


def _schema_to_gemini(schema: dict[str, Any]) -> Any:
    from google.genai import types

    schema_type = schema.get("type", "string")
    type_map = {
        "string": types.Type.STRING,
        "number": types.Type.NUMBER,
        "integer": types.Type.INTEGER,
        "boolean": types.Type.BOOLEAN,
        "object": types.Type.OBJECT,
        "array": types.Type.ARRAY,
    }
    properties = {
        key: _schema_to_gemini(value)
        for key, value in (schema.get("properties") or {}).items()
        if isinstance(value, dict)
    }
    items = schema.get("items")
    return types.Schema(
        type=type_map.get(schema_type, types.Type.STRING),
        description=schema.get("description"),
        enum=schema.get("enum"),
        properties=properties or None,
        required=schema.get("required"),
        items=_schema_to_gemini(items) if isinstance(items, dict) else None,
    )


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text:
        return text
    chunks: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text:
                chunks.append(part_text)
    return "".join(chunks)


def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for index, part in enumerate(getattr(content, "parts", None) or []):
            function_call = getattr(part, "function_call", None) or getattr(part, "functionCall", None)
            if function_call is None:
                continue
            name = getattr(function_call, "name", "") or ""
            args = getattr(function_call, "args", None) or {}
            call_id = getattr(function_call, "id", None) or f"gemini_call_{index}"
            tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": str(name),
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                }
            )
    return tool_calls
