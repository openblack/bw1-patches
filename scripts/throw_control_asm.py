#!/usr/bin/env python3
"""Assemble the `throw_control` code cave + hook for Black & White.

While the player holds an object and drags to throw, HandStateHolding::Update
(vtable slot 3 of HandStateHolding, 0x005B3C70) runs the hand as a damped spring
chasing the point under the cursor, in fixed 10 ms steps:

    vel += ((target - pos) * 260 - vel * 40) * 0.01      ; 0x00BF0198, 0x00BF019C
    |vel| clamped to 124                                   ; 0x00C371FC

(`InThrow` is HandStateHolding+0x104, the spring velocity +0x108.) Every frame
the velocity is copied into CHand+0x48C8, the hand velocity the throw is made
with when the button is released (angular velocity CHand+0x48D4 is zeroed).

So a throw is the hand's speed at the exact frame the button goes up: easing off
the mouse a moment before releasing loses most of the throw, and on large
screens or high-DPI mice the cursor's ground point moves so far per count that
almost every flick hits the 124 cap.

Fix: the copy at 0x005B46BC..0x005B46E9 becomes `call cave; jmp 0x005B46EA`.
The cave keeps the fastest velocity seen in the last `Grace` ms of game frames
(frame time in ms at 0x00C38134) and writes it, scaled by `Strength` percent, to
CHand+0x48C8. Both values come from `.\\BWThrow.ini`, read once with
GetPrivateProfileIntA (resolved via GetModuleHandleA/GetProcAddress, both in the
IAT) at the start of every throw, so the file can be edited while the game runs.
Defaults Strength=100, Grace=0 are exactly the original behaviour.

Emits the bytes for two `replace` ops used by bw1patch:
  * cave  @ file 0x4A8CA0 (vaddr 0x008A8CA0): settings loader + peak hold + scale
  * hook  @ file 0x1B46BC (vaddr 0x005B46BC)

State lives in the zero-filled tail of .data past its VirtualSize (the last
object, __jump_buffer, ends at 0x00FBFE00; the page runs to 0x00FC0000).

All virtual addresses are from the 1.20 / no-CD layout (bw1-decomp BW1W120).
"""
import os
import struct

from keystone import Ks, KS_ARCH_X86, KS_MODE_32, KS_OPT_SYNTAX_INTEL

IMAGE_BASE = 0x00400000

CAVE_VA = 0x008A8CA0       # .text trailing zero-pad (after widescreen_cinema_bars' cave)
HOOK_VA = 0x005B46BC       # velocity copy in HandStateHolding::Update

IAT_GETMODULEHANDLEA = 0x008A91CC
IAT_GETPROCADDRESS = 0x008A9170
FRAME_MS = 0x00C38134      # int, ms of game time this frame

# writable state (0x20 bytes) in the .data page tail
DATA_VA = 0x00FBFF00

DEFAULT_STRENGTH = 100
DEFAULT_GRACE = 0


def file_off(va: int) -> int:
    return va - IMAGE_BASE


