"""Canonical SNES hardware state representation.

All values use SNES hardware semantics:
- VRAM addresses are word addresses (0-0x7FFF)
- Register values match the hardware encoding
- Multi-byte values are native Python ints (no endian concern)
"""

from dataclasses import dataclass, field


@dataclass
class CpuState:
    a: int = 0
    x: int = 0
    y: int = 0
    sp: int = 0
    d: int = 0          # direct page
    db: int = 0          # data bank
    pb: int = 0          # program bank
    pc: int = 0          # program counter
    p: int = 0           # processor status
    emulation: bool = False
    irq_source: int = 0  # bitmask: 1=PPU, 2=coprocessor
    nmi_pending: bool = False
    waiting_for_interrupt: bool = False


@dataclass
class BgLayerState:
    tilemap_addr: int = 0    # word address
    chr_addr: int = 0        # word address
    hscroll: int = 0
    vscroll: int = 0
    double_width: bool = False
    double_height: bool = False
    large_tiles: bool = False


@dataclass
class WindowState:
    left: int = 0
    right: int = 0
    # Per-layer active/inverted (6 layers: BG1-4, OBJ, Color)
    active: list[bool] = field(default_factory=lambda: [False] * 6)
    inverted: list[bool] = field(default_factory=lambda: [False] * 6)


@dataclass
class Mode7State:
    matrix: list[int] = field(default_factory=lambda: [0, 0, 0, 0])  # A, B, C, D (int16)
    hscroll: int = 0
    vscroll: int = 0
    center_x: int = 0
    center_y: int = 0
    value_latch: int = 0
    large_map: bool = False
    fill_with_tile0: bool = False
    h_mirror: bool = False
    v_mirror: bool = False


@dataclass
class PpuState:
    forced_blank: bool = False
    brightness: int = 0
    bg_mode: int = 0
    mode1_bg3_priority: bool = False
    main_screen_layers: int = 0   # bitmask
    sub_screen_layers: int = 0    # bitmask

    # VRAM
    vram_addr: int = 0            # word address (0-0x7FFF)
    vram_increment: int = 1       # 1, 32, or 128
    vram_remap: int = 0           # 0-3
    vram_incr_on_high: bool = False
    vram_read_buffer: int = 0

    # OAM
    oam_mode: int = 0             # size select (0-5)
    oam_base_addr: int = 0        # word address
    oam_addr_offset: int = 0      # word address
    oam_ram_addr: int = 0
    internal_oam_addr: int = 0
    oam_priority_rotation: bool = False
    oam_write_buffer: int = 0

    # CGRAM
    cgram_addr: int = 0
    internal_cgram_addr: int = 0
    cgram_write_buffer: int = 0
    cgram_latch: bool = False

    # Mosaic
    mosaic_size: int = 1          # 1-16
    mosaic_enabled: int = 0       # bitmask

    # Display
    hi_res: bool = False
    screen_interlace: bool = False
    obj_interlace: bool = False
    overscan: bool = False
    direct_color: bool = False
    ext_bg: bool = False

    # Color math
    color_clip_mode: int = 0      # ColorWindowMode enum (0-3)
    color_prevent_mode: int = 0
    color_add_subscreen: bool = False
    color_math_enabled: int = 0   # bitmask
    color_subtract: bool = False
    color_halve: bool = False
    fixed_color: int = 0          # 15-bit BGR555

    # Open bus
    ppu1_open_bus: int = 0
    ppu2_open_bus: int = 0

    # Latches
    hv_scroll_latch: int = 0
    h_scroll_latch: int = 0

    # Window mask logic (6 entries, 0-3 each)
    mask_logic: list[int] = field(default_factory=lambda: [0] * 6)
    window_mask_main: list[bool] = field(default_factory=lambda: [False] * 5)
    window_mask_sub: list[bool] = field(default_factory=lambda: [False] * 5)

    # Sub-state
    layers: list[BgLayerState] = field(default_factory=lambda: [BgLayerState() for _ in range(4)])
    windows: list[WindowState] = field(default_factory=lambda: [WindowState() for _ in range(2)])
    mode7: Mode7State = field(default_factory=Mode7State)

    # Raw data
    vram: bytes = b""      # 64KB
    oam: bytes = b""       # 544 bytes
    cgram: list[int] = field(default_factory=list)  # 256 uint16 values


@dataclass
class DmaChannelState:
    transfer_mode: int = 0
    dest_addr: int = 0        # B-bus register ($21xx low byte)
    src_addr: int = 0         # 16-bit A-bus address
    src_bank: int = 0
    transfer_size: int = 0    # also HDMA indirect address
    hdma_bank: int = 0
    hdma_table_addr: int = 0
    hdma_line_counter: int = 0  # combined repeat + line count byte
    invert_direction: bool = False
    hdma_indirect: bool = False
    decrement: bool = False
    fixed_transfer: bool = False
    unused_flag: bool = False
    unused_register: int = 0
    do_transfer: bool = False
    hdma_finished: bool = False
    dma_active: bool = False


@dataclass
class DmaState:
    hdma_channels: int = 0    # $420C bitmask
    channels: list[DmaChannelState] = field(default_factory=lambda: [DmaChannelState() for _ in range(8)])


