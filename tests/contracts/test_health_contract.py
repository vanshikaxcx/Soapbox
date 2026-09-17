import json
import re
from pathlib import Path

import pytest

from services.api import health

CONTRACT_SOURCE = (Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml").read_text(
    encoding="utf-8"
)


def contract_component(name: str) -> str:
    match = re.search(
        rf"(?ms)^    {re.escape(name)}:\n(?P<body>.*?)(?=^    \S|\Z)",
        CONTRACT_SOURCE,
    )
    assert match is not None, f"OpenAPI component {name} is missing"
    return match.group("body")


def required_properties(component_name: str) -> set[str]:
    component = contract_component(component_name)
    required = re.search(r"(?ms)^      required:\n(?P<body>(?:        - \S+\n)+)", component)
    assert required is not None, f"OpenAPI component {component_name} has no required list"
    return set(re.findall(r"^        - (\S+)$", required.group("body"), re.MULTILINE))


def assert_openapi_object(value: object, component_name: str) -> dict[str, object]:
    assert isinstance(value, dict)
    component = contract_component(component_name)
    assert "additionalProperties: false" in component
    allowed = set(re.findall(r"^        ([a-z_]+):$", component, re.MULTILINE))
    assert set(value) == required_properties(component_name)
    assert set(value) <= allowed
    return value


class FixtureIdGenerator:
    def new_id(self) -> str:
        return "fixture-contract-id"


def test_health_success_response_matches_the_documented_envelope() -> None:
    response = health.create_health_handler(FixtureIdGenerator())({}, object())

    assert response["statusCode"] == 200
    assert re.search(
        r'(?s)["\']200["\']:.*?#/components/schemas/HealthSuccessResponse',
        CONTRACT_SOURCE,
    )
    parsed = assert_openapi_object(json.loads(response["body"]), "HealthSuccessResponse")
    data = assert_openapi_object(parsed["data"], "HealthData")
    assert data["status"] == "ok"
    assert parsed["request_id"] == response["headers"]["X-Request-ID"]


def test_internal_error_response_has_no_untrusted_exception_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_request_id: str) -> health.HealthSuccessEnvelope:
        raise RuntimeError("token=not-for-response")

    monkeypatch.setattr(health, "build_health_success", fail)
    response = health.create_health_handler(FixtureIdGenerator())({}, object())
    assert re.search(
        r'(?s)["\']500["\']:.*?#/components/schemas/ErrorResponse',
        CONTRACT_SOURCE,
    )
    parsed = assert_openapi_object(json.loads(response["body"]), "ErrorResponse")
    error = assert_openapi_object(parsed["error"], "ErrorBody")

    assert response["statusCode"] == 500
    assert error["code"] == "internal_error"
    assert error["details"] == {}
    assert parsed["request_id"] == response["headers"]["X-Request-ID"]
    assert "token" not in json.dumps(parsed)