def build(strings_va: int, data_va: int, iat_getmodulehandlea: int,
          iat_getprocaddress: int, frame_ms: int) -> str:
    s = STRINGS_LAYOUT(strings_va)
    HELD = data_va + 0x00          # LHPoint: velocity being held
    AGE = data_va + 0x0C           # int ms since HELD was taken
    STRENGTH_PCT = data_va + 0x10
    GRACE_MS = data_va + 0x14
    SCALE = data_va + 0x18         # float Strength / 100
    LOADED = data_va + 0x1C
    return f"""
    push ebx
    cmp  dword ptr [{LOADED:#x}], 0
    jne  ready
    mov  dword ptr [{LOADED:#x}], 1
    mov  dword ptr [{STRENGTH_PCT:#x}], {DEFAULT_STRENGTH:#x}
    mov  dword ptr [{GRACE_MS:#x}], {DEFAULT_GRACE:#x}
    push {s['kernel32']:#x}
    call dword ptr [{iat_getmodulehandlea:#x}]
    test eax, eax
    je   scale
    push {s['getint']:#x}
    push eax
    call dword ptr [{iat_getprocaddress:#x}]
    test eax, eax
    je   scale
    mov  ebx, eax
    push {s['ini']:#x}
    push {DEFAULT_STRENGTH:#x}
    push {s['strength']:#x}
    push {s['section']:#x}
    call ebx
    mov  dword ptr [{STRENGTH_PCT:#x}], eax
    push {s['ini']:#x}
    push {DEFAULT_GRACE:#x}
    push {s['grace']:#x}
    push {s['section']:#x}
    call ebx
    mov  dword ptr [{GRACE_MS:#x}], eax
scale:
    fild dword ptr [{STRENGTH_PCT:#x}]
    fmul dword ptr [{s['hundredth']:#x}]
    fstp dword ptr [{SCALE:#x}]

ready:
    mov  eax, dword ptr [esi + 0x108]
    or   eax, dword ptr [esi + 0x10c]
    or   eax, dword ptr [esi + 0x110]
    add  eax, eax
    jne  moving
    mov  dword ptr [{HELD:#x}], eax
    mov  dword ptr [{HELD + 4:#x}], eax
    mov  dword ptr [{HELD + 8:#x}], eax
    mov  dword ptr [{AGE:#x}], eax
    mov  dword ptr [{LOADED:#x}], eax
    jmp  output

moving:
    fld  dword ptr [esi + 0x108]
    fmul st(0), st(0)
    fld  dword ptr [esi + 0x10c]
    fmul st(0), st(0)
    faddp st(1), st(0)
    fld  dword ptr [esi + 0x110]
    fmul st(0), st(0)
    faddp st(1), st(0)
    fld  dword ptr [{HELD:#x}]
    fmul st(0), st(0)
    fld  dword ptr [{HELD + 4:#x}]
    fmul st(0), st(0)
    faddp st(1), st(0)
    fld  dword ptr [{HELD + 8:#x}]
    fmul st(0), st(0)
    faddp st(1), st(0)
    fcompp
    fnstsw ax
    test ah, 0x41
    jne  take
    mov  eax, dword ptr [{frame_ms:#x}]
    add  eax, dword ptr [{AGE:#x}]
    mov  dword ptr [{AGE:#x}], eax
    cmp  eax, dword ptr [{GRACE_MS:#x}]
    jle  output
take:
    mov  eax, dword ptr [esi + 0x108]
    mov  dword ptr [{HELD:#x}], eax
    mov  eax, dword ptr [esi + 0x10c]
    mov  dword ptr [{HELD + 4:#x}], eax
    mov  eax, dword ptr [esi + 0x110]
    mov  dword ptr [{HELD + 8:#x}], eax
    mov  dword ptr [{AGE:#x}], 0

output:
    mov  eax, dword ptr [esi + 4]
    add  eax, 0x48c8
    fld  dword ptr [{SCALE:#x}]
    fld  dword ptr [{HELD:#x}]
    fmul st(0), st(1)
    fstp dword ptr [eax]
    fld  dword ptr [{HELD + 4:#x}]
    fmul st(0), st(1)
    fstp dword ptr [eax + 4]
    fmul dword ptr [{HELD + 8:#x}]
    fstp dword ptr [eax + 8]
    xor  edx, edx
    mov  dword ptr [eax + 0x0c], edx
    mov  dword ptr [eax + 0x10], edx
    mov  dword ptr [eax + 0x14], edx
    pop  ebx
    ret
"""


STRINGS = [
    ("hundredth", struct.pack("<f", 0.01)),
    ("kernel32", b"kernel32.dll\0"),
    ("getint", b"GetPrivateProfileIntA\0"),
    ("ini", b".\\BWThrow.ini\0"),
    ("section", b"Throw\0"),
    ("strength", b"Strength\0"),
    ("grace", b"Grace\0"),
]


def STRINGS_LAYOUT(base: int) -> dict:
    out, va = {}, base
    for name, blob in STRINGS:
        out[name] = va
        va += len(blob)
    return out


# mov eax,[esi+4]; lea edx,[esi+0x108]; copy 3 dwords to CHand+0x48C8;
# mov eax,[esi+4]; add eax,0x48D4; zero 3 dwords with ebp
ORIG_HOOK = bytes.fromhex(
    "8B4604 8D9608010000 8B0A 05C8480000 8908 8B4A04 894804 8B5208 895008"
    " 8B4604 05D4480000 896808 896804 8928".replace(" ", "")
)

ks = Ks(KS_ARCH_X86, KS_MODE_32)
ks.syntax = KS_OPT_SYNTAX_INTEL


