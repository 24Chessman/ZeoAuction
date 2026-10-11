"""Shared building blocks every ZeoAuction service is created from.

Every service calls :func:`create_app`, which wires in the platform conventions:
``/healthz``, ``/readyz``, ``/metrics``, request-id propagation, JSON logging and the
uniform error envelope (SDD section 7.1.1).
"""

from zeo_common.app_factory import create_app
from zeo_common.errors import ApiError, ErrorBody
from zeo_common.money import MoneyError, format_money, parse_money
from zeo_common.request_context import get_request_id

__all__ = [
    "ApiError",
    "ErrorBody",
    "MoneyError",
    "create_app",
    "format_money",
    "get_request_id",
    "parse_money",
]
