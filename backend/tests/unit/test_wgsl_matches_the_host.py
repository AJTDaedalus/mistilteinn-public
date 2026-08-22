"""The WGSL `Case` struct and the host's field offsets are two definitions of one layout.

`gpu.ts` packs a flat `Float32Array` and `damage.wgsl` reads it as a struct. Nothing in
either language checks the other. If a field is added, removed or reordered on one side, the
shader reads a **plausible wrong number** for every case after the first — no crash, no type
error, just damage figures that are confidently incorrect.

The 2,000-case gate does catch it, loudly. This catches it *specifically*, with a message
that names the mismatch rather than reporting two thousand divergent cases and leaving the
reader to work out why.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
WGSL = FRONTEND / "src" / "app" / "sim" / "damage.wgsl"
HOST = FRONTEND / "src" / "app" / "sim" / "gpu.ts"


def _wgsl_case_fields() -> list[str]:
    """Field names of the WGSL `Case` struct, in declaration order."""
    struct = re.search(r"struct Case \{(.*?)\n\}", WGSL.read_text(), re.S)
    assert struct, "damage.wgsl no longer declares `struct Case`"
    return re.findall(r"^\s*(\w+)\s*:\s*f32\s*,", struct.group(1), re.M)


def _host_fields() -> dict[str, int]:
    """`FIELD` from gpu.ts, as name → offset."""
    block = re.search(r"export const FIELD = \{(.*?)\n\} as const;", HOST.read_text(), re.S)
    assert block, "gpu.ts no longer exports a `FIELD` map"
    return {name: int(offset) for name, offset in re.findall(r"(\w+):\s*(\d+),", block.group(1))}


def _stride() -> int:
    match = re.search(r"export const CASE_STRIDE = (\d+);", HOST.read_text())
    assert match, "gpu.ts no longer exports CASE_STRIDE"
    return int(match.group(1))


def test_the_stride_matches_the_struct_size():
    """A stride smaller than the struct reads every case after the first misaligned."""
    fields = _wgsl_case_fields()

    assert len(fields) == _stride(), (
        f"the WGSL `Case` struct has {len(fields)} f32 fields but CASE_STRIDE is {_stride()}. "
        f"Every case after the first would be read at the wrong offset, producing plausible "
        f"wrong damage rather than an error."
    )


def test_every_host_offset_names_the_field_the_shader_reads_there():
    """Catches a reorder, which is the failure with no other symptom."""
    wgsl = _wgsl_case_fields()
    host = _host_fields()

    mismatches = [
        f"offset {offset}: host calls it {name!r}, shader has {wgsl[offset]!r}"
        for name, offset in sorted(host.items(), key=lambda kv: kv[1])
        if offset < len(wgsl) and _snake(name) != wgsl[offset]
    ]

    assert not mismatches, "host and shader disagree about the layout:\n  " + "\n  ".join(
        mismatches,
    )


def test_the_host_maps_every_field_the_shader_reads_except_padding():
    """A field the shader reads and the host never writes is silently zero.

    Zero is a legal value for every field here — a zero multiplier, a zero resistance — so it
    would score rather than fail.
    """
    wgsl = [f for f in _wgsl_case_fields() if not f.startswith("_")]
    host = {_snake(name) for name in _host_fields()}

    assert set(wgsl) == host, (
        f"shader reads {sorted(set(wgsl) - host)} that the host never writes, and the host "
        f"writes {sorted(host - set(wgsl))} the shader does not read. An unwritten field is "
        f"zero, and zero is legal for all of these — so it scores rather than failing."
    )


def _snake(camel: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", camel).lower()
