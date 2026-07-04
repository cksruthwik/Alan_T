"""Contract test: real ai-vfs (sqlite + local blobs) mirror sync round-trip."""

import pytest
import yaml

from alan_t.adapters.vfs_files import VfsFiles


@pytest.fixture
async def vfs_setup(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "alan.md").write_text("# Alan\n\nAlan_T uses LangGraph.")
    (notes / "secret.env").write_text("KEY=x")

    cfg = tmp_path / "vfs.yaml"
    cfg.write_text(yaml.safe_dump({
        "mounts": {"notes": {"path": str(notes), "include": ["**/*.md"]}},
        "exclude_global": ["**/.git/**", "**/*.env"],
    }))
    files = VfsFiles(
        metadata_uri=f"sqlite:///{tmp_path}/aifs.db",
        blob_uri=f"file://{tmp_path}/blobs/",
        vfs_config_path=cfg,
    )
    await files.setup()
    yield files, notes
    await files.close()


async def test_sync_read_and_exclusions(vfs_setup):
    files, notes = vfs_setup
    changed = await files.sync_mounts()
    assert changed == ["vfs://notes/alan.md"]  # .env excluded — security boundary

    data = await files.read("vfs://notes/alan.md")
    assert b"LangGraph" in data

    # unchanged re-sync costs nothing
    assert await files.sync_mounts() == []

    # edit → one changed path; delete → tombstone
    (notes / "alan.md").write_text("# Alan\n\nNow with pgvector.")
    assert await files.sync_mounts() == ["vfs://notes/alan.md"]
    (notes / "alan.md").unlink()
    assert await files.sync_mounts() == ["vfs://notes/alan.md"]
    assert await files.list_sources() == []
