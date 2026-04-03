# SNES Save State Converter

Convert SNES emulator save states to [Mesen2](https://github.com/SourMesen/Mesen2) format.

> **DISCLAIMER**
This project is functional but needs broad testing across different games and save state versions. If you encounter issues, please [open a bug report](https://github.com/OmbraRD/snes-save-state-converter/issues) including:
> - Game name, region and CRC32 of the ROM
> - Source emulator and version (e.g. Snes9x 1.62, ZSNES 1.51)
> - The save state file attached
> - Description of the problem (crash, graphical glitch, audio issue, etc.)

## Supported input formats

| Emulator | Extensions | Notes |
|----------|-----------|-------|
| **Snes9x** | `.frz`, `.0xx` | Versions 6-12, gzip-compressed or raw |
| **ZSNES** | `.zst`, `.zs1`-`.zs9` | v0.60 and v1.43, zlib-compressed or raw |

Output is always Mesen2 `.mss` format (version 4).

## Installation

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```
uv sync
```

## Usage

```
snes-save-state-converter game.frz              # Snes9x -> Mesen2
snes-save-state-converter game.zst              # ZSNES -> Mesen2
snes-save-state-converter game.frz -o out.mss   # custom output path
snes-save-state-converter game.zst --rom-name "My Game.sfc"
```

The input format is auto-detected from the file header. The output `.mss` file can be loaded in Mesen2 with the same ROM loaded.

## What gets converted

### Core state (fully mapped)
- **65C816 CPU** -- all registers (A, X, Y, S, D, DB, PB, PC, P, emulation mode)
- **PPU** -- all background layers, scroll positions, Mode 7 matrix, VRAM address/remapping, screen brightness, forced blank, window masking, color math
- **VRAM** (64 KB), **CGRAM** (512 bytes), **OAM** (544 bytes), **WRAM** (128 KB), **SRAM**
- **DMA/HDMA** -- all 8 channel configurations, table addresses, line counters, transfer state
- **SPC700** -- all registers (A, X, Y, SP, PC, PSW), 64 KB RAM, port state, timers
- **DSP** -- 128 register bytes, voice state, echo configuration
- **Internal registers** -- NMI/IRQ enables, timers, joypad auto-read, ALU state

### Coprocessors (Snes9x only)
- **SuperFX / GSU** -- registers, status flags, cache, GSU RAM
- **SA-1** -- full 65C816 CPU state, DMA, timers, math unit, IRAM
- **DSP-1/2/3/4, ST-010/ST-011** -- NEC uPD77C25 set to idle state with RAM preserved
- **CX4** -- CPU set to stopped state, data RAM preserved
- **SPC7110** -- register state, ALU, decompression, optional RTC
- **BSX** -- cart registers, MMC state, Satellaview streams
- **MSU-1** -- track, data pointer, volume, control
- **OBC1, SDD-1** -- passthrough (minimal state)

### Timing
The converter synthesizes consistent Mesen2 timing state (master clock, CPU cycle count, SPC cycle, event scheduling) based on the source emulator's scanline position. HDMA initialization, DRAM refresh, and NMI/IRQ events are scheduled correctly for the target scanline.

## Architecture

```
src/snes_save_state_converter/
    cli.py                  # Click CLI, auto-detects input format
    converter.py            # Snes9x -> Mesen2 field mapping
    snes9x/
        parser.py           # .frz/.s9x block parser (gzip support)
        decoders.py         # Per-block decoders (CPU, PPU, DMA, SND, TIM)
        coprocessors.py     # Coprocessor block decoders
    zsnes/
        parser.py           # .zst parser (v0.60/v1.43, zlib support)
        converter.py        # ZST -> Mesen2 field mapping
    mesen2/
        serializer.py       # Key-value binary writer
        writer.py           # .mss file assembly (header, video, zlib)
        coprocessors.py     # Coprocessor state writers
```

## How it works

Each emulator stores save state data in its own format:

- **Snes9x** uses named blocks (`CPU`, `REG`, `PPU`, `DMA`, `VRA`, `RAM`, `SND`, etc.) with big-endian fields
- **ZSNES** uses a flat binary dump with a 3019-byte PPU register block, where VRAM addresses are byte-addressed (doubled from SNES word addresses)
- **Mesen2** uses a key-value binary format where each field is stored as `[null-terminated key][uint32 size][value bytes]` in little-endian

The converter parses the source format, maps each field to the corresponding Mesen2 key (applying the correct normalization, type sizes, and encoding conversions), then assembles the `.mss` file with header, dummy video frame, and zlib-compressed state data.

Key encoding differences handled:
- Snes9x big-endian integers to Mesen2 little-endian
- ZSNES byte-addressed VRAM pointers to Mesen2 word addresses (`>> 1`)
- ZSNES inverted VRAM increment direction flag
- Snes9x VMA.Shift (0,5,6,7) to Mesen2 VramAddressRemapping (0,1,2,3)
- Snes9x/ZSNES OAM name select encoding to Mesen2's `(n+1) << 12` formula
- Mesen2 `enum class` types default to 4 bytes (not 1)
- SPC timer stage mapping between blargg's model and Mesen2's toggle-based model

## Limitations

- **DSP voice state** is mapped directly between emulator internal representations. Audio resumes correctly but there may be a brief glitch on the first frame as voices resync.
- **Coprocessors** that use fundamentally different internal models (NEC DSP chips, CX4) are set to idle state with RAM preserved rather than attempting cycle-accurate state mapping.
- **ZSNES coprocessor** save state conversion is not yet implemented (standard SNES games only).
- The output `.mss` includes a black placeholder screenshot thumbnail.

## TODO

- [x] Snes9x save state parser (gzip, block splitting, version 6-12)
- [x] Snes9x per-block decoders (CPU, REG, PPU, DMA, SND, TIM) verified field-by-field against source
- [x] Snes9x coprocessor decoders (SuperFX, SA-1, DSP-1/2/4, CX4, SPC7110, S-RTC, OBC1, BSX, MSU-1, ST-010)
- [x] Mesen2 binary serializer (key-value format with correct normalization and type sizes)
- [x] Mesen2 .mss file writer (header, video placeholder, zlib compression)
- [x] Full Snes9x -> Mesen2 conversion (CPU, PPU, SPC/DSP, DMA/HDMA, memory, internal registers, coprocessors)
- [x] SPC timer stage mapping (blargg prescaler/counter/output to Mesen2 toggle-based model)
- [x] All Mesen2 field types verified against source (enum class 4-byte sizes, voice bitmasks, uint8/16/32/64)
- [x] All Mesen2 key names verified against NormalizeName algorithm (HScroll -> hscroll, etc.)
- [x] ZSNES save state parser (v0.60 and v1.43, zlib support)
- [x] ZSNES PPU register block decoder (3019-byte sndrot layout mapped from regs.inc)
- [x] ZSNES VRAM pointer byte-to-word address conversion (verified against regsw.inc handlers)
- [x] ZSNES DMA/HDMA state mapping (dmadata mirror verified, hdmatype/nexthdma/curhdma flags)
- [x] ZSNES OAM size mode reverse lookup (from regsw.inc objsize1/objsize2 tables)
- [x] ZSNES SPC state (registers, RAM, ports, timers, DSP registers)
- [x] Timing synthesis (scanline-aware master clock, event scheduling, HDMA init at scanline 0)
- [x] Format auto-detection (header sniffing for Snes9x vs ZSNES)
- [x] Full audit of Snes9x decoders against source (PPU, SND, CPU, REG, DMA, TIM - all verified correct)
- [x] Full audit of Mesen2 key names and types against source (0 missing keys, 0 size mismatches)
- [ ] ZSNES coprocessor save state support (SuperFX, SA-1, DSP-1, C4, SPC7110, SETA)
- [ ] ZSNES v1.43 extra data section parsing (220 bytes of additional system state)
- [ ] Capture screenshot thumbnail from VRAM/CGRAM for the .mss preview instead of black frame
- [ ] Add support for more input formats (bsnes/higan, RetroArch .state)
- [ ] Add support for more output formats (Snes9x, bsnes)
- [ ] Test with a broader set of games (Mode 7, Hi-Res, interlace, enhancement chips)
- [ ] Add `--info` flag to dump save state contents without converting
- [ ] SRAM size detection from ROM header (optional ROM input) for accurate cart.saveRam sizing

## License

MIT
