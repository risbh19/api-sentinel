import json

import pytest

from api_sentinel.inventory.parser import MAX_BYTES, InvalidDocument, parse


def spec() -> dict[str, object]:
    return {
        "openapi": "3.1.1",
        "info": {"title": "Synthetic", "version": "1"},
        "components": {
            "securitySchemes": {"session": {"type": "http", "scheme": "bearer"}},
            "pathItems": {"items": {"get": {"operationId": "readItems"}}},
        },
        "security": [{"session": []}, {}],
        "paths": {
            "/items": {"$ref": "#/components/pathItems/items"},
            "/status": {"get": {"security": []}},
        },
    }


def test_resolve_local_path_and_security_inheritance() -> None:
    result = parse(json.dumps(spec()).encode(), True)
    assert [(op.method, op.path, op.operation_id, op.security) for op in result.operations] == [
        ("GET", "/items", "readItems", [{"session": []}, {}]),
        ("GET", "/status", None, []),
    ]
    yaml = b"""openapi: 3.0.3
info: {title: Local, version: "1"}
paths:
  /ping:
    get:
      responses:
        200: {description: ok}
"""
    assert parse(yaml, False).operations[0].security is None


@pytest.mark.parametrize(
    "patch",
    [
        {"openapi": "3.2.0"},
        {"paths": []},
        {"info": {}},
        {"paths": {"/a/{id}": {}, "/a/{other}": {}}},
        {"paths": {"/a": {"$ref": "#/paths/~1a"}}},
        {"components": {"schemas": {"x": {"$ref": "https://example.invalid/contract"}}}},
        {"paths": {"/a": {"$ref": "#/missing"}}},
        {"paths": {"/a": {"get": {"security": [{"unknown": []}]}}}},
        {"paths": {"/a": {"get": {"responses": {"200": {}}}}}},
        {"paths": {"/a": {"$ref": "file:///local-contract"}}},
    ],
)
def test_unsupported_inputs_do_not_echo_the_document(patch: dict[str, object]) -> None:
    with pytest.raises(InvalidDocument) as error:
        parse(json.dumps({**spec(), **patch}).encode(), True)
    assert "example.invalid" not in str(error.value)


@pytest.mark.parametrize(
    ("body", "is_json"),
    [
        (b"{", True),
        (b"{x: [", False),
        (b"a: &root {}\nb: *root", False),
        (b"a: !!str test", False),
        (b'{"openapi":"3.0.3","openapi":"3.1.1"}', True),
        (b"a: 1\na: 2", False),
        (b"[" * 50 + b"]" * 50, False),
        (b"[" * 50 + b"]" * 50, True),
        (b" " * (MAX_BYTES + 1), False),
        (b"a: x\n---\nb: y", False),
    ],
)
def test_reject_malformed_and_unbounded_files(body: bytes, is_json: bool) -> None:
    with pytest.raises(InvalidDocument):
        parse(body, is_json)


def test_operation_limit_and_inventory_warnings() -> None:
    with pytest.raises(InvalidDocument, match="500"):
        parse(
            json.dumps({**spec(), "paths": {f"/p/{i}": {"get": {}} for i in range(501)}}).encode(),
            True,
        )
    empty = parse(json.dumps({**spec(), "paths": {}, "webhooks": {"example": {}}}).encode(), True)
    assert not empty.operations and len(empty.warnings) == 2


@pytest.mark.parametrize(
    ("version", "scheme", "roles", "valid"),
    [
        ("3.0.3", {"type": "mutualTLS"}, [], False),
        ("3.1.1", {"type": "mutualTLS"}, [], True),
        ("3.0.3", {"type": "http", "scheme": "bearer"}, ["employee"], False),
        ("3.1.1", {"type": "http", "scheme": "bearer"}, ["employee"], True),
        ("3.1.1", {"type": "http"}, [], False),
        ("3.1.1", {"type": "apiKey", "in": "header"}, [], False),
        ("3.1.1", {"type": "apiKey", "name": "local", "in": "elsewhere"}, [], False),
        ("3.0.3", {"type": "apiKey", "name": "local", "in": "header"}, [], True),
        ("3.1.1", {"type": "openIdConnect"}, [], False),
        ("3.1.1", {"type": "oauth2", "flows": {"clientCredentials": {"scopes": {}}}}, [], False),
        (
            "3.0.3",
            {
                "type": "oauth2",
                "flows": {
                    "clientCredentials": {"scopes": {"read": "Read access"}, "tokenUrl": "/token"}
                },
            },
            ["read"],
            True,
        ),
    ],
)
def test_version_specific_security(
    version: str, scheme: dict[str, object], roles: list[str], valid: bool
) -> None:
    doc = {
        "openapi": version,
        "info": {"title": "Local", "version": "1"},
        "paths": {},
        "components": {"securitySchemes": {"auth": scheme}},
        "security": [{"auth": roles}],
    }
    if valid:
        assert not parse(json.dumps(doc).encode(), True).operations
    else:
        with pytest.raises(InvalidDocument):
            parse(json.dumps(doc).encode(), True)


def test_shared_path_items_charge_an_aggregate_work_budget() -> None:
    shared = {
        "get": {"responses": {f"{status}": {"description": "test"} for status in range(200, 300)}}
    }
    doc = {
        **spec(),
        "components": {"pathItems": {"shared": shared}},
        "security": [],
        "paths": {f"/group/{i}": {"$ref": "#/components/pathItems/shared"} for i in range(125)},
    }
    with pytest.raises(InvalidDocument, match="Expanded inventory exceeds the field limit"):
        parse(json.dumps(doc).encode(), True)
