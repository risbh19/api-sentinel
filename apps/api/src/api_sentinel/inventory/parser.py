"""Extract a bounded inventory from a single document, without URI resolution."""

import json
import re
from collections.abc import Hashable
from dataclasses import dataclass

import yaml
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent, ScalarEvent
from yaml.nodes import MappingNode

MAX_BYTES = 128 * 1024
METHODS = frozenset(["get", "put", "post", "delete", "options", "head", "patch", "trace"])
NAME = re.compile(r"[A-Za-z0-9._:/-]{1,128}")
PARAM = re.compile(r"\{[A-Za-z0-9_.-]+\}")


class InvalidDocument(ValueError):
    pass


def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise InvalidDocument("Duplicate document keys are unsupported.")
    return result


class LocalLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Hashable, object]:
        result: dict[Hashable, object] = {}
        for key, value in node.value:
            if not isinstance(key, yaml.ScalarNode) or key.value == "<<":
                raise InvalidDocument("YAML keys must be plain fields without merges.")
            if key.value in result:
                raise InvalidDocument("Duplicate document keys are unsupported.")
            result[key.value] = self.construct_object(value, deep=deep)
        return result


def decode(data: bytes, is_json: bool) -> object:
    if len(data) > MAX_BYTES:
        raise InvalidDocument("File exceeds the 128 KiB limit.")
    try:
        source = data.decode("utf-8-sig")
        if is_json:
            return json.loads(source, object_pairs_hook=unique, parse_constant=reject_constant)
        depth = 0
        for count, event in enumerate(yaml.parse(source, Loader=yaml.SafeLoader)):
            if count > 12000:
                raise InvalidDocument("Document contains too many nodes.")
            if (
                isinstance(event, AliasEvent)
                or getattr(event, "anchor", None)
                or getattr(event, "tag", None)
            ):
                raise InvalidDocument("YAML aliases, anchors and explicit tags are unsupported.")
            if isinstance(event, CollectionStartEvent):
                depth += 1
            elif isinstance(event, CollectionEndEvent):
                depth -= 1
            if depth > 40 or (isinstance(event, ScalarEvent) and len(event.value) > 16384):
                raise InvalidDocument("Document exceeds nesting or scalar limits.")
        return yaml.load(source, Loader=LocalLoader)
    except InvalidDocument:
        raise
    except (UnicodeError, ValueError, OverflowError, RecursionError, yaml.YAMLError) as exc:
        raise InvalidDocument("Invalid UTF-8 JSON or YAML document.") from exc


def reject_constant(value: str) -> object:
    raise InvalidDocument("Invalid JSON number.")


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise InvalidDocument("Expected an OpenAPI object.")
    return value


def pointer(root: dict[str, object], ref: object) -> object:
    if not isinstance(ref, str) or not ref.startswith("#/") or len(ref) > 512:
        raise InvalidDocument("Only document-local JSON Pointer references are supported.")
    current: object = root
    for part in ref[2:].split("/"):
        if "%" in part or re.search(r"~(?![01])", part):
            raise InvalidDocument("Unsupported JSON Pointer escape.")
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif (
            isinstance(current, list)
            and re.fullmatch(r"0|[1-9][0-9]{0,5}", key)
            and int(key) < len(current)
        ):
            current = current[int(key)]
        else:
            raise InvalidDocument("Document-local reference does not exist.")
    return current


