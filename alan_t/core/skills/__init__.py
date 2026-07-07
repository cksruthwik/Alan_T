"""Skill system (Docs_COMPLEX/ai/SKILLS.md) — the unit of reuse.

A skill = SKILL.md (frontmatter + instruction body) in a directory here.
Loaded once at startup, immutable, concurrently readable by the supervisor,
every agent, and MCP (the Shared Resource Layer, ADR-019).

Progressive disclosure: only name+description are ever in context at selection
time; the body loads when a skill is selected. Selection is deliberate —
supervisor at routing time, or an agent mid-turn — never ambient.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("alan_t.skills")

SKILLS_DIR = Path(__file__).parent


@dataclass
class Skill:
    name: str
    description: str
    body: str
    required_tools: list[str] = field(default_factory=list)
    role_hint: str = "CHAT"
    version: int = 1


def _parse(path: Path) -> Skill:
    text = path.read_text()
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front)
    return Skill(
        name=meta["name"],
        description=" ".join(str(meta["description"]).split()),
        body=body.strip(),
        required_tools=meta.get("required_tools", []),
        role_hint=meta.get("role_hint", "CHAT"),
        version=meta.get("version", 1),
    )


class SkillLibrary:
    def __init__(self, root: Path = SKILLS_DIR, registered_tools: set[str] | None = None):
        self._skills: dict[str, Skill] = {}
        for skill_md in sorted(root.glob("*/SKILL.md")):
            skill = _parse(skill_md)
            if registered_tools is not None:
                unknown = set(skill.required_tools) - registered_tools
                if unknown:
                    # SKILLS.md §5: a skill can't fire without its tools. Tools are
                    # conditional on adapter config (email creds etc.), so this is
                    # skip-not-crash: the skill simply isn't offered this run.
                    log.warning("skill '%s' skipped — needs unavailable tools: %s",
                                skill.name, sorted(unknown))
                    continue
            self._skills[skill.name] = skill
            log.info("skill loaded name=%s v%d", skill.name, skill.version)

    def menu(self) -> str:
        """The cheap selection menu: one line per skill, nothing more."""
        return "\n".join(f"- {s.name}: {s.description}" for s in self._skills.values())

    def names(self) -> list[str]:
        return list(self._skills)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def render(self, names: list[str]) -> list[str]:
        """Full bodies for selected skills — the SKILLS layer of the prompt."""
        out = []
        for n in names:
            if s := self._skills.get(n):
                out.append(f"## Skill: {s.name}\n{s.body}")
        return out
