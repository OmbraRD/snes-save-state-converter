"""Per-block decoders for snes9x save state data.

Every multi-byte integer in snes9x blocks is big-endian.
The SND (APU) block is an exception — its internal fields are little-endian.
"""


def _be(data: bytes, offset: int, size: int) -> int:
    return int.from_bytes(data[offset : offset + size], "big")


def _be_s(data: bytes, offset: int, size: int) -> int:
    return int.from_bytes(data[offset : offset + size], "big", signed=True)


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------


def decode_cpu_block(data: bytes, version: int) -> dict:
    o = 0
    cpu = {}
    cpu["Cycles"] = _be_s(data, o, 4); o += 4
    cpu["PrevCycles"] = _be_s(data, o, 4); o += 4
    cpu["V_Counter"] = _be_s(data, o, 4); o += 4
    cpu["Flags"] = _be(data, o, 4); o += 4
    if version < 7:
        cpu["CPU_IRQActive"] = data[o]; o += 1  # OBSOLETE v6, deleted v7
    cpu["IRQPending"] = _be_s(data, o, 4); o += 4
    cpu["MemSpeed"] = _be_s(data, o, 4); o += 4
    cpu["MemSpeedx2"] = _be_s(data, o, 4); o += 4
    cpu["FastROMSpeed"] = _be_s(data, o, 4); o += 4
    cpu["InDMA"] = data[o]; o += 1
    cpu["InHDMA"] = data[o]; o += 1
    cpu["InDMAorHDMA"] = data[o]; o += 1
    cpu["InWRAMDMAorHDMA"] = data[o]; o += 1
    cpu["HDMARanInDMA"] = data[o]; o += 1
    cpu["WhichEvent"] = data[o]; o += 1
    cpu["NextEvent"] = _be_s(data, o, 4); o += 4
    cpu["WaitingForInterrupt"] = data[o]; o += 1
    if version < 7:
        # DELETED entries: WaitAddress(4), WaitCounter(4), PBPCAtOpcodeStart(4)
        o += 4 + 4 + 4
    if version >= 7:
        cpu["NMIPending"] = data[o]; o += 1
        cpu["IRQLine"] = data[o]; o += 1
        cpu["IRQTransition"] = data[o]; o += 1
        cpu["IRQLastState"] = data[o]; o += 1
        cpu["IRQExternal"] = data[o]; o += 1
    return cpu


# ---------------------------------------------------------------------------
# Registers
# ---------------------------------------------------------------------------


def decode_reg_block(data: bytes) -> dict:
    o = 0
    reg = {}
    reg["PB"] = data[o]; o += 1
    reg["DB"] = data[o]; o += 1
    reg["P"] = _be(data, o, 2); o += 2
    reg["A"] = _be(data, o, 2); o += 2
    reg["D"] = _be(data, o, 2); o += 2
    reg["S"] = _be(data, o, 2); o += 2
    reg["X"] = _be(data, o, 2); o += 2
    reg["Y"] = _be(data, o, 2); o += 2
    reg["PC"] = _be(data, o, 2); o += 2
    return reg


# ---------------------------------------------------------------------------
# PPU
# ---------------------------------------------------------------------------


