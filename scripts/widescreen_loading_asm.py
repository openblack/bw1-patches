#!/usr/bin/env python3
"""Assemble the `widescreen_loading` code cave + hook for Black & White.

The tip-of-the-day loading screen (drawn by the local helper at vaddr 0x005F3DC0,
called from RenderLoadingFrame @ 0x005F4E40) computes its whole layout in a single
block at 0x005F3E5C..0x005F3F18:

    [esp+0x44] = 0.125 * w    text wrap left          (x)
    [esp+0x50] = 0.875 * w    text wrap right         (x)
    [esp+0x3c] = 0.600 * w    tip text band top       (y!)
    [esp+0x18] = 0.950 * h    band bottom / version   (y)
    [esp+0x4c] = 0.180 * w    tip image left          (x)
    [esp+0x48] = 0.050 * h    tip image top           (y)
    [esp+0x40] = 0.640 * w    tip image width
    [esp+0x2c] = 0.640 * h    tip image height
    eax        = fade * 255   overlay alpha

The layout was authored for 4:3 displays: the image is 0.64w x 0.64h (only 4:3 when
w = 4/3 h) and, worse, the text band's *vertical* position is a fraction of the
*width* (0.6w = 0.8h on 4:3, but 1.07h on 16:9 -> drawn below the screen, which is
why the tip text disappears and the bottom band breaks up on widescreen).

Fix: replace the block with a jump into a code cave that computes the same eight
values from an effective 4:3 width cw = min(w, h*4/3) and re-centres the
x-coordinates with xoff = (w - cw) / 2. On 4:3 / 5:4 displays cw == w and xoff == 0,
so the layout is unchanged. The full-screen blurred background and bottom-fade keep
using the real w/h (they are drawn from esi/edi later and genuinely want to fill
the screen), and the gray text band still spans the full width.

All virtual addresses come from bw1-decomp (win1.41 / unprotected layout).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32, KS_OPT_SYNTAX_INTEL

IMAGE_BASE = 0x00400000

# --- fixed virtual addresses (from bw1-decomp) ---
HOOK_VA  = 0x005F3E5C       # start of the layout block inside the tip-screen drawer
RET_VA   = 0x005F3F19       # first instruction after the block (push 0 / SetCursor)
BLOCK_LEN = RET_VA - HOOK_VA  # 0xBD = 189 bytes
CAVE_VA  = 0x008A8AB0       # .text trailing zero-pad, after saves_in_documents' 318 bytes

W_GLOBAL = 0x00E85058       # uint16 screen width  (data_bytes + 0x4bf058)
H_GLOBAL = 0x00E8505A       # uint16 screen height (data_bytes + 0x4bf05a)

# .rdata float constants the original block multiplies by (reused as-is)
C_0125 = 0x008AB620         # 0.125f
C_0875 = 0x008AB618         # 0.875f
C_06   = 0x008C7BDC         # 0.6f
C_095  = 0x008CF000         # 0.95f
C_018  = 0x008C49E8         # 0.18f
C_005  = 0x008AC3F4         # 0.05f
C_064  = 0x008CA28C         # 0.64f
C_255  = 0x008AB270         # 255.0f

def file_off(va: int) -> int:
    return va - IMAGE_BASE

# --- the cave routine ---
# Entry state (same as original block at 0x005F3E5C): ebx/ebp/esi already pushed,
# x87 st0 = fade in [0,1]. The original block pushes edi itself; we replicate that.
# Exit state expected by 0x005F3F19: esi = w, edi = h, eax = int(fade*255),
# the eight stack slots filled, FPU empty. ecx/edx are dead (caller reloads both).
code = f"""
    mov  esi, dword ptr [{W_GLOBAL:#x}]
    and  esi, 0xFFFF                  ; esi = screen width
    push edi
    xor  edi, edi
    mov  di, word ptr [{H_GLOBAL:#x}] ; edi = screen height
    mov  [esp+0x1c], esi              ; original block stores w / h ints too
    mov  [esp+0x34], edi

    ; cw = min(w, h*4/3), xoff = (w - cw) / 2
    lea  eax, [edi*4]
    xor  edx, edx
    mov  ecx, 3
    div  ecx                          ; eax = h*4/3
    cmp  eax, esi
    jbe  cw_done
    mov  eax, esi
cw_done:
    mov  ecx, esi
    sub  ecx, eax
    shr  ecx, 1                       ; ecx = xoff

    ; width-derived values, from cw instead of w (st0=fade)
    mov  [esp+0x2c], eax
    fild dword ptr [esp+0x2c]         ; st0=cw, st1=fade
    fld  st(0)
    fmul dword ptr [{C_0125:#x}]
    fistp dword ptr [esp+0x44]        ; text wrap left  = 0.125*cw + xoff
    add  [esp+0x44], ecx
    fld  st(0)
    fmul dword ptr [{C_0875:#x}]
    fistp dword ptr [esp+0x50]        ; text wrap right = 0.875*cw + xoff
    add  [esp+0x50], ecx
    fld  st(0)
    fmul dword ptr [{C_06:#x}]
    fistp dword ptr [esp+0x3c]        ; band top (y)    = 0.6*cw  (= 0.8*h)
    fld  st(0)
    fmul dword ptr [{C_018:#x}]
    fistp dword ptr [esp+0x4c]        ; image left      = 0.18*cw + xoff
    add  [esp+0x4c], ecx
    fmul dword ptr [{C_064:#x}]       ; (consumes cw)
    fistp dword ptr [esp+0x40]        ; image width     = 0.64*cw (4:3 vs height)

    ; height-derived values, unchanged (st0=h, st1=fade)
    mov  [esp+0x2c], edi
    fild dword ptr [esp+0x2c]
    fld  st(0)
    fmul dword ptr [{C_095:#x}]
    fistp dword ptr [esp+0x18]        ; band bottom     = 0.95*h
    fld  st(0)
    fmul dword ptr [{C_005:#x}]
    fistp dword ptr [esp+0x48]        ; image top       = 0.05*h
    fmul dword ptr [{C_064:#x}]       ; (consumes h)
    fistp dword ptr [esp+0x2c]        ; image height    = 0.64*h

    ; eax = int(fade*255), FPU left empty (st0=fade)
    fmul dword ptr [{C_255:#x}]
    push eax
    fistp dword ptr [esp]
    pop  eax
    jmp  {RET_VA:#x}
"""

ks = Ks(KS_ARCH_X86, KS_MODE_32)
ks.syntax = KS_OPT_SYNTAX_INTEL
# keystone treats ';' as a statement separator, not a comment -- strip them
asm_src = "\n".join(line.split(";")[0].rstrip() for line in code.splitlines())
routine, _ = ks.asm(asm_src, CAVE_VA)
routine = bytes(routine)

# hook: jmp cave, then NOP out the rest of the 189-byte block
rel = CAVE_VA - (HOOK_VA + 5)
hook_bytes = bytes([0xE9]) + rel.to_bytes(4, "little") + b"\x90" * (BLOCK_LEN - 5)

# The original 189 bytes of the layout block, used as the `expect` anchor
# (decomp runblack.reassemble.0627, 0x5F3E5C..0x5F3F18; verified against a vanilla exe)
block_expect = bytes.fromhex(
    "8b 35 58 50 e8 00 81 e6 ff ff 00 00 57 89 74 24 1c db 44 24 1c"
    "33 ff 66 8b 3d 5a 50 e8 00 d9 c0 d8 0d 20 b6 8a 00 89 7c 24 34"
    "e8 75 d5 1a 00 d9 c0 d8 0d 18 b6 8a 00 89 44 24 44 e8 64 d5 1a"
    "00 d9 c0 d8 0d dc 7b 8c 00 89 44 24 50 e8 53 d5 1a 00 db 44 24"
    "34 89 44 24 3c d9 54 24 2c d8 0d 00 f0 8c 00 e8 3c d5 1a 00 d9"
    "c0 d8 0d e8 49 8c 00 89 44 24 18 e8 2b d5 1a 00 d9 44 24 2c d8"
    "0d f4 c3 8a 00 89 44 24 4c e8 18 d5 1a 00 d8 0d 8c a2 8c 00 89"
    "44 24 48 e8 09 d5 1a 00 d9 44 24 2c d8 0d 8c a2 8c 00 89 44 24"
    "40 e8 f6 d4 1a 00 d8 0d 70 b2 8a 00 89 44 24 2c e8 e7 d4 1a 00"
    .replace(" ", "")
)
assert len(block_expect) == BLOCK_LEN, len(block_expect)
assert len(hook_bytes) == BLOCK_LEN

CAVE_BUDGET = 0x8A9000 - CAVE_VA   # remaining zero-pad after saves_in_documents
assert len(routine) <= CAVE_BUDGET, f"routine {len(routine)} > budget {CAVE_BUDGET}"

def hx_wrapped(b: bytes, per_line: int = 24) -> str:
    lines = []
    for i in range(0, len(b), per_line):
        lines.append("  " + " ".join(f"{x:02X}" for x in b[i:i + per_line]))
    return "\n".join(lines)

toml = f"""name = "widescreen_loading"
title = "Widescreen Loading Screen"
summary = "Keep the loading-screen tip image 4:3 and the tip text on-screen on widescreen displays."
doc = "docs/widescreen_loading.md"

# The tip-of-the-day loading screen (helper at vaddr 0x005F3DC0, called from
# RenderLoadingFrame @ 0x005F4E40) computes its layout from the screen WIDTH,
# assuming w == 4/3 h: the tip image is 0.64w x 0.64h (stretched on 16:9) and the
# text band's *vertical* position is 0.6w (= 1.07h at 16:9, i.e. below the screen,
# which is why the tip text disappears). We redirect the 189-byte layout block at
# 0x005F3E5C into a cave that uses cw = min(w, h*4/3) and re-centres the
# x-coordinates with (w-cw)/2. 4:3 and 5:4 displays are bit-for-bit unaffected.
#
# Bytes are produced by tool/widescreen_loading_asm.py (keystone). The cave sits in
# the .text tail zero-pad after the saves_in_documents routine.

# 1) The code cave ({len(routine)} bytes at vaddr 0x{CAVE_VA:X}).
[[op]]
kind = "replace"
offset = 0x{file_off(CAVE_VA):X}
note = "4:3 letterboxed layout computation for the tip loading screen"
bytes = '''
{hx_wrapped(routine)}
'''
expect = '''
{hx_wrapped(bytes(len(routine)))}
'''

# 2) Hook: jmp into the cave, NOP the rest of the original layout block.
#    `expect` is the entire original 189-byte block.
[[op]]
kind = "replace"
offset = 0x{file_off(HOOK_VA):X}
note = "redirect layout block 0x5F3E5C..0x5F3F18 into the cave"
bytes = '''
{hx_wrapped(hook_bytes)}
'''
expect = '''
{hx_wrapped(block_expect)}
'''
"""

import os
out_path = os.path.join(os.path.dirname(__file__), "..", "patches", "widescreen_loading.toml")
with open(out_path, "w", newline="\n") as f:
    f.write(toml)

print(f"cave vaddr     : {CAVE_VA:#010x} (file {file_off(CAVE_VA):#x})")
print(f"routine length : {len(routine)} bytes (budget {CAVE_BUDGET})")
print(f"hook vaddr     : {HOOK_VA:#010x} (file {file_off(HOOK_VA):#x}), {BLOCK_LEN} bytes")
print(f"wrote          : {os.path.normpath(out_path)}")
