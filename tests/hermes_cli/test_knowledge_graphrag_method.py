"""Tests for GraphRAG ``auto`` method resolution (no graphrag package required)."""

from hermes_cli.knowledge_graphrag_method import resolve_graphrag_query_method


def test_resolve_explicit():
    m, tag = resolve_graphrag_query_method("anything", "global")
    assert m == "global" and tag == "explicit"


def test_resolve_auto_short_query_basic():
    m, tag = resolve_graphrag_query_method("短问题看看", "auto")
    assert m == "basic" and tag == "auto_short_query"


def test_resolve_auto_global_keyword_zh():
    m, tag = resolve_graphrag_query_method("请总结各章要点", "auto")
    assert m == "global"
    assert tag.startswith("auto_global_keyword")


def test_resolve_auto_global_keyword_en():
    m, tag = resolve_graphrag_query_method("Give an overview of the risks", "auto")
    assert m == "global"
    assert "overview" in tag or tag.startswith("auto_global_keyword")


def test_resolve_auto_default_local_long():
    q = (
        "张三在本项目中负责的具体接口定义与错误码是什么，"
        "请结合上下文说明其与支付网关模块的依赖关系与异常处理路径"
    )
    assert len(q) > 24
    m, tag = resolve_graphrag_query_method(q, "auto")
    assert m == "local"
    assert tag == "auto_default"


def test_resolve_invalid_explicit_falls_back(monkeypatch):
    m, tag = resolve_graphrag_query_method("x", "drift")
    assert m == "local"
    assert "invalid" in tag


def test_resolve_auto_disabled_config(monkeypatch):
    import hermes_cli.knowledge_graphrag_method as mod

    def _cfg():
        return {
            "knowledge": {
                "graphrag": {
                    "auto_method": {
                        "enabled": False,
                        "default_method": "global",
                    },
                },
            },
        }

    monkeypatch.setattr(mod, "load_config", _cfg)
    m, tag = mod.resolve_graphrag_query_method("any long query without global keywords", "auto")
    assert m == "global"
    assert "disabled" in tag
