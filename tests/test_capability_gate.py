"""Capability gate (LLM_STRATEGY §5): bad model swaps die at startup."""

import pytest

from alan_t.adapters.model_router import ModelRouter


def _write(tmp_path, models: str, caps: str):
    m, c = tmp_path / "models.yaml", tmp_path / "capabilities.yaml"
    m.write_text(models)
    c.write_text(caps)
    return ModelRouter(m, c)


def test_gate_passes_on_capable_model(tmp_path):
    router = _write(
        tmp_path,
        "CHAT:\n  primary: { provider: groq, model: good }\n",
        "groq/good: [chat, streaming]\n",
    )
    router.verify()  # no raise


def test_gate_rejects_missing_capability(tmp_path):
    router = _write(
        tmp_path,
        "VISION:\n  primary: { provider: groq, model: blind }\n",
        "groq/blind: [chat]\n",
    )
    with pytest.raises(RuntimeError, match="vision_in"):
        router.verify()


def test_gate_rejects_unknown_model(tmp_path):
    router = _write(tmp_path, "CHAT:\n  primary: { provider: groq, model: mystery }\n", "{}")
    with pytest.raises(RuntimeError, match="can't verify"):
        router.verify()


def test_shipped_config_boots_clean():
    from alan_t.app.config import CONFIG_DIR, MODELS_YAML

    ModelRouter(MODELS_YAML, CONFIG_DIR / "capabilities.yaml").verify()
