"""LocalFiles contract: scan filters, change detection, and the read boundary."""

import pytest
import yaml

from alan_t.adapters.local_files import LocalFiles


@pytest.fixture
def files(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "alan.md").write_text("# Alan\n\nAlan_T uses a supervisor.")
    (notes / "secret.env").write_text("KEY=x")
    (tmp_path / "outside.md").write_text("not yours")
    (notes / "escape.md_link").symlink_to(tmp_path / "outside.md")

    cfg = tmp_path / "mounts.yaml"
    cfg.write_text(yaml.safe_dump({
        "mounts": {"notes": {"path": str(notes), "include": ["**/*.md"]}},
        "exclude_global": ["**/.git/**", "**/*.env"],
    }))
    return LocalFiles(cfg), notes


async def test_scan_filters_and_hashes(files):
    lf, notes = files
    sources = await lf.scan()
    assert [s.vpath for s in sources] == ["vfs://notes/alan.md"]  # .env + symlink excluded
    first_hash = sources[0].content_hash

    # unchanged rescan → same hash (served from the mtime/size cache)
    assert (await lf.scan())[0].content_hash == first_hash

    (notes / "alan.md").write_text("# Alan\n\nEdited.")
    assert (await lf.scan())[0].content_hash != first_hash


async def test_read_and_boundary(files):
    lf, _ = files
    assert b"supervisor" in await lf.read("vfs://notes/alan.md")

    with pytest.raises(PermissionError):  # traversal out of the mount
        await lf.read("vfs://notes/../outside.md")
    with pytest.raises(PermissionError):  # symlink escaping the mount
        await lf.read("vfs://notes/escape.md_link")
    with pytest.raises(PermissionError):  # excluded by filter, even with a direct vpath
        await lf.read("vfs://notes/secret.env")
    with pytest.raises(FileNotFoundError):
        await lf.read("vfs://nope/x.md")


async def test_missing_mount_dir_degrades(tmp_path):
    cfg = tmp_path / "mounts.yaml"
    cfg.write_text(yaml.safe_dump({"mounts": {"gone": {"path": str(tmp_path / "missing")}}}))
    assert await LocalFiles(cfg).scan() == []  # warns, never crashes ingestion
