"""Map decoded snes9x state into a Mesen2 serialized binary blob."""

from snes_save_state_converter.mesen2.coprocessors import (
    write_bsx_cart,
    write_cx4,
    write_gsu,
    write_msu1,
    write_nec_dsp,
    write_sa1,
    write_spc7110,
)
from snes_save_state_converter.mesen2.serializer import MesenSerializer
from snes_save_state_converter.snes9x.coprocessors import (
    decode_bsx_block,
    decode_dsp1_block,
    decode_dsp2_block,
    decode_dsp4_block,
    decode_msu1_block,
    decode_obc1_block,
    decode_sa1_block,
    decode_sar_block,
    decode_sfx_block,
    decode_spc7110_block,
    decode_srtc_block,
    decode_st010_block,
)
from snes_save_state_converter.snes9x.decoders import (
    decode_cpu_block,
    decode_dma_block,
    decode_ppu_block,
    decode_reg_block,
    decode_snd_block,
    decode_tim_block,
)
from snes_save_state_converter.snes9x.parser import Snes9xState


# -- FillRAM helpers (snes9x register backing store) -----------------------
# The FIL block is a raw copy of Memory.FillRAM starting at offset 0.
# Hardware register $XXXX is at fillram[$XXXX].


def _fr(fillram: bytes, addr: int) -> int:
    return fillram[addr] if 0 <= addr < len(fillram) else 0


def _fr16(fillram: bytes, addr: int) -> int:
    return _fr(fillram, addr) | (_fr(fillram, addr + 1) << 8)


# -- Conversion ------------------------------------------------------------


def _write_coprocessors(
    ser: MesenSerializer,
    s9x: Snes9xState,
    fillram: bytes,
) -> None:
    """Detect which coprocessor blocks exist and write the Mesen2 state."""
    blocks = s9x.blocks
    ver = s9x.version

    # SuperFX / GSU
    if "SFX" in blocks:
        sfx = decode_sfx_block(blocks["SFX"])
        # GSU RAM is stored in the SRAM block for SuperFX games
        gsu_ram = blocks.get("SRA", b"")
        write_gsu(ser, sfx, gsu_ram)
        return

    # SA-1
    if "SA1" in blocks and "SAR" in blocks:
        sa1 = decode_sa1_block(blocks["SA1"], ver)
        sar = decode_sar_block(blocks["SAR"])
        # SA-1 IRAM is stored in the FillRAM area or as part of SRAM
        iram = b""
        write_sa1(ser, sa1, sar, fillram, iram)
        return

    # DSP-1
    if "DP1" in blocks:
        dsp1 = decode_dsp1_block(blocks["DP1"])
        # NEC uPD77C25: RAM=256 words (512 bytes), stack=16 words (32 bytes)
        write_nec_dsp(ser, dsp1, ram=b"", ram_size=512, stack_size=32)
        return

    # DSP-2
    if "DP2" in blocks:
        dsp2 = decode_dsp2_block(blocks["DP2"])
        write_nec_dsp(ser, dsp2, ram=b"", ram_size=512, stack_size=32)
        return

    # DSP-4
    if "DP4" in blocks:
        dsp4 = decode_dsp4_block(blocks["DP4"])
        write_nec_dsp(ser, dsp4, ram=b"", ram_size=512, stack_size=32)
        return

    # ST-010 / ST-011 (SETA chips — also use NEC DSP in Mesen2)
    if "ST0" in blocks:
        st010 = decode_st010_block(blocks["ST0"])
        # ST-010: RAM=2048 words, stack=32 words
        write_nec_dsp(ser, st010, ram=b"", ram_size=4096, stack_size=64)
        return

    # CX4
    if "CX4" in blocks:
        write_cx4(ser, blocks["CX4"])
        return

    # SPC7110
    if "S71" in blocks:
        s71 = decode_spc7110_block(blocks["S71"])
        rtc_data = blocks.get("CLK", None)
        write_spc7110(ser, s71, rtc_data)
        return

    # OBC1 — Mesen2 has an empty Serialize(), nothing to write
    if "OBC" in blocks:
        _ = decode_obc1_block(blocks["OBC"])
        return

    # BS-X
    if "BSX" in blocks:
        bsx = decode_bsx_block(blocks["BSX"])
        write_bsx_cart(ser, bsx)
        return

    # S-RTC (standalone, without SPC7110)
    if "SRT" in blocks:
        _ = decode_srtc_block(blocks["SRT"])
        # S-RTC is handled within Mesen2's SPC7110 or as a simple RTC —
        # standalone S-RTC doesn't have a separate coprocessor in Mesen2
        return


