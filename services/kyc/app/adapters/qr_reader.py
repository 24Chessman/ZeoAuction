"""QR decoding with zxing-cpp, the maintained C++ port of Google's ZXing (Apache-2.0).

A Secure QR is dense (version 25-40 for a few kilobytes of photo and signature), and sellers
send phone photos of it: tilted, unevenly lit, sometimes a whole e-Aadhaar page. zxing-cpp
handles that well (rotation, inversion and downscaled passes), ships wheels for every platform
we build on, and needs no system library.

Blocking and CPU-bound, so the service calls it with ``asyncio.to_thread``. Nothing here logs
or keeps the image or the decoded text.
"""

from typing import Protocol

import cv2
import numpy as np
import zxingcpp

MAX_SIDE = 4000  # larger photos are scaled down first; a printed QR stays readable at this size


class QrReader(Protocol):
    def read(self, image: bytes) -> list[str] | None:
        """The text of every QR code in the photo; ``None`` if the image can't be decoded."""
        ...


class ZxingQrReader:
    def read(self, image: bytes) -> list[str] | None:
        gray = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None
        height, width = gray.shape[:2]
        if max(height, width) > MAX_SIDE:
            scale = MAX_SIDE / max(height, width)
            gray = cv2.resize(gray, (round(width * scale), round(height * scale)),
                              interpolation=cv2.INTER_AREA)
        codes = zxingcpp.read_barcodes(gray, formats=zxingcpp.BarcodeFormat.QRCode)
        return [code.text for code in codes if code.valid and code.text]