def check_tree(root: dict[str, object]) -> None:
    pending: list[tuple[object, int]] = [(root, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > 40 or count > 12000:
            raise InvalidDocument("Document exceeds nesting or node limits.")
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "$ref":
                    pointer(root, item)
                if key in {"$dynamicRef", "$recursiveRef", "$id"}:
                    raise InvalidDocument(
                        "Schema resource and dynamic references are unsupported."
                    )
                pending.extend(((key, depth + 1), (item, depth + 1)))
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
        elif isinstance(value, str) and (
            len(value) > 16384 or "\x00" in value or re.search(r"[\ud800-\udfff]", value)
        ):
            raise InvalidDocument("Invalid document text.")


def resolved(root: dict[str, object], value: object) -> dict[str, object]:
    item = mapping(value)
    for _ in range(16):
        if "$ref" not in item:
            return item
        if len(item) != 1:
            raise InvalidDocument("Referenced inventory objects cannot have sibling fields.")
        item = mapping(pointer(root, item["$ref"]))
    raise InvalidDocument("Reference chain is cyclic or too deep.")


def identifier(value: object) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise InvalidDocument("Invalid or unsupported inventory identifier.")
    return value


Security = list[dict[str, list[str]]]


def text_field(obj: dict[str, object], field: str) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InvalidDocument("Missing or invalid security scheme field.")
    return value


def scheme_type(scheme: dict[str, object], legacy: bool) -> str:
    kind = text_field(scheme, "type")
    if kind == "apiKey":
        text_field(scheme, "name")
        if scheme.get("in") not in ("header", "cookie", "query"):
            raise InvalidDocument("Invalid API key location.")
    elif kind == "http":
        identifier(text_field(scheme, "scheme"))
    elif kind == "openIdConnect":
        text_field(scheme, "openIdConnectUrl")
    elif kind == "oauth2":
        urls = {
            "implicit": ("authorizationUrl",),
            "password": ("tokenUrl",),
            "clientCredentials": ("tokenUrl",),
            "authorizationCode": ("authorizationUrl", "tokenUrl"),
        }
        flows = mapping(scheme.get("flows"))
        if not any(name in flows for name in urls):
            raise InvalidDocument("Expected at least one supported OAuth flow.")
        for name, definition in flows.items():
            if name.startswith("x-"):
                continue
            if name not in urls:
                raise InvalidDocument("Unsupported OAuth flow.")
            flow = mapping(definition)
            for field in urls[name]:
                text_field(flow, field)
            if not all(
                isinstance(description, str)
                for description in mapping(flow.get("scopes")).values()
            ):
                raise InvalidDocument("Invalid OAuth scope descriptions.")
    elif kind != "mutualTLS" or legacy:
        raise InvalidDocument("Unsupported security scheme type for this OpenAPI version.")
    return kind


def requirements(value: object, schemes: dict[str, str], legacy: bool) -> Security:
    if not isinstance(value, list) or len(value) > 8:
        raise InvalidDocument("Invalid or oversized security requirements.")
    alternatives = []
    for item in value:
        group = mapping(item)
        if len(group) > 8:
            raise InvalidDocument("Too many security schemes.")
        parsed = {}
        for scheme, scopes in group.items():
            if (
                identifier(scheme) not in schemes
                or not isinstance(scopes, list)
                or len(scopes) > 8
            ):
                raise InvalidDocument("Invalid security scheme or scope list.")
            if legacy and scopes and schemes[scheme] not in ("oauth2", "openIdConnect"):
                raise InvalidDocument(
                    "This OpenAPI 3.0 security scheme requires an empty scope list."
                )
            parsed[scheme] = [identifier(scope) for scope in scopes]
        alternatives.append(parsed)
    return alternatives


@dataclass
class Operation:
    method: str
    path: str
    operation_id: str | None
    security: Security | None


@dataclass
class Inventory:
    version: str
    operations: list[Operation]
    warnings: list[str]


def parse(data: bytes, is_json: bool) -> Inventory:
    root = mapping(decode(data, is_json))
    check_tree(root)
    version = root.get("openapi")
    if not isinstance(version, str) or not re.fullmatch(r"3\.[01]\.[0-9]{1,3}", version):
        raise InvalidDocument("Supported OpenAPI versions are 3.0.x and 3.1.x.")
    info = mapping(root.get("info"))
    if not all(
        isinstance(info.get(k), str) and str(info[k]).strip() for k in ("title", "version")
    ):
        raise InvalidDocument("The info object requires a title and string version.")
    paths = mapping(root.get("paths"))
    legacy = version.startswith("3.0.")
    definitions = mapping(mapping(root.get("components", {})).get("securitySchemes", {}))
    schemes = {}
    checked: dict[int, str] = {}
    for name, definition in definitions.items():
        if name.startswith("x-"):
            continue
        scheme = resolved(root, definition)
        if id(scheme) not in checked:
            checked[id(scheme)] = scheme_type(scheme, legacy)
        schemes[identifier(name)] = checked[id(scheme)]
    default = requirements(root["security"], schemes, legacy) if "security" in root else None
    operations: list[Operation] = []
    templates: set[str] = set()
    ids: set[str] = set()
    warnings: set[str] = set()
    if root.get("webhooks"):
        warnings.add("Webhooks are outside the paths inventory.")
    stored_bytes = 0
    expanded_fields = 0
    for path, value in paths.items():
        if path.startswith("x-"):
            continue
        normalized = PARAM.sub("{}", path)
        literal = PARAM.sub("", path)
        if (
            not path.startswith("/")
            or len(path) > 512
            or not re.fullmatch(r"[A-Za-z0-9._~!$&'()*+,;=:@%/{}-]+", path)
            or "{" in literal
            or "}" in literal
            or normalized in templates
        ):
            raise InvalidDocument("Invalid or ambiguous path template.")
        templates.add(normalized)
        path_item = resolved(root, value)
        expanded_fields += len(path_item)
        if expanded_fields > 12000:
            raise InvalidDocument("Expanded inventory exceeds the field limit.")
        for method, raw in path_item.items():
            if method in {"summary", "description", "parameters", "servers"} or method.startswith(
                "x-"
            ):
                continue
            if method not in METHODS:
                raise InvalidDocument("Unsupported path item field or method.")
            op = mapping(raw)
            if "$ref" in op:
                raise InvalidDocument("Operation references are unsupported.")
            if version.startswith("3.0.") or "responses" in op:
                responses = mapping(op.get("responses"))
                if not responses:
                    raise InvalidDocument("Expected nonempty operation responses.")
                expanded_fields += len(responses)
                if expanded_fields > 12000:
                    raise InvalidDocument("Expanded inventory exceeds the field limit.")
                for status, response in responses.items():
                    if status.startswith("x-"):
                        continue
                    if not re.fullmatch(r"default|[1-5](?:[0-9]{2}|XX)", status):
                        raise InvalidDocument("Invalid response status key.")
                    if not isinstance(resolved(root, response).get("description"), str):
                        raise InvalidDocument("Response descriptions must be strings.")
            op_id = identifier(op["operationId"]) if "operationId" in op else None
            if op_id is not None:
                if op_id in ids:
                    raise InvalidDocument("Duplicate operation ID.")
                ids.add(op_id)
            security = (
                requirements(op["security"], schemes, legacy) if "security" in op else default
            )
            if op.get("callbacks"):
                warnings.add("Callbacks are outside the paths inventory.")
            stored_bytes += len(path) + len(op_id or "") + len(json.dumps(security))
            if stored_bytes > 512 * 1024:
                raise InvalidDocument("Expanded inventory exceeds the metadata limit.")
            operations.append(Operation(method.upper(), path, op_id, security))
            if len(operations) > 500:
                raise InvalidDocument("Inventory exceeds 500 operations.")
    if not operations:
        warnings.add("The paths inventory contains no operations.")
    return Inventory(version, operations, sorted(warnings))