def decode_ppu_block(data: bytes, version: int) -> dict:
    o = 0
    ppu = {}

    ppu["VMA_High"] = data[o]; o += 1
    ppu["VMA_Increment"] = data[o]; o += 1
    ppu["VMA_Address"] = _be(data, o, 2); o += 2
    ppu["VMA_Mask1"] = _be(data, o, 2); o += 2
    ppu["VMA_FullGraphicCount"] = _be(data, o, 2); o += 2
    ppu["VMA_Shift"] = _be(data, o, 2); o += 2  # uint16 in SPPU
    ppu["WRAM"] = _be(data, o, 4); o += 4

    for i in range(4):
        p = f"BG{i}_"
        ppu[p + "SCBase"] = _be(data, o, 2); o += 2
        ppu[p + "HOffset"] = _be(data, o, 2); o += 2
        ppu[p + "VOffset"] = _be(data, o, 2); o += 2
        ppu[p + "BGSize"] = data[o]; o += 1
        ppu[p + "NameBase"] = _be(data, o, 2); o += 2
        ppu[p + "SCSize"] = _be(data, o, 2); o += 2

    ppu["BGMode"] = data[o]; o += 1
    ppu["BG3Priority"] = data[o]; o += 1
    ppu["CGFLIP"] = data[o]; o += 1
    ppu["CGFLIPRead"] = data[o]; o += 1
    ppu["CGADD"] = data[o]; o += 1

    if version >= 11:
        ppu["CGSavedByte"] = data[o]; o += 1

    cgdata = []
    for _ in range(256):
        cgdata.append(_be(data, o, 2)); o += 2
    ppu["CGDATA"] = cgdata

    objs = []
    for _ in range(128):
        obj = {}
        obj["HPos"] = _be_s(data, o, 2); o += 2
        obj["VPos"] = _be(data, o, 2); o += 2
        obj["HFlip"] = data[o]; o += 1
        obj["VFlip"] = data[o]; o += 1
        obj["Name"] = _be(data, o, 2); o += 2
        obj["Priority"] = data[o]; o += 1
        obj["Palette"] = data[o]; o += 1
        obj["Size"] = data[o]; o += 1
        objs.append(obj)
    ppu["OBJ"] = objs

    ppu["OBJThroughMain"] = data[o]; o += 1
    ppu["OBJThroughSub"] = data[o]; o += 1
    ppu["OBJAddition"] = data[o]; o += 1
    ppu["OBJNameBase"] = _be(data, o, 2); o += 2
    ppu["OBJNameSelect"] = _be(data, o, 2); o += 2
    ppu["OBJSizeSelect"] = data[o]; o += 1
    ppu["OAMAddr"] = _be(data, o, 2); o += 2
    ppu["SavedOAMAddr"] = _be(data, o, 2); o += 2
    ppu["OAMPriorityRotation"] = data[o]; o += 1
    ppu["OAMFlip"] = data[o]; o += 1
    ppu["OAMReadFlip"] = data[o]; o += 1
    ppu["OAMTileAddress"] = _be(data, o, 2); o += 2
    ppu["OAMWriteRegister"] = _be(data, o, 2); o += 2
    ppu["OAMData"] = data[o : o + 544]; o += 544

    ppu["FirstSprite"] = data[o]; o += 1
    ppu["LastSprite"] = data[o]; o += 1
    ppu["HTimerEnabled"] = data[o]; o += 1
    ppu["VTimerEnabled"] = data[o]; o += 1
    ppu["HTimerPosition"] = _be_s(data, o, 2); o += 2
    ppu["VTimerPosition"] = _be_s(data, o, 2); o += 2
    ppu["IRQHBeamPos"] = _be(data, o, 2); o += 2
    ppu["IRQVBeamPos"] = _be(data, o, 2); o += 2
    ppu["HBeamFlip"] = data[o]; o += 1
    ppu["VBeamFlip"] = data[o]; o += 1
    ppu["HBeamPosLatched"] = _be(data, o, 2); o += 2
    ppu["VBeamPosLatched"] = _be(data, o, 2); o += 2
    ppu["GunHLatch"] = _be(data, o, 2); o += 2
    ppu["GunVLatch"] = _be(data, o, 2); o += 2
    ppu["HVBeamCounterLatched"] = data[o]; o += 1

    # Mode 7
    ppu["Mode7HFlip"] = data[o]; o += 1
    ppu["Mode7VFlip"] = data[o]; o += 1
    ppu["Mode7Repeat"] = data[o]; o += 1
    ppu["MatrixA"] = _be_s(data, o, 2); o += 2
    ppu["MatrixB"] = _be_s(data, o, 2); o += 2
    ppu["MatrixC"] = _be_s(data, o, 2); o += 2
    ppu["MatrixD"] = _be_s(data, o, 2); o += 2
    ppu["CentreX"] = _be_s(data, o, 2); o += 2
    ppu["CentreY"] = _be_s(data, o, 2); o += 2
    ppu["M7HOFS"] = _be_s(data, o, 2); o += 2
    ppu["M7VOFS"] = _be_s(data, o, 2); o += 2

    ppu["Mosaic"] = data[o]; o += 1
    ppu["MosaicStart"] = data[o]; o += 1
    ppu["BGMosaic"] = [data[o + i] for i in range(4)]; o += 4

    ppu["Window1Left"] = data[o]; o += 1
    ppu["Window1Right"] = data[o]; o += 1
    ppu["Window2Left"] = data[o]; o += 1
    ppu["Window2Right"] = data[o]; o += 1
    ppu["RecomputeClipWindows"] = data[o]; o += 1

    for i in range(6):
        p = f"Clip{i}_"
        ppu[p + "Count"] = data[o]; o += 1
        ppu[p + "OverlapLogic"] = data[o]; o += 1
        ppu[p + "Window1Enable"] = data[o]; o += 1
        ppu[p + "Window2Enable"] = data[o]; o += 1
        ppu[p + "Window1Inside"] = data[o]; o += 1
        ppu[p + "Window2Inside"] = data[o]; o += 1

    ppu["ForcedBlanking"] = data[o]; o += 1
    ppu["FixedColourRed"] = data[o]; o += 1
    ppu["FixedColourGreen"] = data[o]; o += 1
    ppu["FixedColourBlue"] = data[o]; o += 1
    ppu["Brightness"] = data[o]; o += 1
    ppu["ScreenHeight"] = _be(data, o, 2); o += 2
    ppu["Need16x8Multiply"] = data[o]; o += 1
    ppu["BGnxOFSbyte"] = data[o]; o += 1
    ppu["M7byte"] = data[o]; o += 1
    ppu["HDMA"] = data[o]; o += 1
    ppu["HDMAEnded"] = data[o]; o += 1
    ppu["OpenBus1"] = data[o]; o += 1
    ppu["OpenBus2"] = data[o]; o += 1

    if version >= 11:
        ppu["VRAMReadBuffer"] = _be(data, o, 2); o += 2

    return ppu