@dataclass
class SpcTimerState:
    enabled: bool = False
    target: int = 0        # 0-255 (0 = 256)
    stage0: int = 0        # prescaler counter
    counter: int = 0       # main counter (0 to target-1)
    output: int = 0        # output counter (4-bit)


@dataclass
class DspVoiceState:
    env_volume: int = 0
    prev_env: int = 0
    interp_pos: int = 0
    env_mode: int = 0       # 0=Release, 1=Attack, 2=Decay, 3=Sustain
    brr_addr: int = 0
    brr_offset: int = 1     # Mesen2 default
    voice_bit: int = 0
    key_on_delay: int = 0
    env_out: int = 0
    buffer_pos: int = 0
    sample_buffer: list[int] = field(default_factory=lambda: [0] * 12)


@dataclass
class DspState:
    regs: bytes = b""           # 128 bytes
    external_regs: bytes = b""  # 128 bytes

    voices: list[DspVoiceState] = field(default_factory=lambda: [DspVoiceState(voice_bit=1 << i) for i in range(8)])

    noise_lfsr: int = 0x4000
    counter: int = 0
    step: int = 0
    out_reg_buffer: int = 0
    env_reg_buffer: int = 0
    voice_end_buffer: int = 0
    voice_output: int = 0
    out_samples: list[int] = field(default_factory=lambda: [0, 0])
    pitch: int = 0
    sample_addr: int = 0
    brr_next_addr: int = 0
    dir_sample_table_addr: int = 0
    noise_on: int = 0           # voice bitmask
    pitch_mod_on: int = 0       # voice bitmask
    key_on: int = 0
    new_key_on: int = 0
    key_off: int = 0
    every_other_sample: int = 0
    source_number: int = 0
    brr_header: int = 0
    brr_data: int = 0
    looped: int = 0             # voice bit flag
    adsr1: int = 0

    echo_in: list[int] = field(default_factory=lambda: [0, 0])
    echo_out: list[int] = field(default_factory=lambda: [0, 0])
    echo_history: list[int] = field(default_factory=lambda: [0] * 16)
    echo_pointer: int = 0
    echo_length: int = 0
    echo_offset: int = 0
    echo_history_pos: int = 0
    echo_ring_buffer_addr: int = 0
    echo_on: int = 0            # voice bitmask
    echo_enabled: bool = False


@dataclass
class SpcState:
    a: int = 0
    x: int = 0
    y: int = 0
    sp: int = 0xFF
    pc: int = 0
    psw: int = 0

    # Ports
    cpu_regs: list[int] = field(default_factory=lambda: [0] * 4)     # CPU → SPC
    output_regs: list[int] = field(default_factory=lambda: [0] * 4)  # SPC → CPU
    ram_regs: list[int] = field(default_factory=lambda: [0, 0])      # $F8, $F9

    # Flags from TEST register ($F0)
    write_enabled: bool = True
    rom_enabled: bool = False
    timers_enabled: bool = True
    timers_disabled: bool = False
    internal_speed: int = 0
    external_speed: int = 0

    dsp_reg: int = 0  # $F2 value

    # Timers
    timers: list[SpcTimerState] = field(default_factory=lambda: [SpcTimerState() for _ in range(3)])

    # Internal execution state
    op_code: int = 0
    op_step: int = 0      # 0 = ReadOpCode
    op_sub_step: int = 0
    operand_a: int = 0
    operand_b: int = 0
    tmp1: int = 0
    tmp2: int = 0
    tmp3: int = 0
    enabled: bool = True
    new_cpu_regs: list[int] = field(default_factory=lambda: [0] * 4)
    pending_cpu_reg_update: bool = False

    # RAM
    ram: bytes = b""  # 64KB

    # DSP
    dsp: DspState = field(default_factory=DspState)


@dataclass
class InternalRegState:
    enable_fast_rom: bool = False
    nmi_flag: bool = False
    enable_nmi: bool = False
    enable_h_irq: bool = False
    enable_v_irq: bool = False
    h_timer: int = 0
    v_timer: int = 0
    io_port_output: int = 0
    controller_data: list[int] = field(default_factory=lambda: [0] * 4)  # uint16[4]
    irq_level: bool = False
    need_irq: int = 0
    enable_auto_joypad: bool = False
    irq_flag: bool = False

    # ALU
    mult_operand1: int = 0
    mult_operand2: int = 0
    mult_result: int = 0
    dividend: int = 0
    divisor: int = 0
    div_result: int = 0

    # Latched counters
    h_counter: int = 0
    v_counter: int = 0


@dataclass
class TimingState:
    """Synthesized timing for the target emulator."""
    scanline: int = 0
    is_pal: bool = False
    overscan: bool = False


@dataclass
class SnesState:
    """Complete SNES hardware state in canonical form."""
    cpu: CpuState = field(default_factory=CpuState)
    ppu: PpuState = field(default_factory=PpuState)
    spc: SpcState = field(default_factory=SpcState)
    dma: DmaState = field(default_factory=DmaState)
    internal_regs: InternalRegState = field(default_factory=InternalRegState)
    timing: TimingState = field(default_factory=TimingState)

    # Memory
    wram: bytes = b""       # 128KB
    sram: bytes = b""       # variable
    wram_port_addr: int = 0 # $2180 sequential address

    # Coprocessor (opaque for now — format-specific)
    coprocessor_type: str = ""
    coprocessor_data: dict = field(default_factory=dict)
