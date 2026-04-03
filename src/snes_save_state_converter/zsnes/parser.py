"""Parse ZSNES save state files (.zst) into structured data.

The ZST format is a flat binary dump with an optional zlib compression layer.
Header: ``ZSNES Save State File V143\\x1a\\x8f`` (28 bytes).
"""

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

ZST_HEADER_V143 = b"ZSNES Save State File V143\x1a\x8f"
ZST_HEADER_V060 = b"ZSNES Save State File V0.6\x1a\x3c"

# Section sizes
PH65816REGSIZE = 36
SPC_TIMER_SIZE = 8
PPU_REG_SIZE = 3019
WRAM_SIZE = 131072
VRAM_SIZE = 65536
PH_SPCSAVE = 65856
PH_DSPSAVE = 1068
DSP_MEM_SIZE = 256
EXTRA_DATA_SIZE = 220


def _le16(data: bytes, o: int) -> int:
    return int.from_bytes(data[o : o + 2], "little")


def _le32(data: bytes, o: int) -> int:
    return int.from_bytes(data[o : o + 4], "little")


def _le16s(data: bytes, o: int) -> int:
    return int.from_bytes(data[o : o + 2], "little", signed=True)


@dataclass
class ZsnesState:
    version: str = "143"
    # CPU registers
    a: int = 0
    x: int = 0
    y: int = 0
    s: int = 0
    d: int = 0
    db: int = 0
    pb: int = 0
    pc: int = 0
    p: int = 0
    e: int = 0
    irq: int = 0
    nmi: int = 0
    curypos: int = 0
    spcon: int = 0
    # PPU register block (3019 bytes raw)
    ppu_raw: bytes = b""
    # Main memory
    wram: bytes = b""
    vram: bytes = b""
    sram: bytes = b""
    # SPC
    spc_ram: bytes = b""
    spc_pc: int = 0
    spc_a: int = 0
    spc_x: int = 0
    spc_y: int = 0
    spc_p: int = 0
    spc_sp: int = 0
    spc_dp: int = 0
    spc_cycle: int = 0
    spc_ports: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    spc_timer_enable: int = 0
    spc_timer_target: list[int] = field(default_factory=lambda: [0, 0, 0])
    spc_timer_ticks: list[int] = field(default_factory=lambda: [0, 0, 0])
    spc_extra_ram: bytes = b""
    # DSP
    dsp_state: bytes = b""  # PHdspsave raw blob
    dsp_regs: bytes = b""  # DSPMem (256 bytes)
    # Extra data (v143)
    extra_data: bytes = b""
    # Expansion chips (raw blocks)
    c4_ram: bytes = b""
    sfx_ram: bytes = b""
    sfx_regs: bytes = b""
    sa1_regs: bytes = b""
    sa1_ram: bytes = b""
    sa1_extra: bytes = b""


def parse_zst(path: Path) -> ZsnesState:
    raw = path.read_bytes()
    state = ZsnesState()

    # Detect format
    if raw[:27] == ZST_HEADER_V143[:27]:
        state.version = "143"
        data = raw[28:]  # skip 28-byte header
    elif raw[:27] == ZST_HEADER_V060[:27]:
        state.version = "060"
        data = raw[28:]
    else:
        # Try compressed format: 3-byte size, then zlib data
        size_val = int.from_bytes(raw[:3], "little")
        if size_val & 0x800000:
            # Uncompressed with flag
            data = raw[3:]
            if data[:27] == ZST_HEADER_V143[:27]:
                state.version = "143"
                data = data[28:]
            else:
                raise ValueError("Not a valid ZST file")
        else:
            # Compressed
            data = zlib.decompress(raw[3 : 3 + size_val])
            state.version = "143"

    o = 0

    # === Section 1: CPU state (36 bytes) ===
    state.curypos = _le16(data, o + 1)
    state.spcon = data[o + 8]
    state.a = _le16(data, o + 13)
    state.db = data[o + 15]
    state.pb = data[o + 16]
    state.s = _le16(data, o + 17)
    state.d = _le16(data, o + 19)
    state.x = _le16(data, o + 21)
    state.y = _le16(data, o + 23)
    state.p = data[o + 25]
    state.e = data[o + 26]
    state.pc = _le16(data, o + 27)
    state.irq = data[o + 29]
    state.nmi = data[o + 35]
    o += PH65816REGSIZE

    # === SPC timers (8 bytes) ===
    # cycpbl and cycpblt
    o += SPC_TIMER_SIZE

    # === PPU register block (3019 bytes) ===
    state.ppu_raw = data[o : o + PPU_REG_SIZE]
    o += PPU_REG_SIZE

    # === WRAM (128KB) ===
    state.wram = data[o : o + WRAM_SIZE]
    o += WRAM_SIZE

    # === VRAM (64KB) ===
    state.vram = data[o : o + VRAM_SIZE]
    o += VRAM_SIZE

    # === SPC data (conditional on spcon) ===
    if state.spcon:
        # SPC RAM + registers (PHspcsave bytes)
        spc_block = data[o : o + PH_SPCSAVE]
        o += PH_SPCSAVE

        # Parse SPC block
        state.spc_ram = spc_block[0:65472]
        # After RAM: 80 bytes of ROM copy, then registers
        reg_off = 65552
        state.spc_pc = _le32(spc_block, reg_off) & 0xFFFF; reg_off += 4
        state.spc_a = _le32(spc_block, reg_off) & 0xFF; reg_off += 4
        state.spc_x = _le32(spc_block, reg_off) & 0xFF; reg_off += 4
        state.spc_y = _le32(spc_block, reg_off) & 0xFF; reg_off += 4
        state.spc_p = _le32(spc_block, reg_off) & 0xFF; reg_off += 4
        reg_off += 4  # spcNZ
        state.spc_sp = _le32(spc_block, reg_off) & 0xFF; reg_off += 4
        state.spc_dp = _le32(spc_block, reg_off); reg_off += 4
        state.spc_cycle = _le32(spc_block, reg_off); reg_off += 4
        state.spc_ports = [
            spc_block[reg_off],
            spc_block[reg_off + 1],
            spc_block[reg_off + 2],
            spc_block[reg_off + 3],
        ]
        reg_off += 4
        state.spc_timer_enable = spc_block[reg_off]; reg_off += 1
        state.spc_timer_target = [
            spc_block[reg_off],
            spc_block[reg_off + 1],
            spc_block[reg_off + 2],
        ]
        reg_off += 3
        state.spc_timer_ticks = [
            spc_block[reg_off],
            spc_block[reg_off + 1],
            spc_block[reg_off + 2],
        ]
        reg_off += 3
        reg_off += 1  # timrcall
        state.spc_extra_ram = spc_block[reg_off : reg_off + 64]

        # DSP state (PHdspsave bytes)
        state.dsp_state = data[o : o + PH_DSPSAVE]
        o += PH_DSPSAVE

        # DSP registers (256 bytes)
        state.dsp_regs = data[o : o + DSP_MEM_SIZE]
        o += DSP_MEM_SIZE

    # === Expansion chips (conditional) ===
    # TODO: parse C4, SFX, SA1, DSP1, SETA, SPC7110, DSP4 blocks
    # For now, skip to extra data

    # === Extra data (v143 only, 220 bytes) ===
    if state.version == "143" and o + EXTRA_DATA_SIZE <= len(data):
        state.extra_data = data[o : o + EXTRA_DATA_SIZE]
        o += EXTRA_DATA_SIZE

    # === SRAM (remaining data, variable size) ===
    if o < len(data):
        state.sram = data[o:]

    return state
