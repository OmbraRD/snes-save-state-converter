"""Decoders for snes9x coprocessor save-state blocks.

All multi-byte integers are big-endian unless noted otherwise.
"""


def _be(data: bytes, o: int, n: int) -> int:
    return int.from_bytes(data[o : o + n], "big")


def _be_s(data: bytes, o: int, n: int) -> int:
    return int.from_bytes(data[o : o + n], "big", signed=True)


# ---------------------------------------------------------------------------
# SuperFX  (SFX block)
# ---------------------------------------------------------------------------

def decode_sfx_block(data: bytes) -> dict:
    o = 0
    sfx: dict = {}

    regs = []
    for _ in range(16):
        regs.append(_be(data, o, 4)); o += 4
    sfx["avReg"] = regs

    sfx["vColorReg"] = _be(data, o, 4); o += 4
    sfx["vPlotOptionReg"] = _be(data, o, 4); o += 4
    sfx["vStatusReg"] = _be(data, o, 4); o += 4
    sfx["vPrgBankReg"] = _be(data, o, 4); o += 4
    sfx["vRomBankReg"] = _be(data, o, 4); o += 4
    sfx["vRamBankReg"] = _be(data, o, 4); o += 4
    sfx["vCacheBaseReg"] = _be(data, o, 4); o += 4
    sfx["vCacheFlags"] = _be(data, o, 4); o += 4
    sfx["vLastRamAdr"] = _be(data, o, 4); o += 4

    # Pointer fields stored as offsets relative to avReg base
    sfx["pvDreg_offset"] = _be_s(data, o, 4); o += 4
    sfx["pvSreg_offset"] = _be_s(data, o, 4); o += 4

    sfx["vRomBuffer"] = data[o]; o += 1
    sfx["vPipe"] = data[o]; o += 1
    sfx["vPipeAdr"] = _be(data, o, 4); o += 4
    sfx["vSign"] = _be(data, o, 4); o += 4
    sfx["vZero"] = _be(data, o, 4); o += 4
    sfx["vCarry"] = _be(data, o, 4); o += 4
    sfx["vOverflow"] = _be_s(data, o, 4); o += 4
    sfx["vErrorCode"] = _be_s(data, o, 4); o += 4
    sfx["vIllegalAddress"] = _be(data, o, 4); o += 4
    sfx["bBreakPoint"] = data[o]; o += 1
    sfx["vBreakPoint"] = _be(data, o, 4); o += 4
    sfx["vStepPoint"] = _be(data, o, 4); o += 4
    sfx["nRamBanks"] = _be(data, o, 4); o += 4
    sfx["nRomBanks"] = _be(data, o, 4); o += 4
    sfx["vMode"] = _be(data, o, 4); o += 4
    sfx["vPrevMode"] = _be(data, o, 4); o += 4

    # pvScreenBase offset
    sfx["pvScreenBase_offset"] = _be_s(data, o, 4); o += 4

    # apvScreen[32] offsets
    screen_offsets = []
    for _ in range(32):
        screen_offsets.append(_be_s(data, o, 4)); o += 4
    sfx["apvScreen_offsets"] = screen_offsets

    x_vals = []
    for _ in range(32):
        x_vals.append(_be(data, o, 4)); o += 4
    sfx["x"] = x_vals

    sfx["vScreenHeight"] = _be(data, o, 4); o += 4
    sfx["vScreenRealHeight"] = _be(data, o, 4); o += 4
    sfx["vPrevScreenHeight"] = _be(data, o, 4); o += 4
    sfx["vScreenSize"] = _be(data, o, 4); o += 4

    # More pointer offsets
    sfx["pvRamBank_offset"] = _be_s(data, o, 4); o += 4
    sfx["pvRomBank_offset"] = _be_s(data, o, 4); o += 4
    sfx["pvPrgBank_offset"] = _be_s(data, o, 4); o += 4

    ram_bank_offsets = []
    for _ in range(4):
        ram_bank_offsets.append(_be_s(data, o, 4)); o += 4
    sfx["apvRamBank_offsets"] = ram_bank_offsets

    sfx["bCacheActive"] = data[o]; o += 1
    sfx["pvCache_offset"] = _be_s(data, o, 4); o += 4
    sfx["avCacheBackup"] = data[o : o + 512]; o += 512
    sfx["vCounter"] = _be(data, o, 4); o += 4
    sfx["vInstCount"] = _be(data, o, 4); o += 4
    sfx["vSCBRDirty"] = _be(data, o, 4); o += 4

    return sfx


# ---------------------------------------------------------------------------
# SA-1  (SA1 block + SAR block)
# ---------------------------------------------------------------------------