def assemble_cave(cave_va: int, **addrs) -> tuple[bytes, int]:
    """Cave bytes for `cave_va` and the length of its code part."""
    # Assemble once with a placeholder to size the code, then place the strings
    # 4-byte aligned right after it and assemble for real.
    probe, _ = ks.asm(build(cave_va + 0x1000, **addrs), cave_va, as_bytes=True)
    strings_va = (cave_va + len(probe) + 3) & ~3
    routine, _ = ks.asm(build(strings_va, **addrs), cave_va, as_bytes=True)
    assert len(routine) == len(probe)
    cave = bytes(routine) + bytes(strings_va - cave_va - len(routine))
    return cave + b"".join(blob for _, blob in STRINGS), len(routine)


def assemble_hook(hook_va: int, cave_va: int) -> bytes:
    """`call cave; jmp past the copy`, NOP-padded to the copy's length."""
    hook, _ = ks.asm(f"call {cave_va:#x}; jmp {hook_va + len(ORIG_HOOK):#x}", hook_va, as_bytes=True)
    hook = bytes(hook)
    return hook + b"\x90" * (len(ORIG_HOOK) - len(hook))


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def hx_wrapped(b: bytes, per_line: int = 24, indent: str = "  ") -> str:
    return "\n".join(
        indent + " ".join(f"{x:02X}" for x in b[i : i + per_line])
        for i in range(0, len(b), per_line)
    )


def render_toml(cave: bytes, hook: bytes) -> str:
    return f"""\
name = "throw_control"
title = "Throw Control"
summary = "Make throws keep your fastest recent swing instead of the release frame's speed, and scale throw strength (BWThrow.ini)."
doc = "docs/throw_control.md"

# While dragging a held object, HandStateHolding::Update (0x005B3C70) moves the
# hand as a damped spring (K 260 @ 0x00BF0198, damping 40 @ 0x00BF019C, speed
# cap 124 @ 0x00C371FC) and copies its velocity (HandStateHolding+0x108) into
# CHand+0x48C8 every frame; the throw uses whatever is there on release. So the
# throw is the speed of the release frame: slowing down just before letting go
# kills it, and fast cursors (large screens, high-DPI mice) hit the cap.
#
# The copy becomes `call cave; jmp 0x5B46EA`. The {len(cave)}-byte cave keeps the
# fastest velocity of the last Grace ms (game frame time @ 0x00C38134) and
# writes it times Strength/100. Settings: [Throw] Strength=, Grace= in
# BWThrow.ini next to the exe (defaults 100 / 0 = original behaviour), read at
# the start of every throw via GetPrivateProfileIntA. State: 0x20 bytes at
# 0x00FBFF00, in the zero tail of .data past its VirtualSize. See docs/throw_control.md.
#
# Bytes are produced by scripts/throw_control_asm.py (keystone).

# 1) The code cave. `expect` is the zero pad, so the op aborts unless the
#    region is genuinely empty (right exe, not already patched).
[[op]]
kind = "replace"
offset = 0x{file_off(CAVE_VA):X}
note = "throw velocity peak hold + strength scale ({len(cave)} bytes; cave vaddr 0x{CAVE_VA:X})"
bytes = '''
{hx_wrapped(cave)}
'''
expect = '''
{hx_wrapped(bytes(len(cave)))}
'''

# 2) Hook: replace the velocity copy into CHand+0x48C8 with a call to the cave.
[[op]]
kind = "replace"
offset = 0x{file_off(HOOK_VA):X}
note = "HandStateHolding::Update: hand velocity copy -> cave"
expect = '''
{hx_wrapped(ORIG_HOOK)}
'''
bytes = '''
{hx_wrapped(hook)}
'''
"""


def main() -> None:
    assert HOOK_VA + len(ORIG_HOOK) == 0x005B46EA
    cave, code_len = assemble_cave(CAVE_VA, data_va=DATA_VA,
                                   iat_getmodulehandlea=IAT_GETMODULEHANDLEA,
                                   iat_getprocaddress=IAT_GETPROCADDRESS, frame_ms=FRAME_MS)
    hook = assemble_hook(HOOK_VA, CAVE_VA)

    toml = render_toml(cave, hook)
    out_path = os.path.join(os.path.dirname(__file__), "..", "patches", "throw_control.toml")
    with open(out_path, "w", newline="\n") as f:
        f.write(toml)

    print(f"cave vaddr     : {CAVE_VA:#010x} (file 0x{file_off(CAVE_VA):X}), {len(cave)} bytes"
          f" (code {code_len})")
    print(f"cave end       : {CAVE_VA + len(cave):#010x}")
    print(f"hook @ file 0x{file_off(HOOK_VA):X}: {hx(hook)}")
    print(f"wrote          : {os.path.normpath(out_path)}")


if __name__ == "__main__":
    main()
