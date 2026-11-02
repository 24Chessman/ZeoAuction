"""Listing photos: upload, order, limits, and who may change them when."""

from uuid import uuid4

import asyncpg
import pytest

from app.adapters.auction_repo import ImageSlotTaken, PostgresAuctionRepository
from app.domain.images import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    ImageInvalid,
    ListingImage,
    sniff,
    validate_image,
)
from tests.support import NOW, bearer, draft
from tests.test_postgres_repo import FakePool

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-body"
PNG = b"\x89PNG\r\n\x1a\n" + b"png-body"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"webp-body"


def upload(harness, auction_id, data=JPEG, headers=None, name="photo.jpg"):
    return harness.client.post(f"/api/v1/auctions/{auction_id}/images",
                               files={"image": (name, data, "image/jpeg")},
                               headers=headers or bearer())


def store(harness):
    return harness.service.images


def test_the_seller_uploads_photos_and_the_auction_lists_them(harness):
    auction_id = harness.created()
    first = upload(harness, auction_id)
    assert first.status_code == 201, first.text
    upload(harness, auction_id, PNG, name="second.png")
    body = harness.client.get(f"/api/v1/auctions/{auction_id}").json()
    assert [(i["position"], i["mime_type"]) for i in body["images"]] == [
        (0, "image/jpeg"), (1, "image/png")]
    image = body["images"][0]
    assert "X-Amz-Expires=300" in image["url"]
    key = f"listings/{auction_id}/{image['image_id']}.jpg"
    assert store(harness).objects[key] == (JPEG, "image/jpeg")
    assert "photo.jpg" not in str(store(harness).objects)  # the file name is never kept


def test_a_new_auction_has_no_photos(harness):
    assert harness.create().json()["images"] == []


def test_the_type_comes_from_the_bytes_not_the_name(harness):
    auction_id = harness.created()
    refused = upload(harness, auction_id, b"GIF89a-not-allowed", name="cat.jpg")
    assert refused.status_code == 422
    assert refused.json()["code"] == "VALIDATION_ERROR"
    assert refused.json()["details"] == {"field": "image", "reason": "unsupported_format"}
    assert store(harness).objects == {}


def test_too_large_and_empty_photos_are_refused(harness):
    auction_id = harness.created()
    big = upload(harness, auction_id, JPEG + b"x" * MAX_IMAGE_BYTES)
    assert big.json()["details"]["reason"] == "too_large"
    assert upload(harness, auction_id, b"").json()["details"]["reason"] == "empty"


def test_at_most_six_photos(harness):
    auction_id = harness.created()
    for _ in range(MAX_IMAGES):
        assert upload(harness, auction_id).status_code == 201
    extra = upload(harness, auction_id)
    assert extra.status_code == 422
    assert extra.json()["details"]["reason"] == "too_many"


def test_removing_a_photo_frees_its_slot_and_its_object(harness):
    auction_id = harness.created()
    for _ in range(3):
        upload(harness, auction_id)
    images = harness.client.get(f"/api/v1/auctions/{auction_id}").json()["images"]
    removed = harness.client.delete(
        f"/api/v1/auctions/{auction_id}/images/{images[1]['image_id']}", headers=bearer())
    assert removed.status_code == 200
    assert [i["position"] for i in removed.json()["images"]] == [0, 2]
    assert len(store(harness).objects) == 2
    again = upload(harness, auction_id).json()["images"]
    assert [i["position"] for i in again] == [0, 1, 2]
    missing = harness.client.delete(f"/api/v1/auctions/{auction_id}/images/{uuid4()}",
                                    headers=bearer())
    assert missing.status_code == 404


def test_only_the_seller_can_change_photos(harness):
    auction_id = harness.created()
    other = bearer(uuid4())
    assert upload(harness, auction_id, headers=other).status_code == 403
    assert upload(harness, auction_id, headers=bearer(kyc_status="UNDER_REVIEW")).status_code == 403
    assert upload(harness, uuid4()).status_code == 404


def test_photos_are_fixed_once_the_auction_opens(harness):
    auction_id = harness.created()
    upload(harness, auction_id)
    harness.drive(auction_id, "publish")
    assert upload(harness, auction_id).status_code == 201  # SCHEDULED still allows it
    harness.drive(auction_id, "open")
    refused = upload(harness, auction_id)
    assert refused.status_code == 409
    assert refused.json()["details"] == {"state": "OPEN"}
    image_id = harness.client.get(f"/api/v1/auctions/{auction_id}").json()["images"][0]["image_id"]
    assert harness.client.delete(f"/api/v1/auctions/{auction_id}/images/{image_id}",
                                 headers=bearer()).status_code == 409


def test_a_storage_failure_is_retryable_and_leaves_nothing_behind(harness):
    auction_id = harness.created()
    store(harness).fail_next_put = True
    response = upload(harness, auction_id)
    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"
    assert harness.repo.photos == {}


def test_a_lost_slot_race_removes_the_stored_object(harness):
    auction_id = harness.created()

    async def raced(image):
        raise ImageSlotTaken(str(image.auction_id))

    harness.repo.add_image = raced
    response = upload(harness, auction_id)
    assert response.status_code == 409
    assert store(harness).objects == {}


def test_sniffing():
    assert sniff(JPEG) == ("image/jpeg", "jpg")
    assert sniff(PNG) == ("image/png", "png")
    assert sniff(WEBP) == ("image/webp", "webp")
    assert sniff(b"RIFF\x00\x00\x00\x00WAVE") is None
    with pytest.raises(ImageInvalid):
        validate_image(b"%PDF-1.7")


async def test_postgres_images_round_trip():
    auction = draft()
    row = {"id": uuid4(), "auction_id": auction.id, "object_key": "listings/a/b.jpg",
           "position": 0, "mime_type": "image/jpeg", "size_bytes": 12, "uploaded_at": NOW}
    pool = FakePool(rows=[row])
    repo = PostgresAuctionRepository(pool)
    [image] = await repo.images(auction.id)
    assert image.object_key == "listings/a/b.jpg"
    sql, _ = pool.log[-1]
    assert sql.endswith("WHERE auction_id = $1 ORDER BY position")
    await repo.add_image(image)
    assert pool.log[-1][0].startswith("INSERT INTO auction_images")
    assert len(pool.log[-1][1]) == 7
    removed = await repo.remove_image(auction.id, image.id)
    assert removed == image
    assert pool.log[-1][0].startswith("DELETE FROM auction_images")
    assert await PostgresAuctionRepository(FakePool()).remove_image(auction.id, uuid4()) is None


async def test_postgres_unique_slot_violation_is_a_lost_race():
    class Clashing(FakePool):
        async def execute(self, sql, *args):
            raise asyncpg.UniqueViolationError("auction_images_auction_id_position_key")

    auction = draft()
    image = ListingImage(id=uuid4(), auction_id=auction.id, object_key="listings/a/b.jpg",
                         position=0, mime_type="image/jpeg", size_bytes=1, uploaded_at=NOW)
    with pytest.raises(ImageSlotTaken):
        await PostgresAuctionRepository(Clashing()).add_image(image)
