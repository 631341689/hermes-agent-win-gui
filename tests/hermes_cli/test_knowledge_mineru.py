"""MinerU hook for knowledge PDF uploads (disabled by default)."""

import json
from pathlib import Path


def _opts(**kw):
    base = {
        "enabled": False,
        "backend": "pipeline",
        "parse_method": "auto",
        "lang": "ch",
        "model_source": "huggingface",
        "local_models": {},
        "llm_aided_use_hermes_openai": True,
        "llm_aided_provider": "openai",
        "llm_aided_model_id": "",
    }
    base.update(kw)
    return base


def test_try_convert_disabled_noop(tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("hermes_cli.knowledge_mineru._mineru_options", lambda: _opts(enabled=False))
    from hermes_cli.knowledge_mineru import try_convert_uploaded_pdf

    assert try_convert_uploaded_pdf(pdf) is False
    assert pdf.is_file()


def test_try_convert_enabled_no_root_skips(tmp_path, monkeypatch):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("hermes_cli.knowledge_mineru._mineru_options", lambda: _opts(enabled=True))
    monkeypatch.setattr("hermes_cli.knowledge_mineru._mineru_root_from_config", lambda: "")
    from hermes_cli.knowledge_mineru import try_convert_uploaded_pdf

    assert try_convert_uploaded_pdf(pdf) is False
    assert pdf.is_file()


def test_try_convert_non_pdf(tmp_path, monkeypatch):
    p = tmp_path / "note.txt"
    p.write_text("hi", encoding="utf-8")
    monkeypatch.setattr("hermes_cli.knowledge_mineru._mineru_options", lambda: _opts(enabled=True))
    monkeypatch.setattr(
        "hermes_cli.knowledge_mineru._mineru_root_from_config",
        lambda: str(tmp_path),
    )
    from hermes_cli.knowledge_mineru import try_convert_uploaded_pdf

    assert try_convert_uploaded_pdf(p) is False


def test_hermes_llm_aided_config_uses_openai_env_and_top_model(monkeypatch):
    from hermes_cli import knowledge_mineru as km

    def _env(name: str) -> str:
        return {
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_BASE_URL": "https://example.com/v1",
        }.get(name, "")

    monkeypatch.setattr("hermes_cli.config.get_env_value", _env)
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"model": "gpt-4o-mini"})
    cfg = km._hermes_llm_aided_config_for_mineru(
        _opts(llm_aided_use_hermes_openai=True, llm_aided_provider="openai", llm_aided_model_id=""),
    )
    assert cfg is not None
    assert cfg["title_aided"]["api_key"] == "sk-test"
    assert cfg["title_aided"]["base_url"] == "https://example.com/v1"
    assert cfg["title_aided"]["model"] == "gpt-4o-mini"
    assert cfg["title_aided"]["enable"] is True


def test_hermes_llm_aided_config_prefers_llm_aided_model_id(monkeypatch):
    from hermes_cli import knowledge_mineru as km

    monkeypatch.setattr(
        "hermes_cli.config.get_env_value",
        lambda name: "sk-x" if name == "OPENAI_API_KEY" else "",
    )
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"model": "ignored"})
    cfg = km._hermes_llm_aided_config_for_mineru(_opts(llm_aided_model_id="my-title-model"))
    assert cfg["title_aided"]["model"] == "my-title-model"


def test_hermes_llm_aided_config_default_base_when_empty(monkeypatch):
    from hermes_cli import knowledge_mineru as km

    monkeypatch.setattr(
        "hermes_cli.config.get_env_value",
        lambda name: "sk-x" if name == "OPENAI_API_KEY" else "",
    )
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"model": "m"})
    cfg = km._hermes_llm_aided_config_for_mineru(_opts())
    assert cfg["title_aided"]["base_url"] == "https://api.openai.com/v1"