def _pad(data: bytes, size: int) -> bytes:
    if len(data) >= size:
        return data[:size]
    return data + b"\x00" * (size - len(data))


def convert(s9x: Snes9xState) -> bytes:
    """Return Mesen2 serialized state bytes built from *s9x*."""
    ser = MesenSerializer()
    ver = s9x.version

    cpu_b = decode_cpu_block(s9x.blocks.get("CPU", b"\x00" * 100), ver)
    reg_b = decode_reg_block(s9x.blocks.get("REG", b"\x00" * 20))
    ppu_b = decode_ppu_block(s9x.blocks.get("PPU", b"\x00" * 5000), ver)
    dma_ch = decode_dma_block(s9x.blocks.get("DMA", b"\x00" * 200))
    snd = decode_snd_block(s9x.blocks.get("SND", b"\x00" * (65 * 1024)))
    tim = decode_tim_block(s9x.blocks.get("TIM", b"\x00" * 100), ver)

    vram = s9x.blocks.get("VRA", b"\x00" * 0x10000)
    wram = s9x.blocks.get("RAM", b"\x00" * 0x20000)
    sram = s9x.blocks.get("SRA", b"")
    fr = s9x.blocks.get("FIL", b"\x00" * 0x8000)

    fast_rom = cpu_b["FastROMSpeed"] == 6
    setini = _fr(fr, 0x2133)
    overscan = bool(setini & 0x04)

    # --- Timing: place execution at start of VBlank (after DRAM refresh) ---
    # SNES NTSC: 1364 master clocks per scanline, 262 scanlines per frame
    # Event chain per VBlank scanline: DramRefresh@538 → EndOfScanline@1360
    is_pal = tim.get("V_Max_Master", 262) > 262
    vbl_start = 240 if overscan else 225
    vbl_end = 311 if is_pal else 261
    h_period = 1364
    # masterClock at start of VBlank scanline, 8-byte aligned for DRAM calc
    master_clock = vbl_start * h_period
    master_clock = (master_clock + 7) & ~7  # align to 8
    dram_refresh_pos = 538 - (master_clock & 0x07)  # = 538 since aligned
    # Place hClock just past DRAM refresh so next event is EndOfScanline
    h_clock = dram_refresh_pos + 40  # 40 master clocks for DRAM refresh itself
    master_clock += h_clock
    # SPC cycle: clockRatio ≈ 32040*64 / 21477270 ≈ 0.09548 for NTSC
    spc_clock_rate = 32040 * 64
    master_clock_rate = 24607104 if is_pal else 21477270
    spc_cycle = int(master_clock * spc_clock_rate / master_clock_rate)

    # =================================================================
    # CPU
    # =================================================================
    ser.write_u16("cpu.a", reg_b["A"])
    ser.write_u64("cpu.cycleCount", master_clock)
    ser.write_u16("cpu.d", reg_b["D"])
    ser.write_u8("cpu.dbr", reg_b["DB"])
    ser.write_bool("cpu.emulationMode", False)
    irq = 0
    if cpu_b.get("IRQLine", 0):
        irq |= 1
    if cpu_b.get("IRQExternal", 0):
        irq |= 2
    ser.write_u8("cpu.irqSource", irq)
    ser.write_u8("cpu.k", reg_b["PB"])
    ser.write_u8("cpu.nmiFlagCounter", 0)
    ser.write_u16("cpu.pc", reg_b["PC"])
    ser.write_u8("cpu.prevIrqSource", 0)
    ser.write_u8("cpu.ps", reg_b["P"] & 0xFF)
    ser.write_u16("cpu.sp", reg_b["S"])
    ser.write_u8("cpu.stopState", 2 if cpu_b["WaitingForInterrupt"] else 0)
    ser.write_u16("cpu.x", reg_b["X"])
    ser.write_u16("cpu.y", reg_b["Y"])
    ser.write_bool("cpu.irqLock", False)
    ser.write_bool("cpu.needNmi", bool(cpu_b.get("NMIPending", 0)))
    ser.write_bool("cpu.waiOver", False)

    # =================================================================
    # Memory Manager
    # =================================================================
    ser.write_u64("memoryManager.masterClock", master_clock)
    ser.write_u8("memoryManager.openBus", 0)
    ser.write_u8("memoryManager.cpuSpeed", 6 if fast_rom else 8)
    ser.write_u16("memoryManager.hClock", h_clock)
    ser.write_u16("memoryManager.dramRefreshPosition", dram_refresh_pos)
    ser.write_u32("memoryManager.memTypeBusA", 0)  # MemoryType enum (4 bytes)
    # Next event: EndOfScanline (3) at hClock=1360
    ser.write_u8("memoryManager.nextEvent", 3)   # SnesEventType::EndOfScanline
    ser.write_u16("memoryManager.nextEventClock", 1360)
    ser.write_array_u8("memoryManager.workRam", _pad(wram, 0x20000))
    ser.write_u32("memoryManager.registerHandlerB.wramPosition", ppu_b["WRAM"] & 0x1FFFF)

    # =================================================================
    # PPU
    # =================================================================
    ser.write_bool("ppu.forcedBlank", bool(ppu_b["ForcedBlanking"]))
    ser.write_u8("ppu.screenBrightness", ppu_b["Brightness"])
    ser.write_u16("ppu.scanline", vbl_start)  # in VBlank
    ser.write_u32("ppu.frameCount", 0)
    ser.write_u8("ppu.bgMode", ppu_b["BGMode"])
    ser.write_bool("ppu.mode1Bg3Priority", bool(ppu_b["BG3Priority"]))
    ser.write_u8("ppu.mainScreenLayers", _fr(fr, 0x212C))
    ser.write_u8("ppu.subScreenLayers", _fr(fr, 0x212D))
    ser.write_u16("ppu.vramAddress", ppu_b["VMA_Address"])
    ser.write_u8("ppu.vramIncrementValue", ppu_b["VMA_Increment"])
    # snes9x VMA.Shift stores the shift amount (0,5,6,7) — convert to Mesen2's
    # 2-bit mode index (0,1,2,3) which is the raw (reg >> 2) & 3 value.
    shift_to_mode = {0: 0, 5: 1, 6: 2, 7: 3}
    ser.write_u8("ppu.vramAddressRemapping", shift_to_mode.get(ppu_b["VMA_Shift"], 0))
    ser.write_bool("ppu.vramAddrIncrementOnSecondReg", bool(ppu_b["VMA_High"]))
    ser.write_u16("ppu.vramReadBuffer", ppu_b.get("VRAMReadBuffer", 0))
    ser.write_u8("ppu.ppu1OpenBus", ppu_b["OpenBus1"])
    ser.write_u8("ppu.ppu2OpenBus", ppu_b["OpenBus2"])
    ser.write_u8("ppu.cgramAddress", ppu_b["CGADD"])
    mosaic = _fr(fr, 0x2106)
    ser.write_u8("ppu.mosaicSize", ((mosaic >> 4) & 0xF) + 1)
    ser.write_u8("ppu.mosaicEnabled", mosaic & 0x0F)
    obsel = _fr(fr, 0x2101)
    ser.write_u8("ppu.oamMode", (obsel >> 5) & 7)
    ser.write_u16("ppu.oamBaseAddress", (obsel & 0x07) << 13)
    ser.write_u16("ppu.oamAddressOffset", (((obsel >> 3) & 0x03) + 1) << 12)
    ser.write_u16("ppu.oamRamAddress", ppu_b["OAMAddr"])
    ser.write_bool("ppu.enableOamPriority", bool(ppu_b["OAMPriorityRotation"]))
    ser.write_u8("ppu.oamWriteBuffer", ppu_b["OAMWriteRegister"] & 0xFF)
    ser.write_bool("ppu.timeOver", False)
    ser.write_bool("ppu.rangeOver", False)
    ser.write_bool("ppu.hiResMode", bool(setini & 0x08))
    ser.write_bool("ppu.screenInterlace", bool(setini & 0x01))
    ser.write_bool("ppu.objInterlace", bool(setini & 0x02))
    ser.write_bool("ppu.overscanMode", overscan)
    ser.write_bool("ppu.directColorMode", bool(_fr(fr, 0x2130) & 0x01))

    r2130 = _fr(fr, 0x2130)
    r2131 = _fr(fr, 0x2131)
    # ColorWindowMode is enum class (4 bytes, not 1)
    ser.write_u32("ppu.colorMathClipMode", (r2130 >> 6) & 3)
    ser.write_u32("ppu.colorMathPreventMode", (r2130 >> 4) & 3)
    ser.write_bool("ppu.colorMathAddSubscreen", bool(r2130 & 0x02))
    ser.write_u8("ppu.colorMathEnabled", r2131 & 0x3F)
    ser.write_bool("ppu.colorMathSubtractMode", bool(r2131 & 0x80))
    ser.write_bool("ppu.colorMathHalveResult", bool(r2131 & 0x40))

    r = ppu_b["FixedColourRed"] & 0x1F
    g = ppu_b["FixedColourGreen"] & 0x1F
    b = ppu_b["FixedColourBlue"] & 0x1F
    ser.write_u16("ppu.fixedColor", r | (g << 5) | (b << 10))

    ser.write_u8("ppu.hvScrollLatchValue", ppu_b["BGnxOFSbyte"])
    ser.write_u8("ppu.hScrollLatchValue", 0)

    wlog1 = _fr(fr, 0x212A)
    wlog2 = _fr(fr, 0x212B)
    # WindowMaskLogic is enum class (4 bytes)
    for i in range(6):
        shift = (i * 2) if i < 4 else ((i - 4) * 2)
        reg = wlog1 if i < 4 else wlog2
        ser.write_u32(f"ppu.maskLogic[{i}]", (reg >> shift) & 3)

    wmain = _fr(fr, 0x212E)
    wsub = _fr(fr, 0x212F)
    for i in range(5):
        ser.write_bool(f"ppu.windowMaskMain[{i}]", bool(wmain & (1 << i)))
        ser.write_bool(f"ppu.windowMaskSub[{i}]", bool(wsub & (1 << i)))

    # Mode 7
    ser.write_i16("ppu.mode7.centerX", ppu_b["CentreX"])
    ser.write_i16("ppu.mode7.centerY", ppu_b["CentreY"])
    ser.write_bool("ppu.extBgEnabled", bool(setini & 0x40))
    ser.write_bool("ppu.mode7.fillWithTile0", ppu_b["Mode7Repeat"] == 0)
    ser.write_bool("ppu.mode7.horizontalMirroring", bool(ppu_b["Mode7HFlip"]))
    ser.write_i16("ppu.mode7.hscroll", ppu_b["M7HOFS"])
    ser.write_bool("ppu.mode7.largeMap", ppu_b["Mode7Repeat"] >= 2)
    ser.write_i16("ppu.mode7.matrix[0]", ppu_b["MatrixA"])
    ser.write_i16("ppu.mode7.matrix[1]", ppu_b["MatrixB"])
    ser.write_i16("ppu.mode7.matrix[2]", ppu_b["MatrixC"])
    ser.write_i16("ppu.mode7.matrix[3]", ppu_b["MatrixD"])
    ser.write_u8("ppu.mode7.valueLatch", ppu_b["M7byte"])
    ser.write_bool("ppu.mode7.verticalMirroring", bool(ppu_b["Mode7VFlip"]))
    ser.write_i16("ppu.mode7.vscroll", ppu_b["M7VOFS"])

    ser.write_bool("ppu.cgramAddressLatch", bool(ppu_b["CGFLIP"]))
    ser.write_u8("ppu.cgramWriteBuffer", ppu_b.get("CGSavedByte", 0))
    ser.write_u16("ppu.internalOamAddress", ppu_b["SavedOAMAddr"])
    ser.write_u8("ppu.internalCgramAddress", ppu_b["CGADD"])

    # Layers
    for i in range(4):
        lp = f"ppu.layers[{i}]."
        sp = f"BG{i}_"
        ser.write_u16(lp + "chrAddress", ppu_b[sp + "NameBase"])
        sc = ppu_b[sp + "SCSize"]
        ser.write_bool(lp + "doubleHeight", bool(sc & 2))
        ser.write_bool(lp + "doubleWidth", bool(sc & 1))
        ser.write_u16(lp + "hscroll", ppu_b[sp + "HOffset"])
        ser.write_bool(lp + "largeTiles", bool(ppu_b[sp + "BGSize"]))
        ser.write_u16(lp + "tilemapAddress", ppu_b[sp + "SCBase"])
        ser.write_u16(lp + "vscroll", ppu_b[sp + "VOffset"])

    # Windows
    regs_w = [_fr(fr, 0x2123), _fr(fr, 0x2124), _fr(fr, 0x2125)]
    for w in range(2):
        wp = f"ppu.window[{w}]."
        for layer in range(6):
            bits = (regs_w[layer // 2] >> ((layer % 2) * 4 + w * 2)) & 3
            ser.write_bool(f"{wp}activeLayers[{layer}]", bool(bits & 2))
        for layer in range(6):
            bits = (regs_w[layer // 2] >> ((layer % 2) * 4 + w * 2)) & 3
            ser.write_bool(f"{wp}invertedLayers[{layer}]", bool(bits & 1))
        if w == 0:
            ser.write_u8(wp + "left", ppu_b["Window1Left"])
            ser.write_u8(wp + "right", ppu_b["Window1Right"])
        else:
            ser.write_u8(wp + "left", ppu_b["Window2Left"])
            ser.write_u8(wp + "right", ppu_b["Window2Right"])

    # VRAM (uint16 LE array, 32K words)
    vram_words = [
        int.from_bytes(vram[i : i + 2], "little")
        for i in range(0, min(len(vram), 0x10000), 2)
    ]
    vram_words.extend([0] * (0x8000 - len(vram_words)))
    ser.write_array_u16("ppu.vram", vram_words)

    ser.write_array_u8("ppu.oamRam", ppu_b["OAMData"])
    ser.write_array_u16("ppu.cgram", ppu_b["CGDATA"])

    # Internal PPU timing
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

    # Layer tile cache — keys match SVI(_layerData[N].Tiles[i].Field) normalized
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
    # DMA
    # =================================================================
    ser.write_bool("dmaController.hdmaPending", False)
    ser.write_u8("dmaController.hdmaChannels", ppu_b["HDMA"])
    ser.write_bool("dmaController.dmaPending", False)
    ser.write_u32("dmaController.dmaClockCounter", 0)
    ser.write_bool("dmaController.hdmaInitPending", False)
    ser.write_bool("dmaController.dmaStartDelay", False)
    ser.write_bool("dmaController.needToProcess", False)

    for i in range(8):
        dp = f"dmaController.channel[{i}]."
        ch = dma_ch[i]
        ser.write_bool(dp + "decrement", bool(ch["AAddressDecrement"]))
        ser.write_u8(dp + "destAddress", ch["BAddress"])
        ser.write_bool(dp + "doTransfer", bool(ch["DoTransfer"]))
        ser.write_bool(dp + "fixedTransfer", bool(ch["AAddressFixed"]))
        ser.write_u8(dp + "hdmaBank", ch["IndirectBank"])
        ser.write_bool(dp + "hdmaFinished", False)
        ser.write_bool(dp + "hdmaIndirectAddressing", bool(ch["HDMAIndirectAddressing"]))
        ser.write_u8(dp + "hdmaLineCounterAndRepeat", ch["LineCount"] | (ch["Repeat"] << 7))
        ser.write_u16(dp + "hdmaTableAddress", ch["Address"])
        ser.write_bool(dp + "invertDirection", bool(ch["ReverseTransfer"]))
        ser.write_u16(dp + "srcAddress", ch["AAddress"])
        ser.write_u8(dp + "srcBank", ch["ABank"])
        ser.write_u8(dp + "transferMode", ch["TransferMode"])
        ser.write_u16(dp + "transferSize", ch["DMACount_Or_HDMAIndirectAddress"])
        ser.write_bool(dp + "unusedControlFlag", bool(ch["UnusedBit43x0"]))
        ser.write_bool(dp + "dmaActive", False)
        ser.write_u8(dp + "unusedRegister", ch["UnknownByte"])

    # =================================================================
    # Internal Registers
    # =================================================================
    ser.write_bool("internalRegisters.enableFastRom", fast_rom)
    ser.write_bool("internalRegisters.nmiFlag", True)  # we're in VBlank
    r4200 = _fr(fr, 0x4200)
    ser.write_bool("internalRegisters.enableNmi", bool(r4200 & 0x80))
    ser.write_bool("internalRegisters.enableHorizontalIrq", bool(ppu_b["HTimerEnabled"]))
    ser.write_bool("internalRegisters.enableVerticalIrq", bool(ppu_b["VTimerEnabled"]))
    ser.write_u16("internalRegisters.horizontalTimer", ppu_b["IRQHBeamPos"])
    ser.write_u16("internalRegisters.verticalTimer", ppu_b["IRQVBeamPos"])
    ser.write_u8("internalRegisters.ioPortOutput", _fr(fr, 0x4201))
    # ControllerData is uint16[4] — each entry is a full 16-bit joypad read
    for i in range(4):
        ser.write_u16(f"internalRegisters.controllerData[{i}]", _fr16(fr, 0x4218 + i * 2))
    ser.write_bool("internalRegisters.irqLevel", False)
    ser.write_u8("internalRegisters.needIrq", 0)
    ser.write_bool("internalRegisters.enableAutoJoypadRead", bool(r4200 & 0x01))
    ser.write_bool("internalRegisters.irqFlag", False)

    ap = "internalRegisters.aluMulDiv."
    ser.write_u8(ap + "multOperand1", _fr(fr, 0x4202))
    ser.write_u8(ap + "multOperand2", _fr(fr, 0x4203))
    ser.write_u16(ap + "multOrRemainderResult", _fr16(fr, 0x4216))
    ser.write_u16(ap + "dividend", _fr16(fr, 0x4204))
    ser.write_u8(ap + "divisor", _fr(fr, 0x4206))
    ser.write_u16(ap + "divResult", _fr16(fr, 0x4214))
    ser.write_u8(ap + "divCounter", 0)
    ser.write_u8(ap + "multCounter", 0)
    ser.write_u32(ap + "shift", 0)  # uint32_t in AluMulDiv
    ser.write_u64(ap + "prevCpuCycle", 0)

    ser.write_u64("internalRegisters.autoReadClockStart", 0)
    ser.write_u64("internalRegisters.autoReadNextClock", 0)
    ser.write_bool("internalRegisters.autoReadActive", False)
    ser.write_bool("internalRegisters.autoReadDisabled", False)
    # autoReadPortXValue is uint8 in Mesen2
    ser.write_u8("internalRegisters.autoReadPort1Value", 0)
    ser.write_u8("internalRegisters.autoReadPort2Value", 0)
    ser.write_u16("internalRegisters.hCounter", ppu_b["HBeamPosLatched"])
    ser.write_u16("internalRegisters.vCounter", ppu_b["VBeamPosLatched"])

    # =================================================================
    # Cartridge
    # =================================================================
    ser.write_array_u8("cart.saveRam", sram if sram else b"")

    # -- Coprocessors (serialized inside BaseCartridge::Serialize) ------
    _write_coprocessors(ser, s9x, fr)

    # =================================================================
    # SPC
    # =================================================================
    ser.write_u8("spc.a", snd["a"])
    ser.write_u64("spc.cycle", spc_cycle)
    ser.write_u16("spc.pc", snd["pc"])
    ser.write_u8("spc.ps", snd["psw"])
    ser.write_u8("spc.sp", snd["sp"])
    ser.write_u8("spc.x", snd["x"])
    ser.write_u8("spc.y", snd["y"])

    cpu_regs = snd.get("cpu_regs", [0, 0, 0, 0])
    for i in range(4):
        ser.write_u8(f"spc.cpuRegs[{i}]", cpu_regs[i] if i < len(cpu_regs) else 0)
    spc_ram = snd["spc_ram"]
    for i in range(4):
        ser.write_u8(f"spc.outputReg[{i}]", spc_ram[0xF4 + i] if len(spc_ram) > 0xF7 else 0)
    ser.write_u8("spc.ramReg[0]", snd.get("ram00f8", 0) & 0xFF)
    ser.write_u8("spc.ramReg[1]", snd.get("ram00f9", 0) & 0xFF)
    # SPC TEST register ($F0) bits — derive from SPC RAM
    spc_test = spc_ram[0xF0] if len(spc_ram) > 0xF0 else 0
    spc_control = spc_ram[0xF1] if len(spc_ram) > 0xF1 else 0
    ser.write_u8("spc.externalSpeed", (spc_test >> 4) & 0x03)
    ser.write_u8("spc.internalSpeed", (spc_test >> 6) & 0x03)
    ser.write_bool("spc.writeEnabled", True)  # must be true or SPC can't write RAM
    ser.write_bool("spc.timersEnabled", bool(spc_test & 0x08) if spc_test else True)
    ser.write_u8("spc.dspReg", snd["dsp_addr"])
    ser.write_bool("spc.romEnabled", bool(snd["iplrom_enable"]))
    ser.write_f64("spc.clockRatio", spc_clock_rate / master_clock_rate)
    ser.write_bool("spc.timersDisabled", bool(spc_test & 0x01) if spc_test else False)

    # Mesen2 SpcTimer fields:
    #   stage0 = prescaler (0..rate-1), stage1 = toggle bit (0 or 1),
    #   stage2 = counter (0..target-1), output = output counter (4-bit)
    # Blargg timer fields:
    #   stage1_ticks = prescaler, stage2_ticks = counter, stage3_ticks = output
    for t in range(3):
        tp = f"spc.timer{t}."
        sp = f"timer{t}_"
        ser.write_u8(tp + "stage0", snd.get(sp + "stage1_ticks", 0) & 0xFF)
        ser.write_u8(tp + "stage1", 0)  # toggle bit — must be 0 or 1
        ser.write_u8(tp + "stage2", snd.get(sp + "stage2_ticks", 0) & 0xFF)
        ser.write_u8(tp + "output", snd.get(sp + "stage3_ticks", 0) & 0x0F)
        ser.write_u8(tp + "target", snd.get(sp + "target", 0))
        ser.write_bool(tp + "enabled", bool(snd.get(sp + "enable", 0)))
        ser.write_bool(tp + "timersEnabled", True)
        ser.write_u8(tp + "prevStage1", 0)

    ser.write_array_u8("spc.ram", _pad(
        spc_ram if isinstance(spc_ram, (bytes, bytearray)) else bytes(spc_ram),
        0x10000,
    ))

    # -- DSP ---------------------------------------------------------------
    ser.write_array_u8("spc.dsp.regs", _pad(snd["dsp_regs"], 128))
    ser.write_array_u8("spc.dsp.externalRegs", _pad(snd.get("dsp_external_regs", snd["dsp_regs"]), 128))

    # DSP voices — map blargg's fields directly to Mesen2's.
    # Both DSPs use similar internal representations for voice state.
    for i in range(8):
        vp = f"spc.dsp.voices[{i}]."
        v = snd["voices"][i]
        ser.write_i32(vp + "envVolume", v["env"])
        ser.write_i32(vp + "prevCalculatedEnv", v["env"])
        ser.write_i32(vp + "interpolationPos", v["interp_pos"])
        ser.write_u32(vp + "envMode", v["env_mode"])  # EnvelopeMode enum (4 bytes)
        ser.write_u16(vp + "brrAddress", v["brr_addr"])
        ser.write_u16(vp + "brrOffset", v["brr_offset"])
        ser.write_u8(vp + "voiceBit", 1 << i)
        ser.write_u8(vp + "keyOnDelay", v["kon_delay"])
        ser.write_u8(vp + "envOut", v["t_envx_out"])
        ser.write_u8(vp + "bufferPos", v["buf_pos"])
        ser.write_array_i16(vp + "sampleBuffer", v["brr_buffer"])

    # DSP global state — map from blargg's DSP state
    ser.write_i32("spc.dsp.noiseLfsr", snd["dsp_noise"])
    ser.write_u16("spc.dsp.counter", snd["dsp_counter"])
    ser.write_u8("spc.dsp.step", snd["dsp_phase"])
    ser.write_u8("spc.dsp.outRegBuffer", snd["dsp_outx_buf"])
    ser.write_u8("spc.dsp.envRegBuffer", snd["dsp_envx_buf"])
    ser.write_u8("spc.dsp.voiceEndBuffer", snd["dsp_endx_buf"])
    ser.write_i32("spc.dsp.voiceOutput", snd["dsp_t_output"])
    ser.write_array_i32("spc.dsp.outSamples", [snd["dsp_t_main_out_l"], snd["dsp_t_main_out_r"]])
    ser.write_i32("spc.dsp.pitch", snd["dsp_t_pitch"])
    ser.write_u16("spc.dsp.sampleAddress", snd["dsp_t_dir_addr"])
    ser.write_u16("spc.dsp.brrNextAddress", snd["dsp_t_brr_next_addr"])
    ser.write_u8("spc.dsp.dirSampleTableAddress", snd["dsp_t_dir"])
    # These are voice bitmasks (uint8), NOT booleans
    ser.write_u8("spc.dsp.noiseOn", snd["dsp_t_non"])
    ser.write_u8("spc.dsp.pitchModulationOn", snd["dsp_t_pmon"])
    ser.write_u8("spc.dsp.keyOn", snd["dsp_kon"])
    ser.write_u8("spc.dsp.newKeyOn", snd["dsp_new_kon"])
    ser.write_u8("spc.dsp.keyOff", snd["dsp_t_koff"])
    ser.write_u8("spc.dsp.everyOtherSample", snd["dsp_every_other_sample"])
    ser.write_u8("spc.dsp.sourceNumber", snd["dsp_t_srcn"])
    ser.write_u8("spc.dsp.brrHeader", snd["dsp_t_brr_header"])
    ser.write_u8("spc.dsp.brrData", snd["dsp_t_brr_byte"])
    ser.write_u8("spc.dsp.looped", snd["dsp_t_looped"])  # voice bit flag, not bool
    ser.write_u8("spc.dsp.adsr1", snd["dsp_t_adsr0"])
    ser.write_array_i32("spc.dsp.echoIn", [snd["dsp_t_echo_in_l"], snd["dsp_t_echo_in_r"]])
    ser.write_array_i32("spc.dsp.echoOut", [snd["dsp_t_echo_out_l"], snd["dsp_t_echo_out_r"]])
    ser.write_array_i16("spc.dsp.echoHistory", snd["echo_history"])
    ser.write_u16("spc.dsp.echoPointer", snd["dsp_t_echo_ptr"])
    ser.write_u16("spc.dsp.echoLength", snd["dsp_echo_length"])
    ser.write_u16("spc.dsp.echoOffset", snd["dsp_echo_offset"])
    ser.write_u8("spc.dsp.echoHistoryPos", 0)
    ser.write_u8("spc.dsp.echoRingBufferAddress", snd["dsp_t_esa"])
    ser.write_u8("spc.dsp.echoOn", snd["dsp_t_eon"])  # voice bitmask
    ser.write_bool("spc.dsp.echoEnabled", bool(snd["dsp_t_echo_enabled"]))

    # SPC internal
    ser.write_u16("spc.operandA", 0)
    ser.write_u16("spc.operandB", 0)
    ser.write_u16("spc.tmp1", 0)
    ser.write_u16("spc.tmp2", 0)
    ser.write_u16("spc.tmp3", 0)
    ser.write_u8("spc.opCode", snd.get("opcode_number", 0) & 0xFF)
    ser.write_u8("spc.opStep", 0)
    ser.write_u8("spc.opSubStep", 0)
    ser.write_bool("spc.enabled", True)
    ser.write_array_u8("spc.newCpuRegs", cpu_regs[:4] if len(cpu_regs) >= 4 else [0, 0, 0, 0])
    ser.write_bool("spc.pendingCpuRegUpdate", False)

    # =================================================================
    # MSU-1 (console-level, between spc and controlManager)
    # =================================================================
    if "MSU" in s9x.blocks:
        msu = decode_msu1_block(s9x.blocks["MSU"])
        write_msu1(ser, msu)

    # =================================================================
    # Control Manager
    # =================================================================
    ser.write_u32("controlManager.pollCounter", 0)
    # Controller devices — port 0 is SnesController, port 1 is SnesMultitap
    ser.write_u8("controlManager.controlDevices[0].state", 0)
    ser.write_bool("controlManager.controlDevices[0].strobe", False)
    ser.write_u16("controlManager.controlDevices[1].state", 0)
    ser.write_u32("controlManager.controlDevices[1].stateBuffer", 0)
    ser.write_bool("controlManager.controlDevices[1].strobe", False)
    ser.write_u8("controlManager.lastWriteValue", 0)
    ser.write_bool("controlManager.autoReadStrobe", False)

    return ser.get_data()
