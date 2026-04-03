"""Convert a canonical SnesState into Mesen2 serialized binary data.

This module takes a :class:`~snes_save_state_converter.state.SnesState` and
produces the raw Mesen2 key-value binary blob.  The .mss file envelope is
handled separately by :func:`~snes_save_state_converter.mesen2.writer.write_mesen_savestate`.

Every key name, type, and encoding matches what Mesen2 expects (verified
against the Mesen2 C++ source ``Serialize()`` calls).
"""

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
from snes_save_state_converter.state import SnesState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pad(data: bytes, size: int) -> bytes:
    if len(data) >= size:
        return data[:size]
    return data + b"\x00" * (size - len(data))


def _write_coprocessors(ser: MesenSerializer, state: SnesState) -> None:
    """Dispatch coprocessor data to the appropriate Mesen2 writer."""
    ctype = state.coprocessor_type
    cdata = state.coprocessor_data
    if not ctype:
        return

    if ctype == "gsu":
        write_gsu(ser, cdata["sfx"], cdata["gsu_ram"])
    elif ctype == "sa1":
        write_sa1(ser, cdata["sa1"], cdata["sar"], cdata["fillram"], cdata["iram"])
    elif ctype == "nec_dsp":
        write_nec_dsp(ser, cdata["dsp"], ram=cdata["ram"],
                       ram_size=cdata["ram_size"], stack_size=cdata["stack_size"])
    elif ctype == "cx4":
        write_cx4(ser, cdata["raw"])
    elif ctype == "spc7110":
        write_spc7110(ser, cdata["spc7110"], cdata.get("rtc_data"))
    elif ctype == "bsx":
        write_bsx_cart(ser, cdata["bsx"])
    elif ctype == "msu1":
        write_msu1(ser, cdata["msu"])
    # obc1, srtc — nothing to serialize in Mesen2


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert(state: SnesState) -> bytes:
    """Return Mesen2 serialized state bytes built from *state*."""
    ser = MesenSerializer()

    cpu = state.cpu
    ppu = state.ppu
    spc = state.spc
    dma = state.dma
    iregs = state.internal_regs
    timing = state.timing

    # ---------------------------------------------------------------
    # Timing synthesis
    # ---------------------------------------------------------------
    is_pal = timing.is_pal
    overscan = timing.overscan
    vbl_start = timing.scanline  # typically 225 or 240
    vbl_end = 311 if is_pal else 261
    h_period = 1364

    # masterClock at start of VBlank scanline, 8-byte aligned for DRAM calc
    master_clock = vbl_start * h_period
    master_clock = (master_clock + 7) & ~7  # align to 8
    dram_refresh_pos = 538 - (master_clock & 0x07)  # = 538 since aligned
    # Place hClock just past DRAM refresh so next event is EndOfScanline
    h_clock = dram_refresh_pos + 40  # 40 master clocks for DRAM refresh
    master_clock += h_clock

    # SPC cycle: clockRatio ~ 32040*64 / 21477270 ~ 0.09548 for NTSC
    spc_clock_rate = 32040 * 64
    master_clock_rate = 24607104 if is_pal else 21477270
    spc_cycle = int(master_clock * spc_clock_rate / master_clock_rate)
    clock_ratio = spc_clock_rate / master_clock_rate

    # =================================================================
    # CPU
    # =================================================================
    ser.write_u16("cpu.a", cpu.a)
    ser.write_u64("cpu.cycleCount", master_clock)
    ser.write_u16("cpu.d", cpu.d)
    ser.write_u8("cpu.dbr", cpu.db)
    ser.write_bool("cpu.emulationMode", cpu.emulation)
    ser.write_u8("cpu.irqSource", cpu.irq_source)
    ser.write_u8("cpu.k", cpu.pb)
    ser.write_u8("cpu.nmiFlagCounter", 0)
    ser.write_u16("cpu.pc", cpu.pc)
    ser.write_u8("cpu.prevIrqSource", 0)
    ser.write_u8("cpu.ps", cpu.p & 0xFF)
    ser.write_u16("cpu.sp", cpu.sp)
    ser.write_u8("cpu.stopState", 2 if cpu.waiting_for_interrupt else 0)
    ser.write_u16("cpu.x", cpu.x)
    ser.write_u16("cpu.y", cpu.y)
    ser.write_bool("cpu.irqLock", False)
    ser.write_bool("cpu.needNmi", cpu.nmi_pending)
    ser.write_bool("cpu.waiOver", False)

    # =================================================================
    # Memory Manager
    # =================================================================
    ser.write_u64("memoryManager.masterClock", master_clock)
    ser.write_u8("memoryManager.openBus", 0)
    ser.write_u8("memoryManager.cpuSpeed", 6 if iregs.enable_fast_rom else 8)
    ser.write_u16("memoryManager.hClock", h_clock)
    ser.write_u16("memoryManager.dramRefreshPosition", dram_refresh_pos)
    ser.write_u32("memoryManager.memTypeBusA", 0)  # MemoryType enum (4 bytes)
    # Next event: EndOfScanline (3) at hClock=1360
    ser.write_u8("memoryManager.nextEvent", 3)   # SnesEventType::EndOfScanline
    ser.write_u16("memoryManager.nextEventClock", 1360)
    ser.write_array_u8("memoryManager.workRam", _pad(state.wram, 0x20000))
    ser.write_u32("memoryManager.registerHandlerB.wramPosition", state.wram_port_addr & 0x1FFFF)

    # =================================================================
    # PPU
    # =================================================================
    ser.write_bool("ppu.forcedBlank", ppu.forced_blank)
    ser.write_u8("ppu.screenBrightness", ppu.brightness)
    ser.write_u16("ppu.scanline", vbl_start)  # in VBlank
    ser.write_u32("ppu.frameCount", 0)
    ser.write_u8("ppu.bgMode", ppu.bg_mode)
    ser.write_bool("ppu.mode1Bg3Priority", ppu.mode1_bg3_priority)
    ser.write_u8("ppu.mainScreenLayers", ppu.main_screen_layers)
    ser.write_u8("ppu.subScreenLayers", ppu.sub_screen_layers)
    ser.write_u16("ppu.vramAddress", ppu.vram_addr)
    ser.write_u8("ppu.vramIncrementValue", ppu.vram_increment)
    ser.write_u8("ppu.vramAddressRemapping", ppu.vram_remap)
    ser.write_bool("ppu.vramAddrIncrementOnSecondReg", ppu.vram_incr_on_high)
    ser.write_u16("ppu.vramReadBuffer", ppu.vram_read_buffer)
    ser.write_u8("ppu.ppu1OpenBus", ppu.ppu1_open_bus)
    ser.write_u8("ppu.ppu2OpenBus", ppu.ppu2_open_bus)
    ser.write_u8("ppu.cgramAddress", ppu.cgram_addr)
    ser.write_u8("ppu.mosaicSize", ppu.mosaic_size)
    ser.write_u8("ppu.mosaicEnabled", ppu.mosaic_enabled)
    ser.write_u8("ppu.oamMode", ppu.oam_mode)
    ser.write_u16("ppu.oamBaseAddress", ppu.oam_base_addr)
    ser.write_u16("ppu.oamAddressOffset", ppu.oam_addr_offset)
    ser.write_u16("ppu.oamRamAddress", ppu.oam_ram_addr)
    ser.write_bool("ppu.enableOamPriority", ppu.oam_priority_rotation)
    ser.write_u8("ppu.oamWriteBuffer", ppu.oam_write_buffer & 0xFF)
    ser.write_bool("ppu.timeOver", False)
    ser.write_bool("ppu.rangeOver", False)
    ser.write_bool("ppu.hiResMode", ppu.hi_res)
    ser.write_bool("ppu.screenInterlace", ppu.screen_interlace)
    ser.write_bool("ppu.objInterlace", ppu.obj_interlace)
    ser.write_bool("ppu.overscanMode", ppu.overscan)
    ser.write_bool("ppu.directColorMode", ppu.direct_color)

    # ColorWindowMode is enum class (4 bytes, not 1)
    ser.write_u32("ppu.colorMathClipMode", ppu.color_clip_mode)
    ser.write_u32("ppu.colorMathPreventMode", ppu.color_prevent_mode)
    ser.write_bool("ppu.colorMathAddSubscreen", ppu.color_add_subscreen)
    ser.write_u8("ppu.colorMathEnabled", ppu.color_math_enabled)
    ser.write_bool("ppu.colorMathSubtractMode", ppu.color_subtract)
    ser.write_bool("ppu.colorMathHalveResult", ppu.color_halve)
    ser.write_u16("ppu.fixedColor", ppu.fixed_color)

    ser.write_u8("ppu.hvScrollLatchValue", ppu.hv_scroll_latch)
    ser.write_u8("ppu.hScrollLatchValue", ppu.h_scroll_latch)

    # WindowMaskLogic is enum class (4 bytes)
    for i in range(6):
        ser.write_u32(f"ppu.maskLogic[{i}]", ppu.mask_logic[i])

    for i in range(5):
        ser.write_bool(f"ppu.windowMaskMain[{i}]", ppu.window_mask_main[i])
        ser.write_bool(f"ppu.windowMaskSub[{i}]", ppu.window_mask_sub[i])

    # Mode 7
    ser.write_i16("ppu.mode7.centerX", ppu.mode7.center_x)
    ser.write_i16("ppu.mode7.centerY", ppu.mode7.center_y)
    ser.write_bool("ppu.extBgEnabled", ppu.ext_bg)
    ser.write_bool("ppu.mode7.fillWithTile0", ppu.mode7.fill_with_tile0)
    ser.write_bool("ppu.mode7.horizontalMirroring", ppu.mode7.h_mirror)
    ser.write_i16("ppu.mode7.hscroll", ppu.mode7.hscroll)
    ser.write_bool("ppu.mode7.largeMap", ppu.mode7.large_map)
    ser.write_i16("ppu.mode7.matrix[0]", ppu.mode7.matrix[0])
    ser.write_i16("ppu.mode7.matrix[1]", ppu.mode7.matrix[1])
    ser.write_i16("ppu.mode7.matrix[2]", ppu.mode7.matrix[2])
    ser.write_i16("ppu.mode7.matrix[3]", ppu.mode7.matrix[3])
    ser.write_u8("ppu.mode7.valueLatch", ppu.mode7.value_latch)
    ser.write_bool("ppu.mode7.verticalMirroring", ppu.mode7.v_mirror)
    ser.write_i16("ppu.mode7.vscroll", ppu.mode7.vscroll)

    ser.write_bool("ppu.cgramAddressLatch", ppu.cgram_latch)
    ser.write_u8("ppu.cgramWriteBuffer", ppu.cgram_write_buffer)
    ser.write_u16("ppu.internalOamAddress", ppu.internal_oam_addr)
    ser.write_u8("ppu.internalCgramAddress", ppu.internal_cgram_addr)

    # Layers
    for i in range(4):
        lp = f"ppu.layers[{i}]."
        layer = ppu.layers[i]
        ser.write_u16(lp + "chrAddress", layer.chr_addr)
        ser.write_bool(lp + "doubleHeight", layer.double_height)
        ser.write_bool(lp + "doubleWidth", layer.double_width)
        ser.write_u16(lp + "hscroll", layer.hscroll)
        ser.write_bool(lp + "largeTiles", layer.large_tiles)
        ser.write_u16(lp + "tilemapAddress", layer.tilemap_addr)
        ser.write_u16(lp + "vscroll", layer.vscroll)

    # Windows
    for w in range(2):
        wp = f"ppu.window[{w}]."
        win = ppu.windows[w]
        for layer in range(6):
            ser.write_bool(f"{wp}activeLayers[{layer}]", win.active[layer])
        for layer in range(6):
            ser.write_bool(f"{wp}invertedLayers[{layer}]", win.inverted[layer])
        ser.write_u8(wp + "left", win.left)
        ser.write_u8(wp + "right", win.right)

    # VRAM (uint16 LE array, 32K words)
    vram_raw = ppu.vram
    vram_words = [
        int.from_bytes(vram_raw[i : i + 2], "little")
        for i in range(0, min(len(vram_raw), 0x10000), 2)
    ]
    vram_words.extend([0] * (0x8000 - len(vram_words)))
    ser.write_array_u16("ppu.vram", vram_words)

    ser.write_array_u8("ppu.oamRam", ppu.oam)
    ser.write_array_u16("ppu.cgram", ppu.cgram)

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

    # Layer tile cache
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
    ser.write_u8("dmaController.hdmaChannels", dma.hdma_channels)
    ser.write_bool("dmaController.dmaPending", False)
    ser.write_u32("dmaController.dmaClockCounter", 0)
    ser.write_bool("dmaController.hdmaInitPending", False)
    ser.write_bool("dmaController.dmaStartDelay", False)
    ser.write_bool("dmaController.needToProcess", False)

    for i in range(8):
        dp = f"dmaController.channel[{i}]."
        ch = dma.channels[i]
        ser.write_bool(dp + "decrement", ch.decrement)
        ser.write_u8(dp + "destAddress", ch.dest_addr)
        ser.write_bool(dp + "doTransfer", ch.do_transfer)
        ser.write_bool(dp + "fixedTransfer", ch.fixed_transfer)
        ser.write_u8(dp + "hdmaBank", ch.hdma_bank)
        ser.write_bool(dp + "hdmaFinished", ch.hdma_finished)
        ser.write_bool(dp + "hdmaIndirectAddressing", ch.hdma_indirect)
        ser.write_u8(dp + "hdmaLineCounterAndRepeat", ch.hdma_line_counter)
        ser.write_u16(dp + "hdmaTableAddress", ch.hdma_table_addr)
        ser.write_bool(dp + "invertDirection", ch.invert_direction)
        ser.write_u16(dp + "srcAddress", ch.src_addr)
        ser.write_u8(dp + "srcBank", ch.src_bank)
        ser.write_u8(dp + "transferMode", ch.transfer_mode)
        ser.write_u16(dp + "transferSize", ch.transfer_size)
        ser.write_bool(dp + "unusedControlFlag", ch.unused_flag)
        ser.write_bool(dp + "dmaActive", ch.dma_active)
        ser.write_u8(dp + "unusedRegister", ch.unused_register)

    # =================================================================
    # Internal Registers
    # =================================================================
    ser.write_bool("internalRegisters.enableFastRom", iregs.enable_fast_rom)
    ser.write_bool("internalRegisters.nmiFlag", iregs.nmi_flag)
    ser.write_bool("internalRegisters.enableNmi", iregs.enable_nmi)
    ser.write_bool("internalRegisters.enableHorizontalIrq", iregs.enable_h_irq)
    ser.write_bool("internalRegisters.enableVerticalIrq", iregs.enable_v_irq)
    ser.write_u16("internalRegisters.horizontalTimer", iregs.h_timer)
    ser.write_u16("internalRegisters.verticalTimer", iregs.v_timer)
    ser.write_u8("internalRegisters.ioPortOutput", iregs.io_port_output)
    # ControllerData is uint16[4]
    for i in range(4):
        ser.write_u16(f"internalRegisters.controllerData[{i}]",
                       iregs.controller_data[i] if i < len(iregs.controller_data) else 0)
    ser.write_bool("internalRegisters.irqLevel", iregs.irq_level)
    ser.write_u8("internalRegisters.needIrq", iregs.need_irq)
    ser.write_bool("internalRegisters.enableAutoJoypadRead", iregs.enable_auto_joypad)
    ser.write_bool("internalRegisters.irqFlag", iregs.irq_flag)

    ap = "internalRegisters.aluMulDiv."
    ser.write_u8(ap + "multOperand1", iregs.mult_operand1)
    ser.write_u8(ap + "multOperand2", iregs.mult_operand2)
    ser.write_u16(ap + "multOrRemainderResult", iregs.mult_result)
    ser.write_u16(ap + "dividend", iregs.dividend)
    ser.write_u8(ap + "divisor", iregs.divisor)
    ser.write_u16(ap + "divResult", iregs.div_result)
    ser.write_u8(ap + "divCounter", 0)
    ser.write_u8(ap + "multCounter", 0)
    ser.write_u32(ap + "shift", 0)  # uint32_t in AluMulDiv
    ser.write_u64(ap + "prevCpuCycle", 0)

    ser.write_u64("internalRegisters.autoReadClockStart", 0)
    ser.write_u64("internalRegisters.autoReadNextClock", 0)
    ser.write_bool("internalRegisters.autoReadActive", False)
    ser.write_bool("internalRegisters.autoReadDisabled", False)
    ser.write_u8("internalRegisters.autoReadPort1Value", 0)
    ser.write_u8("internalRegisters.autoReadPort2Value", 0)
    ser.write_u16("internalRegisters.hCounter", iregs.h_counter)
    ser.write_u16("internalRegisters.vCounter", iregs.v_counter)

    # =================================================================
    # Cartridge
    # =================================================================
    ser.write_array_u8("cart.saveRam", state.sram if state.sram else b"")

    # -- Coprocessors (serialized inside BaseCartridge::Serialize) ------
    _write_coprocessors(ser, state)

    # =================================================================
    # SPC
    # =================================================================
    ser.write_u8("spc.a", spc.a)
    ser.write_u64("spc.cycle", spc_cycle)
    ser.write_u16("spc.pc", spc.pc)
    ser.write_u8("spc.ps", spc.psw)
    ser.write_u8("spc.sp", spc.sp)
    ser.write_u8("spc.x", spc.x)
    ser.write_u8("spc.y", spc.y)

    for i in range(4):
        ser.write_u8(f"spc.cpuRegs[{i}]",
                      spc.cpu_regs[i] if i < len(spc.cpu_regs) else 0)
    for i in range(4):
        ser.write_u8(f"spc.outputReg[{i}]",
                      spc.output_regs[i] if i < len(spc.output_regs) else 0)
    ser.write_u8("spc.ramReg[0]", spc.ram_regs[0] if len(spc.ram_regs) > 0 else 0)
    ser.write_u8("spc.ramReg[1]", spc.ram_regs[1] if len(spc.ram_regs) > 1 else 0)

    ser.write_u8("spc.externalSpeed", spc.external_speed)
    ser.write_u8("spc.internalSpeed", spc.internal_speed)
    ser.write_bool("spc.writeEnabled", spc.write_enabled)
    ser.write_bool("spc.timersEnabled", spc.timers_enabled)
    ser.write_u8("spc.dspReg", spc.dsp_reg)
    ser.write_bool("spc.romEnabled", spc.rom_enabled)
    ser.write_f64("spc.clockRatio", clock_ratio)
    ser.write_bool("spc.timersDisabled", spc.timers_disabled)

    # Mesen2 SpcTimer fields:
    #   stage0 = prescaler, stage1 = toggle bit (0 or 1),
    #   stage2 = counter, output = output counter (4-bit)
    for t in range(3):
        tp = f"spc.timer{t}."
        timer = spc.timers[t]
        ser.write_u8(tp + "stage0", timer.stage0 & 0xFF)
        ser.write_u8(tp + "stage1", 0)  # toggle bit
        ser.write_u8(tp + "stage2", timer.counter & 0xFF)
        ser.write_u8(tp + "output", timer.output & 0x0F)
        ser.write_u8(tp + "target", timer.target)
        ser.write_bool(tp + "enabled", timer.enabled)
        ser.write_bool(tp + "timersEnabled", True)
        ser.write_u8(tp + "prevStage1", 0)

    ser.write_array_u8("spc.ram", _pad(
        spc.ram if isinstance(spc.ram, (bytes, bytearray)) else bytes(spc.ram),
        0x10000,
    ))

    # -- DSP ---------------------------------------------------------------
    dsp = spc.dsp
    ser.write_array_u8("spc.dsp.regs", _pad(dsp.regs, 128))
    ser.write_array_u8("spc.dsp.externalRegs", _pad(dsp.external_regs, 128))

    # DSP voices
    for i in range(8):
        vp = f"spc.dsp.voices[{i}]."
        v = dsp.voices[i]
        ser.write_i32(vp + "envVolume", v.env_volume)
        ser.write_i32(vp + "prevCalculatedEnv", v.prev_env)
        ser.write_i32(vp + "interpolationPos", v.interp_pos)
        ser.write_u32(vp + "envMode", v.env_mode)  # EnvelopeMode enum (4 bytes)
        ser.write_u16(vp + "brrAddress", v.brr_addr)
        ser.write_u16(vp + "brrOffset", v.brr_offset)
        ser.write_u8(vp + "voiceBit", v.voice_bit)
        ser.write_u8(vp + "keyOnDelay", v.key_on_delay)
        ser.write_u8(vp + "envOut", v.env_out)
        ser.write_u8(vp + "bufferPos", v.buffer_pos)
        ser.write_array_i16(vp + "sampleBuffer", v.sample_buffer)

    # DSP global state
    ser.write_i32("spc.dsp.noiseLfsr", dsp.noise_lfsr)
    ser.write_u16("spc.dsp.counter", dsp.counter)
    ser.write_u8("spc.dsp.step", dsp.step)
    ser.write_u8("spc.dsp.outRegBuffer", dsp.out_reg_buffer)
    ser.write_u8("spc.dsp.envRegBuffer", dsp.env_reg_buffer)
    ser.write_u8("spc.dsp.voiceEndBuffer", dsp.voice_end_buffer)
    ser.write_i32("spc.dsp.voiceOutput", dsp.voice_output)
    ser.write_array_i32("spc.dsp.outSamples", dsp.out_samples)
    ser.write_i32("spc.dsp.pitch", dsp.pitch)
    ser.write_u16("spc.dsp.sampleAddress", dsp.sample_addr)
    ser.write_u16("spc.dsp.brrNextAddress", dsp.brr_next_addr)
    ser.write_u8("spc.dsp.dirSampleTableAddress", dsp.dir_sample_table_addr)
    # These are voice bitmasks (uint8), NOT booleans
    ser.write_u8("spc.dsp.noiseOn", dsp.noise_on)
    ser.write_u8("spc.dsp.pitchModulationOn", dsp.pitch_mod_on)
    ser.write_u8("spc.dsp.keyOn", dsp.key_on)
    ser.write_u8("spc.dsp.newKeyOn", dsp.new_key_on)
    ser.write_u8("spc.dsp.keyOff", dsp.key_off)
    ser.write_u8("spc.dsp.everyOtherSample", dsp.every_other_sample)
    ser.write_u8("spc.dsp.sourceNumber", dsp.source_number)
    ser.write_u8("spc.dsp.brrHeader", dsp.brr_header)
    ser.write_u8("spc.dsp.brrData", dsp.brr_data)
    ser.write_u8("spc.dsp.looped", dsp.looped)  # voice bit flag, not bool
    ser.write_u8("spc.dsp.adsr1", dsp.adsr1)
    ser.write_array_i32("spc.dsp.echoIn", dsp.echo_in)
    ser.write_array_i32("spc.dsp.echoOut", dsp.echo_out)
    ser.write_array_i16("spc.dsp.echoHistory", dsp.echo_history)
    ser.write_u16("spc.dsp.echoPointer", dsp.echo_pointer)
    ser.write_u16("spc.dsp.echoLength", dsp.echo_length)
    ser.write_u16("spc.dsp.echoOffset", dsp.echo_offset)
    ser.write_u8("spc.dsp.echoHistoryPos", dsp.echo_history_pos)
    ser.write_u8("spc.dsp.echoRingBufferAddress", dsp.echo_ring_buffer_addr)
    ser.write_u8("spc.dsp.echoOn", dsp.echo_on)  # voice bitmask
    ser.write_bool("spc.dsp.echoEnabled", dsp.echo_enabled)

    # SPC internal
    ser.write_u16("spc.operandA", spc.operand_a)
    ser.write_u16("spc.operandB", spc.operand_b)
    ser.write_u16("spc.tmp1", spc.tmp1)
    ser.write_u16("spc.tmp2", spc.tmp2)
    ser.write_u16("spc.tmp3", spc.tmp3)
    ser.write_u8("spc.opCode", spc.op_code & 0xFF)
    ser.write_u8("spc.opStep", spc.op_step)
    ser.write_u8("spc.opSubStep", spc.op_sub_step)
    ser.write_bool("spc.enabled", spc.enabled)
    ser.write_array_u8("spc.newCpuRegs",
                        spc.new_cpu_regs[:4] if len(spc.new_cpu_regs) >= 4 else [0, 0, 0, 0])
    ser.write_bool("spc.pendingCpuRegUpdate", spc.pending_cpu_reg_update)

    # =================================================================
    # MSU-1 (console-level, between spc and controlManager)
    # =================================================================
    if state.coprocessor_type == "msu1":
        write_msu1(ser, state.coprocessor_data["msu"])

    # =================================================================
    # Control Manager
    # =================================================================
    ser.write_u32("controlManager.pollCounter", 0)
    # Controller devices -- port 0 is SnesController, port 1 is SnesMultitap
    ser.write_u8("controlManager.controlDevices[0].state", 0)
    ser.write_bool("controlManager.controlDevices[0].strobe", False)
    ser.write_u16("controlManager.controlDevices[1].state", 0)
    ser.write_u32("controlManager.controlDevices[1].stateBuffer", 0)
    ser.write_bool("controlManager.controlDevices[1].strobe", False)
    ser.write_u8("controlManager.lastWriteValue", 0)
    ser.write_bool("controlManager.autoReadStrobe", False)

    return ser.get_data()
