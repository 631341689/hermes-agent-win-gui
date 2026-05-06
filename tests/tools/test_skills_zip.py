"""Tests for tools/skills_zip.py — ZIP layout normalization and safety."""

import io
import zipfile

import pytest

from tools.skills_zip import (
    extract_skill_files_from_zip,
    list_skill_install_categories,
    resolve_install_skill_name,
)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


SKILL_MD_MIN = b"""---
name: demo-skill
description: Test skill.
---

# Demo
"""


class TestExtractZip:
    def test_flat_skill_md_at_root(self):
        z = _zip_bytes({"SKILL.md": SKILL_MD_MIN, "notes.txt": b"hello"})
        files = extract_skill_files_from_zip(z)
        assert set(files.keys()) == {"SKILL.md", "notes.txt"}
        assert files["notes.txt"] == "hello"

    def test_single_top_level_folder_stripped(self):
        z = _zip_bytes(
            {
                "my-skill/SKILL.md": SKILL_MD_MIN,
                "my-skill/sub/x.md": b"# x",
            }
        )
        files = extract_skill_files_from_zip(z)
        assert set(files.keys()) == {"SKILL.md", "sub/x.md"}

    def test_rejects_parent_path(self):
        z = _zip_bytes({"../evil.txt": b"x"})
        with pytest.raises(ValueError, match="Unsafe|skill"):
            extract_skill_files_from_zip(z)

    def test_rejects_two_skill_md_trees(self):
        z = _zip_bytes(
            {
                "a/SKILL.md": SKILL_MD_MIN,
                "b/SKILL.md": SKILL_MD_MIN,
            }
        )
        with pytest.raises(ValueError, match="only one skill"):
            extract_skill_files_from_zip(z)

    def test_rejects_file_outside_prefix(self):
        z = _zip_bytes(
            {
                "skill/SKILL.md": SKILL_MD_MIN,
                "other/readme.md": b"oops",
            }
        )
        with pytest.raises(ValueError, match="outside skill folder"):
            extract_skill_files_from_zip(z)


class TestListSkillCategories:
    def test_lists_category_buckets_only(self, tmp_path, monkeypatch):
        skills = tmp_path / "skills"
        skills.mkdir()
        # Top-level skill (has SKILL.md here) — not a category
        (skills / "flat-skill" / "SKILL.md").parent.mkdir(parents=True)
        (skills / "flat-skill" / "SKILL.md").write_bytes(SKILL_MD_MIN)
        # Category bucket: no SKILL.md at bucket root, nested skill
        bucket = skills / "my-cat" / "nested" / "SKILL.md"
        bucket.parent.mkdir(parents=True)
        bucket.write_bytes(SKILL_MD_MIN)
        monkeypatch.setattr("tools.skills_zip.SKILLS_DIR", skills)
        assert list_skill_install_categories() == ["my-cat"]


class TestResolveName:
    def test_from_frontmatter(self):
        text = SKILL_MD_MIN.decode("utf-8")
        assert resolve_install_skill_name(text, "") == "demo-skill"

    def test_override_wins(self):
        text = "---\nname: old-name\n---\n"
        assert resolve_install_skill_name(text, "new-name") == "new-name"

    def test_invalid_override(self):
        with pytest.raises(ValueError, match="Invalid skill name"):
            resolve_install_skill_name("---\nname: ok\n---\n", "99bad")
