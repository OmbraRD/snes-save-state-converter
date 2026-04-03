"""Convert a parsed ZSNES state into a canonical SnesState.

PPU register offsets reference the 3019-byte ``sndrot`` block defined in
``cpu/regs.inc``.  All multi-byte values in the ZST are little-endian.
"""

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
from snes_save_state_converter.zsnes.parser import ZsnesState


def _ppu8(ppu: bytes, off: int) -> int:
    return ppu[off] if off < len(ppu) else 0


def _ppu16(ppu: bytes, off: int) -> int:
    return int.from_bytes(ppu[off : off + 2], "little") if off + 1 < len(ppu) else 0


def _ppu16s(ppu: bytes, off: int) -> int:
    return int.from_bytes(ppu[off : off + 2], "little", signed=True) if off + 1 < len(ppu) else 0


def _ppu32(ppu: bytes, off: int) -> int:
    return int.from_bytes(ppu[off : off + 4], "little") if off + 3 < len(ppu) else 0


def convert(zst: ZsnesState) -> SnesState:
    ppu = zst.ppu_raw

    # --- Timing: use ZSNES curypos for scanline --------------------------
    overscan = _ppu16(ppu, 0x6F) > 224
    is_pal = _ppu16(ppu, 0x6F) > 262
    scanline = zst.curypos

    # =================================================================
    # CPU
    # =================================================================
    cpu = CpuState(
        a=zst.a,
        x=zst.x,
        y=zst.y,
        sp=zst.s,
        d=zst.d,
        db=zst.db,
        pb=zst.pb,
        pc=zst.pc,
        p=zst.p,
        emulation=bool(zst.e),
        irq_source=0,
        nmi_pending=bool(zst.nmi),
        waiting_for_interrupt=False,
    )

    # =================================================================
    # PPU
    # =================================================================
    scrnon = _ppu16(ppu, 0x6C)

    # VRAM — ZSNES stores byte addresses, convert to word addresses (>> 1)
    vram_addr_bytes = _ppu32(ppu, 0x65) & 0xFFFF
    addrincr = _ppu16(ppu, 0x61)
    incr_map = {2: 1, 64: 32, 128: 128, 256: 128}
    # vraminctype at offset 0x9D0 stores the FULL $2115 register value
    vraminctype = _ppu8(ppu, 0x09D0)

    # OAM — ZSNES stores byte addresses, convert to word addresses
    objptr_bytes = _ppu32(ppu, 0x09)  # OBJ name base (byte addr)
    objptrn_bytes = _ppu32(ppu, 0x0D)  # OBJ name select (byte addr)
    name_offset = (objptrn_bytes - objptr_bytes) >> 1  # word offset
    if name_offset <= 0:
        name_offset = 0x1000  # minimum per SNES hardware
    # OAM size mode — reverse-lookup from ZSNES decoded sizes
    sz1 = _ppu8(ppu, 0x11)
    sz2 = _ppu8(ppu, 0x12)
    size_mode_table = {
        (1, 4): 0, (1, 16): 1, (1, 64): 2,
        (4, 16): 3, (4, 64): 4, (16, 64): 5,
    }
    oam_mode = size_mode_table.get((sz1, sz2), 0)

    resolutn = _ppu16(ppu, 0x6F)

    # Color math
    scaddset = _ppu8(ppu, 0x01C6)  # $2130
    scaddtype = _ppu8(ppu, 0x01C7)  # $2131
    r = _ppu8(ppu, 0x01C2) & 0x1F
    g = _ppu8(ppu, 0x01C3) & 0x1F
    b = _ppu8(ppu, 0x01C4) & 0x1F

    # Mask logic
    winlogica = _ppu8(ppu, 0x89)  # $212A
    winlogicb = _ppu8(ppu, 0x8A)  # $212B
    mask_logic = [0] * 6
    for i in range(4):
        mask_logic[i] = (winlogica >> (i * 2)) & 3
    mask_logic[4] = winlogicb & 3
    mask_logic[5] = (winlogicb >> 2) & 3

    winenabm = _ppu8(ppu, 0x8B)  # $212E
    winenabs = _ppu8(ppu, 0x8C)  # $212F
    window_mask_main = [bool(winenabm & (1 << i)) for i in range(5)]
    window_mask_sub = [bool(winenabs & (1 << i)) for i in range(5)]

    # Mode 7
    m7set = _ppu8(ppu, 0x8D)  # $211A
    mode7 = Mode7State(
        matrix=[
            _ppu16s(ppu, 0x8E),
            _ppu16s(ppu, 0x90),
            _ppu16s(ppu, 0x92),
            _ppu16s(ppu, 0x94),
        ],
        hscroll=_ppu16s(ppu, 0x4F),  # use BG1 hscroll for Mode 7
        vscroll=_ppu16s(ppu, 0x59),  # BG1 vscroll
        center_x=_ppu16s(ppu, 0x96),
        center_y=_ppu16s(ppu, 0x98),
        value_latch=0,
        large_map=bool(m7set & 0x80),
        fill_with_tile0=(m7set & 0xC0) == 0,
        h_mirror=bool(m7set & 0x01),
        v_mirror=bool(m7set & 0x02),
    )

    # Layers — ZSNES stores decoded pointers
    bg_ptr_offsets = [0x23, 0x25, 0x27, 0x29]  # tilemap pointers
    bg_chr_offsets = [0x47, 0x49, 0x4B, 0x4D]  # character pointers
    bg_hscroll = [0x4F, 0x51, 0x53, 0x55]
    bg_vscroll = [0x59, 0x5B, 0x5D, 0x5F]
    bg_scsize = [0x43, 0x44, 0x45, 0x46]
    bgtilesz = _ppu8(ppu, 0x20)
    layers = []
    for i in range(4):
        sc = _ppu8(ppu, bg_scsize[i])
        layers.append(BgLayerState(
            # ZSNES stores byte addresses, convert to word addresses (>> 1)
            tilemap_addr=(_ppu16(ppu, bg_ptr_offsets[i]) >> 1) & 0x7FFF,
            chr_addr=(_ppu16(ppu, bg_chr_offsets[i]) >> 1) & 0x7FFF,
            hscroll=_ppu16(ppu, bg_hscroll[i]),
            vscroll=_ppu16(ppu, bg_vscroll[i]),
            double_width=bool(sc & 1),
            double_height=bool(sc & 2),
            large_tiles=bool(bgtilesz & (1 << i)),
        ))

    # Windows
    win_regs = [
        _ppu8(ppu, 0x83),  # $2123
        _ppu8(ppu, 0x84),
        _ppu8(ppu, 0x85),  # $2124
        _ppu8(ppu, 0x86),
        _ppu8(ppu, 0x87),  # $2125
        _ppu8(ppu, 0x88),
    ]
    reg_2123 = (win_regs[0] & 0x0F) | ((win_regs[1] & 0x0F) << 4)
    reg_2124 = (win_regs[2] & 0x0F) | ((win_regs[3] & 0x0F) << 4)
    reg_2125 = (win_regs[4] & 0x0F) | ((win_regs[5] & 0x0F) << 4)
    regs_w = [reg_2123, reg_2124, reg_2125]
    windows = []
    for w in range(2):
        active = [False] * 6
        inverted = [False] * 6
        for layer in range(6):
            bits = (regs_w[layer // 2] >> ((layer % 2) * 4 + w * 2)) & 3
            active[layer] = bool(bits & 2)
        for layer in range(6):
            bits = (regs_w[layer // 2] >> ((layer % 2) * 4 + w * 2)) & 3
            inverted[layer] = bool(bits & 1)
        if w == 0:
            left = _ppu8(ppu, 0x7F)
            right = _ppu8(ppu, 0x80)
        else:
            left = _ppu8(ppu, 0x81)
            right = _ppu8(ppu, 0x82)
        windows.append(WindowState(
            left=left,
            right=right,
            active=active,
            inverted=inverted,
        ))

    # VRAM as raw bytes (64KB)
    vram_data = zst.vram
    if len(vram_data) < 0x10000:
        vram_data = vram_data + b"\x00" * (0x10000 - len(vram_data))
    vram_data = vram_data[:0x10000]

    # OAM (544 bytes from offset 0x01D0 in PPU block)
    oam_data = ppu[0x01D0 : 0x01D0 + 544]
    if len(oam_data) < 544:
        oam_data = oam_data + b"\x00" * (544 - len(oam_data))

    # CGRAM (256 uint16 from offset 0x05D0)
    cgram_data = ppu[0x05D0 : 0x05D0 + 512]
    cgram = []
    for i in range(0, min(len(cgram_data), 512), 2):
        cgram.append(int.from_bytes(cgram_data[i : i + 2], "little"))
    while len(cgram) < 256:
        cgram.append(0)

    ppu_state = PpuState(
        forced_blank=bool(_ppu8(ppu, 0x08)),
        brightness=_ppu8(ppu, 0x06),
        bg_mode=_ppu8(ppu, 0x1E),
        mode1_bg3_priority=bool(_ppu8(ppu, 0x1F)),
        main_screen_layers=scrnon & 0xFF,
        sub_screen_layers=(scrnon >> 8) & 0xFF,

        # VRAM
        vram_addr=(vram_addr_bytes >> 1) & 0x7FFF,
        vram_increment=incr_map.get(addrincr, 1),
        vram_remap=(vraminctype >> 2) & 0x03,
        vram_incr_on_high=bool(vraminctype & 0x80),
        vram_read_buffer=_ppu8(ppu, 0x64) | (_ppu8(ppu, 0x09E7) << 8),

        # OAM
        oam_mode=oam_mode,
        oam_base_addr=(objptr_bytes >> 1) & 0x7FFF,
        oam_addr_offset=name_offset & 0x7FFF,
        oam_ram_addr=_ppu16(ppu, 0x19),
        internal_oam_addr=_ppu16(ppu, 0x1B),
        oam_priority_rotation=bool(_ppu8(ppu, 0x1D)),
        oam_write_buffer=0,

        # CGRAM
        cgram_addr=_ppu16(ppu, 0x69) & 0xFF,
        internal_cgram_addr=_ppu16(ppu, 0x69) & 0xFF,
        cgram_write_buffer=0,
        cgram_latch=False,

        # Mosaic
        mosaic_size=(_ppu8(ppu, 0x22) & 0x0F) + 1,
        mosaic_enabled=_ppu8(ppu, 0x21),

        # Display
        hi_res=False,
        screen_interlace=bool(_ppu8(ppu, 0x09DE)),
        obj_interlace=False,
        overscan=resolutn > 224,
        direct_color=bool(_ppu8(ppu, 0x01C6) & 0x01),
        ext_bg=False,

        # Color math
        color_clip_mode=(scaddset >> 6) & 3,
        color_prevent_mode=(scaddset >> 4) & 3,
        color_add_subscreen=bool(scaddset & 0x02),
        color_math_enabled=scaddtype & 0x3F,
        color_subtract=bool(scaddtype & 0x80),
        color_halve=bool(scaddtype & 0x40),
        fixed_color=r | (g << 5) | (b << 10),

        # Open bus
        ppu1_open_bus=0,
        ppu2_open_bus=0,

        # Latches
        hv_scroll_latch=0,
        h_scroll_latch=0,

        # Window mask logic
        mask_logic=mask_logic,
        window_mask_main=window_mask_main,
        window_mask_sub=window_mask_sub,

        # Sub-state
        layers=layers,
        windows=windows,
        mode7=mode7,

        # Raw data
        vram=vram_data,
        oam=oam_data,
        cgram=cgram,
    )

    # =================================================================
    # DMA — parse from PPU block dmadata at offset 0xA5 (129 bytes)
    # =================================================================
    nexthdma = _ppu8(ppu, 0x0127)  # which channels run next scanline
    curhdma = _ppu8(ppu, 0x0128)   # which channels are enabled ($420C)
    hdmatype = _ppu8(ppu, 0x01C1)  # which channels need first-time init / do transfer

    dma_channels = []
    dma_base = 0xA5
    for i in range(8):
        ch_off = dma_base + i * 16  # 16 bytes per channel in ZSNES $43x0-$43xF
        if ch_off + 16 <= len(ppu):
            reg0 = _ppu8(ppu, ch_off)  # $43x0
            dma_channels.append(DmaChannelState(
                transfer_mode=reg0 & 0x07,
                dest_addr=_ppu8(ppu, ch_off + 1),
                src_addr=_ppu16(ppu, ch_off + 2),
                src_bank=_ppu8(ppu, ch_off + 4),
                transfer_size=_ppu16(ppu, ch_off + 5),
                hdma_bank=_ppu8(ppu, ch_off + 7),
                hdma_table_addr=_ppu16(ppu, ch_off + 8),
                hdma_line_counter=_ppu8(ppu, ch_off + 10),
                invert_direction=bool(reg0 & 0x80),
                hdma_indirect=bool(reg0 & 0x40),
                decrement=bool(reg0 & 0x10),
                fixed_transfer=bool(reg0 & 0x08),
                unused_flag=bool(reg0 & 0x20),
                unused_register=_ppu8(ppu, ch_off + 11) if ch_off + 11 < len(ppu) else 0,
                # doTransfer: channel will transfer data on next scanline
                do_transfer=bool(hdmatype & (1 << i)),
                # hdmaFinished: channel enabled in $420C but no longer in nexthdma
                hdma_finished=bool((curhdma & (1 << i)) and not (nexthdma & (1 << i))),
                dma_active=False,
            ))
        else:
            # Default empty channel
            dma_channels.append(DmaChannelState())

    dma = DmaState(
        hdma_channels=curhdma,
        channels=dma_channels,
    )

    # =================================================================
    # Internal Registers
    # =================================================================
    int_en = _ppu8(ppu, 0x02)  # INTEnab = $4200
    vbl_start = 240 if overscan else 225
    in_vblank = scanline >= vbl_start

    internal_regs = InternalRegState(
        enable_fast_rom=True,  # default; ZSNES doesn't store this directly
        nmi_flag=in_vblank,
        enable_nmi=bool(int_en & 0x80),
        enable_h_irq=bool(int_en & 0x10),
        enable_v_irq=bool(int_en & 0x20),
        h_timer=_ppu16(ppu, 0x09DF),
        v_timer=_ppu16(ppu, 0x04),
        io_port_output=_ppu8(ppu, 0x09EB),
        controller_data=[0, 0, 0, 0],
        irq_level=False,
        need_irq=0,
        enable_auto_joypad=bool(int_en & 0x01),
        irq_flag=False,

        # ALU
        mult_operand1=_ppu8(ppu, 0x71),
        mult_operand2=0,
        mult_result=_ppu16(ppu, 0x76),
        dividend=_ppu16(ppu, 0x72),
        divisor=0,
        div_result=_ppu16(ppu, 0x74),

        # Latched counters
        h_counter=_ppu16(ppu, 0x78),
        v_counter=_ppu16(ppu, 0x7A),
    )

    # =================================================================
    # Timing
    # =================================================================
    timing = TimingState(
        scanline=scanline,
        is_pal=is_pal,
        overscan=overscan,
    )

    # =================================================================
    # Memory
    # =================================================================
    wram = zst.wram
    if len(wram) < 0x20000:
        wram = wram + b"\x00" * (0x20000 - len(wram))
    wram = wram[:0x20000]

    wram_port_addr = _ppu32(ppu, 0xA1) & 0x1FFFF

    # =================================================================
    # SPC
    # =================================================================
    if zst.spcon:
        spc = _build_spc(zst)
    else:
        spc = _build_spc_defaults()

    # =================================================================
    # Assemble final state
    # =================================================================
    return SnesState(
        cpu=cpu,
        ppu=ppu_state,
        spc=spc,
        dma=dma,
        internal_regs=internal_regs,
        timing=timing,
        wram=wram,
        sram=zst.sram if zst.sram else b"",
        wram_port_addr=wram_port_addr,
    )


def _build_spc(zst: ZsnesState) -> SpcState:
    spc_ram = zst.spc_ram

    # Ports: ZSNES reg1read-reg4read are the CPU->SPC port values
    cpu_regs = list(zst.spc_ports[:4])
    # Output regs from SPC RAM $F4-$F7
    output_regs = [
        spc_ram[0xF4 + i] if len(spc_ram) > 0xF7 else 0
        for i in range(4)
    ]
    ram_regs = [
        spc_ram[0xF8] if len(spc_ram) > 0xF8 else 0,
        spc_ram[0xF9] if len(spc_ram) > 0xF9 else 0,
    ]
    dsp_reg = spc_ram[0xF2] if len(spc_ram) > 0xF2 else 0

    # Timers
    timers = []
    for t in range(3):
        enabled = bool(zst.spc_timer_enable & (1 << t))
        timers.append(SpcTimerState(
            enabled=enabled,
            target=zst.spc_timer_target[t],
            stage0=0,
            counter=zst.spc_timer_ticks[t],
            output=0,
        ))

    # SPC RAM — need to extend to 64KB (ZSNES stores 65472 bytes)
    ram_full = bytearray(0x10000)
    ram_full[: len(spc_ram)] = spc_ram[: min(len(spc_ram), 0x10000)]
    # Copy extra RAM (TCALL) to $FFC0-$FFFF
    if zst.spc_extra_ram:
        extra = zst.spc_extra_ram[:64]
        ram_full[0xFFC0 : 0xFFC0 + len(extra)] = extra

    # DSP — registers from DSPMem (256 bytes)
    dsp_regs_raw = zst.dsp_regs[:128] if len(zst.dsp_regs) >= 128 else zst.dsp_regs + b"\x00" * (128 - len(zst.dsp_regs))
    ext_regs = dsp_regs_raw  # same as regs for ZSNES

    # DSP voices — initialize from DSP registers (ZSNES DSP internals don't
    # map to Mesen2's cycle-accurate model)
    voices = []
    for i in range(8):
        voices.append(DspVoiceState(
            env_volume=0,
            prev_env=0,
            interp_pos=0,
            env_mode=0,  # Release
            brr_addr=0,
            brr_offset=1,
            voice_bit=1 << i,
            key_on_delay=0,
            env_out=0,
            buffer_pos=0,
            sample_buffer=[0] * 12,
        ))

    # DSP global state
    esa = dsp_regs_raw[0x6D] if len(dsp_regs_raw) > 0x6D else 0
    edl = (dsp_regs_raw[0x7D] & 0x0F) if len(dsp_regs_raw) > 0x7D else 0
    echo_len = edl * 0x800 if edl else 4
    flg = dsp_regs_raw[0x6C] if len(dsp_regs_raw) > 0x6C else 0

    dsp = DspState(
        regs=dsp_regs_raw,
        external_regs=ext_regs,
        voices=voices,
        noise_lfsr=0x4000,
        counter=0,
        step=0,
        out_reg_buffer=0,
        env_reg_buffer=0,
        voice_end_buffer=dsp_regs_raw[0x7C] if len(dsp_regs_raw) > 0x7C else 0,
        voice_output=0,
        out_samples=[0, 0],
        pitch=0,
        sample_addr=0,
        brr_next_addr=0,
        dir_sample_table_addr=dsp_regs_raw[0x5D] if len(dsp_regs_raw) > 0x5D else 0,
        noise_on=0,
        pitch_mod_on=0,
        key_on=0,
        new_key_on=0,
        key_off=0,
        every_other_sample=0,
        source_number=0,
        brr_header=0,
        brr_data=0,
        looped=0,
        adsr1=0,
        echo_in=[0, 0],
        echo_out=[0, 0],
        echo_history=[0] * 16,
        echo_pointer=esa << 8,
        echo_length=echo_len,
        echo_offset=0,
        echo_history_pos=0,
        echo_ring_buffer_addr=esa,
        echo_on=0,
        echo_enabled=not bool(flg & 0x20),
    )

    return SpcState(
        a=zst.spc_a,
        x=zst.spc_x,
        y=zst.spc_y,
        sp=zst.spc_sp,
        pc=zst.spc_pc,
        psw=zst.spc_p,
        cpu_regs=cpu_regs,
        output_regs=output_regs,
        ram_regs=ram_regs,
        write_enabled=True,
        rom_enabled=False,
        timers_enabled=True,
        timers_disabled=False,
        internal_speed=0,
        external_speed=0,
        dsp_reg=dsp_reg,
        timers=timers,
        op_code=0,
        op_step=0,  # ReadOpCode
        op_sub_step=0,
        operand_a=0,
        operand_b=0,
        tmp1=0,
        tmp2=0,
        tmp3=0,
        enabled=True,
        new_cpu_regs=list(zst.spc_ports[:4]),
        pending_cpu_reg_update=False,
        ram=bytes(ram_full),
        dsp=dsp,
    )


def _build_spc_defaults() -> SpcState:
    """Build minimal SPC state when SPC was disabled in the ZST."""
    # Timers
    timers = [
        SpcTimerState(enabled=False, target=0, stage0=0, counter=0, output=0)
        for _ in range(3)
    ]

    # DSP voices
    voices = [
        DspVoiceState(
            env_volume=0,
            prev_env=0,
            interp_pos=0,
            env_mode=0,
            brr_addr=0,
            brr_offset=1,
            voice_bit=1 << i,
            key_on_delay=0,
            env_out=0,
            buffer_pos=0,
            sample_buffer=[0] * 12,
        )
        for i in range(8)
    ]

    dsp = DspState(
        regs=bytes(128),
        external_regs=bytes(128),
        voices=voices,
        noise_lfsr=0x4000,
        counter=0,
        step=0,
        out_reg_buffer=0,
        env_reg_buffer=0,
        voice_end_buffer=0,
        voice_output=0,
        out_samples=[0, 0],
        pitch=0,
        sample_addr=0,
        brr_next_addr=0,
        dir_sample_table_addr=0,
        noise_on=0,
        pitch_mod_on=0,
        key_on=0,
        new_key_on=0,
        key_off=0,
        every_other_sample=0,
        source_number=0,
        brr_header=0,
        brr_data=0,
        looped=0,
        adsr1=0,
        echo_in=[0, 0],
        echo_out=[0, 0],
        echo_history=[0] * 16,
        echo_pointer=0,
        echo_length=4,
        echo_offset=0,
        echo_history_pos=0,
        echo_ring_buffer_addr=0,
        echo_on=0,
        echo_enabled=False,
    )

    return SpcState(
        a=0,
        x=0,
        y=0,
        sp=0xFF,
        pc=0xFFC0,
        psw=0,
        cpu_regs=[0, 0, 0, 0],
        output_regs=[0, 0, 0, 0],
        ram_regs=[0, 0],
        write_enabled=True,
        rom_enabled=True,
        timers_enabled=True,
        timers_disabled=False,
        internal_speed=0,
        external_speed=0,
        dsp_reg=0,
        timers=timers,
        op_code=0,
        op_step=0,
        op_sub_step=0,
        operand_a=0,
        operand_b=0,
        tmp1=0,
        tmp2=0,
        tmp3=0,
        enabled=True,
        new_cpu_regs=[0, 0, 0, 0],
        pending_cpu_reg_update=False,
        ram=bytes(0x10000),
        dsp=dsp,
    )