def decode_sa1_block(data: bytes, version: int) -> dict:
    o = 0
    sa1: dict = {}
    sa1["ShiftedPB"] = _be(data, o, 4); o += 4
    sa1["ShiftedDB"] = _be(data, o, 4); o += 4
    sa1["Flags"] = _be(data, o, 4); o += 4
    sa1["WaitingForInterrupt"] = data[o]; o += 1
    sa1["overflow"] = data[o]; o += 1
    sa1["in_char_dma"] = data[o]; o += 1
    sa1["op1"] = _be(data, o, 2); o += 2
    sa1["op2"] = _be(data, o, 2); o += 2
    sa1["arithmetic_op"] = _be_s(data, o, 4); o += 4
    sa1["sum"] = int.from_bytes(data[o : o + 8], "big"); o += 8
    sa1["VirtualBitmapFormat"] = data[o]; o += 1
    sa1["variable_bit_pos"] = data[o]; o += 1
    if version >= 7:
        sa1["Cycles"] = _be_s(data, o, 4); o += 4
        sa1["PrevCycles"] = _be_s(data, o, 4); o += 4
        sa1["TimerIRQLastState"] = _be_s(data, o, 4); o += 4
        sa1["HTimerIRQPos"] = _be_s(data, o, 4); o += 4
        sa1["VTimerIRQPos"] = _be_s(data, o, 4); o += 4
        sa1["HCounter"] = _be_s(data, o, 4); o += 4
        sa1["VCounter"] = _be_s(data, o, 4); o += 4
        sa1["PrevHCounter"] = _be_s(data, o, 4); o += 4
        sa1["MemSpeed"] = _be_s(data, o, 4); o += 4
        sa1["MemSpeedx2"] = _be_s(data, o, 4); o += 4
    return sa1


def decode_sar_block(data: bytes) -> dict:
    """SA-1 registers — same layout as main CPU REG block."""
    o = 0
    r: dict = {}
    r["PB"] = data[o]; o += 1
    r["DB"] = data[o]; o += 1
    r["P"] = _be(data, o, 2); o += 2
    r["A"] = _be(data, o, 2); o += 2
    r["D"] = _be(data, o, 2); o += 2
    r["S"] = _be(data, o, 2); o += 2
    r["X"] = _be(data, o, 2); o += 2
    r["Y"] = _be(data, o, 2); o += 2
    r["PC"] = _be(data, o, 2); o += 2
    return r


# ---------------------------------------------------------------------------
# DSP-1  (DP1 block)
# ---------------------------------------------------------------------------

def decode_dsp1_block(data: bytes) -> dict:
    o = 0
    d: dict = {}
    d["waiting4command"] = data[o]; o += 1
    d["first_parameter"] = data[o]; o += 1
    d["command"] = data[o]; o += 1
    d["in_count"] = _be(data, o, 4); o += 4
    d["in_index"] = _be(data, o, 4); o += 4
    d["out_count"] = _be(data, o, 4); o += 4
    d["out_index"] = _be(data, o, 4); o += 4
    d["parameters"] = data[o : o + 512]; o += 512
    d["output"] = data[o : o + 512]; o += 512
    # Remaining fields are 3D math state — many int16s
    # We store the rest as raw for potential future use
    d["_raw_tail"] = data[o:]
    return d


# ---------------------------------------------------------------------------
# DSP-2  (DP2 block)
# ---------------------------------------------------------------------------

def decode_dsp2_block(data: bytes) -> dict:
    o = 0
    d: dict = {}
    d["waiting4command"] = data[o]; o += 1
    d["command"] = data[o]; o += 1
    d["in_count"] = _be(data, o, 4); o += 4
    d["in_index"] = _be(data, o, 4); o += 4
    d["out_count"] = _be(data, o, 4); o += 4
    d["out_index"] = _be(data, o, 4); o += 4
    d["parameters"] = data[o : o + 512]; o += 512
    d["output"] = data[o : o + 512]; o += 512
    d["_raw_tail"] = data[o:]
    return d


# ---------------------------------------------------------------------------
# DSP-4  (DP4 block)
# ---------------------------------------------------------------------------

def decode_dsp4_block(data: bytes) -> dict:
    o = 0
    d: dict = {}
    d["waiting4command"] = data[o]; o += 1
    d["half_command"] = data[o]; o += 1
    d["command"] = _be(data, o, 2); o += 2
    d["in_count"] = _be(data, o, 4); o += 4
    d["in_index"] = _be(data, o, 4); o += 4
    d["out_count"] = _be(data, o, 4); o += 4
    d["out_index"] = _be(data, o, 4); o += 4
    d["parameters"] = data[o : o + 512]; o += 512
    d["output"] = data[o : o + 512]; o += 512
    d["_raw_tail"] = data[o:]
    return d


# ---------------------------------------------------------------------------
# ST-010  (ST0 block)
# ---------------------------------------------------------------------------

def decode_st010_block(data: bytes) -> dict:
    o = 0
    d: dict = {}
    d["input_params"] = data[o : o + 16]; o += 16
    d["output_params"] = data[o : o + 16]; o += 16
    d["op_reg"] = data[o]; o += 1
    d["execute"] = data[o]; o += 1
    d["control_enable"] = data[o]; o += 1
    return d


# ---------------------------------------------------------------------------
# OBC1  (OBC block + OBM block)
# ---------------------------------------------------------------------------

