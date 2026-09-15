from services.api.health import get_health


def test_health_envelope_shape() -> None:
    response = get_health()
    assert response["data"]["status"] == "ok"
    assert "time" in response["data"]
    assert "request_id" in response
