"""Map decoded snes9x state into a canonical SnesState dataclass."""

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
from snes_save_state_converter.state import (
    BgLayerState,
    CpuState,
    DmaChannelState,
    DmaState,
    DspState,
    DspVoiceState,
    InternalRegState,
    Mode7State,
    PpuState,
    SnesState,
    SpcState,
    SpcTimerState,
    TimingState,
    WindowState,
)


# -- FillRAM helpers (snes9x register backing store) -----------------------
# The FIL block is a raw copy of Memory.FillRAM starting at offset 0.
# Hardware register $XXXX is at fillram[$XXXX].


def _fr(fillram: bytes, addr: int) -> int:
    return fillram[addr] if 0 <= addr < len(fillram) else 0


def _fr16(fillram: bytes, addr: int) -> int:
    return _fr(fillram, addr) | (_fr(fillram, addr + 1) << 8)


# -- Conversion ------------------------------------------------------------


def _write_coprocessors(
    s9x: Snes9xState,
    fillram: bytes,
) -> tuple[str, dict]:
    """Detect which coprocessor blocks exist and return (type_name, data_dict)."""
    blocks = s9x.blocks
    ver = s9x.version

    # SuperFX / GSU
    if "SFX" in blocks:
        sfx = decode_sfx_block(blocks["SFX"])
        gsu_ram = blocks.get("SRA", b"")
        return "gsu", {"sfx": sfx, "gsu_ram": gsu_ram}

    # SA-1
    if "SA1" in blocks and "SAR" in blocks:
        sa1 = decode_sa1_block(blocks["SA1"], ver)
        sar = decode_sar_block(blocks["SAR"])
        iram = b""
        return "sa1", {"sa1": sa1, "sar": sar, "fillram": fillram, "iram": iram}

    # DSP-1
    if "DP1" in blocks:
        dsp1 = decode_dsp1_block(blocks["DP1"])
        return "nec_dsp", {"dsp": dsp1, "ram": b"", "ram_size": 512, "stack_size": 32}

    # DSP-2
    if "DP2" in blocks:
        dsp2 = decode_dsp2_block(blocks["DP2"])
        return "nec_dsp", {"dsp": dsp2, "ram": b"", "ram_size": 512, "stack_size": 32}

    # DSP-4
    if "DP4" in blocks:
        dsp4 = decode_dsp4_block(blocks["DP4"])
        return "nec_dsp", {"dsp": dsp4, "ram": b"", "ram_size": 512, "stack_size": 32}

    # ST-010 / ST-011 (SETA chips — also use NEC DSP in Mesen2)
    if "ST0" in blocks:
        st010 = decode_st010_block(blocks["ST0"])
        return "nec_dsp", {"dsp": st010, "ram": b"", "ram_size": 4096, "stack_size": 64}

    # CX4
    if "CX4" in blocks:
        return "cx4", {"raw": blocks["CX4"]}

    # SPC7110
    if "S71" in blocks:
        s71 = decode_spc7110_block(blocks["S71"])
        rtc_data = blocks.get("CLK", None)
        return "spc7110", {"spc7110": s71, "rtc_data": rtc_data}

    # OBC1 — Mesen2 has an empty Serialize(), nothing to write
    if "OBC" in blocks:
        _ = decode_obc1_block(blocks["OBC"])
        return "obc1", {}

    # BS-X
    if "BSX" in blocks:
        bsx = decode_bsx_block(blocks["BSX"])
        return "bsx", {"bsx": bsx}

    # S-RTC (standalone, without SPC7110)
    if "SRT" in blocks:
        _ = decode_srtc_block(blocks["SRT"])
        return "srtc", {}

    # MSU-1 (not a coprocessor in the traditional sense, but included here)
    if "MSU" in blocks:
        msu = decode_msu1_block(blocks["MSU"])
        return "msu1", {"msu": msu}

    return "", {}


def _pad(data: bytes, size: int) -> bytes:
    if len(data) >= size:
        return data[:size]
    return data + b"\x00" * (size - len(data))


