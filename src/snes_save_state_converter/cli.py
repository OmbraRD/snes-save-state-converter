"""CLI entry point using Click."""

from pathlib import Path

import click

from snes_save_state_converter.converter import convert
from snes_save_state_converter.mesen2.writer import write_mesen_savestate
from snes_save_state_converter.snes9x.parser import parse_snes9x


@click.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Output .mss file path.")
@click.option("--rom-name", type=str, default=None, help="ROM filename to embed in save state.")
def cli(input_file: Path, output: Path | None, rom_name: str | None) -> None:
    """Convert a SNES9x save state to Mesen2 format."""
    output = output or input_file.with_suffix(".mss")
    rom_name = rom_name or input_file.stem

    click.echo(f"Reading snes9x state: {input_file}")
    s9x = parse_snes9x(input_file)
    click.echo(f"  Version: {s9x.version}")
    click.echo(f"  Blocks: {', '.join(s9x.blocks.keys())}")

    click.echo("Converting to Mesen2 format...")
    serialized = convert(s9x)
    click.echo(f"  Serialized state size: {len(serialized)} bytes")

    write_mesen_savestate(output, serialized, rom_name)
    click.echo(f"Written: {output}")
