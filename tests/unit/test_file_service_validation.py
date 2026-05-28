"""Pin avatar-upload defences:
- magic-byte sniff (don't trust client Content-Type)
- decompression-bomb dimension guard
- EXIF orientation bake-in

The actual MinIO storage layer is mocked out; we exercise only the
validation pipeline since that's where the security boundary sits.
"""

import io
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from PIL import Image

from utils.file_service import FileService


def _make_service():
    return FileService(media_storage=MagicMock())


def _png_bytes(width: int = 32, height: int = 32) -> bytes:
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ─── magic-byte sniff ───────────────────────────────────────────────


class TestMagicByteSniff:
    """The content-type header is client-controlled. The sniff is the
    actual gate: if these tests pass, an attacker can't mark random
    bytes as 'image/jpeg' and slip them past us."""

    def test_real_png_accepted(self):
        assert FileService._sniff_image_magic(_png_bytes()) is True

    def test_real_jpeg_accepted(self):
        img = Image.new("RGB", (32, 32), "blue")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        assert FileService._sniff_image_magic(buf.getvalue()) is True

    def test_plain_text_rejected(self):
        assert (
            FileService._sniff_image_magic(b"GET /etc/passwd HTTP/1.1\r\n")
            is False
        )

    def test_zip_rejected(self):
        # PK\x03\x04 is the ZIP local-file-header signature
        assert FileService._sniff_image_magic(b"PK\x03\x04mockzipcontent") is False

    def test_pdf_rejected(self):
        assert FileService._sniff_image_magic(b"%PDF-1.7\nfake pdf") is False

    def test_too_short_rejected(self):
        assert FileService._sniff_image_magic(b"\xff\xd8") is False

    def test_webp_brand_accepted(self):
        # RIFF....WEBPVP8...
        data = b"RIFF\x00\x00\x00\x00WEBPVP8 \x00\x00\x00\x00"
        assert FileService._sniff_image_magic(data) is True

    def test_riff_without_webp_brand_rejected(self):
        # RIFF without the WEBP brand at byte 8 — could be WAV, AVI etc.
        data = b"RIFF\x00\x00\x00\x00WAVE\x00\x00\x00\x00"
        assert FileService._sniff_image_magic(data) is False

    def test_heic_brand_accepted(self):
        # ISO-BMFF: size(4) + 'ftyp' + brand
        data = b"\x00\x00\x00\x20ftypheic\x00\x00\x00\x00mif1heic"
        assert FileService._sniff_image_magic(data) is True


# ─── decompression-bomb dimension guard ──────────────────────────────


class TestDimensionGuard:
    """A 100KB PNG can describe a 50000x50000 image; PIL's lazy decode
    would balloon to ~7.5GB RAM mid-process. Guard fires BEFORE pixel
    operations so we 400-fast instead of OOM-killing the worker."""

    def test_normal_image_allowed(self):
        img = Image.new("RGB", (1024, 1024))
        FileService._guard_dimensions(img)  # no raise

    def test_exactly_at_limit_allowed(self):
        # 25_000_000 pixels — the cap, not above it.
        img = MagicMock()
        img.size = (5000, 5000)
        FileService._guard_dimensions(img)

    def test_above_limit_rejected(self):
        img = MagicMock()
        img.size = (10_000, 10_000)  # 100M pixels — 4x cap
        with pytest.raises(HTTPException) as exc:
            FileService._guard_dimensions(img)
        assert exc.value.status_code == 400
        assert "exceeds" in exc.value.detail

    def test_classic_bomb_dimensions_rejected(self):
        img = MagicMock()
        img.size = (50_000, 50_000)
        with pytest.raises(HTTPException) as exc:
            FileService._guard_dimensions(img)
        assert exc.value.status_code == 400


# ─── EXIF orientation bake-in (integration with _process_image) ─────


class TestExifBakeIn:
    """_process_image must apply ImageOps.exif_transpose so any client
    that uploads a raw-from-camera JPEG (which embeds Orientation=6
    for portrait shots) gets pixels rotated correctly on the server."""

    @pytest.mark.asyncio
    async def test_landscape_with_orientation_6_becomes_portrait(self):
        # Synthesize a 200x100 JPEG with EXIF Orientation=6 (rotate
        # 90° CW to view correctly). After processing the pixel
        # dimensions should swap to portrait.
        import struct

        img = Image.new("RGB", (200, 100), "green")
        # Build minimal EXIF block: APP1 marker + 'Exif\0\0' + TIFF
        # header + 1 IFD entry (Orientation=6).
        exif = (
            b"Exif\x00\x00"
            b"II*\x00"
            b"\x08\x00\x00\x00"  # offset to first IFD
            b"\x01\x00"           # 1 entry
            b"\x12\x01"           # tag 0x0112 = Orientation
            b"\x03\x00"           # type SHORT
            b"\x01\x00\x00\x00"   # count 1
            + struct.pack("<H", 6) + b"\x00\x00"  # value 6
            + b"\x00\x00\x00\x00"  # next IFD offset
        )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif)

        svc = _make_service()
        processed = await svc._process_image(buf.getvalue())
        out = Image.open(io.BytesIO(processed))
        # Source was 200x100; orientation=6 means correct view is 100x200.
        assert out.size[0] < out.size[1], (
            f"EXIF transpose didn't run — output is {out.size}, expected portrait"
        )
