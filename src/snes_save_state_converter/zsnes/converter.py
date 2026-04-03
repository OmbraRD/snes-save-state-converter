"""Convert a parsed ZSNES state into a Mesen2 serialized binary blob.

PPU register offsets reference the 3019-byte ``sndrot`` block defined in
``cpu/regs.inc``.  All multi-byte values in the ZST are little-endian.
"""

from snes_save_state_converter.mesen2.serializer import MesenSerializer
from snes_save_state_converter.zsnes.parser import ZsnesState


def _ppu8(ppu: bytes, off: int) -> int:
    return ppu[off] if off < len(ppu) else 0


def _ppu16(ppu: bytes, off: int) -> int:
    return int.from_bytes(ppu[off : off + 2], "little") if off + 1 < len(ppu) else 0


def _ppu16s(ppu: bytes, off: int) -> int:
    return int.from_bytes(ppu[off : off + 2], "little", signed=True) if off + 1 < len(ppu) else 0


def _ppu32(ppu: bytes, off: int) -> int:
    return int.from_bytes(ppu[off : off + 4], "little") if off + 3 < len(ppu) else 0


def convert(zst: ZsnesState) -> bytes:
    ser = MesenSerializer()
    ppu = zst.ppu_raw

    # --- Timing: use ZSNES curypos for scanline --------------------------
    overscan = _ppu16(ppu, 0x6F) > 224
    is_pal = _ppu16(ppu, 0x6F) > 262
    vbl_start = 240 if overscan else 225
    vbl_end = 311 if is_pal else 261
    h_period = 1364
    scanline = zst.curypos  # always use actual scanline, 0 = start of frame
    in_vblank = scanline >= vbl_start
    master_clock = scanline * h_period
    master_clock = (master_clock + 7) & ~7
    dram_refresh_pos = 538 - (master_clock & 0x07)
    if scanline == 0:
        # Start of frame: hClock must be BEFORE HdmaInit event (~12)
        # so the HDMA init event fires correctly
        h_clock = 0
    elif in_vblank:
        # VBlank: past DRAM refresh, before EndOfScanline
        h_clock = dram_refresh_pos + 40
    else:
        # Mid-frame: past DRAM refresh
        h_clock = dram_refresh_pos + 40
    master_clock += h_clock
    fast_rom = True  # default; ZSNES doesn't store this directly
    spc_clock_rate = 32040 * 64
    master_clock_rate = 21477270
    spc_cycle = int(master_clock * spc_clock_rate / master_clock_rate)

    # =================================================================
    # CPU
    # =================================================================
    ser.write_u16("cpu.a", zst.a)
    ser.write_u64("cpu.cycleCount", master_clock)
    ser.write_u16("cpu.d", zst.d)
    ser.write_u8("cpu.dbr", zst.db)
    ser.write_bool("cpu.emulationMode", bool(zst.e))
    ser.write_u8("cpu.irqSource", 0)
    ser.write_u8("cpu.k", zst.pb)
    ser.write_u8("cpu.nmiFlagCounter", 0)
    ser.write_u16("cpu.pc", zst.pc)
    ser.write_u8("cpu.prevIrqSource", 0)
    ser.write_u8("cpu.ps", zst.p)
    ser.write_u16("cpu.sp", zst.s)
    ser.write_u8("cpu.stopState", 0)
    ser.write_u16("cpu.x", zst.x)
    ser.write_u16("cpu.y", zst.y)
    ser.write_bool("cpu.irqLock", False)
    ser.write_bool("cpu.needNmi", bool(zst.nmi))
    ser.write_bool("cpu.waiOver", False)

    # =================================================================
    # Memory Manager
    # =================================================================
    ser.write_u64("memoryManager.masterClock", master_clock)
    ser.write_u8("memoryManager.openBus", 0)
    ser.write_u8("memoryManager.cpuSpeed", 6 if fast_rom else 8)
    ser.write_u16("memoryManager.hClock", h_clock)
    ser.write_u16("memoryManager.dramRefreshPosition", dram_refresh_pos)
    ser.write_u32("memoryManager.memTypeBusA", 0)
    # Event scheduling depends on scanline position
    if scanline == 0:
        # Scanline 0: next event is HdmaInit
        ser.write_u8("memoryManager.nextEvent", 0)  # HdmaInit
        ser.write_u16("memoryManager.nextEventClock", 12 + (master_clock & 0x07))
    elif in_vblank:
        # VBlank: next event is EndOfScanline (no HDMA during VBlank)
        ser.write_u8("memoryManager.nextEvent", 3)  # EndOfScanline
        ser.write_u16("memoryManager.nextEventClock", 1360)
    else:
        # Active scanline: past DRAM refresh, next event is HdmaStart or EndOfScanline
        ser.write_u8("memoryManager.nextEvent", 3)  # EndOfScanline
        ser.write_u16("memoryManager.nextEventClock", 1360)
    wram = zst.wram if len(zst.wram) >= 0x20000 else zst.wram + b"\x00" * (0x20000 - len(zst.wram))
    ser.write_array_u8("memoryManager.workRam", wram[:0x20000])
    # WRAM address is a direct 17-bit address (not byte/word issue)
    ser.write_u32("memoryManager.registerHandlerB.wramPosition", _ppu32(ppu, 0xA1) & 0x1FFFF)

    # =================================================================
    # PPU
    # =================================================================
    ser.write_bool("ppu.forcedBlank", bool(_ppu8(ppu, 0x08)))
    ser.write_u8("ppu.screenBrightness", _ppu8(ppu, 0x06))
    ser.write_u16("ppu.scanline", scanline)
    ser.write_u32("ppu.frameCount", 0)
    ser.write_u8("ppu.bgMode", _ppu8(ppu, 0x1E))
    ser.write_bool("ppu.mode1Bg3Priority", bool(_ppu8(ppu, 0x1F)))

    scrnon = _ppu16(ppu, 0x6C)
    ser.write_u8("ppu.mainScreenLayers", scrnon & 0xFF)
    ser.write_u8("ppu.subScreenLayers", (scrnon >> 8) & 0xFF)

    # VRAM — ZSNES stores byte addresses, Mesen2 uses word addresses (>> 1)
    vram_addr_bytes = _ppu32(ppu, 0x65) & 0xFFFF
    addrincr = _ppu16(ppu, 0x61)
    incr_map = {2: 1, 64: 32, 128: 128, 256: 128}
    ser.write_u16("ppu.vramAddress", (vram_addr_bytes >> 1) & 0x7FFF)
    ser.write_u8("ppu.vramIncrementValue", incr_map.get(addrincr, 1))
    # vraminctype at offset 0x9D0 stores the FULL $2115 register value
    vraminctype = _ppu8(ppu, 0x09D0)
    ser.write_u8("ppu.vramAddressRemapping", (vraminctype >> 2) & 0x03)
    # Bit 7 of $2115: 1=increment on high byte ($2119) write = "second reg"
    # ZSNES vramincr at 0x63 is INVERTED (0=high, 1=low), so use vraminctype bit 7
    ser.write_bool("ppu.vramAddrIncrementOnSecondReg", bool(vraminctype & 0x80))
    ser.write_u16("ppu.vramReadBuffer", _ppu8(ppu, 0x64) | (_ppu8(ppu, 0x09E7) << 8))
    ser.write_u8("ppu.ppu1OpenBus", 0)
    ser.write_u8("ppu.ppu2OpenBus", 0)

    # CGRAM
    ser.write_u8("ppu.cgramAddress", _ppu16(ppu, 0x69) & 0xFF)
    ser.write_u8("ppu.mosaicSize", (_ppu8(ppu, 0x22) & 0x0F) + 1)
    ser.write_u8("ppu.mosaicEnabled", _ppu8(ppu, 0x21))

    # OAM — ZSNES stores byte addresses, Mesen2 uses word addresses
    objptr_bytes = _ppu32(ppu, 0x09)  # OBJ name base (byte addr)
    objptrn_bytes = _ppu32(ppu, 0x0D)  # OBJ name select (byte addr)
    name_offset = (objptrn_bytes - objptr_bytes) >> 1  # word offset
    if name_offset <= 0:
        name_offset = 0x1000  # minimum per SNES hardware
    # OAM size mode — reverse-lookup from ZSNES decoded sizes
    # ZSNES size encoding: 1=8px, 4=16px, 16=32px, 64=64px
    # Mode table from regsw.inc: .objsize1/.objsize2
    # Mode: 0:(1,4) 1:(1,16) 2:(1,64) 3:(4,16) 4:(4,64) 5:(16,64) 6:(1,4) 7:(1,4)
    sz1 = _ppu8(ppu, 0x11)
    sz2 = _ppu8(ppu, 0x12)
    size_mode_table = {
        (1, 4): 0, (1, 16): 1, (1, 64): 2,
        (4, 16): 3, (4, 64): 4, (16, 64): 5,
    }
    oam_mode = size_mode_table.get((sz1, sz2), 0)
    ser.write_u8("ppu.oamMode", oam_mode)
    ser.write_u16("ppu.oamBaseAddress", (objptr_bytes >> 1) & 0x7FFF)
    ser.write_u16("ppu.oamAddressOffset", name_offset & 0x7FFF)
    ser.write_u16("ppu.oamRamAddress", _ppu16(ppu, 0x19))
    ser.write_bool("ppu.enableOamPriority", bool(_ppu8(ppu, 0x1D)))
    ser.write_u8("ppu.oamWriteBuffer", 0)
    ser.write_bool("ppu.timeOver", False)
    ser.write_bool("ppu.rangeOver", False)

    resolutn = _ppu16(ppu, 0x6F)
    ser.write_bool("ppu.hiResMode", False)
    ser.write_bool("ppu.screenInterlace", bool(_ppu8(ppu, 0x09DE)))
    ser.write_bool("ppu.objInterlace", False)
    ser.write_bool("ppu.overscanMode", resolutn > 224)
    ser.write_bool("ppu.directColorMode", bool(_ppu8(ppu, 0x01C6) & 0x01))

    # Color math
    scaddset = _ppu8(ppu, 0x01C6)  # $2130
    scaddtype = _ppu8(ppu, 0x01C7)  # $2131
    ser.write_u32("ppu.colorMathClipMode", (scaddset >> 6) & 3)
    ser.write_u32("ppu.colorMathPreventMode", (scaddset >> 4) & 3)
    ser.write_bool("ppu.colorMathAddSubscreen", bool(scaddset & 0x02))
    ser.write_u8("ppu.colorMathEnabled", scaddtype & 0x3F)
    ser.write_bool("ppu.colorMathSubtractMode", bool(scaddtype & 0x80))
    ser.write_bool("ppu.colorMathHalveResult", bool(scaddtype & 0x40))

    r = _ppu8(ppu, 0x01C2) & 0x1F
    g = _ppu8(ppu, 0x01C3) & 0x1F
    b = _ppu8(ppu, 0x01C4) & 0x1F
    ser.write_u16("ppu.fixedColor", r | (g << 5) | (b << 10))

    ser.write_u8("ppu.hvScrollLatchValue", 0)
    ser.write_u8("ppu.hScrollLatchValue", 0)

    # Mask logic
    winlogica = _ppu8(ppu, 0x89)  # $212A
    winlogicb = _ppu8(ppu, 0x8A)  # $212B
    for i in range(4):
        ser.write_u32(f"ppu.maskLogic[{i}]", (winlogica >> (i * 2)) & 3)
    ser.write_u32("ppu.maskLogic[4]", winlogicb & 3)
    ser.write_u32("ppu.maskLogic[5]", (winlogicb >> 2) & 3)

    winenabm = _ppu8(ppu, 0x8B)  # $212E
    winenabs = _ppu8(ppu, 0x8C)  # $212F
    for i in range(5):
        ser.write_bool(f"ppu.windowMaskMain[{i}]", bool(winenabm & (1 << i)))
        ser.write_bool(f"ppu.windowMaskSub[{i}]", bool(winenabs & (1 << i)))

    # Mode 7
    m7set = _ppu8(ppu, 0x8D)  # $211A
    ser.write_i16("ppu.mode7.centerX", _ppu16s(ppu, 0x96))
    ser.write_i16("ppu.mode7.centerY", _ppu16s(ppu, 0x98))
    ser.write_bool("ppu.extBgEnabled", False)
    ser.write_bool("ppu.mode7.fillWithTile0", (m7set & 0xC0) == 0)
    ser.write_bool("ppu.mode7.horizontalMirroring", bool(m7set & 0x01))
    ser.write_i16("ppu.mode7.hscroll", _ppu16s(ppu, 0x4F))  # use BG1 hscroll for Mode 7
    ser.write_bool("ppu.mode7.largeMap", bool(m7set & 0x80))
    ser.write_i16("ppu.mode7.matrix[0]", _ppu16s(ppu, 0x8E))
    ser.write_i16("ppu.mode7.matrix[1]", _ppu16s(ppu, 0x90))
    ser.write_i16("ppu.mode7.matrix[2]", _ppu16s(ppu, 0x92))
    ser.write_i16("ppu.mode7.matrix[3]", _ppu16s(ppu, 0x94))
    ser.write_u8("ppu.mode7.valueLatch", 0)
    ser.write_bool("ppu.mode7.verticalMirroring", bool(m7set & 0x02))
    ser.write_i16("ppu.mode7.vscroll", _ppu16s(ppu, 0x59))  # BG1 vscroll

    ser.write_bool("ppu.cgramAddressLatch", False)
    ser.write_u8("ppu.cgramWriteBuffer", 0)
    ser.write_u16("ppu.internalOamAddress", _ppu16(ppu, 0x1B))
    ser.write_u8("ppu.internalCgramAddress", _ppu16(ppu, 0x69) & 0xFF)

    # Layers — ZSNES stores decoded pointers
    bg_ptr_offsets = [0x23, 0x25, 0x27, 0x29]  # tilemap pointers
    bg_chr_offsets = [0x47, 0x49, 0x4B, 0x4D]  # character pointers
    bg_hscroll = [0x4F, 0x51, 0x53, 0x55]
    bg_vscroll = [0x59, 0x5B, 0x5D, 0x5F]
    bg_scsize = [0x43, 0x44, 0x45, 0x46]
    bgtilesz = _ppu8(ppu, 0x20)
    for i in range(4):
        lp = f"ppu.layers[{i}]."
        # ZSNES stores byte addresses, Mesen2 uses word addresses (>> 1)
        ser.write_u16(lp + "chrAddress", (_ppu16(ppu, bg_chr_offsets[i]) >> 1) & 0x7FFF)
        sc = _ppu8(ppu, bg_scsize[i])
        ser.write_bool(lp + "doubleHeight", bool(sc & 2))
        ser.write_bool(lp + "doubleWidth", bool(sc & 1))
        ser.write_u16(lp + "hscroll", _ppu16(ppu, bg_hscroll[i]))
        ser.write_bool(lp + "largeTiles", bool(bgtilesz & (1 << i)))
        ser.write_u16(lp + "tilemapAddress", (_ppu16(ppu, bg_ptr_offsets[i]) >> 1) & 0x7FFF)
        ser.write_u16(lp + "vscroll", _ppu16(ppu, bg_vscroll[i]))

    # Windows
    win_regs = [
        _ppu8(ppu, 0x83),  # $2123
        _ppu8(ppu, 0x84),  # (high nibble of $2123 in ZSNES format)
        _ppu8(ppu, 0x85),  # $2124
        _ppu8(ppu, 0x86),
        _ppu8(ppu, 0x87),  # $2125
        _ppu8(ppu, 0x88),
    ]
    # ZSNES stores per-BG window enable as individual bytes, each holding the
    # 4-bit value for one BG's two windows from the $2123-$2125 register pair.
    # Reconstruct the original $2123/$2124/$2125 register values.
    reg_2123 = (win_regs[0] & 0x0F) | ((win_regs[1] & 0x0F) << 4)
    reg_2124 = (win_regs[2] & 0x0F) | ((win_regs[3] & 0x0F) << 4)
    reg_2125 = (win_regs[4] & 0x0F) | ((win_regs[5] & 0x0F) << 4)
    regs_w = [reg_2123, reg_2124, reg_2125]
    for w in range(2):
        wp = f"ppu.window[{w}]."
        for layer in range(6):
            bits = (regs_w[layer // 2] >> ((layer % 2) * 4 + w * 2)) & 3
            ser.write_bool(f"{wp}activeLayers[{layer}]", bool(bits & 2))
        for layer in range(6):
            bits = (regs_w[layer // 2] >> ((layer % 2) * 4 + w * 2)) & 3
            ser.write_bool(f"{wp}invertedLayers[{layer}]", bool(bits & 1))
        if w == 0:
            ser.write_u8(wp + "left", _ppu8(ppu, 0x7F))
            ser.write_u8(wp + "right", _ppu8(ppu, 0x80))
        else:
            ser.write_u8(wp + "left", _ppu8(ppu, 0x81))
            ser.write_u8(wp + "right", _ppu8(ppu, 0x82))

    # VRAM as uint16 LE array (32K words)
    vram_data = zst.vram
    vram_words = [
        int.from_bytes(vram_data[i : i + 2], "little")
        for i in range(0, min(len(vram_data), 0x10000), 2)
    ]
    vram_words.extend([0] * (0x8000 - len(vram_words)))
    ser.write_array_u16("ppu.vram", vram_words)

    # OAM (544 bytes from offset 0x01D0 in PPU block)
    oam_data = ppu[0x01D0 : 0x01D0 + 544]
    if len(oam_data) < 544:
        oam_data = oam_data + b"\x00" * (544 - len(oam_data))
    ser.write_array_u8("ppu.oamRam", oam_data)

    # CGRAM (256 uint16 from offset 0x05D0)
    cgram_data = ppu[0x05D0 : 0x05D0 + 512]
    cgram = []
    for i in range(0, min(len(cgram_data), 512), 2):
        cgram.append(int.from_bytes(cgram_data[i : i + 2], "little"))
    while len(cgram) < 256:
        cgram.append(0)
    ser.write_array_u16("ppu.cgram", cgram)

    # PPU internal timing
    ser.write_u16("ppu.horizontalLocation", 0)
    ser.write_bool("ppu.horizontalLocToggle", False)
    ser.write_u16("ppu.verticalLocation", 0)
    ser.write_bool("ppu.verticalLocationToggle", False)
    ser.write_bool("ppu.locationLatched", False)
    ser.write_u8("ppu.oddFrame", 0)
    ser.write_u16("ppu.vblankStartScanline", vbl_start)
    ser.write_u16("ppu.nmiScanline", vbl_start + 1)
    ser.write_u16("ppu.vblankEndScanline", vbl_end)
    ser.write_u16("ppu.adjustedVblankEndScanline", vbl_end)
    ser.write_u16("ppu.baseVblankEndScanline", vbl_end)
    ser.write_bool("ppu.overclockEnabled", False)
    ser.write_u16("ppu.drawStartX", 0)
    ser.write_u16("ppu.drawEndX", 0)
    ser.write_u16("ppu.mosaicScanlineCounter", 0)

    # Tile cache (zeroed)
    for ti in range(33):
        for la in range(4):
            for c in range(4):
                ser.write_u16(f"ppu.layerData[{la}].tiles[{ti}].chrData[{c}]", 0)
            ser.write_u16(f"ppu.layerData[{la}].tiles[{ti}].tilemapData", 0)
            ser.write_u16(f"ppu.layerData[{la}].tiles[{ti}].vscroll", 0)

    ser.write_u16("ppu.hOffset", 0)
    ser.write_u16("ppu.vOffset", 0)
    ser.write_u16("ppu.fetchBgStart", 0)
    ser.write_u16("ppu.fetchBgEnd", 0)
    ser.write_u16("ppu.fetchSpriteStart", 0)
    ser.write_u16("ppu.fetchSpriteEnd", 0)

    # =================================================================
    # DMA — parse from PPU block dmadata at offset 0xA5 (129 bytes)
    # =================================================================
    nexthdma = _ppu8(ppu, 0x0127)  # which channels run next scanline
    curhdma = _ppu8(ppu, 0x0128)   # which channels are enabled ($420C)
    hdmatype = _ppu8(ppu, 0x01C1)  # which channels need first-time init / do transfer
    ser.write_bool("dmaController.hdmaPending", False)
    ser.write_u8("dmaController.hdmaChannels", curhdma)  # $420C value
    ser.write_bool("dmaController.dmaPending", False)
    ser.write_u32("dmaController.dmaClockCounter", 0)
    ser.write_bool("dmaController.hdmaInitPending", False)
    ser.write_bool("dmaController.dmaStartDelay", False)
    ser.write_bool("dmaController.needToProcess", False)

    dma_base = 0xA5
    for i in range(8):
        dp = f"dmaController.channel[{i}]."
        ch_off = dma_base + i * 16  # 16 bytes per channel in ZSNES $43x0-$43xF
        if ch_off + 16 <= len(ppu):
            reg0 = _ppu8(ppu, ch_off)  # $43x0
            ser.write_bool(dp + "invertDirection", bool(reg0 & 0x80))
            ser.write_bool(dp + "hdmaIndirectAddressing", bool(reg0 & 0x40))
            ser.write_bool(dp + "unusedControlFlag", bool(reg0 & 0x20))
            ser.write_bool(dp + "decrement", bool(reg0 & 0x10))
            ser.write_bool(dp + "fixedTransfer", bool(reg0 & 0x08))
            ser.write_u8(dp + "transferMode", reg0 & 0x07)
            ser.write_u8(dp + "destAddress", _ppu8(ppu, ch_off + 1))
            ser.write_u16(dp + "srcAddress", _ppu16(ppu, ch_off + 2))
            ser.write_u8(dp + "srcBank", _ppu8(ppu, ch_off + 4))
            ser.write_u16(dp + "transferSize", _ppu16(ppu, ch_off + 5))
            ser.write_u8(dp + "hdmaBank", _ppu8(ppu, ch_off + 7))
            ser.write_u16(dp + "hdmaTableAddress", _ppu16(ppu, ch_off + 8))
            ser.write_u8(dp + "hdmaLineCounterAndRepeat", _ppu8(ppu, ch_off + 10))
            # doTransfer: channel will transfer data on next scanline
            ser.write_bool(dp + "doTransfer", bool(hdmatype & (1 << i)))
            # hdmaFinished: channel enabled in $420C but no longer in nexthdma
            ser.write_bool(dp + "hdmaFinished", bool((curhdma & (1 << i)) and not (nexthdma & (1 << i))))
            ser.write_bool(dp + "dmaActive", False)
            ser.write_u8(dp + "unusedRegister", _ppu8(ppu, ch_off + 11) if ch_off + 11 < len(ppu) else 0)
        else:
            # Default empty channel
            for field, writer in [
                ("decrement", ser.write_bool), ("destAddress", ser.write_u8),
                ("doTransfer", ser.write_bool), ("fixedTransfer", ser.write_bool),
                ("hdmaBank", ser.write_u8), ("hdmaFinished", ser.write_bool),
                ("hdmaIndirectAddressing", ser.write_bool),
                ("hdmaLineCounterAndRepeat", ser.write_u8),
                ("hdmaTableAddress", ser.write_u16),
                ("invertDirection", ser.write_bool),
                ("srcAddress", ser.write_u16), ("srcBank", ser.write_u8),
                ("transferMode", ser.write_u8), ("transferSize", ser.write_u16),
                ("unusedControlFlag", ser.write_bool),
                ("dmaActive", ser.write_bool), ("unusedRegister", ser.write_u8),
            ]:
                writer(dp + field, 0)

    # =================================================================
    # Internal Registers
    # =================================================================
    int_en = _ppu8(ppu, 0x02)  # INTEnab = $4200
    ser.write_bool("internalRegisters.enableFastRom", fast_rom)
    ser.write_bool("internalRegisters.nmiFlag", in_vblank)
    ser.write_bool("internalRegisters.enableNmi", bool(int_en & 0x80))
    ser.write_bool("internalRegisters.enableHorizontalIrq", bool(int_en & 0x10))
    ser.write_bool("internalRegisters.enableVerticalIrq", bool(int_en & 0x20))
    ser.write_u16("internalRegisters.horizontalTimer", _ppu16(ppu, 0x09DF))
    ser.write_u16("internalRegisters.verticalTimer", _ppu16(ppu, 0x04))
    ser.write_u8("internalRegisters.ioPortOutput", _ppu8(ppu, 0x09EB))
    for i in range(4):
        ser.write_u16(f"internalRegisters.controllerData[{i}]", 0)
    ser.write_bool("internalRegisters.irqLevel", False)
    ser.write_u8("internalRegisters.needIrq", 0)
    ser.write_bool("internalRegisters.enableAutoJoypadRead", bool(int_en & 0x01))
    ser.write_bool("internalRegisters.irqFlag", False)

    ap = "internalRegisters.aluMulDiv."
    ser.write_u8(ap + "multOperand1", _ppu8(ppu, 0x71))
    ser.write_u8(ap + "multOperand2", 0)
    ser.write_u16(ap + "multOrRemainderResult", _ppu16(ppu, 0x76))
    ser.write_u16(ap + "dividend", _ppu16(ppu, 0x72))
    ser.write_u8(ap + "divisor", 0)
    ser.write_u16(ap + "divResult", _ppu16(ppu, 0x74))
    ser.write_u8(ap + "divCounter", 0)
    ser.write_u8(ap + "multCounter", 0)
    ser.write_u32(ap + "shift", 0)
    ser.write_u64(ap + "prevCpuCycle", 0)

    ser.write_u64("internalRegisters.autoReadClockStart", 0)
    ser.write_u64("internalRegisters.autoReadNextClock", 0)
    ser.write_bool("internalRegisters.autoReadActive", False)
    ser.write_bool("internalRegisters.autoReadDisabled", False)
    ser.write_u8("internalRegisters.autoReadPort1Value", 0)
    ser.write_u8("internalRegisters.autoReadPort2Value", 0)
    ser.write_u16("internalRegisters.hCounter", _ppu16(ppu, 0x78))
    ser.write_u16("internalRegisters.vCounter", _ppu16(ppu, 0x7A))

    # =================================================================
    # Cartridge
    # =================================================================
    ser.write_array_u8("cart.saveRam", zst.sram if zst.sram else b"")

    # =================================================================
    # SPC
    # =================================================================
    if zst.spcon:
        _write_spc(ser, zst, spc_cycle, spc_clock_rate, master_clock_rate)
    else:
        _write_spc_defaults(ser, spc_cycle, spc_clock_rate, master_clock_rate)

    # =================================================================
    # Control Manager
    # =================================================================
    ser.write_u32("controlManager.pollCounter", 0)
    ser.write_u8("controlManager.controlDevices[0].state", 0)
    ser.write_bool("controlManager.controlDevices[0].strobe", False)
    ser.write_u16("controlManager.controlDevices[1].state", 0)
    ser.write_u32("controlManager.controlDevices[1].stateBuffer", 0)
    ser.write_bool("controlManager.controlDevices[1].strobe", False)
    ser.write_u8("controlManager.lastWriteValue", 0)
    ser.write_bool("controlManager.autoReadStrobe", False)

    return ser.get_data()


def _write_spc(
    ser: MesenSerializer,
    zst: ZsnesState,
    spc_cycle: int,
    spc_clock_rate: int,
    master_clock_rate: int,
) -> None:
    ser.write_u8("spc.a", zst.spc_a)
    ser.write_u64("spc.cycle", spc_cycle)
    ser.write_u16("spc.pc", zst.spc_pc)

    # Reconstruct PSW from ZSNES spcP
    ser.write_u8("spc.ps", zst.spc_p)
    ser.write_u8("spc.sp", zst.spc_sp)
    ser.write_u8("spc.x", zst.spc_x)
    ser.write_u8("spc.y", zst.spc_y)

    # Ports: ZSNES reg1read-reg4read are the CPU→SPC port values
    for i in range(4):
        ser.write_u8(f"spc.cpuRegs[{i}]", zst.spc_ports[i])
    # Output regs from SPC RAM $F4-$F7
    spc_ram = zst.spc_ram
    for i in range(4):
        ser.write_u8(f"spc.outputReg[{i}]", spc_ram[0xF4 + i] if len(spc_ram) > 0xF7 else 0)
    ser.write_u8("spc.ramReg[0]", spc_ram[0xF8] if len(spc_ram) > 0xF8 else 0)
    ser.write_u8("spc.ramReg[1]", spc_ram[0xF9] if len(spc_ram) > 0xF9 else 0)

    ser.write_u8("spc.externalSpeed", 0)
    ser.write_u8("spc.internalSpeed", 0)
    ser.write_bool("spc.writeEnabled", True)
    ser.write_bool("spc.timersEnabled", True)
    ser.write_u8("spc.dspReg", spc_ram[0xF2] if len(spc_ram) > 0xF2 else 0)
    ser.write_bool("spc.romEnabled", False)
    ser.write_f64("spc.clockRatio", spc_clock_rate / master_clock_rate)
    ser.write_bool("spc.timersDisabled", False)

    # Timers
    for t in range(3):
        tp = f"spc.timer{t}."
        enabled = bool(zst.spc_timer_enable & (1 << t))
        ser.write_u8(tp + "stage0", 0)
        ser.write_u8(tp + "stage1", 0)
        ser.write_u8(tp + "stage2", zst.spc_timer_ticks[t])
        ser.write_u8(tp + "output", 0)
        ser.write_u8(tp + "target", zst.spc_timer_target[t])
        ser.write_bool(tp + "enabled", enabled)
        ser.write_bool(tp + "timersEnabled", True)
        ser.write_u8(tp + "prevStage1", 0)

    # SPC RAM — need to extend to 64KB (ZSNES stores 65472 bytes)
    ram_full = bytearray(0x10000)
    ram_full[: len(spc_ram)] = spc_ram[: min(len(spc_ram), 0x10000)]
    # Copy extra RAM (TCALL) to $FFC0-$FFFF
    if zst.spc_extra_ram:
        extra = zst.spc_extra_ram[:64]
        ram_full[0xFFC0 : 0xFFC0 + len(extra)] = extra
    ser.write_array_u8("spc.ram", bytes(ram_full))

    # DSP — registers from DSPMem (256 bytes)
    dsp_regs = zst.dsp_regs[:128] if len(zst.dsp_regs) >= 128 else zst.dsp_regs + b"\x00" * (128 - len(zst.dsp_regs))
    ext_regs = dsp_regs  # same as regs for ZSNES
    ser.write_array_u8("spc.dsp.regs", dsp_regs)
    ser.write_array_u8("spc.dsp.externalRegs", ext_regs)

    # DSP voices — initialize from DSP registers (ZSNES DSP internals don't
    # map to Mesen2's cycle-accurate model)
    for i in range(8):
        vp = f"spc.dsp.voices[{i}]."
        ser.write_i32(vp + "envVolume", 0)
        ser.write_i32(vp + "prevCalculatedEnv", 0)
        ser.write_i32(vp + "interpolationPos", 0)
        ser.write_u32(vp + "envMode", 0)  # Release
        ser.write_u16(vp + "brrAddress", 0)
        ser.write_u16(vp + "brrOffset", 1)
        ser.write_u8(vp + "voiceBit", 1 << i)
        ser.write_u8(vp + "keyOnDelay", 0)
        ser.write_u8(vp + "envOut", 0)
        ser.write_u8(vp + "bufferPos", 0)
        ser.write_array_i16(vp + "sampleBuffer", [0] * 12)

    # DSP global state
    ser.write_i32("spc.dsp.noiseLfsr", 0x4000)
    ser.write_u16("spc.dsp.counter", 0)
    ser.write_u8("spc.dsp.step", 0)
    ser.write_u8("spc.dsp.outRegBuffer", 0)
    ser.write_u8("spc.dsp.envRegBuffer", 0)
    ser.write_u8("spc.dsp.voiceEndBuffer", dsp_regs[0x7C] if len(dsp_regs) > 0x7C else 0)
    ser.write_i32("spc.dsp.voiceOutput", 0)
    ser.write_array_i32("spc.dsp.outSamples", [0, 0])
    ser.write_i32("spc.dsp.pitch", 0)
    ser.write_u16("spc.dsp.sampleAddress", 0)
    ser.write_u16("spc.dsp.brrNextAddress", 0)
    ser.write_u8("spc.dsp.dirSampleTableAddress", dsp_regs[0x5D] if len(dsp_regs) > 0x5D else 0)
    ser.write_u8("spc.dsp.noiseOn", 0)
    ser.write_u8("spc.dsp.pitchModulationOn", 0)
    ser.write_u8("spc.dsp.keyOn", 0)
    ser.write_u8("spc.dsp.newKeyOn", 0)
    ser.write_u8("spc.dsp.keyOff", 0)
    ser.write_u8("spc.dsp.everyOtherSample", 0)
    ser.write_u8("spc.dsp.sourceNumber", 0)
    ser.write_u8("spc.dsp.brrHeader", 0)
    ser.write_u8("spc.dsp.brrData", 0)
    ser.write_u8("spc.dsp.looped", 0)
    ser.write_u8("spc.dsp.adsr1", 0)
    ser.write_array_i32("spc.dsp.echoIn", [0, 0])
    ser.write_array_i32("spc.dsp.echoOut", [0, 0])
    ser.write_array_i16("spc.dsp.echoHistory", [0] * 16)
    esa = dsp_regs[0x6D] if len(dsp_regs) > 0x6D else 0
    edl = (dsp_regs[0x7D] & 0x0F) if len(dsp_regs) > 0x7D else 0
    echo_len = edl * 0x800 if edl else 4
    ser.write_u16("spc.dsp.echoPointer", esa << 8)
    ser.write_u16("spc.dsp.echoLength", echo_len)
    ser.write_u16("spc.dsp.echoOffset", 0)
    ser.write_u8("spc.dsp.echoHistoryPos", 0)
    ser.write_u8("spc.dsp.echoRingBufferAddress", esa)
    flg = dsp_regs[0x6C] if len(dsp_regs) > 0x6C else 0
    ser.write_u8("spc.dsp.echoOn", 0)
    ser.write_bool("spc.dsp.echoEnabled", not bool(flg & 0x20))

    # SPC internal
    ser.write_u16("spc.operandA", 0)
    ser.write_u16("spc.operandB", 0)
    ser.write_u16("spc.tmp1", 0)
    ser.write_u16("spc.tmp2", 0)
    ser.write_u16("spc.tmp3", 0)
    ser.write_u8("spc.opCode", 0)
    ser.write_u8("spc.opStep", 0)  # ReadOpCode
    ser.write_u8("spc.opSubStep", 0)
    ser.write_bool("spc.enabled", True)
    ser.write_array_u8("spc.newCpuRegs", list(zst.spc_ports[:4]))
    ser.write_bool("spc.pendingCpuRegUpdate", False)


def _write_spc_defaults(
    ser: MesenSerializer,
    spc_cycle: int,
    spc_clock_rate: int,
    master_clock_rate: int,
) -> None:
    """Write minimal SPC state when SPC was disabled in the ZST."""
    ser.write_u8("spc.a", 0)
    ser.write_u64("spc.cycle", spc_cycle)
    ser.write_u16("spc.pc", 0xFFC0)
    ser.write_u8("spc.ps", 0)
    ser.write_u8("spc.sp", 0xFF)
    ser.write_u8("spc.x", 0)
    ser.write_u8("spc.y", 0)
    for i in range(4):
        ser.write_u8(f"spc.cpuRegs[{i}]", 0)
        ser.write_u8(f"spc.outputReg[{i}]", 0)
    ser.write_u8("spc.ramReg[0]", 0)
    ser.write_u8("spc.ramReg[1]", 0)
    ser.write_u8("spc.externalSpeed", 0)
    ser.write_u8("spc.internalSpeed", 0)
    ser.write_bool("spc.writeEnabled", True)
    ser.write_bool("spc.timersEnabled", True)
    ser.write_u8("spc.dspReg", 0)
    ser.write_bool("spc.romEnabled", True)
    ser.write_f64("spc.clockRatio", spc_clock_rate / master_clock_rate)
    ser.write_bool("spc.timersDisabled", False)
    for t in range(3):
        tp = f"spc.timer{t}."
        for f in ("stage0", "stage1", "stage2", "output", "target"):
            ser.write_u8(tp + f, 0)
        ser.write_bool(tp + "enabled", False)
        ser.write_bool(tp + "timersEnabled", True)
        ser.write_u8(tp + "prevStage1", 0)
    ser.write_array_u8("spc.ram", bytes(0x10000))
    ser.write_array_u8("spc.dsp.regs", bytes(128))
    ser.write_array_u8("spc.dsp.externalRegs", bytes(128))
    for i in range(8):
        vp = f"spc.dsp.voices[{i}]."
        ser.write_i32(vp + "envVolume", 0)
        ser.write_i32(vp + "prevCalculatedEnv", 0)
        ser.write_i32(vp + "interpolationPos", 0)
        ser.write_u32(vp + "envMode", 0)
        ser.write_u16(vp + "brrAddress", 0)
        ser.write_u16(vp + "brrOffset", 1)
        ser.write_u8(vp + "voiceBit", 1 << i)
        ser.write_u8(vp + "keyOnDelay", 0)
        ser.write_u8(vp + "envOut", 0)
        ser.write_u8(vp + "bufferPos", 0)
        ser.write_array_i16(vp + "sampleBuffer", [0] * 12)
    ser.write_i32("spc.dsp.noiseLfsr", 0x4000)
    ser.write_u16("spc.dsp.counter", 0)
    ser.write_u8("spc.dsp.step", 0)
    ser.write_u8("spc.dsp.outRegBuffer", 0)
    ser.write_u8("spc.dsp.envRegBuffer", 0)
    ser.write_u8("spc.dsp.voiceEndBuffer", 0)
    ser.write_i32("spc.dsp.voiceOutput", 0)
    ser.write_array_i32("spc.dsp.outSamples", [0, 0])
    ser.write_i32("spc.dsp.pitch", 0)
    ser.write_u16("spc.dsp.sampleAddress", 0)
    ser.write_u16("spc.dsp.brrNextAddress", 0)
    ser.write_u8("spc.dsp.dirSampleTableAddress", 0)
    ser.write_u8("spc.dsp.noiseOn", 0)
    ser.write_u8("spc.dsp.pitchModulationOn", 0)
    ser.write_u8("spc.dsp.keyOn", 0)
    ser.write_u8("spc.dsp.newKeyOn", 0)
    ser.write_u8("spc.dsp.keyOff", 0)
    ser.write_u8("spc.dsp.everyOtherSample", 0)
    ser.write_u8("spc.dsp.sourceNumber", 0)
    ser.write_u8("spc.dsp.brrHeader", 0)
    ser.write_u8("spc.dsp.brrData", 0)
    ser.write_u8("spc.dsp.looped", 0)
    ser.write_u8("spc.dsp.adsr1", 0)
    ser.write_array_i32("spc.dsp.echoIn", [0, 0])
    ser.write_array_i32("spc.dsp.echoOut", [0, 0])
    ser.write_array_i16("spc.dsp.echoHistory", [0] * 16)
    ser.write_u16("spc.dsp.echoPointer", 0)
    ser.write_u16("spc.dsp.echoLength", 4)
    ser.write_u16("spc.dsp.echoOffset", 0)
    ser.write_u8("spc.dsp.echoHistoryPos", 0)
    ser.write_u8("spc.dsp.echoRingBufferAddress", 0)
    ser.write_u8("spc.dsp.echoOn", 0)
    ser.write_bool("spc.dsp.echoEnabled", False)
    ser.write_u16("spc.operandA", 0)
    ser.write_u16("spc.operandB", 0)
    ser.write_u16("spc.tmp1", 0)
    ser.write_u16("spc.tmp2", 0)
    ser.write_u16("spc.tmp3", 0)
    ser.write_u8("spc.opCode", 0)
    ser.write_u8("spc.opStep", 0)
    ser.write_u8("spc.opSubStep", 0)
    ser.write_bool("spc.enabled", True)
    ser.write_array_u8("spc.newCpuRegs", [0, 0, 0, 0])
    ser.write_bool("spc.pendingCpuRegUpdate", False)
