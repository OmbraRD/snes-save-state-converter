"""Mesen2 binary save-state serializer.

Each field is stored as::

    <null-terminated key>  <uint32-LE size>  <value bytes (LE)>

Keys use lowercase-leading-segment dot notation, e.g. ``cpu.cycleCount``.
"""

import struct


class MesenSerializer:
    """Incrementally builds Mesen2's key-value binary blob."""

    def __init__(self) -> None:
        self._data = bytearray()

    # -- low-level helpers --------------------------------------------------

    def _write_key(self, key: str) -> None:
        self._data.extend(key.encode("ascii"))
        self._data.append(0)

    # -- scalar writers -----------------------------------------------------

    def write_u8(self, key: str, value: int) -> None:
        self._write_key(key)
        self._data.extend(struct.pack("<IB", 1, value & 0xFF))

    def write_bool(self, key: str, value: bool) -> None:
        self.write_u8(key, 1 if value else 0)

    def write_u16(self, key: str, value: int) -> None:
        self._write_key(key)
        self._data.extend(struct.pack("<IH", 2, value & 0xFFFF))

    def write_i16(self, key: str, value: int) -> None:
        self._write_key(key)
        self._data.extend(struct.pack("<Ih", 2, value))

    def write_u32(self, key: str, value: int) -> None:
        self._write_key(key)
        self._data.extend(struct.pack("<II", 4, value & 0xFFFFFFFF))

    def write_i32(self, key: str, value: int) -> None:
        self._write_key(key)
        self._data.extend(struct.pack("<Ii", 4, value))

    def write_u64(self, key: str, value: int) -> None:
        self._write_key(key)
        self._data.extend(struct.pack("<IQ", 8, value & 0xFFFFFFFFFFFFFFFF))

    def write_f64(self, key: str, value: float) -> None:
        self._write_key(key)
        self._data.extend(struct.pack("<Id", 8, value))

    # -- array writers ------------------------------------------------------

    def write_array_u8(self, key: str, data: bytes | bytearray | list[int]) -> None:
        if isinstance(data, list):
            data = bytes(data)
        self._write_key(key)
        self._data.extend(struct.pack("<I", len(data)))
        self._data.extend(data)

    def write_array_u16(self, key: str, values: list[int]) -> None:
        self._write_key(key)
        self._data.extend(struct.pack("<I", len(values) * 2))
        for v in values:
            self._data.extend(struct.pack("<H", v & 0xFFFF))

    def write_array_i16(self, key: str, values: list[int]) -> None:
        self._write_key(key)
        self._data.extend(struct.pack("<I", len(values) * 2))
        for v in values:
            self._data.extend(struct.pack("<h", v))

    def write_array_i32(self, key: str, values: list[int]) -> None:
        self._write_key(key)
        self._data.extend(struct.pack("<I", len(values) * 4))
        for v in values:
            self._data.extend(struct.pack("<i", v))

    # -- output -------------------------------------------------------------

    def get_data(self) -> bytes:
        return bytes(self._data)
