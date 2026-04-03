"""CLI entry point using Click."""

import gzip
import zlib
from enum import Enum
from pathlib import Path

import click

from snes_save_state_converter.mesen2.converter import convert as convert_to_mesen2
from snes_save_state_converter.mesen2.writer import write_mesen_savestate
from snes_save_state_converter.snes9x.converter import convert as convert_snes9x
from snes_save_state_converter.snes9x.parser import parse_snes9x
from snes_save_state_converter.zsnes.converter import convert as convert_zsnes
from snes_save_state_converter.zsnes.parser import parse_zsnes


class Format(Enum):
    SNES9X = "snes9x"
    ZSNES = "zsnes"


def _detect_format(path: Path) -> Format | None:
    """Detect save state format from file header."""
    raw = path.read_bytes()

    # Check for snes9x magic (possibly gzip-compressed)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    if raw[:9] == b"#!s9xsnp:":
        return Format.SNES9X

    # Check for ZSNES magic
    if raw[:22] == b"ZSNES Save State File ":
        return Format.ZSNES

    # ZSNES uncompressed with flag: 3-byte size (bit 23 set), then magic at offset 3
    if len(raw) > 31:
        size_val = int.from_bytes(raw[:3], "little")
        if (size_val & 0x800000) and raw[3:25] == b"ZSNES Save State File ":
            return Format.ZSNES

    # ZSNES compressed: 3-byte LE size, then zlib data (no magic anywhere)
    if len(raw) > 3:
        size_val = int.from_bytes(raw[:3], "little")
        if not (size_val & 0x800000) and 0 < size_val <= len(raw) - 3:
            try:
                zlib.decompress(raw[3 : 3 + size_val])
                return Format.ZSNES
            except zlib.error:
                pass

    return None


@click.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Output .mss file path.")
@click.option("--rom-name", type=str, default=None, help="ROM filename to embed in save state.")
def cli(input_file: Path, output: Path | None, rom_name: str | None) -> None:
    """Convert a SNES save state (Snes9x or ZSNES) to Mesen2 format."""
    output = output or input_file.with_suffix(".mss")
    rom_name = rom_name or input_file.stem

    fmt = _detect_format(input_file)

    if fmt == Format.SNES9X:
        click.echo(f"Reading Snes9x state: {input_file}")
        s9x = parse_snes9x(input_file)
        click.echo(f"  Version: {s9x.version}")
        click.echo(f"  Blocks: {', '.join(s9x.blocks.keys())}")

        click.echo("Converting...")
        state = convert_snes9x(s9x)
    elif fmt == Format.ZSNES:
        click.echo(f"Reading ZSNES state: {input_file}")
        zst = parse_zsnes(input_file)
        click.echo(f"  Version: {zst.version}")
        click.echo(f"  SPC: {'yes' if zst.spcon else 'no'}")

        click.echo("Converting...")
        state = convert_zsnes(zst)
    else:
        raise click.ClickException(f"Unsupported save state format: {input_file.name}")

    serialized = convert_to_mesen2(state)
    click.echo(f"  Serialized state size: {len(serialized)} bytes")
    write_mesen_savestate(output, serialized, rom_name)
    click.echo(f"Written: {output}")
