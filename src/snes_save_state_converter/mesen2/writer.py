"""Assemble a complete Mesen2 .mss save-state file."""

import io
import struct
import zlib
from pathlib import Path

# Mesen2 2.1.1
_EMU_VERSION = (2 << 16) | (1 << 8) | 1
_FILE_FORMAT_VERSION = 4
_CONSOLE_TYPE_SNES = 0


def write_mesen_savestate(
    output_path: Path,
    serialized_data: bytes,
    rom_name: str = "converted",
) -> None:
    buf = io.BytesIO()

    # Header
    buf.write(b"MSS")
    buf.write(struct.pack("<I", _EMU_VERSION))
    buf.write(struct.pack("<I", _FILE_FORMAT_VERSION))
    buf.write(struct.pack("<I", _CONSOLE_TYPE_SNES))

    # Video data — dummy black frame
    w, h = 256, 224
    fb = b"\x00" * (w * h * 4)
    compressed_fb = zlib.compress(fb, 6)
    buf.write(struct.pack("<I", len(fb)))
    buf.write(struct.pack("<I", w))
    buf.write(struct.pack("<I", h))
    buf.write(struct.pack("<I", 100))  # scale = 1.00
    buf.write(struct.pack("<I", len(compressed_fb)))
    buf.write(compressed_fb)

    # ROM name
    rom_bytes = rom_name.encode("utf-8")
    buf.write(struct.pack("<I", len(rom_bytes)))
    buf.write(rom_bytes)

    # State payload (zlib compressed)
    compressed = zlib.compress(serialized_data, 1)
    buf.write(b"\x01")  # compressed flag
    buf.write(struct.pack("<I", len(serialized_data)))
    buf.write(struct.pack("<I", len(compressed)))
    buf.write(compressed)

    output_path.write_bytes(buf.getvalue())