# ---------------------------------------------------------------------------
# DMA
# ---------------------------------------------------------------------------


def decode_dma_block(data: bytes) -> list[dict]:
    channels = []
    o = 0
    for _ in range(8):
        ch = {}
        ch["ReverseTransfer"] = data[o]; o += 1
        ch["HDMAIndirectAddressing"] = data[o]; o += 1
        ch["UnusedBit43x0"] = data[o]; o += 1
        ch["AAddressFixed"] = data[o]; o += 1
        ch["AAddressDecrement"] = data[o]; o += 1
        ch["TransferMode"] = data[o]; o += 1
        ch["BAddress"] = data[o]; o += 1
        ch["AAddress"] = _be(data, o, 2); o += 2
        ch["ABank"] = data[o]; o += 1
        ch["DMACount_Or_HDMAIndirectAddress"] = _be(data, o, 2); o += 2
        ch["IndirectBank"] = data[o]; o += 1
        ch["Address"] = _be(data, o, 2); o += 2
        ch["Repeat"] = data[o]; o += 1
        ch["LineCount"] = data[o]; o += 1
        ch["UnknownByte"] = data[o]; o += 1
        ch["DoTransfer"] = data[o]; o += 1
        channels.append(ch)
    return channels


# ---------------------------------------------------------------------------
# SND  (SPC700 + DSP — internal fields are little-endian)
# ---------------------------------------------------------------------------