def decode_obc1_block(data: bytes) -> dict:
    o = 0
    d: dict = {}
    d["address"] = _be(data, o, 2); o += 2
    d["basePtr"] = _be(data, o, 2); o += 2
    d["shift"] = _be(data, o, 2); o += 2
    return d


# ---------------------------------------------------------------------------
# SPC7110  (S71 block)
# ---------------------------------------------------------------------------

def decode_spc7110_block(data: bytes) -> dict:
    o = 0
    s: dict = {}

    # Registers (all uint8)
    for reg in [
        "r4801", "r4802", "r4803", "r4804", "r4805", "r4806",
        "r4807", "r4808", "r4809", "r480a", "r480b", "r480c",
    ]:
        s[reg] = data[o]; o += 1

    for reg in [
        "r4811", "r4812", "r4813", "r4814", "r4815", "r4816",
        "r4817", "r4818",
    ]:
        s[reg] = data[o]; o += 1

    s["r481x"] = data[o]; o += 1
    s["r4814_latch"] = data[o]; o += 1
    s["r4815_latch"] = data[o]; o += 1

    for reg in [
        "r4820", "r4821", "r4822", "r4823", "r4824", "r4825",
        "r4826", "r4827", "r4828", "r4829", "r482a", "r482b",
        "r482c", "r482d", "r482e", "r482f",
        "r4830", "r4831", "r4832", "r4833", "r4834",
    ]:
        s[reg] = data[o]; o += 1

    s["dx_offset"] = _be(data, o, 4); o += 4
    s["ex_offset"] = _be(data, o, 4); o += 4
    s["fx_offset"] = _be(data, o, 4); o += 4

    s["r4840"] = data[o]; o += 1
    s["r4841"] = data[o]; o += 1
    s["r4842"] = data[o]; o += 1

    s["rtc_state"] = _be_s(data, o, 4); o += 4
    s["rtc_mode"] = _be_s(data, o, 4); o += 4
    s["rtc_index"] = _be(data, o, 4); o += 4

    s["decomp_mode"] = _be(data, o, 4); o += 4
    s["decomp_offset"] = _be(data, o, 4); o += 4
    s["decomp_buffer"] = data[o : o + 64]; o += 64
    s["decomp_buffer_rdoffset"] = _be(data, o, 4); o += 4
    s["decomp_buffer_wroffset"] = _be(data, o, 4); o += 4
    s["decomp_buffer_length"] = _be(data, o, 4); o += 4

    # 32 context entries (index, invert)
    contexts = []
    for _ in range(32):
        ctx = {"index": data[o], "invert": data[o + 1]}
        o += 2
        contexts.append(ctx)
    s["contexts"] = contexts

    return s


# ---------------------------------------------------------------------------
# S-RTC  (SRT block)
# ---------------------------------------------------------------------------

def decode_srtc_block(data: bytes) -> dict:
    o = 0
    d: dict = {}
    d["rtc_mode"] = _be_s(data, o, 4); o += 4
    d["rtc_index"] = _be_s(data, o, 4); o += 4
    return d


# ---------------------------------------------------------------------------
# BS-X  (BSX block)
# ---------------------------------------------------------------------------

def decode_bsx_block(data: bytes) -> dict:
    o = 0
    b: dict = {}
    b["dirty"] = data[o]; o += 1
    b["dirty2"] = data[o]; o += 1
    b["bootup"] = data[o]; o += 1
    b["flash_enable"] = data[o]; o += 1
    b["write_enable"] = data[o]; o += 1
    b["read_enable"] = data[o]; o += 1
    b["flash_command"] = _be(data, o, 4); o += 4
    b["old_write"] = _be(data, o, 4); o += 4
    b["new_write"] = _be(data, o, 4); o += 4
    b["out_index"] = data[o]; o += 1
    b["output"] = data[o : o + 32]; o += 32
    b["PPU"] = data[o : o + 32]; o += 32
    b["MMC"] = data[o : o + 16]; o += 16
    b["prevMMC"] = data[o : o + 16]; o += 16
    b["test2192"] = data[o : o + 32]; o += 32
    return b


# ---------------------------------------------------------------------------
# MSU-1  (MSU block)
# ---------------------------------------------------------------------------

def decode_msu1_block(data: bytes) -> dict:
    o = 0
    m: dict = {}
    m["STATUS"] = data[o]; o += 1
    m["DATA_SEEK"] = _be(data, o, 4); o += 4
    m["DATA_POS"] = _be(data, o, 4); o += 4
    m["TRACK_SEEK"] = _be(data, o, 2); o += 2
    m["CURRENT_TRACK"] = _be(data, o, 2); o += 2
    m["RESUME_TRACK"] = _be(data, o, 4); o += 4
    m["VOLUME"] = data[o]; o += 1
    m["CONTROL"] = data[o]; o += 1
    m["AUDIO_POS"] = _be(data, o, 4); o += 4
    m["RESUME_POS"] = _be(data, o, 4); o += 4
    return m
