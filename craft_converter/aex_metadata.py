"""Read only declared effect identity from a Windows After Effects PiPL resource.

PiPL stores the effect's display/match names and category, NOT its render
algorithm, parameter definitions, bounds, group hierarchy or keyframe flags.
This parser never loads or executes the DLL. Unsupported or damaged optional
resources yield no identity rather than guessed parameter metadata.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable

MAX_RESOURCE_BYTES = 1 << 20
MAX_ENTRIES = 128


@dataclass(frozen=True)
class AEEffectIdentity:
    name: str
    category: str | None
    match_name: str | None


def _pascal(value: bytes) -> str | None:
    if not value or value[0] == 0 or value[0] >= len(value):
        return None
    chars = value[1:1 + value[0]]
    if any(c < 32 or c == 127 for c in chars):
        return None
    try:
        text = chars.decode('utf-8')
    except UnicodeDecodeError:
        text = chars.decode('cp1252', errors='replace')
    return text.strip()[:256] or None


def _pipl_identity(blob: bytes) -> AEEffectIdentity | None:
    # Windows AE PiPL: 32-bit version, 16 reserved bits, 32-bit property count;
    # each property has 8BIM signature, 4-char key, 4 reserved bytes, 32-bit
    # length and 4-byte-aligned data. Windows stores the 4-char codes reversed.
    if len(blob) < 10 or blob[:6] != b'\x01\x00\x00\x00\x00\x00':
        return None
    count = struct.unpack_from('<I', blob, 6)[0]
    if count == 0 or count > MAX_ENTRIES:
        return None
    pos = 10
    fields: dict[bytes, str] = {}
    for _ in range(count):
        if pos + 16 > len(blob):
            return None
        signature, key = blob[pos:pos + 4], blob[pos + 4:pos + 8][::-1]
        length = struct.unpack_from('<I', blob, pos + 12)[0]
        if length > len(blob) - pos - 16:
            return None
        if signature == b'MIB8' and key in (b'name', b'catg', b'eMNA'):
            text = _pascal(blob[pos + 16:pos + 16 + length])
            if text:
                fields[key] = text
        pos += 16 + ((length + 3) & ~3)
        if pos > len(blob):
            return None
    if not fields.get(b'name'):
        return None
    return AEEffectIdentity(fields[b'name'], fields.get(b'catg'), fields.get(b'eMNA'))


def read_pipl_identities(data: bytes, resource_rva: int, resource_size: int,
                         rva_offset: Callable[[int, int], int]) -> tuple[AEEffectIdentity, ...]:
    """Return PiPL identities from a bounded PE resource tree, if present.

    `rva_offset` belongs to the caller's validated section map. Malformed
    resource trees are ignored; their contents never become executable code.
    """
    if not resource_rva or not 16 <= resource_size <= MAX_RESOURCE_BYTES:
        return ()

    def relative(offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset > resource_size - size:
            raise ValueError('PiPL resource pointer is outside its section')
        at = rva_offset(resource_rva + offset, size)
        return data[at:at + size]

    def entries(offset: int) -> list[tuple[int, int]]:
        header = relative(offset, 16)
        count = struct.unpack_from('<H', header, 12)[0] + struct.unpack_from('<H', header, 14)[0]
        if count > MAX_ENTRIES:
            raise ValueError('Too many PiPL resource entries')
        raw = relative(offset + 16, count * 8)
        return [struct.unpack_from('<II', raw, n * 8) for n in range(count)]

    def name(value: int) -> str | None:
        if not value & 0x80000000:
            return None
        offset = value & 0x7fffffff
        count = struct.unpack('<H', relative(offset, 2))[0]
        if not 0 < count <= 64:
            return None
        return relative(offset + 2, count * 2).decode('utf-16le', errors='replace')

    identities: list[AEEffectIdentity] = []
    try:
        for resource_name, target in entries(0):
            if (name(resource_name) or '').casefold() != 'pipl' or not target & 0x80000000:
                continue
            for _, language_directory in entries(target & 0x7fffffff):
                if not language_directory & 0x80000000:
                    continue
                for _, leaf in entries(language_directory & 0x7fffffff):
                    if leaf & 0x80000000:
                        continue
                    rva, size = struct.unpack('<II', relative(leaf, 8))
                    if not 10 <= size <= MAX_RESOURCE_BYTES:
                        continue
                    at = rva_offset(rva, size)
                    identity = _pipl_identity(data[at:at + size])
                    if identity and identity not in identities:
                        identities.append(identity)
                    if len(identities) >= 32:
                        return tuple(identities)
    except (ValueError, struct.error, UnicodeError):
        return tuple(identities)
    return tuple(identities)
