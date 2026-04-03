"""CLI entry point using Click."""

from pathlib import Path

import click

from snes_save_state_converter.mesen2.writer import write_mesen_savestate


def _detect_format(path: Path) -> str:
    """Detect save state format from file header/extension."""
    raw = path.read_bytes()

    # Check for snes9x magic (possibly gzip-compressed)
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    if raw[:9] == b"#!s9xsnp:":
        return "snes9x"

    # Check for ZSNES magic
    if raw[:22] == b"ZSNES Save State File ":
        return "zsnes"

    # Try ZSNES compressed format (3-byte size header)
    if len(raw) > 3:
        import zlib
        size_val = int.from_bytes(raw[:3], "little")
        if not (size_val & 0x800000) and size_val > 0 and size_val <= len(raw) - 3:
            try:
                zlib.decompress(raw[3 : 3 + size_val])
                return "zsnes"
            except zlib.error:
                pass

    # Fall back to extension
    ext = path.suffix.lower()
    if ext in (".zst", ".zs1", ".zs2", ".zs3", ".zs4", ".zs5", ".zs6", ".zs7", ".zs8", ".zs9"):
        return "zsnes"

    return "snes9x"  # default


@click.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Output .mss file path.")
@click.option("--rom-name", type=str, default=None, help="ROM filename to embed in save state.")
def cli(input_file: Path, output: Path | None, rom_name: str | None) -> None:
    """Convert a SNES save state (snes9x or ZSNES) to Mesen2 format."""
    output = output or input_file.with_suffix(".mss")
    rom_name = rom_name or input_file.stem

    fmt = _detect_format(input_file)

    if fmt == "zsnes":
        from snes_save_state_converter.zsnes.parser import parse_zst
        from snes_save_state_converter.zsnes.converter import convert_zst

        click.echo(f"Reading ZSNES state: {input_file}")
        zst = parse_zst(input_file)
        click.echo(f"  Version: {zst.version}")
        click.echo(f"  SPC: {'yes' if zst.spcon else 'no'}")

        click.echo("Converting to Mesen2 format...")
        serialized = convert_zst(zst)
    else:
        from snes_save_state_converter.converter import convert
        from snes_save_state_converter.snes9x.parser import parse_snes9x

        click.echo(f"Reading snes9x state: {input_file}")
        s9x = parse_snes9x(input_file)
        click.echo(f"  Version: {s9x.version}")
        click.echo(f"  Blocks: {', '.join(s9x.blocks.keys())}")

        click.echo("Converting to Mesen2 format...")
        serialized = convert(s9x)

    click.echo(f"  Serialized state size: {len(serialized)} bytes")
    write_mesen_savestate(output, serialized, rom_name)
    click.echo(f"Written: {output}")
