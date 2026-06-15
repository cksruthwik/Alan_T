"""Mem0 adapter — implements MemoryPort over the mem0ai library.

Mem0's Memory class is synchronous; every call is offloaded to a thread so the
async event loop is never blocked. The adapter is constructed with a pre-built
Memory instance so bootstrap controls configuration without touching this file.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mem0 import Memory


class Mem0Provider:
    """MemoryPort backed by mem0ai (MEMORY_ARCHITECTURE.md)."""

    def __init__(self, memory: Memory) -> None:
        self._memory = memory

    async def add(self, user_id: str, content: str) -> None:
        await asyncio.to_thread(self._memory.add, content, user_id=user_id)

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        result = await asyncio.to_thread(
            self._memory.search,
            query,
            filters={"user_id": user_id},
            top_k=limit,
        )
        return [item["memory"] for item in result.get("results", [])]
