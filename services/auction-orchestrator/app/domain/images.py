"""Listing photos: which files a seller may attach to an auction, and where they are kept.

Pure logic, no I/O. The seller adds photos while the auction is DRAFT or SCHEDULED; once it
opens, bidders are looking at it and the photos are fixed. A photo is checked by its magic
bytes, not the file name or the declared type, and stored under
``listings/{auction_id}/{image_id}.{ext}`` (ids only, never the uploaded file name).
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.auction import Auction

MAX_IMAGES = 6
MAX_IMAGE_BYTES = 5 * 1024 * 1024
EDITABLE_STATES = frozenset({"DRAFT", "SCHEDULED"})

_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)


class ImageInvalid(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class ImagesLocked(Exception):
    def __init__(self, state: str) -> None:
        super().__init__(
            f"Photos can only change while the auction is DRAFT or SCHEDULED, not {state}"
        )
        self.state = state


@dataclass(frozen=True)
class ListingImage:
    id: UUID
    auction_id: UUID
    object_key: str
    position: int
    mime_type: str
    size_bytes: int
    uploaded_at: datetime


def sniff(data: bytes) -> tuple[str, str] | None:
    for magic, mime, extension in _SIGNATURES:
        if data.startswith(magic):
            return mime, extension
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def validate_image(data: bytes, max_bytes: int = MAX_IMAGE_BYTES) -> tuple[str, str]:
    """The MIME type and extension of an acceptable photo."""
    if not data:
        raise ImageInvalid("empty", "The photo is empty")
    if len(data) > max_bytes:
        raise ImageInvalid(
            "too_large", f"Each photo must be at most {max_bytes // (1024 * 1024)} MB"
        )
    sniffed = sniff(data)
    if sniffed is None:
        raise ImageInvalid("unsupported_format", "Only JPEG, PNG and WebP photos are accepted")
    return sniffed


def check_editable(auction: Auction) -> None:
    if auction.state not in EDITABLE_STATES:
        raise ImagesLocked(auction.state)


def next_position(existing: list[ListingImage]) -> int:
    """The first free slot; photos keep their order when one in the middle is removed."""
    taken = {image.position for image in existing}
    for position in range(MAX_IMAGES):
        if position not in taken:
            return position
    raise ImageInvalid("too_many", f"An auction can have at most {MAX_IMAGES} photos")


def object_key(auction_id: UUID, image_id: UUID, extension: str) -> str:
    return f"listings/{auction_id}/{image_id}.{extension}"


def new_image(
    *, image_id: UUID, auction: Auction, data: bytes, existing: list[ListingImage], now: datetime,
) -> ListingImage:
    mime, extension = validate_image(data)
    return ListingImage(
        id=image_id, auction_id=auction.id, object_key=object_key(auction.id, image_id, extension),
        position=next_position(existing), mime_type=mime, size_bytes=len(data), uploaded_at=now,
    )
