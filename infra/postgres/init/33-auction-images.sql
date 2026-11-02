-- Schema: auction — listing photos (owner: Sumit)
--
-- 30-auction.sql created auction_images with the object key and position only. The seller
-- uploads photos while the auction is DRAFT or SCHEDULED; the bytes live in the
-- `listing-images` bucket (infra/s3/create-buckets.sh) and are read through signed URLs, so
-- the row keeps what a reader needs to show it without asking the store.

ALTER TABLE auction.auction_images
  ADD COLUMN mime_type   text NOT NULL DEFAULT 'image/jpeg'
    CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
  ADD COLUMN size_bytes  integer NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
  ADD COLUMN uploaded_at timestamptz NOT NULL DEFAULT now(),
  -- Object keys are relative paths, never URLs (zeo_common.storage.validate_object_key).
  ADD CONSTRAINT auction_images_object_key_check
    CHECK (object_key !~ '://' AND object_key !~ '^/'),
  -- At most six photos per auction (app/domain/images.py MAX_IMAGES).
  ADD CONSTRAINT auction_images_position_check CHECK (position BETWEEN 0 AND 5);
