"""Prompt templates: versioned Jinja2 artifacts, loaded once, immutable (PROMPTS.md §1)."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template: str, **kwargs) -> str:
    return _env.get_template(template).render(**kwargs)
