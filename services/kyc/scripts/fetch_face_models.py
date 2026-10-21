"""Download the OpenCV face models the KYC face check needs, and verify their checksums.

    python services/kyc/scripts/fetch_face_models.py [DEST]   # default: services/kyc/models

YuNet (face detection) and SFace (face recognition) come from the OpenCV model zoo
(https://github.com/opencv/opencv_zoo, Apache-2.0). They are not committed (SFace is 38 MB);
the Dockerfile runs this script at build time. Existing files with the right checksum are kept.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        f"{ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "face_recognition_sface_2021dec.onnx": (
        f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in MODELS.items():
        target = dest / name
        if target.is_file() and sha256(target) == digest:
            print(f"ok      {name}")
            continue
        partial = target.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - fixed https URL
            partial.write_bytes(response.read())
        if sha256(partial) != digest:
            partial.unlink()
            raise SystemExit(f"checksum mismatch for {name}; refusing to install it")
        partial.replace(target)
        print(f"fetched {name}")


if __name__ == "__main__":
    default = Path(__file__).resolve().parent.parent / "models"
    fetch(Path(sys.argv[1]) if len(sys.argv) > 1 else default)
