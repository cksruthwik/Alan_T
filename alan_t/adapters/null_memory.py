"""No-op MemoryStore for M0 — replaced by the Mem0 adapter at M1."""

from alan_t.core.types import MemoryFact


class NullMemory:
    async def recall(self, query: str, limit: int = 10) -> list[MemoryFact]:
        return []

    async def remember(self, content: str, kind: str = "fact", source: str = "explicit") -> None:
        pass

    async def extract_from_turn(self, user_text: str, assistant_text: str) -> None:
        pass
