"""Payment, Fees & Escrow routes. Plan 3: the public fee quote (SDD 7.4, Listing 7.3)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from app.fees import quote
from zeo_common import ApiError, format_money, parse_money
from zeo_common.money import MONEY_PATTERN

router = APIRouter(prefix="/api/v1", tags=["payments"])


class FeeQuoteView(BaseModel):
    bid_amount: str = Field(examples=["1250.00"])
    convenience_fee: str = Field(examples=["25.00"])
    total: str = Field(examples=["1275.00"])
    currency: str = Field(examples=["USD"])
    fee_version: str = Field(
        description="The fee_config row in force; disclosure, invoice and settlement agree.",
        examples=["2026-08-v1"],
    )


@router.get("/fees/quote", response_model=FeeQuoteView, operation_id="quoteFee")
async def quote_fee(
    bid_amount: Annotated[str, Query(pattern=MONEY_PATTERN, examples=["1250.00"])],
    response: Response,
) -> FeeQuoteView:
    """Public: the flat fee and resulting total, shown before a bid is placed (AC-07)."""
    try:
        result = quote(parse_money(bid_amount))
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": "bid_amount"}) from exc
    # Same answer for every caller until the fee_version changes.
    response.headers["Cache-Control"] = "public, max-age=60"
    return FeeQuoteView(
        bid_amount=format_money(result.bid_amount),
        convenience_fee=format_money(result.convenience_fee),
        total=format_money(result.total),
        currency=result.currency,
        fee_version=result.fee_version,
    )
