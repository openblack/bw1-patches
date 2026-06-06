#!/usr/bin/env python3
"""Assemble the `saves_in_documents` code cave + hook for Black & White.

Emits the exact bytes for two `replace` ops used by bw1patch:
  * cave   @ file 0x4A8970 (vaddr 0x008A8970): strings + routine
  * hook   @ file 0x38EA00 (vaddr 0x0078EA00): 5-byte jmp into the cave

All virtual addresses come from bw1-decomp (1.20/no-cd layout).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32, KS_OPT_SYNTAX_INTEL

# --- fixed virtual addresses (from bw1-decomp) ---
CAVE_VA      = 0x008A8970   # .text trailing zero-pad (1680 bytes free)
HOOK_VA      = 0x0078EA00   # PathCreator innermost ".\%s" builder
SPRINTF_VA   = 0x007C57D2   # CRT sprintf (from the E8 disp at 0x78EA0E: 0x78EA13 + 0x36DBF;
                            # cross-checked at 0x78EA4C: 0x78EA51 + 0x36D81 = same)
IAT_CREATEDIR  = 0x008A9168 # CreateDirectoryA
IAT_LOADLIB    = 0x008A916C # LoadLibraryA
IAT_GETPROC    = 0x008A9170 # GetProcAddress
IAT_GETENV     = 0x008A92C0 # GetEnvironmentVariableA
IMAGE_BASE   = 0x00400000

def file_off(va: int) -> int:
    return va - IMAGE_BASE

# --- string table, laid at the start of the cave (NUL terminated) ---
strings = {
    "s_shell32":  b"shell32.dll\x00",
    "s_proc":     b"SHGetFolderPathA\x00",
    "s_userprof": b"USERPROFILE\x00",
    "fmt_sh":     b"%s\\My Games\\Black & White\x00",
    "fmt_env":    b"%s\\Documents\\My Games\\Black & White\x00",
    "s_2s":       b"%s\\%s\x00",
}
addr = {}
blob = bytearray()
off = 0
for name, data in strings.items():
    addr[name] = CAVE_VA + off
    blob += data
    off += len(data)

ENTRY_VA = CAVE_VA + len(blob)   # routine starts right after the strings

# --- the routine (Intel syntax, LLVM/keystone labels) ---
# entry state: ecx = PathCreator*, [esp+4] = dest buffer, [esp] = ret addr; ret 4
# locals (ebp-relative, stable across pushes):
#   docpath = ebp-0x25C  (0x110 bytes)
#   base    = ebp-0x14C  (0x140 bytes)
code = f"""
    push ebp
    mov  ebp, esp
    push ebx
    push esi
    push edi
    sub  esp, 0x250
    mov  edi, [ecx+4]                 ; edi = save-name ptr (callee-saved across WinAPI/CRT)

    ; --- hmod = LoadLibraryA("shell32.dll") ---
    push {addr['s_shell32']:#x}
    call dword ptr [{IAT_LOADLIB:#x}]
    test eax, eax
    je   use_env
    ; --- pfn = GetProcAddress(hmod, "SHGetFolderPathA") ---
    push {addr['s_proc']:#x}
    push eax
    call dword ptr [{IAT_GETPROC:#x}]
    test eax, eax
    je   use_env
    ; --- SHGetFolderPathA(0, CSIDL_PERSONAL=5, 0, 0, docpath) ---
    lea  edx, [ebp-0x25c]
    push edx
    push 0
    push 0
    push 5
    push 0
    call eax                          ; stdcall: cleans its own 20 bytes
    test eax, eax
    jne  use_env                      ; HRESULT != S_OK -> fallback
    mov  esi, {addr['fmt_sh']:#x}
    jmp  build_base

use_env:
    ; --- GetEnvironmentVariableA("USERPROFILE", docpath, 0x110) ---
    lea  edx, [ebp-0x25c]
    push 0x110
    push edx
    push {addr['s_userprof']:#x}
    call dword ptr [{IAT_GETENV:#x}]
    mov  esi, {addr['fmt_env']:#x}

build_base:
    ; base = sprintf(esi_fmt, docpath)
    lea  eax, [ebp-0x25c]
    push eax
    push esi
    lea  eax, [ebp-0x14c]
    push eax
    call {SPRINTF_VA:#x}
    add  esp, 0xc

    ; --- mkdir -p over base (create each path component) ---
    lea  esi, [ebp-0x14c]             ; esi = base (callee-saved across CreateDirectoryA)
    lea  ebx, [esi+3]                 ; ebx = cursor, skip drive "C:\\"
scan:
    mov  al, [ebx]
    test al, al
    je   mk_final
    cmp  al, 0x5c                     ; '\\'
    jne  scan_inc
    mov  byte ptr [ebx], 0            ; split here
    push 0
    push esi
    call dword ptr [{IAT_CREATEDIR:#x}]
    mov  byte ptr [ebx], 0x5c         ; restore
scan_inc:
    inc  ebx
    jmp  scan
mk_final:
    push 0
    push esi
    call dword ptr [{IAT_CREATEDIR:#x}]

    ; --- dest = sprintf("%s\\%s", base, name) ---
    mov  ecx, [ebp+8]                 ; dest (caller's buffer arg)
    push edi
    lea  eax, [ebp-0x14c]
    push eax
    push {addr['s_2s']:#x}
    push ecx
    call {SPRINTF_VA:#x}
    add  esp, 0x10

    add  esp, 0x250
    pop  edi
    pop  esi
    pop  ebx
    pop  ebp
    ret  4
"""

def strip_comments(src: str) -> str:
    # keystone's Intel parser rejects ';' comments
    return "\n".join(line.split(";", 1)[0].rstrip() for line in src.splitlines())

ks = Ks(KS_ARCH_X86, KS_MODE_32)
ks.syntax = KS_OPT_SYNTAX_INTEL
routine, _ = ks.asm(strip_comments(code), ENTRY_VA, as_bytes=True)

cave_bytes = bytes(blob) + routine

# --- hook: 5-byte jmp at HOOK_VA into the routine entry ---
hook_bytes, _ = ks.asm(f"jmp {ENTRY_VA:#x}", HOOK_VA, as_bytes=True)
assert len(hook_bytes) == 5, hook_bytes.hex()

def hx_wrapped(b: bytes, per_line: int = 24, indent: str = "  ") -> str:
    out = []
    for i in range(0, len(b), per_line):
        out.append(indent + " ".join(f"{x:02X}" for x in b[i : i + per_line]))
    return "\n".join(out)

assert len(cave_bytes) <= 1680, "cave overflows the 1680-byte zero region"
cave_off = file_off(CAVE_VA)
hook_off = file_off(HOOK_VA)
cave_expect = bytes(len(cave_bytes))  # the region is zero-filled in the target

toml = f"""\
name = "saves_in_documents"
title = "Saves in Documents"
summary = "Redirect all save games / profiles to %USERPROFILE%\\\\Documents\\\\My Games\\\\Black & White instead of the (often read-only) install directory."
doc = "docs/saves_in_documents.md"

# Black & White builds every save path relative to the current working directory
# (the install folder) through PathCreator's innermost helper at .text:0x0078EA00:
#     sprintf(dest, ".\\%s", obj->name)        ; ".\\%s" string @ 0x00C285D4
# Every other PathCreator method roots its path in that ".\\" prefix, so redirecting
# this one function moves all saves at once. Bundled game data (Data\\, Scripts\\) is
# loaded by unrelated code and is left untouched.
#
# We append a small routine into the 1680-byte zero pad at the tail of .text
# (file 0x{cave_off:X} / vaddr 0x{CAVE_VA:X}) and jump to it from 0x0078EA00. The routine
# resolves the user's Documents folder via SHGetFolderPathA(CSIDL_PERSONAL), falling
# back to %USERPROFILE%\\Documents, creates Documents\\My Games\\Black & White (mkdir -p),
# and writes "<that>\\<name>" into the caller's buffer. See docs/saves_in_documents.md.
#
# Bytes are produced by tool/saves_in_documents_asm.py (keystone). Cave entry is at
# vaddr 0x{ENTRY_VA:X}; the routine starts after a {len(blob)}-byte string table.

# 1) The code cave. `expect` is the full {len(cave_bytes)}-byte zero pad, so the op aborts
#    unless that region is genuinely empty (right exe, not already patched).
[[op]]
kind = "replace"
offset = 0x{cave_off:X}
note = "PathCreator -> Documents redirect routine ({len(cave_bytes)} bytes: {len(blob)} string + {len(routine)} code)"
bytes = '''
{hx_wrapped(cave_bytes)}
'''
expect = '''
{hx_wrapped(cave_expect)}
'''

# 2) Hook: overwrite the first 5 bytes of 0x0078EA00 with `jmp 0x{ENTRY_VA:X}`.
[[op]]
kind = "replace"
offset = 0x{hook_off:X}
note = "jmp into the redirect routine (was: mov eax,[ecx+4]; mov ecx,...)"
expect = "8B 41 04 8B 4C"
bytes = "{' '.join(f'{x:02X}' for x in hook_bytes)}"
"""

import os
out_path = os.path.join(os.path.dirname(__file__), "..", "patches", "saves_in_documents.toml")
with open(out_path, "w", newline="\n") as f:
    f.write(toml)

print(f"cave entry vaddr  : {ENTRY_VA:#010x}")
print(f"strings length    : {len(blob)} bytes")
print(f"routine length    : {len(routine)} bytes")
print(f"total cave length : {len(cave_bytes)} bytes (budget 1680)")
print(f"hook bytes        : {' '.join(f'{x:02X}' for x in hook_bytes)}")
print(f"wrote             : {os.path.normpath(out_path)}")
