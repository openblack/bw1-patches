#!/usr/bin/env python3
"""Assemble the `widescreen_cinema_bars` code cave + hooks for Black & White.

The cinematic letterbox bars (script command SET_WIDESCREEN, HelpSystem state at
this+0x45E8/0x45F0) are sized everywhere by the same formula:

    bar_total = h - w * 0.5625        (h = [0xE839E8], w = [0xE839E4],
                                       0.5625 = 9/16 @ rdata 0x8C7A50)

i.e. "crop the screen to 16:9". On a 4:3 display that's 25% of the height
(12.5% per bar); on a 16:9 display it is exactly zero, so the bars never
appear and cutscenes lose the cinematic framing.

The formula is computed in five places (all the identical 12-byte pair
`fild [0xE839E4]` / `fmul [0x8C7A50]`, found via bw1-decomp):

    0x005C5786  HelpSystem bar-height helper @ 0x5C5780 (* pct / 2) -- feeds the
                dialogue/help text rect (0x5C57B0) during cutscenes
    0x0081E8B6  shared bar-height helper @ 0x81E8B0 (* pct / 2) -- feeds the two
                black-bar drawers (0x82F686, 0x870154) and the visible-area rect
                helpers (0x81E881, 0x81E8E1, 0x81E922)
    0x00456F22  \
    0x0045B978   } inline usable-height clamps in GInterface (mouse / UI
    0x0045D05F  /  placement), gated on the widescreen flag

Fix: replace each pair with a call to a cave that computes

    min(w, h * 4/3) * 0.5625

instead of `w * 0.5625`. On 4:3 / 5:4 displays `min()` returns w, so behaviour
is bit-for-bit identical. On wider displays the bars become the same fraction
of the height they always were on 4:3 (12.5% per side), giving a ~2.37:1
visible area on 16:9 -- the classic cinema scope ratio. All five sites share
one formula again, so bars, text rect and input clamps stay in agreement.

Deliberately NOT patched:
  * the movie player's copy of the formula (0x54DBEB) -- its bars work and its
    widescreen stretch is a separate fix;
  * the other 0.5625 user at 0x44FB34 -- unrelated squared-distance math that
    happens to share the .rdata constant;
  * every other `fild [0xE839E4]` -- those use the width as a width (bar quad
    extents, rect widths), which must keep spanning the full screen.

All virtual addresses come from bw1-decomp (win1.41 / unprotected layout).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32, KS_OPT_SYNTAX_INTEL

IMAGE_BASE = 0x00400000

W_GLOBAL = 0x00E839E4       # int, interface transform width  (g_info_transform)
H_GLOBAL = 0x00E839E8       # int, interface transform height (g_info_transform+4)
C_09_16  = 0x008C7A50       # 0.5625f (9/16) in .rdata

HOOK_VAS = [
    (0x00456F22, "GInterface usable-height clamp #1"),
    (0x0045B978, "GInterface usable-height clamp #2"),
    (0x0045D05F, "GInterface usable-height clamp #3"),
    (0x005C5786, "HelpSystem bar-height helper"),
    (0x0081E8B6, "shared bar-height helper (bar drawers, visible-area rects)"),
]
PAIR_LEN = 12  # fild [0xE839E4] (6) + fmul [0x8C7A50] (6)

# .text tail zero-pad, after the widescreen_logos caves (which end by 0x8A8C50);
# the pad runs to 0x8A9000. Pad layout: saves_in_documents 0x8A8970..0x8A8AAE,
# widescreen_loading 0x8A8AB0..0x8A8B72, windowed_screen_capture
# 0x8A8B80..0x8A8B95, widescreen_logos 0x8A8BA0..<0x8A8C50, us.
CAVE_VA  = 0x008A8C50
CAVE_END = 0x008A9000

def file_off(va: int) -> int:
    return va - IMAGE_BASE

# Entry: st0 = h (the callers fild [0xE839E8] first). Exit: st0 = min(w, h*4/3)
# * 0.5625, st1 = h -- exactly what the replaced fild+fmul pair left behind.
# The five call sites have different live registers, so preserve eax/ecx/edx.
code = f"""
    push  eax
    push  ecx
    push  edx
    mov   eax, dword ptr [{H_GLOBAL:#x}]   ; h
    lea   eax, [eax*4]
    xor   edx, edx
    mov   ecx, 3
    div   ecx                              ; eax = h*4/3
    mov   ecx, dword ptr [{W_GLOBAL:#x}]   ; w
    cmp   eax, ecx
    jbe   cw_ok
    mov   eax, ecx
cw_ok:                                     ; eax = cw = min(w, h*4/3)
    push  eax
    fild  dword ptr [esp]
    fmul  dword ptr [{C_09_16:#x}]         ; st0 = cw * 9/16
    pop   eax
    pop   edx
    pop   ecx
    pop   eax
    ret
"""

ks = Ks(KS_ARCH_X86, KS_MODE_32)
ks.syntax = KS_OPT_SYNTAX_INTEL
cleaned = "\n".join(line.split(";")[0].rstrip() for line in code.splitlines())
cave, _ = ks.asm(cleaned, CAVE_VA)
cave = bytes(cave)
assert CAVE_VA + len(cave) <= CAVE_END, "cave exceeds zero-pad budget"

PAIR_EXPECT = bytes.fromhex("db05e439e800" + "d80d507a8c00")

def hook(hook_va: int) -> bytes:
    rel = CAVE_VA - (hook_va + 5)
    return bytes([0xE8]) + rel.to_bytes(4, "little", signed=True) + b"\x90" * (PAIR_LEN - 5)

def hx_wrapped(b: bytes, per_line: int = 24) -> str:
    lines = []
    for i in range(0, len(b), per_line):
        lines.append("  " + " ".join(f"{x:02X}" for x in b[i:i + per_line]))
    return "\n".join(lines)

ops = [f"""# 1) The code cave ({len(cave)} bytes at vaddr 0x{CAVE_VA:X}).
[[op]]
kind = "replace"
offset = 0x{file_off(CAVE_VA):X}
note = "bar height from effective 4:3 width: min(w, h*4/3) * 9/16"
bytes = '''
{hx_wrapped(cave)}
'''
expect = '''
{hx_wrapped(bytes(len(cave)))}
'''"""]

for i, (va, what) in enumerate(HOOK_VAS, start=2):
    ops.append(f"""# {i}) {what} @ 0x{va:X}.
[[op]]
kind = "replace"
offset = 0x{file_off(va):X}
note = "{what}: w*9/16 -> cave"
bytes = '''
{hx_wrapped(hook(va))}
'''
expect = '''
{hx_wrapped(PAIR_EXPECT)}
'''""")

ops_str = "\n\n".join(ops)
toml = f"""name = "widescreen_cinema_bars"
title = "Widescreen Cinematic Bars"
summary = "Bring back the cinematic letterbox bars in cutscenes on widescreen displays."
doc = "docs/widescreen_cinema_bars.md"

# The cutscene letterbox bars (script command SET_WIDESCREEN) are sized as
# h - w*9/16 -- "crop to 16:9" -- which is exactly zero on a 16:9 display, so
# the bars never show on widescreen. We redirect the five copies of that
# formula into a cave that uses the effective 4:3 width min(w, h*4/3) instead,
# restoring the original 12.5%%-of-height bars (a ~2.37:1 visible area on 16:9,
# the classic cinema scope ratio). 4:3 and 5:4 displays are bit-for-bit
# unaffected. Bar drawing, help-text placement and the cutscene mouse/UI
# clamps all share these five sites, so everything stays in agreement.
#
# Bytes are produced by tool/widescreen_cinema_bars_asm.py (keystone). The cave
# sits in the .text tail zero-pad after the widescreen_logos caves; all the
# widescreen patches are independent and can be applied in any order.

{ops_str}
"""

import os
out_path = os.path.join(os.path.dirname(__file__), "..", "patches", "widescreen_cinema_bars.toml")
with open(out_path, "w", newline="\n") as f:
    f.write(toml)

print(f"cave       : {CAVE_VA:#010x} (file {file_off(CAVE_VA):#x}), {len(cave)} bytes")
for va, what in HOOK_VAS:
    print(f"hook       : {va:#010x} (file {file_off(va):#x})  {what}")
print(f"pad budget : {CAVE_END - CAVE_VA} bytes")
print(f"wrote      : {os.path.normpath(out_path)}")