def decode_snd_block(data: bytes) -> dict:
    snd: dict = {}

    snd["spc_ram"] = data[0:0x10000]
    o = 0x10000

    def r32() -> int:
        nonlocal o
        val = int.from_bytes(data[o : o + 4], "little")
        o += 4
        return val

    snd["clock"] = r32()
    snd["opcode_number"] = r32()
    snd["opcode_cycle"] = r32()
    snd["pc"] = r32() & 0xFFFF
    snd["sp"] = r32() & 0xFF
    snd["a"] = r32() & 0xFF
    snd["x"] = r32() & 0xFF
    snd["y"] = r32() & 0xFF

    psw_n = r32(); psw_v = r32(); psw_p = r32(); psw_b = r32()
    psw_h = r32(); psw_i = r32(); psw_z = r32(); psw_c = r32()
    psw = 0
    if psw_n: psw |= 0x80
    if psw_v: psw |= 0x40
    if psw_p: psw |= 0x20
    if psw_b: psw |= 0x10
    if psw_h: psw |= 0x08
    if psw_i: psw |= 0x04
    if psw_z: psw |= 0x02
    if psw_c: psw |= 0x01
    snd["psw"] = psw

    snd["iplrom_enable"] = r32()
    snd["dsp_addr"] = r32() & 0xFF
    snd["ram00f8"] = r32()
    snd["ram00f9"] = r32()

    for i in range(3):
        p = f"timer{i}_"
        snd[p + "enable"] = r32()
        snd[p + "target"] = r32() & 0xFF
        snd[p + "stage1_ticks"] = r32()
        snd[p + "stage2_ticks"] = r32()
        snd[p + "stage3_ticks"] = r32()

    snd["smp_rd"] = r32()
    snd["smp_wr"] = r32()
    snd["smp_dp"] = r32()
    snd["smp_sp"] = r32()
    snd["smp_ya"] = r32()
    snd["smp_bit"] = r32()

    # DSP registers
    snd["dsp_regs"] = data[o : o + 128]; o += 128

    # Voices
    voices = []
    for _ in range(8):
        voice: dict = {}
        brr_buf = []
        for _ in range(12):
            brr_buf.append(int.from_bytes(data[o : o + 2], "little", signed=True)); o += 2
        voice["brr_buffer"] = brr_buf
        voice["interp_pos"] = int.from_bytes(data[o : o + 2], "little"); o += 2
        voice["brr_addr"] = int.from_bytes(data[o : o + 2], "little"); o += 2
        voice["env"] = int.from_bytes(data[o : o + 2], "little"); o += 2
        voice["hidden_env"] = int.from_bytes(data[o : o + 2], "little", signed=True); o += 2
        voice["buf_pos"] = data[o]; o += 1
        voice["brr_offset"] = data[o]; o += 1
        voice["kon_delay"] = data[o]; o += 1
        voice["env_mode"] = data[o]; o += 1
        voice["t_envx_out"] = data[o]; o += 1
        o += 1  # padding
        voices.append(voice)
    snd["voices"] = voices

    # Echo history (8 * 2 = 16 int16)
    echo_hist = []
    for _ in range(16):
        echo_hist.append(int.from_bytes(data[o : o + 2], "little", signed=True)); o += 2
    snd["echo_history"] = echo_hist

    snd["dsp_every_other_sample"] = data[o]; o += 1
    snd["dsp_kon"] = data[o]; o += 1
    snd["dsp_noise"] = int.from_bytes(data[o : o + 2], "little"); o += 2
    snd["dsp_counter"] = int.from_bytes(data[o : o + 2], "little"); o += 2
    snd["dsp_echo_offset"] = int.from_bytes(data[o : o + 2], "little"); o += 2
    snd["dsp_echo_length"] = int.from_bytes(data[o : o + 2], "little"); o += 2
    snd["dsp_phase"] = data[o]; o += 1
    snd["dsp_new_kon"] = data[o]; o += 1
    snd["dsp_endx_buf"] = data[o]; o += 1
    snd["dsp_envx_buf"] = data[o]; o += 1
    snd["dsp_outx_buf"] = data[o]; o += 1
    snd["dsp_t_pmon"] = data[o]; o += 1
    snd["dsp_t_non"] = data[o]; o += 1
    snd["dsp_t_eon"] = data[o]; o += 1
    snd["dsp_t_dir"] = data[o]; o += 1
    snd["dsp_t_koff"] = data[o]; o += 1
    snd["dsp_t_brr_next_addr"] = int.from_bytes(data[o : o + 2], "little"); o += 2
    snd["dsp_t_adsr0"] = data[o]; o += 1
    snd["dsp_t_brr_header"] = data[o]; o += 1
    snd["dsp_t_brr_byte"] = data[o]; o += 1
    snd["dsp_t_srcn"] = data[o]; o += 1
    snd["dsp_t_esa"] = data[o]; o += 1
    snd["dsp_t_echo_enabled"] = data[o]; o += 1
    snd["dsp_t_main_out_l"] = int.from_bytes(data[o : o + 2], "little", signed=True); o += 2
    snd["dsp_t_main_out_r"] = int.from_bytes(data[o : o + 2], "little", signed=True); o += 2
    snd["dsp_t_echo_out_l"] = int.from_bytes(data[o : o + 2], "little", signed=True); o += 2
    snd["dsp_t_echo_out_r"] = int.from_bytes(data[o : o + 2], "little", signed=True); o += 2
    snd["dsp_t_echo_in_l"] = int.from_bytes(data[o : o + 2], "little", signed=True); o += 2
    snd["dsp_t_echo_in_r"] = int.from_bytes(data[o : o + 2], "little", signed=True); o += 2
    snd["dsp_t_dir_addr"] = int.from_bytes(data[o : o + 2], "little"); o += 2
    snd["dsp_t_pitch"] = int.from_bytes(data[o : o + 2], "little"); o += 2
    snd["dsp_t_output"] = int.from_bytes(data[o : o + 2], "little", signed=True); o += 2
    snd["dsp_t_echo_ptr"] = int.from_bytes(data[o : o + 2], "little"); o += 2
    snd["dsp_t_looped"] = data[o]; o += 1
    snd["dsp_external_regs"] = data[o : o + 128]; o += 128
    if o < len(data):
        o += 1  # padding

    if o + 16 <= len(data):
        snd["reference_time"] = int.from_bytes(data[o : o + 4], "little", signed=True); o += 4
        snd["remainder"] = int.from_bytes(data[o : o + 4], "little"); o += 4
        snd["dsp_clock"] = int.from_bytes(data[o : o + 4], "little", signed=True); o += 4
        snd["cpu_regs"] = list(data[o : o + 4]); o += 4

    return snd


