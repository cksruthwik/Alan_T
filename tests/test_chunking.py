from alan_t.core.knowledge.chunking import chunk_file, chunk_markdown

DOC = """# Alan_T design

Intro paragraph about the assistant, which is a self-hosted single-user system
with persistent memory, retrieval over the user's own files, and a Telegram
gateway for remote access from the phone at any time of day.

## Memory

Memory is the product. It uses Mem0 over Postgres with recall scoring
that combines embedding similarity, recency decay, access frequency, and a
kind prior so preferences and active goals always stay in reach of recall.

## Knowledge

RAG over the user's own files with citations. Sources are mirrored into ai-vfs,
chunked on heading boundaries, embedded through the LiteLLM seam, and fused with
a keyword leg using reciprocal rank fusion before answer generation happens.
"""


def test_heading_chunks_with_context_headers():
    chunks = chunk_markdown("vfs://notes/design.md", DOC, "notes", "abc123")
    assert len(chunks) >= 2
    memory_chunk = next(c for c in chunks if "Mem0" in c.body)
    assert memory_chunk.body.startswith("[notes] design.md > Alan_T design > Memory")
    assert memory_chunk.payload["mount"] == "notes"
    assert memory_chunk.payload["content_hash"] == "abc123"


def test_deterministic_ids():
    a = chunk_markdown("vfs://notes/design.md", DOC, "notes", "h1")
    b = chunk_markdown("vfs://notes/design.md", DOC, "notes", "h2")
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]


def test_unsupported_type_is_typed_skip():
    assert chunk_file("vfs://notes/image.png", b"\x89PNG", "h") is None


def test_plain_text_file():
    chunks = chunk_file("vfs://notes/todo.txt", b"buy milk\n\ncall mom", "h")
    assert chunks and chunks[0].vpath == "vfs://notes/todo.txt"