def convert(s9x: Snes9xState) -> SnesState:
    """Return a SnesState populated from *s9x*."""
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
    is_pal = tim.get("V_Max_Master", 262) > 262

    state = SnesState()

    # =================================================================
    # CPU
    # =================================================================
    irq = 0
    if cpu_b.get("IRQLine", 0):
        irq |= 1
    if cpu_b.get("IRQExternal", 0):
        irq |= 2

    state.cpu = CpuState(
        a=reg_b["A"],
        x=reg_b["X"],
        y=reg_b["Y"],
        sp=reg_b["S"],
        d=reg_b["D"],
        db=reg_b["DB"],
        pb=reg_b["PB"],
        pc=reg_b["PC"],
        p=reg_b["P"] & 0xFF,
        emulation=False,
        irq_source=irq,
        nmi_pending=bool(cpu_b.get("NMIPending", 0)),
        waiting_for_interrupt=bool(cpu_b["WaitingForInterrupt"]),
    )

    # =================================================================
    # Timing
    # =================================================================
    vbl_start = 240 if overscan else 225

    state.timing = TimingState(
        scanline=vbl_start,
        is_pal=is_pal,
        overscan=overscan,
    )

    # =================================================================
    # PPU
    # =================================================================
    r2130 = _fr(fr, 0x2130)
    r2131 = _fr(fr, 0x2131)
    mosaic = _fr(fr, 0x2106)
    obsel = _fr(fr, 0x2101)

    r = ppu_b["FixedColourRed"] & 0x1F
    g = ppu_b["FixedColourGreen"] & 0x1F
    b = ppu_b["FixedColourBlue"] & 0x1F

    # snes9x VMA.Shift stores the shift amount (0,5,6,7) — convert to
    # 2-bit mode index (0,1,2,3) which is the raw (reg >> 2) & 3 value.
    shift_to_mode = {0: 0, 5: 1, 6: 2, 7: 3}

    wlog1 = _fr(fr, 0x212A)
    wlog2 = _fr(fr, 0x212B)
    mask_logic = [0] * 6
    for i in range(6):
        shift = (i * 2) if i < 4 else ((i - 4) * 2)
        reg = wlog1 if i < 4 else wlog2
        mask_logic[i] = (reg >> shift) & 3

    wmain = _fr(fr, 0x212E)
    wsub = _fr(fr, 0x212F)
    window_mask_main = [bool(wmain & (1 << i)) for i in range(5)]
    window_mask_sub = [bool(wsub & (1 << i)) for i in range(5)]

    # Mode 7
    mode7 = Mode7State(
        matrix=[ppu_b["MatrixA"], ppu_b["MatrixB"], ppu_b["MatrixC"], ppu_b["MatrixD"]],
        hscroll=ppu_b["M7HOFS"],
        vscroll=ppu_b["M7VOFS"],
        center_x=ppu_b["CentreX"],
        center_y=ppu_b["CentreY"],
        value_latch=ppu_b["M7byte"],
        large_map=ppu_b["Mode7Repeat"] >= 2,
        fill_with_tile0=ppu_b["Mode7Repeat"] == 0,
        h_mirror=bool(ppu_b["Mode7HFlip"]),
        v_mirror=bool(ppu_b["Mode7VFlip"]),
    )

    # Layers
    layers = []
    for i in range(4):
        sp = f"BG{i}_"
        sc = ppu_b[sp + "SCSize"]
        layers.append(BgLayerState(
            tilemap_addr=ppu_b[sp + "SCBase"],
            chr_addr=ppu_b[sp + "NameBase"],
            hscroll=ppu_b[sp + "HOffset"],
            vscroll=ppu_b[sp + "VOffset"],
            double_width=bool(sc & 1),
            double_height=bool(sc & 2),
            large_tiles=bool(ppu_b[sp + "BGSize"]),
        ))

    # Windows
    regs_w = [_fr(fr, 0x2123), _fr(fr, 0x2124), _fr(fr, 0x2125)]
    windows = []
    for w in range(2):
        active = [False] * 6
        inverted = [False] * 6
        for layer in range(6):
            bits = (regs_w[layer // 2] >> ((layer % 2) * 4 + w * 2)) & 3
            active[layer] = bool(bits & 2)
            inverted[layer] = bool(bits & 1)
        if w == 0:
            left = ppu_b["Window1Left"]
            right = ppu_b["Window1Right"]
        else:
            left = ppu_b["Window2Left"]
            right = ppu_b["Window2Right"]
        windows.append(WindowState(
            left=left,
            right=right,
            active=active,
            inverted=inverted,
        ))

    # VRAM — kept as raw bytes (64KB)
    vram_padded = _pad(vram, 0x10000)

    state.ppu = PpuState(
        forced_blank=bool(ppu_b["ForcedBlanking"]),
        brightness=ppu_b["Brightness"],
        bg_mode=ppu_b["BGMode"],
        mode1_bg3_priority=bool(ppu_b["BG3Priority"]),
        main_screen_layers=_fr(fr, 0x212C),
        sub_screen_layers=_fr(fr, 0x212D),
        vram_addr=ppu_b["VMA_Address"],
        vram_increment=ppu_b["VMA_Increment"],
        vram_remap=shift_to_mode.get(ppu_b["VMA_Shift"], 0),
        vram_incr_on_high=bool(ppu_b["VMA_High"]),
        vram_read_buffer=ppu_b.get("VRAMReadBuffer", 0),
        oam_mode=(obsel >> 5) & 7,
        oam_base_addr=(obsel & 0x07) << 13,
        oam_addr_offset=(((obsel >> 3) & 0x03) + 1) << 12,
        oam_ram_addr=ppu_b["OAMAddr"],
        internal_oam_addr=ppu_b["SavedOAMAddr"],
        oam_priority_rotation=bool(ppu_b["OAMPriorityRotation"]),
        oam_write_buffer=ppu_b["OAMWriteRegister"] & 0xFF,
        cgram_addr=ppu_b["CGADD"],
        internal_cgram_addr=ppu_b["CGADD"],
        cgram_write_buffer=ppu_b.get("CGSavedByte", 0),
        cgram_latch=bool(ppu_b["CGFLIP"]),
        mosaic_size=((mosaic >> 4) & 0xF) + 1,
        mosaic_enabled=mosaic & 0x0F,
        hi_res=bool(setini & 0x08),
        screen_interlace=bool(setini & 0x01),
        obj_interlace=bool(setini & 0x02),
        overscan=overscan,
        direct_color=bool(r2130 & 0x01),
        ext_bg=bool(setini & 0x40),
        color_clip_mode=(r2130 >> 6) & 3,
        color_prevent_mode=(r2130 >> 4) & 3,
        color_add_subscreen=bool(r2130 & 0x02),
        color_math_enabled=r2131 & 0x3F,
        color_subtract=bool(r2131 & 0x80),
        color_halve=bool(r2131 & 0x40),
        fixed_color=r | (g << 5) | (b << 10),
        ppu1_open_bus=ppu_b["OpenBus1"],
        ppu2_open_bus=ppu_b["OpenBus2"],
        hv_scroll_latch=ppu_b["BGnxOFSbyte"],
        h_scroll_latch=0,
        mask_logic=mask_logic,
        window_mask_main=window_mask_main,
        window_mask_sub=window_mask_sub,
        layers=layers,
        windows=windows,
        mode7=mode7,
        vram=vram_padded,
        oam=bytes(ppu_b["OAMData"]) if not isinstance(ppu_b["OAMData"], bytes) else ppu_b["OAMData"],
        cgram=list(ppu_b["CGDATA"]),
    )

    # =================================================================
    # DMA
    # =================================================================
    dma_channels = []
    for i in range(8):
        ch = dma_ch[i]
        dma_channels.append(DmaChannelState(
            transfer_mode=ch["TransferMode"],
            dest_addr=ch["BAddress"],
            src_addr=ch["AAddress"],
            src_bank=ch["ABank"],
            transfer_size=ch["DMACount_Or_HDMAIndirectAddress"],
            hdma_bank=ch["IndirectBank"],
            hdma_table_addr=ch["Address"],
            hdma_line_counter=ch["LineCount"] | (ch["Repeat"] << 7),
            invert_direction=bool(ch["ReverseTransfer"]),
            hdma_indirect=bool(ch["HDMAIndirectAddressing"]),
            decrement=bool(ch["AAddressDecrement"]),
            fixed_transfer=bool(ch["AAddressFixed"]),
            unused_flag=bool(ch["UnusedBit43x0"]),
            unused_register=ch["UnknownByte"],
            do_transfer=bool(ch["DoTransfer"]),
            hdma_finished=False,
            dma_active=False,
        ))

    state.dma = DmaState(
        hdma_channels=ppu_b["HDMA"],
        channels=dma_channels,
    )

    # =================================================================
    # Internal Registers
    # =================================================================
    r4200 = _fr(fr, 0x4200)

    controller_data = [_fr16(fr, 0x4218 + i * 2) for i in range(4)]

    state.internal_regs = InternalRegState(
        enable_fast_rom=fast_rom,
        nmi_flag=True,  # we're in VBlank
        enable_nmi=bool(r4200 & 0x80),
        enable_h_irq=bool(ppu_b["HTimerEnabled"]),
        enable_v_irq=bool(ppu_b["VTimerEnabled"]),
        h_timer=ppu_b["IRQHBeamPos"],
        v_timer=ppu_b["IRQVBeamPos"],
        io_port_output=_fr(fr, 0x4201),
        controller_data=controller_data,
        irq_level=False,
        need_irq=0,
        enable_auto_joypad=bool(r4200 & 0x01),
        irq_flag=False,
        mult_operand1=_fr(fr, 0x4202),
        mult_operand2=_fr(fr, 0x4203),
        mult_result=_fr16(fr, 0x4216),
        dividend=_fr16(fr, 0x4204),
        divisor=_fr(fr, 0x4206),
        div_result=_fr16(fr, 0x4214),
        h_counter=ppu_b["HBeamPosLatched"],
        v_counter=ppu_b["VBeamPosLatched"],
    )

    # =================================================================
    # Memory
    # =================================================================
    state.wram = _pad(wram, 0x20000)
    state.sram = sram if sram else b""
    state.wram_port_addr = ppu_b["WRAM"] & 0x1FFFF

    # =================================================================
    # Coprocessors
    # =================================================================
    coproc_type, coproc_data = _write_coprocessors(s9x, fr)
    state.coprocessor_type = coproc_type
    state.coprocessor_data = coproc_data

    # =================================================================
    # SPC
    # =================================================================
    cpu_regs = snd.get("cpu_regs", [0, 0, 0, 0])
    spc_ram = snd["spc_ram"]
    output_regs = [
        spc_ram[0xF4 + i] if len(spc_ram) > 0xF7 else 0
        for i in range(4)
    ]

    # SPC TEST register ($F0) bits — derive from SPC RAM
    spc_test = spc_ram[0xF0] if len(spc_ram) > 0xF0 else 0

    # Timers
    spc_timers = []
    for t in range(3):
        sp = f"timer{t}_"
        spc_timers.append(SpcTimerState(
            enabled=bool(snd.get(sp + "enable", 0)),
            target=snd.get(sp + "target", 0),
            stage0=snd.get(sp + "stage1_ticks", 0) & 0xFF,
            counter=snd.get(sp + "stage2_ticks", 0) & 0xFF,
            output=snd.get(sp + "stage3_ticks", 0) & 0x0F,
        ))

    # DSP voices
    dsp_voices = []
    for i in range(8):
        v = snd["voices"][i]
        dsp_voices.append(DspVoiceState(
            env_volume=v["env"],
            prev_env=v["env"],
            interp_pos=v["interp_pos"],
            env_mode=v["env_mode"],
            brr_addr=v["brr_addr"],
            brr_offset=v["brr_offset"],
            voice_bit=1 << i,
            key_on_delay=v["kon_delay"],
            env_out=v["t_envx_out"],
            buffer_pos=v["buf_pos"],
            sample_buffer=list(v["brr_buffer"]),
        ))

    # DSP state
    dsp = DspState(
        regs=_pad(snd["dsp_regs"], 128),
        external_regs=_pad(snd.get("dsp_external_regs", snd["dsp_regs"]), 128),
        voices=dsp_voices,
        noise_lfsr=snd["dsp_noise"],
        counter=snd["dsp_counter"],
        step=snd["dsp_phase"],
        out_reg_buffer=snd["dsp_outx_buf"],
        env_reg_buffer=snd["dsp_envx_buf"],
        voice_end_buffer=snd["dsp_endx_buf"],
        voice_output=snd["dsp_t_output"],
        out_samples=[snd["dsp_t_main_out_l"], snd["dsp_t_main_out_r"]],
        pitch=snd["dsp_t_pitch"],
        sample_addr=snd["dsp_t_dir_addr"],
        brr_next_addr=snd["dsp_t_brr_next_addr"],
        dir_sample_table_addr=snd["dsp_t_dir"],
        noise_on=snd["dsp_t_non"],
        pitch_mod_on=snd["dsp_t_pmon"],
        key_on=snd["dsp_kon"],
        new_key_on=snd["dsp_new_kon"],
        key_off=snd["dsp_t_koff"],
        every_other_sample=snd["dsp_every_other_sample"],
        source_number=snd["dsp_t_srcn"],
        brr_header=snd["dsp_t_brr_header"],
        brr_data=snd["dsp_t_brr_byte"],
        looped=snd["dsp_t_looped"],
        adsr1=snd["dsp_t_adsr0"],
        echo_in=[snd["dsp_t_echo_in_l"], snd["dsp_t_echo_in_r"]],
        echo_out=[snd["dsp_t_echo_out_l"], snd["dsp_t_echo_out_r"]],
        echo_history=list(snd["echo_history"]),
        echo_pointer=snd["dsp_t_echo_ptr"],
        echo_length=snd["dsp_echo_length"],
        echo_offset=snd["dsp_echo_offset"],
        echo_history_pos=0,
        echo_ring_buffer_addr=snd["dsp_t_esa"],
        echo_on=snd["dsp_t_eon"],
        echo_enabled=bool(snd["dsp_t_echo_enabled"]),
    )

    state.spc = SpcState(
        a=snd["a"],
        x=snd["x"],
        y=snd["y"],
        sp=snd["sp"],
        pc=snd["pc"],
        psw=snd["psw"],
        cpu_regs=list(cpu_regs[:4]) if len(cpu_regs) >= 4 else [0, 0, 0, 0],
        output_regs=output_regs,
        ram_regs=[snd.get("ram00f8", 0) & 0xFF, snd.get("ram00f9", 0) & 0xFF],
        write_enabled=True,  # must be true or SPC can't write RAM
        rom_enabled=bool(snd["iplrom_enable"]),
        timers_enabled=bool(spc_test & 0x08) if spc_test else True,
        timers_disabled=bool(spc_test & 0x01) if spc_test else False,
        internal_speed=(spc_test >> 6) & 0x03,
        external_speed=(spc_test >> 4) & 0x03,
        dsp_reg=snd["dsp_addr"],
        timers=spc_timers,
        op_code=snd.get("opcode_number", 0) & 0xFF,
        op_step=0,
        op_sub_step=0,
        operand_a=0,
        operand_b=0,
        tmp1=0,
        tmp2=0,
        tmp3=0,
        enabled=True,
        new_cpu_regs=list(cpu_regs[:4]) if len(cpu_regs) >= 4 else [0, 0, 0, 0],
        pending_cpu_reg_update=False,
        ram=_pad(
            spc_ram if isinstance(spc_ram, (bytes, bytearray)) else bytes(spc_ram),
            0x10000,
        ),
        dsp=dsp,
    )

    return state
