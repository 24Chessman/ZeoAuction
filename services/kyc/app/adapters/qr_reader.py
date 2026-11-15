"""QR decoding with zxing-cpp, the maintained C++ port of Google's ZXing (Apache-2.0).

A Secure QR is dense (version 25-40 for a few kilobytes of photo and signature), and sellers
send phone photos of it: tilted, unevenly lit, sometimes a whole e-Aadhaar page. zxing-cpp
handles that well (rotation, inversion and downscaled passes), ships wheels for every platform
we build on, and needs no system library.

Blocking and CPU-bound, so the service calls it with ``asyncio.to_thread``. Nothing here logs
or keeps the image or the decoded text.
"""

from io import BytesIO
from typing import Protocol

import numpy as np
import zxingcpp
from PIL import Image, UnidentifiedImageError

MAX_SIDE = 4000  # larger photos are scaled down first; a printed QR stays readable at this size


class QrReader(Protocol):
    def read(self, image: bytes) -> list[str] | None:
        """The text of every QR code in the photo; ``None`` if the image can't be decoded."""
        ...


class ZxingQrReader:
    def read(self, image: bytes) -> list[str] | None:
        try:
            gray_image = Image.open(BytesIO(image)).convert("L")
        except (OSError, UnidentifiedImageError):
            return None
        width, height = gray_image.size
        if max(width, height) > MAX_SIDE:
            scale = MAX_SIDE / max(width, height)
            gray_image = gray_image.resize(
                (round(width * scale), round(height * scale)),
                Image.Resampling.LANCZOS,
            )
        gray = np.asarray(gray_image)
        codes = zxingcpp.read_barcodes(gray, formats=zxingcpp.BarcodeFormat.QRCode)
        return [code.text for code in codes if code.valid and code.text]
