"""Write Mesen2 coprocessor state from decoded snes9x blocks.

Each ``write_*`` function takes a :class:`MesenSerializer` and the decoded
snes9x coprocessor dict, and emits the corresponding Mesen2 key-value pairs.

The Mesen2 prefix for all coprocessor state is ``cart.coprocessor.``.

Important: the two emulators have fundamentally different internal
representations for several coprocessors.  snes9x stores high-level I/O
state while Mesen2 cycle-accurately emulates the actual chip.  Where a
one-to-one mapping doesn't exist we set reasonable defaults so that the
converted state is loadable and execution can resume.
"""

from snes_save_state_converter.mesen2.serializer import MesenSerializer

_CP = "cart.coprocessor."


# ===================================================================
# SuperFX / GSU
# ===================================================================

def write_gsu(ser: MesenSerializer, sfx: dict, gsu_ram: bytes) -> None:
    p = _CP

    ser.write_u64(p + "cycleCount", 0)
    ser.write_u8(p + "registerLatch", 0)
    ser.write_u8(p + "programBank", sfx["vPrgBankReg"] & 0xFF)
    ser.write_u8(p + "romBank", sfx["vRomBankReg"] & 0xFF)
    ser.write_u8(p + "ramBank", sfx["vRamBankReg"] & 0xFF)

    status = sfx["vStatusReg"]
    ser.write_bool(p + "irqDisabled", bool(status & 0x04))
    ser.write_bool(p + "highSpeedMode", bool(sfx["vPlotOptionReg"] & 0x20))
    ser.write_bool(p + "clockSelect", bool(sfx["vPlotOptionReg"] & 0x20))
    ser.write_bool(p + "backupRamEnabled", False)

    ser.write_u8(p + "screenBase", (sfx["vMode"] >> 2) & 0xFF)
    ser.write_u8(p + "colorGradient", sfx["vColorReg"] & 0xFF)
    bpp = sfx["vMode"] & 0x03
    plot_bpp_map = {0: 2, 1: 4, 2: 0, 3: 8}
    ser.write_u8(p + "plotBpp", plot_bpp_map.get(bpp, 2))
    sh = sfx["vScreenHeight"]
    screen_height_map = {128: 0, 160: 1, 192: 2, 256: 3}
    ser.write_u8(p + "screenHeight", screen_height_map.get(sh, 0))

    ser.write_bool(p + "gsuRamAccess", False)
    ser.write_bool(p + "gsuRomAccess", False)
    ser.write_u16(p + "cacheBase", sfx["vCacheBaseReg"] & 0xFFFF)

    plot_opt = sfx["vPlotOptionReg"]
    ser.write_bool(p + "plotTransparent", bool(plot_opt & 0x01))
    ser.write_bool(p + "plotDither", bool(plot_opt & 0x02))
    ser.write_bool(p + "colorHighNibble", bool(plot_opt & 0x04))
    ser.write_bool(p + "colorFreezeHigh", bool(plot_opt & 0x08))
    ser.write_bool(p + "objMode", bool(plot_opt & 0x10))

    ser.write_u8(p + "colorReg", sfx["vColorReg"] & 0xFF)
    # src/dest reg indices from pointer offsets (each uint32 = 4 bytes)
    src_idx = max(0, sfx["pvSreg_offset"] // 4) & 0xF
    dst_idx = max(0, sfx["pvDreg_offset"] // 4) & 0xF
    ser.write_u8(p + "srcReg", src_idx)
    ser.write_u8(p + "destReg", dst_idx)

    ser.write_u8(p + "romReadBuffer", sfx["vRomBuffer"])
    ser.write_u8(p + "romDelay", 0)
    ser.write_u8(p + "programReadBuffer", sfx["vPipe"])
    ser.write_u16(p + "ramWriteAddress", sfx["vLastRamAdr"] & 0xFFFF)
    ser.write_u8(p + "ramWriteValue", 0)
    ser.write_u8(p + "ramDelay", 0)
    ser.write_u16(p + "ramAddress", sfx["vLastRamAdr"] & 0xFFFF)

    # Pixel caches (zeroed — will rebuild)
    for cache_name in ("primaryCache", "secondaryCache"):
        cp = p + cache_name + "."
        ser.write_u8(cp + "x", 0)
        ser.write_u8(cp + "y", 0)
        ser.write_u8(cp + "validBits", 0)
    ser.write_array_u8(p + "primaryCache.pixels", bytes(8))
    ser.write_array_u8(p + "secondaryCache.pixels", bytes(8))

    # Status flags
    sfr = p + "sfr."
    ser.write_bool(sfr + "alt1", bool(status & 0x0100))
    ser.write_bool(sfr + "alt2", bool(status & 0x0200))
    ser.write_bool(sfr + "carry", bool(sfx["vCarry"]))
    ser.write_bool(sfr + "immHigh", False)
    ser.write_bool(sfr + "immLow", False)
    ser.write_bool(sfr + "irq", bool(status & 0x8000))
    ser.write_bool(sfr + "overflow", bool(sfx["vOverflow"]))
    ser.write_bool(sfr + "prefix", False)
    ser.write_bool(sfr + "romReadPending", False)
    ser.write_bool(sfr + "running", bool(status & 0x0020))
    ser.write_bool(sfr + "sign", bool(sfx["vSign"]))
    ser.write_bool(sfr + "zero", bool(sfx["vZero"]))

    # R0-R15 (uint16 array)
    r16 = [r & 0xFFFF for r in sfx["avReg"]]
    ser.write_array_u16(p + "r", r16)

    ser.write_bool(p + "waitForRamAccess", False)
    ser.write_bool(p + "waitForRomAccess", False)
    ser.write_bool(p + "stopped", not bool(status & 0x0020))

    # Cache valid bits (32 uint8)
    cache_valid = []
    flags = sfx["vCacheFlags"]
    for i in range(32):
        cache_valid.append(1 if (flags & (1 << i)) else 0)
    ser.write_array_u8(p + "cacheValid", cache_valid)

    ser.write_array_u8(p + "cache", sfx["avCacheBackup"][:512].ljust(512, b"\x00"))

    # GSU RAM
    ser.write_array_u8(p + "gsuRam", gsu_ram)


# ===================================================================
# SA-1
# ===================================================================

def write_sa1(
    ser: MesenSerializer,
    sa1: dict,
    sar: dict,
    fillram: bytes,
    iram: bytes,
) -> None:
    p = _CP

    def _fr(addr: int) -> int:
        return fillram[addr] if 0 <= addr < len(fillram) else 0

    def _fr16(addr: int) -> int:
        return _fr(addr) | (_fr(addr + 1) << 8)

    # SA-1 has its own 65C816 CPU — serialized as a nested SnesCpu
    cp = p + "cpu."
    ser.write_u16(cp + "a", sar["A"])
    ser.write_u64(cp + "cycleCount", max(sa1.get("Cycles", 0), 0))
    ser.write_u16(cp + "d", sar["D"])
    ser.write_u8(cp + "dbr", sar["DB"])
    ser.write_bool(cp + "emulationMode", False)
    ser.write_u8(cp + "irqSource", 0)
    ser.write_u8(cp + "k", sar["PB"])
    ser.write_u8(cp + "nmiFlagCounter", 0)
    ser.write_u16(cp + "pc", sar["PC"])
    ser.write_u8(cp + "prevIrqSource", 0)
    ser.write_u8(cp + "ps", sar["P"] & 0xFF)
    ser.write_u16(cp + "sp", sar["S"])
    ser.write_u8(cp + "stopState", 2 if sa1["WaitingForInterrupt"] else 0)
    ser.write_u16(cp + "x", sar["X"])
    ser.write_u16(cp + "y", sar["Y"])
    ser.write_bool(cp + "irqLock", False)
    ser.write_bool(cp + "needNmi", False)
    ser.write_bool(cp + "waiOver", False)

    # SA-1 control state from FillRAM registers
    ser.write_u16(p + "sa1ResetVector", _fr16(0x2203))
    ser.write_u16(p + "sa1IrqVector", _fr16(0x2207))
    ser.write_u16(p + "sa1NmiVector", _fr16(0x2205))
    r2209 = _fr(0x2209)
    ser.write_bool(p + "sa1IrqRequested", bool(r2209 & 0x80))
    sa1_ie = _fr(0x220A)
    ser.write_bool(p + "sa1IrqEnabled", bool(sa1_ie & 0x80))
    ser.write_bool(p + "sa1NmiRequested", bool(r2209 & 0x10))
    ser.write_bool(p + "sa1NmiEnabled", bool(sa1_ie & 0x10))
    ser.write_bool(p + "sa1Wait", bool(_fr(0x2200) & 0x60))
    ser.write_bool(p + "sa1Reset", bool(_fr(0x2200) & 0x80))
    ser.write_bool(p + "dmaIrqEnabled", bool(sa1_ie & 0x20))
    ser.write_bool(p + "timerIrqEnabled", bool(sa1_ie & 0x40))

    ser.write_u8(p + "sa1MessageReceived", _fr(0x2221))
    ser.write_u8(p + "cpuMessageReceived", _fr(0x2220))
    ser.write_u16(p + "cpuIrqVector", _fr16(0x2241))
    ser.write_u16(p + "cpuNmiVector", _fr16(0x2243))
    r2209_cpu = _fr(0x2209)
    ser.write_bool(p + "useCpuIrqVector", bool(_fr(0x2200) & 0x01))
    ser.write_bool(p + "useCpuNmiVector", bool(_fr(0x2200) & 0x02))
    ser.write_bool(p + "cpuIrqRequested", bool(r2209_cpu & 0x80))
    ser.write_bool(p + "cpuIrqEnabled", True)
    ser.write_bool(p + "charConvIrqFlag", bool(sa1["in_char_dma"]))
    ser.write_bool(p + "charConvIrqEnabled", False)

    # BW-RAM
    ser.write_u8(p + "cpuBwBank", _fr(0x2224))
    ser.write_bool(p + "cpuBwWriteEnabled", True)
    ser.write_u8(p + "sa1BwBank", _fr(0x2225))
    ser.write_u8(p + "sa1BwMode", 0)
    ser.write_bool(p + "sa1BwWriteEnabled", True)
    ser.write_u8(p + "bwWriteProtectedArea", _fr(0x2228))
    ser.write_bool(p + "bwRam2BppMode", bool(sa1["VirtualBitmapFormat"]))

    ser.write_u8(p + "cpuIRamWriteProtect", 0)
    ser.write_u8(p + "sa1IRamWriteProtect", 0)

    # DMA
    ser.write_u32(p + "dmaSrcAddr", 0)
    ser.write_u32(p + "dmaDestAddr", 0)
    ser.write_u16(p + "dmaSize", 0)
    ser.write_bool(p + "dmaEnabled", False)
    ser.write_bool(p + "dmaPriority", False)
    ser.write_bool(p + "dmaCharConv", False)
    ser.write_bool(p + "dmaCharConvAuto", False)
    ser.write_u8(p + "dmaDestDevice", 0)
    ser.write_u8(p + "dmaSrcDevice", 0)
    ser.write_bool(p + "dmaRunning", False)
    ser.write_bool(p + "dmaIrqFlag", False)

    # Timers
    h_timer_en = sa1.get("HTimerIRQPos", 0) != 0
    v_timer_en = sa1.get("VTimerIRQPos", 0) != 0
    ser.write_bool(p + "horizontalTimerEnabled", h_timer_en)
    ser.write_bool(p + "verticalTimerEnabled", v_timer_en)
    ser.write_bool(p + "useLinearTimer", False)
    ser.write_u16(p + "hTimer", sa1.get("HTimerIRQPos", 0) & 0xFFFF)
    ser.write_u16(p + "vTimer", sa1.get("VTimerIRQPos", 0) & 0xFFFF)
    ser.write_u32(p + "linearTimerValue", 0)

    # Math
    ser.write_u8(p + "mathOp", sa1["arithmetic_op"] & 0xFF if sa1["arithmetic_op"] >= 0 else 0)
    ser.write_u16(p + "multiplicandDividend", sa1["op1"])
    ser.write_u16(p + "multiplierDivisor", sa1["op2"])
    ser.write_u64(p + "mathStartClock", 0)
    ser.write_u64(p + "mathOpResult", sa1["sum"] & 0xFFFFFFFFFFFFFFFF)
    ser.write_u8(p + "mathOverflow", sa1["overflow"])

    # Variable-length bit
    ser.write_bool(p + "varLenAutoInc", False)
    ser.write_u8(p + "varLenBitCount", sa1["variable_bit_pos"])
    ser.write_u32(p + "varLenAddress", 0)
    ser.write_u8(p + "varLenCurrentBit", 0)

    # Banks
    for i in range(4):
        ser.write_u8(f"{p}banks[{i}]", _fr(0x2220 + i))

    # Bitmap registers (zeroed)
    for i in range(8):
        ser.write_u8(f"{p}bitmapRegister1[{i}]", 0)
        ser.write_u8(f"{p}bitmapRegister2[{i}]", 0)

    ser.write_bool(p + "charConvDmaActive", False)
    ser.write_u8(p + "charConvBpp", 0)
    ser.write_u8(p + "charConvFormat", 0)
    ser.write_u8(p + "charConvWidth", 0)
    ser.write_u8(p + "charConvCounter", 0)
    ser.write_u8(p + "varLenCurrentBit", 0)
    ser.write_u64(p + "mathStartClock", 0)

    ser.write_u8(p + "lastAccessMemType", 0)
    ser.write_u8(p + "openBus", 0)
    ser.write_array_u8(p + "iRam", iram[:0x800].ljust(0x800, b"\x00") if iram else bytes(0x800))


# ===================================================================
# NEC DSP (DSP-1/2/3/4, ST010/ST011)
# ===================================================================

def write_nec_dsp(
    ser: MesenSerializer,
    dsp_data: dict,
    ram: bytes,
    ram_size: int,
    stack_size: int,
) -> None:
    """Write NecDsp state.

    snes9x stores high-level I/O state (command/parameters/output) while
    Mesen2 emulates the actual NEC uPD77C25 processor.  We set the NEC DSP
    to an idle state and populate the data RAM from the snes9x parameter
    and output buffers where possible.
    """
    p = _CP

    # NEC DSP registers — set to idle defaults
    ser.write_u16(p + "a", 0)
    ser.write_u16(p + "b", 0)
    ser.write_u16(p + "dp", 0)
    ser.write_u16(p + "dr", 0)
    ser.write_u16(p + "k", 0)
    ser.write_u16(p + "l", 0)
    ser.write_u16(p + "m", 0)
    ser.write_u16(p + "n", 0)
    ser.write_u16(p + "pc", 0)
    ser.write_u16(p + "rp", 0)
    ser.write_u16(p + "serialIn", 0)
    ser.write_u16(p + "serialOut", 0)
    ser.write_u8(p + "sp", 0)
    ser.write_u16(p + "sr", 0)
    ser.write_u16(p + "tr", 0)
    ser.write_u16(p + "trb", 0)

    # Flags A & B (all false = idle)
    for flag_set in ("flagsA", "flagsB"):
        fp = p + flag_set + "."
        ser.write_bool(fp + "carry", False)
        ser.write_bool(fp + "overflow0", False)
        ser.write_bool(fp + "overflow1", False)
        ser.write_bool(fp + "sign0", False)
        ser.write_bool(fp + "sign1", False)
        ser.write_bool(fp + "zero", True)

    ser.write_u64(p + "cycleCount", 0)
    ser.write_u8(p + "opCode", 0)
    ser.write_bool(p + "inRqmLoop", True)

    # RAM and stack
    ser.write_array_u8(p + "ram", ram[:ram_size].ljust(ram_size, b"\x00") if ram else bytes(ram_size))
    ser.write_array_u8(p + "stack", bytes(stack_size))


# ===================================================================
# CX4
# ===================================================================

def write_cx4(ser: MesenSerializer, cx4_ram: bytes) -> None:
    """Write Cx4 state.

    snes9x only saves the 8KB C4 RAM block.  Mesen2 emulates the full
    CX4 CPU so we set it to a stopped/idle state and populate the data RAM.
    """
    p = _CP

    ser.write_u64(p + "cycleCount", 0)
    ser.write_u16(p + "pb", 0)
    ser.write_u8(p + "pc", 0)
    ser.write_u32(p + "a", 0)
    ser.write_u16(p + "p", 0)
    ser.write_u8(p + "sp", 0)
    ser.write_u64(p + "mult", 0)
    ser.write_u32(p + "romBuffer", 0)
    ser.write_u8(p + "ramBuffer[0]", 0)
    ser.write_u8(p + "ramBuffer[1]", 0)
    ser.write_u8(p + "ramBuffer[2]", 0)
    ser.write_u32(p + "memoryDataReg", 0)
    ser.write_u32(p + "memoryAddressReg", 0)
    ser.write_u32(p + "dataPointerReg", 0)
    ser.write_bool(p + "negative", False)
    ser.write_bool(p + "zero", True)
    ser.write_bool(p + "carry", False)
    ser.write_bool(p + "overflow", False)
    ser.write_bool(p + "irqFlag", False)
    ser.write_bool(p + "stopped", True)
    ser.write_bool(p + "locked", False)
    ser.write_bool(p + "irqDisabled", False)
    ser.write_bool(p + "singleRom", False)
    ser.write_u8(p + "ramAccessDelay", 0)
    ser.write_u8(p + "romAccessDelay", 0)

    # Bus
    ser.write_u32(p + "bus.address", 0)
    ser.write_u8(p + "bus.delayCycles", 0)
    ser.write_bool(p + "bus.enabled", False)
    ser.write_bool(p + "bus.reading", False)
    ser.write_bool(p + "bus.writing", False)

    # DMA
    ser.write_u32(p + "dma.dest", 0)
    ser.write_bool(p + "dma.enabled", False)
    ser.write_u16(p + "dma.length", 0)
    ser.write_u32(p + "dma.source", 0)
    ser.write_u32(p + "dma.pos", 0)

    # Suspend
    ser.write_u32(p + "suspend.duration", 0)
    ser.write_bool(p + "suspend.enabled", False)

    # Cache
    ser.write_bool(p + "cache.enabled", False)
    ser.write_bool(p + "cache.lock[0]", False)
    ser.write_bool(p + "cache.lock[1]", False)
    ser.write_u32(p + "cache.address[0]", 0)
    ser.write_u32(p + "cache.address[1]", 0)
    ser.write_u32(p + "cache.base", 0)
    ser.write_u16(p + "cache.page", 0)
    ser.write_u16(p + "cache.programBank", 0)
    ser.write_u8(p + "cache.programCounter", 0)
    ser.write_u16(p + "cache.pos", 0)

    # Arrays
    ser.write_array_u8(p + "stack", bytes(8 * 4))  # 8 uint32 = 32 bytes
    ser.write_array_u8(p + "regs", bytes(16 * 4))  # 16 uint32 = 64 bytes
    ser.write_array_u8(p + "vectors", bytes(0x20))

    ser.write_array_u8(p + "prgRam[0]", bytes(256))
    ser.write_array_u8(p + "prgRam[1]", bytes(256))

    # CX4 data RAM — this is the 8KB block snes9x saves
    data_ram_size = 0xC00  # Cx4::DataRamSize
    padded = cx4_ram[:data_ram_size].ljust(data_ram_size, b"\x00") if cx4_ram else bytes(data_ram_size)
    ser.write_array_u8(p + "dataRam", padded)


# ===================================================================
# SPC7110
# ===================================================================

def write_spc7110(ser: MesenSerializer, s71: dict, rtc_data: bytes | None) -> None:
    p = _CP

    ser.write_array_u8(p + "decompBuffer", bytes(32))
    # Data ROM banks
    banks = [
        s71.get("r4831", 0),
        s71.get("r4832", 0),
        s71.get("r4833", 0),
    ]
    ser.write_array_u8(p + "dataRomBanks", banks)

    ser.write_u32(p + "directoryBase",
                  s71.get("r4801", 0) | (s71.get("r4802", 0) << 8) | (s71.get("r4803", 0) << 16))
    ser.write_u8(p + "directoryIndex", 0)
    ser.write_u16(p + "targetOffset",
                  s71.get("r4804", 0) | (s71.get("r4805", 0) << 8))
    ser.write_u16(p + "dataLengthCounter",
                  s71.get("r4809", 0) | (s71.get("r480a", 0) << 8))
    ser.write_u8(p + "skipBytes", 0)
    ser.write_u8(p + "decompFlags", 0)
    ser.write_u8(p + "decompMode", s71["decomp_mode"] & 0xFF)
    ser.write_u32(p + "srcAddress", 0)
    ser.write_u32(p + "decompOffset", s71["decomp_offset"])
    ser.write_u8(p + "decompStatus", 0)

    # ALU
    ser.write_u32(p + "dividend",
                  s71.get("r4820", 0) | (s71.get("r4821", 0) << 8) |
                  (s71.get("r4822", 0) << 16) | (s71.get("r4823", 0) << 24))
    ser.write_u16(p + "multiplier",
                  s71.get("r4824", 0) | (s71.get("r4825", 0) << 8))
    ser.write_u16(p + "divisor",
                  s71.get("r4826", 0) | (s71.get("r4827", 0) << 8))
    ser.write_u32(p + "multDivResult", 0)
    ser.write_u16(p + "remainder", 0)
    ser.write_u8(p + "aluState", 0)
    ser.write_u8(p + "aluFlags", 0)
    ser.write_u8(p + "sramEnabled", s71.get("r4834", 0))
    ser.write_u8(p + "dataRomSize", s71.get("r4830", 0))

    # Read state
    ser.write_u32(p + "readBase",
                  s71.get("r4811", 0) | (s71.get("r4812", 0) << 8) | (s71.get("r4813", 0) << 16))
    ser.write_u16(p + "readOffset",
                  s71.get("r4814", 0) | (s71.get("r4815", 0) << 8))
    ser.write_u16(p + "readStep",
                  s71.get("r4816", 0) | (s71.get("r4817", 0) << 8))
    ser.write_u8(p + "readMode", s71.get("r4818", 0))
    ser.write_u8(p + "readBuffer", 0)

    # Decomp state (nested)
    dp = p + "decomp."
    ser.write_u32(dp + "bpp", 0)
    ser.write_u32(dp + "offset", 0)
    ser.write_u32(dp + "bits", 0)
    ser.write_u16(dp + "range", 0)
    ser.write_u16(dp + "input", 0)
    ser.write_u8(dp + "output", 0)
    ser.write_u64(dp + "pixels", 0)
    ser.write_u64(dp + "colormap", 0)
    ser.write_u32(dp + "result", 0)

    for i in range(15):
        for ctx in range(5):
            ser.write_u8(f"{dp}context[{ctx}][{i}].swap[{i}]", 0)
            ser.write_u8(f"{dp}context[{ctx}][{i}].prediction[{i}]", 0)

    # RTC (optional)
    if rtc_data and len(rtc_data) >= 16:
        rp = p + "rtc."
        ser.write_array_u8(rp + "regs", rtc_data[:16])
        ser.write_u64(rp + "lastTime", 0)
        ser.write_u8(rp + "enabled", 1)
        ser.write_i16(rp + "mode", s71.get("rtc_mode", 0))
        ser.write_i16(rp + "index", s71.get("rtc_index", 0))


# ===================================================================
# MSU-1
# ===================================================================

def write_msu1(ser: MesenSerializer, msu: dict) -> None:
    """MSU-1 is at the console level (prefix ``msu1.``), not cart.coprocessor."""
    p = "msu1."
    ser.write_u16(p + "trackSelect", msu["CURRENT_TRACK"])
    ser.write_u32(p + "tmpDataPointer", msu["DATA_SEEK"])
    ser.write_u32(p + "dataPointer", msu["DATA_POS"])
    ser.write_bool(p + "repeat", bool(msu["CONTROL"] & 0x02))
    ser.write_bool(p + "paused", not bool(msu["CONTROL"] & 0x01))
    ser.write_u8(p + "volume", msu["VOLUME"])
    ser.write_bool(p + "trackMissing", False)
    ser.write_bool(p + "audioBusy", bool(msu["STATUS"] & 0x40))
    ser.write_bool(p + "dataBusy", bool(msu["STATUS"] & 0x80))
    # offset — Mesen reloads the track file from this offset
    ser.write_u32(p + "offset", msu["AUDIO_POS"])


# ===================================================================
# BSX
# ===================================================================

def write_bsx_cart(ser: MesenSerializer, bsx: dict) -> None:
    p = _CP

    # BsxCart state — regs + psram
    ser.write_array_u8(p + "psRam", bytes(0))  # size depends on ROM
    regs = list(bsx.get("MMC", bytes(16)))[:16]
    while len(regs) < 16:
        regs.append(0)
    ser.write_array_u8(p + "regs", regs)

    dirty_regs = list(bsx.get("prevMMC", bytes(16)))[:16]
    while len(dirty_regs) < 16:
        dirty_regs.append(0)
    ser.write_array_u8(p + "dirtyRegs", dirty_regs)
    ser.write_bool(p + "dirty", bool(bsx.get("dirty", 0)))

    # Satellaview nested (minimal)
    sp = p + "satellaview."
    ser.write_u8(sp + "extOutput", bsx.get("out_index", 0))
    ser.write_u8(sp + "streamReg", 0)
    ser.write_u64(sp + "customDate", 0)  # int64
    ser.write_u64(sp + "prevMasterClock", 0)

    # Two streams (minimal defaults)
    for si in range(2):
        stp = f"{sp}stream[{si}]."
        ser.write_u16(stp + "channel", 0)
        ser.write_u8(stp + "prefix", 0)
        ser.write_u8(stp + "data", 0)
        ser.write_u8(stp + "status", 0)
        ser.write_bool(stp + "prefixLatch", False)
        ser.write_bool(stp + "dataLatch", False)
        ser.write_bool(stp + "firstPacket", True)
        ser.write_u32(stp + "fileOffset", 0)
        ser.write_u8(stp + "fileIndex", 0)
        ser.write_u16(stp + "queueLength", 0)
        ser.write_u8(stp + "prefixQueueLength", 0)
        ser.write_u8(stp + "dataQueueLength", 0)
        ser.write_u16(stp + "activeChannel", 0)
        ser.write_u8(stp + "activeFileIndex", 0)
        ser.write_u64(stp + "resetDate", 0)  # int64
        ser.write_u64(stp + "resetMasterClock", 0)


# ===================================================================
# SDD-1  (no snes9x block — transparent decompression)
# ===================================================================

def write_sdd1(ser: MesenSerializer) -> None:
    """SDD-1 has no snes9x save state block; write Mesen2 defaults."""
    p = _CP
    ser.write_u8(p + "allowDmaProcessing", 0)
    ser.write_u8(p + "processNextDma", 0)
    ser.write_bool(p + "needInit", True)
    ser.write_array_u8(p + "dmaAddress", bytes(8 * 4))   # uint32[8]
    ser.write_array_u8(p + "dmaLength", bytes(8 * 2))    # uint16[8]
    ser.write_array_u8(p + "selectedBanks", bytes(4))
    # sdd1Mmc → decompressor (nested, defaults)
    ser.write_u8(p + "sdd1Mmc.decompressor.readAddr", 0)
    ser.write_u8(p + "sdd1Mmc.decompressor.bitCount", 0)
