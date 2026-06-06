#!/usr/bin/env python3
"""Assemble the `widescreen_logos` code caves + hooks for Black & White.

The intro logo screens are two functions in logo.cpp (names from bw1-decomp):

  PlayPreIntroVideo @ 0x006426F0  plays \\data\\pre_intro.bik (skipped when absent)
  PlayLogoScreens   @ 0x00642950  plays frames 1-3 of \\data\\logo.bik (the
                                  Lionhead / EA / B&W logo stills, faded by a Zoomer)

Both pass the raw screen size as the Bink destination rect:

  PlayLogoScreens   0x00642CDB..0x00642D00  Draw(colour|fade, -1, -1, w, h, 0, 0)
                                            via the immediate blitter @ 0x00845740
  PlayPreIntroVideo 0x0064286F..0x006428A1  SetDrawParams(white, 0, 0, w, h, 0, 0)
                                            via the param setter   @ 0x008456C0

The blitter scales each axis independently (destW/videoW, destH/videoH, see
0x008457B9), so 4:3 content stretches on widescreen. The in-game movie player
(0x0054DC6D) and the loading-screen movie path (0x005F410A) compute their own
rects, so we patch only these two call sites, not the shared blitter.

Fix: redirect each w/h+push block into a cave that computes

    cw   = min(w, h * 4/3)
    xoff = (w - cw) / 2

and passes (x + xoff, y, cw, h) instead of (x, y, w, h). On 4:3 / 5:4 displays
cw == w and xoff == 0, so behaviour is bit-for-bit identical (including
PlayLogoScreens' original x = -1 one-pixel overscan). The pillarbox bars stay
black because both functions clear via LH3DRender::StartFrame every frame.

All virtual addresses come from bw1-decomp (win1.41 / unprotected layout).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32, KS_OPT_SYNTAX_INTEL

IMAGE_BASE = 0x00400000

W_GLOBAL = 0x00E85058       # uint16 screen width  (data_bytes + 0x4bf058)
H_GLOBAL = 0x00E8505A       # uint16 screen height (data_bytes + 0x4bf05a)

# PlayLogoScreens: layout+push block before `mov ecx, edi / call 0x845740`
LOGO_HOOK_VA = 0x00642CDB
LOGO_RET_VA  = 0x00642D01   # mov ecx, edi
LOGO_LEN     = LOGO_RET_VA - LOGO_HOOK_VA   # 38 bytes

# PlayPreIntroVideo: layout+push block before `mov ecx, esi / call 0x8456C0`
PRE_HOOK_VA = 0x0064286F
PRE_RET_VA  = 0x006428A2    # mov ecx, esi
PRE_LEN     = PRE_RET_VA - PRE_HOOK_VA      # 51 bytes

# .text tail zero-pad, 16-aligned, after the windowed_screen_capture cave
# (0x8A8B80 + 21 = 0x8A8B95); the pad runs to 0x8A9000.
# Pad layout: saves_in_documents 0x8A8970..0x8A8AAE, widescreen_loading
# 0x8A8AB0..0x8A8B72, windowed_screen_capture 0x8A8B80..0x8A8B95, us, then
# widescreen_cinema_bars @ 0x8A8C50.
CAVE_VA   = 0x008A8BA0
CAVE_END  = 0x008A8C50

def file_off(va: int) -> int:
    return va - IMAGE_BASE

# --- cave 1: PlayLogoScreens ---
# Entry state at 0x642CDB: ebx = fade byte (0..255), esi = fade-phase counter,
# edi = Bink object, [esp+0x3c] = colour local (0xFFFFFF | fade<<24).
# eax/ecx/edx are dead. The cave replicates the original push sequence exactly,
# substituting cw for w and xoff-1 for the original x = -1.
logo_code = f"""
    xor   edx, edx
    mov   dx, word ptr [{H_GLOBAL:#x}]   ; edx = h
    lea   eax, [edx*4]
    push  edx
    xor   edx, edx
    mov   ecx, 3
    div   ecx                            ; eax = h*4/3
    pop   edx
    mov   ecx, dword ptr [{W_GLOBAL:#x}]
    and   ecx, 0xFFFF                    ; ecx = w
    cmp   eax, ecx
    jbe   logo_cw_ok
    mov   eax, ecx
logo_cw_ok:                              ; eax = cw = min(w, h*4/3)
    sub   ecx, eax
    shr   ecx, 1                         ; ecx = xoff
    dec   ecx                            ; ecx = xoff - 1 (original x was -1)
    push  0                              ; arg7 filter flag
    push  0                              ; arg6 z-write flag
    mov   byte ptr [esp+0x47], bl        ; fade alpha into colour local (as original)
    push  edx                            ; arg5 dest h
    push  eax                            ; arg4 dest w = cw
    push  -1                             ; arg3 y
    push  ecx                            ; arg2 x = xoff - 1
    mov   ecx, dword ptr [esp+0x54]      ; colour local (orig [esp+0x44] at 2 pushes)
    push  ecx                            ; arg1 colour
    jmp   {LOGO_RET_VA:#x}
"""

# --- cave 2: PlayPreIntroVideo ---
# Entry state at 0x64286F: ebx = 0, esi = Bink object, [esp+0x10] = colour local.
# eax/ecx/edx are dead. Original x = 0, colour = 0xFFFFFFFF written byte-wise.
pre_code = f"""
    xor   eax, eax
    mov   ax, word ptr [{H_GLOBAL:#x}]   ; eax = h
    push  eax
    shl   eax, 2
    xor   edx, edx
    mov   ecx, 3
    div   ecx                            ; eax = h*4/3
    pop   edx                            ; edx = h
    mov   ecx, dword ptr [{W_GLOBAL:#x}]
    and   ecx, 0xFFFF                    ; ecx = w
    cmp   eax, ecx
    jbe   pre_cw_ok
    mov   eax, ecx
pre_cw_ok:                               ; eax = cw = min(w, h*4/3)
    sub   ecx, eax
    shr   ecx, 1                         ; ecx = xoff (original x was 0)
    push  ebx                            ; arg7 filter flag = 0
    push  ebx                            ; arg6 z-write flag = 0
    mov   byte ptr [esp+0x18], 0xFF      ; colour local = white, full alpha
    mov   byte ptr [esp+0x19], 0xFF
    mov   byte ptr [esp+0x1a], 0xFF
    mov   byte ptr [esp+0x1b], 0xFF
    push  edx                            ; arg5 dest h
    push  eax                            ; arg4 dest w = cw
    push  ebx                            ; arg3 y = 0
    push  ecx                            ; arg2 x = xoff
    mov   edx, dword ptr [esp+0x28]      ; colour local (orig [esp+0x24] at 5 pushes)
    push  edx                            ; arg1 colour
    jmp   {PRE_RET_VA:#x}
"""

ks = Ks(KS_ARCH_X86, KS_MODE_32)
ks.syntax = KS_OPT_SYNTAX_INTEL

def assemble(src: str, addr: int) -> bytes:
    # keystone treats ';' as a statement separator, not a comment -- strip them
    cleaned = "\n".join(line.split(";")[0].rstrip() for line in src.splitlines())
    out, _ = ks.asm(cleaned, addr)
    return bytes(out)

logo_cave_va = CAVE_VA
logo_cave = assemble(logo_code, logo_cave_va)
pre_cave_va = (logo_cave_va + len(logo_cave) + 15) & ~15
pre_cave = assemble(pre_code, pre_cave_va)
assert pre_cave_va + len(pre_cave) <= CAVE_END, "caves exceed zero-pad budget"

def hook(hook_va: int, cave_va: int, block_len: int) -> bytes:
    rel = cave_va - (hook_va + 5)
    return bytes([0xE9]) + rel.to_bytes(4, "little", signed=True) + b"\x90" * (block_len - 5)

logo_hook = hook(LOGO_HOOK_VA, logo_cave_va, LOGO_LEN)
pre_hook = hook(PRE_HOOK_VA, pre_cave_va, PRE_LEN)

# Original bytes (decomp runblack.reassemble.0759, verified against a vanilla exe)
logo_expect = bytes.fromhex(
    "a1 58 50 e8 00 33 d2 66 8b 15 5a 50 e8 00 6a 00 6a 00 25 ff"
    "ff 00 00 88 5c 24 47 8b 4c 24 44 52 50 6a ff 6a ff 51"
    .replace(" ", "")
)
pre_expect = bytes.fromhex(
    "8b 0d 58 50 e8 00 33 c0 66 a1 5a 50 e8 00 53 53 81 e1 ff ff"
    "00 00 c6 44 24 18 ff c6 44 24 19 ff c6 44 24 1a ff 50 51 53"
    "c6 44 24 27 ff 8b 54 24 24 53 52"
    .replace(" ", "")
)
assert len(logo_expect) == LOGO_LEN, len(logo_expect)
assert len(pre_expect) == PRE_LEN, len(pre_expect)

def hx_wrapped(b: bytes, per_line: int = 24) -> str:
    lines = []
    for i in range(0, len(b), per_line):
        lines.append("  " + " ".join(f"{x:02X}" for x in b[i:i + per_line]))
    return "\n".join(lines)

toml = f"""name = "widescreen_logos"
title = "Widescreen Intro Logos"
summary = "Keep the intro logo screens (logo.bik / pre_intro.bik) 4:3 on widescreen displays."
doc = "docs/widescreen_logos.md"

# The intro logo screens -- PlayLogoScreens @ 0x642950 (logo.bik, the Lionhead/EA
# logo stills) and PlayPreIntroVideo @ 0x6426F0 (pre_intro.bik) -- pass the raw
# screen size as the Bink destination rect, so 4:3 content stretches on
# widescreen. We redirect each call-site layout block into a cave that uses
# cw = min(w, h*4/3) as the dest width and centres with x += (w-cw)/2.
# 4:3 and 5:4 displays are bit-for-bit unaffected. The shared Bink blitter
# (0x845740) is left alone: the in-game movie player computes its own rects.
#
# Bytes are produced by tool/widescreen_logos_asm.py (keystone). The caves sit
# in the .text tail zero-pad after the windowed_screen_capture cave; the
# patches are independent and can be applied in any order.

# 1) Cave for PlayLogoScreens ({len(logo_cave)} bytes at vaddr 0x{logo_cave_va:X}).
[[op]]
kind = "replace"
offset = 0x{file_off(logo_cave_va):X}
note = "4:3 letterboxed dest rect for the logo.bik stills"
bytes = '''
{hx_wrapped(logo_cave)}
'''
expect = '''
{hx_wrapped(bytes(len(logo_cave)))}
'''

# 2) Cave for PlayPreIntroVideo ({len(pre_cave)} bytes at vaddr 0x{pre_cave_va:X}).
[[op]]
kind = "replace"
offset = 0x{file_off(pre_cave_va):X}
note = "4:3 letterboxed dest rect for pre_intro.bik"
bytes = '''
{hx_wrapped(pre_cave)}
'''
expect = '''
{hx_wrapped(bytes(len(pre_cave)))}
'''

# 3) Hook in PlayLogoScreens: redirect 0x642CDB..0x642D00 into cave 1.
[[op]]
kind = "replace"
offset = 0x{file_off(LOGO_HOOK_VA):X}
note = "redirect logo.bik dest-rect block into the cave"
bytes = '''
{hx_wrapped(logo_hook)}
'''
expect = '''
{hx_wrapped(logo_expect)}
'''

# 4) Hook in PlayPreIntroVideo: redirect 0x64286F..0x6428A1 into cave 2.
[[op]]
kind = "replace"
offset = 0x{file_off(PRE_HOOK_VA):X}
note = "redirect pre_intro.bik dest-rect block into the cave"
bytes = '''
{hx_wrapped(pre_hook)}
'''
expect = '''
{hx_wrapped(pre_expect)}
'''
"""

import os
out_path = os.path.join(os.path.dirname(__file__), "..", "patches", "widescreen_logos.toml")
with open(out_path, "w", newline="\n") as f:
    f.write(toml)

print(f"logo cave  : {logo_cave_va:#010x} (file {file_off(logo_cave_va):#x}), {len(logo_cave)} bytes")
print(f"pre cave   : {pre_cave_va:#010x} (file {file_off(pre_cave_va):#x}), {len(pre_cave)} bytes")
print(f"logo hook  : {LOGO_HOOK_VA:#010x} (file {file_off(LOGO_HOOK_VA):#x}), {LOGO_LEN} bytes")
print(f"pre hook   : {PRE_HOOK_VA:#010x} (file {file_off(PRE_HOOK_VA):#x}), {PRE_LEN} bytes")
print(f"pad budget : {CAVE_END - CAVE_VA} bytes, used {pre_cave_va + len(pre_cave) - CAVE_VA}")
print(f"wrote      : {os.path.normpath(out_path)}")
