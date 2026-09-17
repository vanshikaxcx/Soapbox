import json

import pytest

from services.api import health


class FixtureIdGenerator:
    def __init__(self, *identifiers: str) -> None:
        self._identifiers = iter(identifiers)

    def new_id(self) -> str:
        return next(self._identifiers)


def test_health_success_uses_the_injected_opaque_id() -> None:
    handler = health.create_health_handler(FixtureIdGenerator("fixture-request-id"))

    response = handler({"requestContext": {}}, object())

    assert response["statusCode"] == 200
    assert response["headers"] == {
        "Content-Type": "application/json",
        "X-Request-ID": "fixture-request-id",
    }
    assert json.loads(response["body"]) == {
        "data": {"status": "ok"},
        "request_id": "fixture-request-id",
    }


def test_health_maps_an_unexpected_failure_to_a_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_request_id: str) -> health.HealthSuccessEnvelope:
        raise RuntimeError("private details must not escape")

    monkeypatch.setattr(health, "build_health_success", fail)
    handler = health.create_health_handler(FixtureIdGenerator("fixture-error-id"))

    response = handler({}, object())

    assert response["statusCode"] == 500
    assert response["headers"]["X-Request-ID"] == "fixture-error-id"
    assert json.loads(response["body"]) == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "details": {},
        },
        "request_id": "fixture-error-id",
    }
