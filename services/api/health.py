"""Dependency-free public liveness transport for the WP-00 baseline."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from services.application.ports.id_generator import IdGenerator


class HealthData(BaseModel):
    """The concrete, intentionally small liveness payload."""

    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["ok"]


class HealthSuccessEnvelope(BaseModel):
    """Successful API response envelope."""

    model_config = ConfigDict(extra="forbid", strict=True)
    data: HealthData
    request_id: str = Field(min_length=1)


class ErrorBody(BaseModel):
    """Safe error details for application-handled failures."""

    model_config = ConfigDict(extra="forbid", strict=True)
    code: Literal["internal_error"]
    message: str
    details: dict[str, object]


class ErrorEnvelope(BaseModel):
    """Error API response envelope."""

    model_config = ConfigDict(extra="forbid", strict=True)
    error: ErrorBody
    request_id: str = Field(min_length=1)


class ApiGatewayResponse(TypedDict):
    """The local subset of an API Gateway proxy response."""

    statusCode: int
    headers: dict[str, str]
    body: str


class UuidIdGenerator:
    """Outer transport adapter for opaque request identifiers."""

    def new_id(self) -> str:
        return str(uuid.uuid4())


def build_health_success(request_id: str) -> HealthSuccessEnvelope:
    """Build the pure health success envelope."""

    return HealthSuccessEnvelope(data=HealthData(status="ok"), request_id=request_id)


def build_internal_error(request_id: str) -> ErrorEnvelope:
    """Build a safe error envelope without exception-derived details."""

    return ErrorEnvelope(
        error=ErrorBody(
            code="internal_error",
            message="An unexpected error occurred.",
            details={},
        ),
        request_id=request_id,
    )


def to_gateway_response(
    status_code: int, envelope: HealthSuccessEnvelope | ErrorEnvelope
) -> ApiGatewayResponse:
    """Translate an already-safe envelope to the proxy transport subset."""

    request_id = envelope.request_id
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
        },
        "body": envelope.model_dump_json(),
    }


def create_health_handler(
    id_generator: IdGenerator,
) -> Callable[[Mapping[str, Any], object], ApiGatewayResponse]:
    """Compose a testable handler with its only dependency injected."""

    def handle(_event: Mapping[str, Any], _context: object) -> ApiGatewayResponse:
        request_id = id_generator.new_id()
        try:
            return to_gateway_response(200, build_health_success(request_id))
        except Exception:
            return to_gateway_response(500, build_internal_error(request_id))

    return handle


def lambda_handler(event: Mapping[str, Any], context: object) -> ApiGatewayResponse:
    """Production composition root; health has no external dependencies."""

    return create_health_handler(UuidIdGenerator())(event, context)
