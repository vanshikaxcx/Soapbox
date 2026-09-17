import json

from services.api import health


class RecordingIdGenerator:
    def __init__(self) -> None:
        self.calls = 0

    def new_id(self) -> str:
        self.calls += 1
        return f"fixture-request-{self.calls}"


def test_representative_gateway_events_are_stateless_and_make_no_external_calls() -> None:
    generator = RecordingIdGenerator()
    handler = health.create_health_handler(generator)
    event = {
        "version": "2.0",
        "routeKey": "GET /health",
        "rawPath": "/health",
        "requestContext": {"http": {"method": "GET", "path": "/health"}},
    }

    first = handler(event, object())
    second = handler(event, object())

    assert [first["statusCode"], second["statusCode"]] == [200, 200]
    assert first["headers"]["Content-Type"] == "application/json"
    assert generator.calls == 2
    assert first["headers"]["X-Request-ID"] != second["headers"]["X-Request-ID"]
    assert json.loads(first["body"])["request_id"] == first["headers"]["X-Request-ID"]
    assert json.loads(second["body"])["request_id"] == second["headers"]["X-Request-ID"]
