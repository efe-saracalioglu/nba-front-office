from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import anyio
from mcp import Client


class ToolCallError(RuntimeError):
    pass


@dataclass
class ToolBox:
    server: Any = None
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.server is None:
            from mcp_server.server import mcp

            self.server = mcp

    async def _call(self, name: str, args: dict) -> Any:
        async with Client(self.server) as c:
            return await c.call_tool(name, args)

    async def _read(self, uri: str) -> str:
        async with Client(self.server) as c:
            result = await c.read_resource(uri)
        return "\n".join(getattr(part, "text", "") for part in result.contents)

    def read(self, uri: str) -> str:
        return anyio.run(self._read, uri)

    def call(self, name: str, **args) -> Any:
        clean = {k: v for k, v in args.items() if v is not None}
        start = time.perf_counter()
        result = anyio.run(self._call, name, clean)
        self.calls.append({"tool": name, "args": clean, "seconds": round(time.perf_counter() - start, 3),
                           "error": bool(result.is_error)})  # fmt: skip
        if result.is_error:
            raise ToolCallError(result.content[0].text if result.content else f"{name} failed")
        data = result.structured_content
        if isinstance(data, dict) and set(data) == {"result"}:
            return data["result"]
        return data