# ---------------------------------------------------------------------------
# Timings
# ---------------------------------------------------------------------------


def decode_tim_block(data: bytes, version: int) -> dict:
    o = 0
    tim = {}
    tim["H_Max_Master"] = _be_s(data, o, 4); o += 4
    tim["H_Max"] = _be_s(data, o, 4); o += 4
    tim["V_Max_Master"] = _be_s(data, o, 4); o += 4
    tim["V_Max"] = _be_s(data, o, 4); o += 4
    tim["HBlankStart"] = _be_s(data, o, 4); o += 4
    tim["HBlankEnd"] = _be_s(data, o, 4); o += 4
    tim["HDMAInit"] = _be_s(data, o, 4); o += 4
    tim["HDMAStart"] = _be_s(data, o, 4); o += 4
    tim["NMITriggerPos"] = _be_s(data, o, 4); o += 4
    tim["WRAMRefreshPos"] = _be_s(data, o, 4); o += 4
    tim["RenderPos"] = _be_s(data, o, 4); o += 4
    tim["InterlaceField"] = data[o]; o += 1
    tim["DMACPUSync"] = _be_s(data, o, 4); o += 4
    tim["NMIDMADelay"] = _be_s(data, o, 4); o += 4
    tim["IRQFlagChanging"] = _be_s(data, o, 4); o += 4
    tim["APUSpeedup"] = _be_s(data, o, 4); o += 4
    if version >= 7:
        tim["IRQTriggerCycles"] = _be_s(data, o, 4); o += 4
        tim["APUAllowTimeOverflow"] = data[o]; o += 1
    if version >= 11:
        tim["NextIRQTimer"] = _be_s(data, o, 4); o += 4
    return tim
