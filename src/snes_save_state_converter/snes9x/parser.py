"""Parse snes9x save state files (.s9x) into block-level data."""

import gzip
from dataclasses import dataclass, field
from pathlib import Path

SNES9X_MAGIC = b"#!s9xsnp:"


@dataclass
class Snes9xState:
    version: int = 0
    blocks: dict[str, bytes] = field(default_factory=dict)


def parse_snes9x(path: Path) -> Snes9xState:
    """Read a snes9x save state file and split it into named blocks.

    The file may be gzip-compressed.  The header is ``#!s9xsnp:XXXX\\n``
    followed by blocks in the format ``NAM:LLLLLL:DATA``.
    """
    raw = path.read_bytes()

    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)

    if not raw.startswith(SNES9X_MAGIC):
        raise ValueError("Not a valid snes9x save state")

    # Header: #!s9xsnp:XXXX\n  (version is between the last ':' and '\n')
    newline_pos = raw.index(b"\n", len(SNES9X_MAGIC))
    version_str = raw[len(SNES9X_MAGIC) : newline_pos].decode("ascii").strip()
    version = int(version_str)

    state = Snes9xState(version=version)

    # Skip past header line
    pos = raw.index(b"\n", 0) + 1

    while pos < len(raw):
        if pos + 3 > len(raw):
            break
        block_name = raw[pos : pos + 3].decode("ascii")
        pos += 3

        if pos >= len(raw) or raw[pos : pos + 1] != b":":
            break
        pos += 1

        length_bytes = raw[pos : pos + 6]
        pos += 6
        try:
            length = int(length_bytes.decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            length = int.from_bytes(length_bytes, "little")

        if pos >= len(raw) or raw[pos : pos + 1] != b":":
            break
        pos += 1

        state.blocks[block_name] = raw[pos : pos + length]
        pos += length

    return state
