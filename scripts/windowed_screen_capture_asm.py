#!/usr/bin/env python3
"""Assemble the `windowed_screen_capture` code cave + hooks for Black & White.

The screen-grab routines (save-game pictures @ 0x00821750, named snapshots @
0x00821370) Lock the FRONT buffer [0x00E85080] and CPU-convert its pixels. In
fullscreen the front buffer holds the last flipped frame, so that works. In
windowed mode the "front buffer" is the emulated desktop primary: on modern
Windows its lockable memory never receives the rendered frame (it reads back
as a solid magenta fill), so every save-game picture comes out pink.

Both grabs run right after present (GGame loop calls 0x00821750 straight after
ProcessGraphicsEngine), and windowed mode presents with a Blt which leaves the
back buffer [0x00E85084] intact - so in windowed mode the back buffer holds
exactly the just-presented frame.

Fix: route every `mov eax, [0xE85080]` in the two grab routines through a tiny
cave that returns the back buffer instead when LHScreen.windowed (LHScreen @
0x00E85050, flag +0x64 = 0x00E850B4, set by LHScreen::SetFullscreenMode) says
we are windowed. Each original instruction is `A1 80 50 E8 00` (5 bytes), the
same size as `call cave`, so no other bytes move.

Emits the bytes for six `replace` ops used by bw1patch:
  * cave   @ file 0x4A8B80 (vaddr 0x008A8B80): surface-select routine
  * 5 hooks: Lock/Unlock surface loads in both grab routines

All virtual addresses come from bw1-decomp (1.20/no-cd layout).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32, KS_OPT_SYNTAX_INTEL

# --- fixed virtual addresses (from bw1-decomp) ---
CAVE_VA      = 0x008A8B80   # .text trailing zero-pad (after widescreen_loading's cave)
FRONT_BUF    = 0x00E85080   # LHScreen+0x30: front/primary IDirectDrawSurface7*
BACK_BUF     = 0x00E85084   # LHScreen+0x34: back buffer IDirectDrawSurface7*
WINDOWED     = 0x00E850B4   # LHScreen+0x64: 1 = windowed (LHScreen::SetFullscreenMode)
IMAGE_BASE   = 0x00400000

# hook sites: every `mov eax, [FRONT_BUF]` (A1 80 50 E8 00) in the grab routines
HOOKS = [
    # save-game picture grab, 0x00821750 (256x256 two-half capture)
    (0x008217A8, "save-picture grab: Lock surface select"),
    (0x008217C2, "save-picture grab: early-out Unlock surface select"),
    (0x00821B53, "save-picture grab: Unlock surface select"),
    # named snapshot grab, 0x00821370 (400x300 capture)
    (0x008213AE, "snapshot grab: Lock surface select"),
    (0x00821712, "snapshot grab: Unlock surface select"),
]

def file_off(va: int) -> int:
    return va - IMAGE_BASE

# --- the cave routine ---
# Same register/flag contract as the instruction it replaces apart from EFLAGS
# (clobbered; every site's next consumer is a mov/push, none read flags).
code = f"""
    cmp  dword ptr [{WINDOWED:#x}], 0
    jne  windowed
    mov  eax, [{FRONT_BUF:#x}]
    ret
windowed:
    mov  eax, [{BACK_BUF:#x}]
    ret
"""

def strip_comments(src: str) -> str:
    return "\n".join(line.split(";", 1)[0].rstrip() for line in src.splitlines())

ks = Ks(KS_ARCH_X86, KS_MODE_32)
ks.syntax = KS_OPT_SYNTAX_INTEL
routine, _ = ks.asm(strip_comments(code), CAVE_VA, as_bytes=True)

def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)

def hx_wrapped(b: bytes, per_line: int = 24, indent: str = "  ") -> str:
    out = []
    for i in range(0, len(b), per_line):
        out.append(indent + " ".join(f"{x:02X}" for x in b[i : i + per_line]))
    return "\n".join(out)

ORIG = bytes.fromhex("A18050E800")  # mov eax, [0xE85080]

hook_ops = []
for va, note in HOOKS:
    call_bytes, _ = ks.asm(f"call {CAVE_VA:#x}", va, as_bytes=True)
    assert len(call_bytes) == 5, call_bytes.hex()
    hook_ops.append((file_off(va), note, bytes(call_bytes)))

toml = f"""\
name = "windowed_screen_capture"
title = "Windowed Screen Capture"
summary = "Fix save-game pictures (and snapshots) rendering solid pink in windowed mode by grabbing the back buffer instead of the emulated front buffer."
doc = "docs/windowed_screen_capture.md"

# The screen-grab routines (save-game pictures @ 0x00821750, named snapshots @
# 0x00821370) Lock the FRONT buffer [0x00E85080]. Fullscreen: fine, it holds the
# last flipped frame. Windowed on modern Windows: the primary is an emulated
# surface whose lockable memory never sees the rendered frame (solid magenta),
# so every thumbnail saves as pink. Both grabs run right after present and the
# windowed Blt-present leaves the back buffer [0x00E85084] intact, so the back
# buffer holds exactly the just-presented frame.
#
# A {len(routine)}-byte cave returns front or back buffer depending on
# LHScreen.windowed (0x00E850B4, LHScreen+0x64). Each `mov eax,[0xE85080]`
# (A1 80 50 E8 00, 5 bytes) in the two grab routines becomes `call cave`
# (also 5 bytes). See docs/windowed_screen_capture.md.
#
# Bytes are produced by tool/windowed_screen_capture_asm.py (keystone).

# 1) The code cave. `expect` is the zero pad, so the op aborts unless the
#    region is genuinely empty (right exe, not already patched).
[[op]]
kind = "replace"
offset = 0x{file_off(CAVE_VA):X}
note = "windowed-aware grab surface select ({len(routine)} bytes; cave vaddr 0x{CAVE_VA:X})"
bytes = '''
{hx_wrapped(bytes(routine))}
'''
expect = '''
{hx_wrapped(bytes(len(routine)))}
'''
"""

for off, note, call_bytes in hook_ops:
    toml += f"""
[[op]]
kind = "replace"
offset = 0x{off:X}
note = "{note} (was: mov eax,[0xE85080])"
expect = "{hx(ORIG)}"
bytes = "{hx(call_bytes)}"
"""

import os
out_path = os.path.join(os.path.dirname(__file__), "..", "patches", "windowed_screen_capture.toml")
with open(out_path, "w", newline="\n") as f:
    f.write(toml)

print(f"cave vaddr     : {CAVE_VA:#010x} (file 0x{file_off(CAVE_VA):X})")
print(f"routine length : {len(routine)} bytes")
print(f"routine bytes  : {hx(bytes(routine))}")
for off, note, call_bytes in hook_ops:
    print(f"hook @ file 0x{off:X}: {hx(call_bytes)}  ; {note}")
print(f"wrote          : {os.path.normpath(out_path)}")
