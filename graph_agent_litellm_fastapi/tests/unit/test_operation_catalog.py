from graph_agent_litellm.graph.operations import GraphOperationCatalog


def test_default_catalog_contains_core_operations() -> None:
    catalog = GraphOperationCatalog.default()

    assert catalog.get("list_users") is not None
    assert catalog.get("list_security_alerts") is not None
    assert catalog.get("update_user").read_only is False
    assert len(catalog.list()) >= 10