def test_hermes_llm_aided_config_deepseek_provider(monkeypatch):
    from hermes_cli import knowledge_mineru as km

    monkeypatch.setattr(
        "hermes_cli.config.get_env_value",
        lambda name: {
            "DEEPSEEK_API_KEY": "ds-key",
            "DEEPSEEK_BASE_URL": "",
        }.get(name, ""),
    )
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"model": "m"})
    cfg = km._hermes_llm_aided_config_for_mineru(_opts(llm_aided_provider="deepseek"))
    assert cfg["title_aided"]["api_key"] == "ds-key"
    assert cfg["title_aided"]["base_url"] == "https://api.deepseek.com/v1"


def test_hermes_llm_aided_config_top_level_model_dict_fallback(monkeypatch):
    from hermes_cli import knowledge_mineru as km

    monkeypatch.setattr(
        "hermes_cli.config.get_env_value",
        lambda name: "sk-x" if name == "OPENAI_API_KEY" else "",
    )
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"model": {"provider": "deepseek", "default": "deepseek-v4-pro"}},
    )
    cfg = km._hermes_llm_aided_config_for_mineru(_opts(llm_aided_model_id=""))
    assert cfg["title_aided"]["model"] == "deepseek-v4-pro"


def test_hermes_llm_aided_config_disabled_or_missing_key(monkeypatch):
    from hermes_cli import knowledge_mineru as km

    assert km._hermes_llm_aided_config_for_mineru(_opts(llm_aided_use_hermes_openai=False)) is None
    monkeypatch.setattr("hermes_cli.config.get_env_value", lambda _name: "")
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"model": "m"})
    assert km._hermes_llm_aided_config_for_mineru(_opts()) is None


def test_normalize_mineru_llm_aided_model_legacy_string():
    from hermes_cli import knowledge_mineru as km

    assert km._normalize_mineru_llm_aided_model({"llm_aided_model": "gpt-4o"}) == ("openai", "gpt-4o")


def test_normalize_mineru_llm_aided_model_dict():
    from hermes_cli import knowledge_mineru as km

    assert km._normalize_mineru_llm_aided_model(
        {"llm_aided_model": {"provider": "openai", "default": "gpt-4o-mini"}},
    ) == ("openai", "gpt-4o-mini")


def test_merge_local_models_env_overrides_yaml(monkeypatch, tmp_path):
    from hermes_cli import knowledge_mineru as km

    d = tmp_path / "pl"
    d.mkdir()
    yaml_pl = tmp_path / "from_yaml"
    yaml_pl.mkdir()
    monkeypatch.setenv("HERMES_MINERU_LOCAL_PIPELINE", str(d))
    merged = km._merge_local_models({"local_models": {"pipeline": str(yaml_pl)}})
    assert merged["pipeline"] == str(d.resolve())


def test_prepare_local_models_pipeline_backend(tmp_path):
    from hermes_cli import knowledge_mineru as km

    pl = tmp_path / "PDF-Extract-Kit"
    pl.mkdir()
    out = km._prepare_local_models_override({"pipeline": str(pl)}, "pipeline")
    assert out is not None
    assert out["pipeline"] == str(pl.resolve())
    assert out["vlm"] == ""


def test_prepare_local_models_vlm_required_for_vlm_backend(tmp_path):
    from hermes_cli import knowledge_mineru as km

    pl = tmp_path / "p"
    pl.mkdir()
    import pytest

    with pytest.raises(ValueError, match="local_models.vlm"):
        km._prepare_local_models_override({"pipeline": str(pl)}, "vlm-something")


def test_discover_local_models_from_mineru_json(monkeypatch, tmp_path):
    from hermes_cli import knowledge_mineru as km

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    pl = fake_home / "pipeline_kit"
    pl.mkdir()
    cfg = fake_home / "mineru.json"
    cfg.write_text(
        json.dumps({"models-dir": {"pipeline": str(pl), "vlm": ""}}),
        encoding="utf-8",
    )
    got = km._discover_local_models_from_user_mineru_json()
    assert got.get("pipeline") == str(pl.resolve())
    assert "vlm" not in got
