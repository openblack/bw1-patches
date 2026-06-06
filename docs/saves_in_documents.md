# Saves in Documents

> Machine-readable definition: [`patches/saves_in_documents.toml`](../patches/saves_in_documents.toml) — apply it with the [`bw1patch`](../tool) tool.

Black & White writes all of its save data — profiles, saved games, saved creatures,
landscape/script blobs — *relative to the current working directory*, i.e. into the
game's install folder. On a modern Windows install that folder usually lives under
`Program Files`, which is not writable by a standard user, so saving silently fails
or requires running the game as administrator.

This patch redirects every save to
`%USERPROFILE%\Documents\My Games\Black & White\…` while leaving the game's
read-only data (`Data\`, `Scripts\`, …) loading from the install directory exactly
as before.

## Procedure

Save paths are built by the `PathCreator` class. Everything it produces is rooted in
one tiny helper at `.text:0x0078EA00`, which lays down the `".\"` (current-directory)
prefix:

```nasm
.text:0078EA00  mov   eax, [ecx+4]        ; PathCreator->name
.text:0078EA03  mov   ecx, [esp+4]        ; destination buffer
.text:0078EA07  push  eax
.text:0078EA08  push  offset aDotS        ; ".\%s"  @ 0x00C285D4
.text:0078EA0D  push  ecx
.text:0078EA0E  call  sprintf             ; sprintf(dest, ".\%s", name)
.text:0078EA13  add   esp, 0Ch
.text:0078EA16  retn  4
```

The higher-level builders chain off it:

```nasm
.text:0078EA20  ... sprintf(out, "%s\%s", <ea00 result>, PathCreator->[+0x11C])
.text:0078EA60  ... wrapper over 0x0078EA20
```

Because every `PathCreator` method (`GetCurrentGamePath`, `GetSaveGamePicturesPath`,
`CheckAndRecreateSaveGamePaths`, and ~28 call sites across the save subsystems) gets
its root from that `".\"` prefix, **rewriting `0x0078EA00` alone redirects every
save path at once**. Bundled game data is loaded by unrelated code with its own
string literals (e.g. `".\scripts\playgrounds\*.txt"`) and is untouched.

We cannot lengthen the `".\%s"` literal in place, and the destination must be
resolved per user at runtime, so we install a small routine in free space and jump
to it.

## The code cave

The reassembly tooling shows the tail of `.text` is zero padding: the last laid-out
code ends at `.text:0x008A895D`, and there are **1680 zero bytes at file offset
`0x4A8970`** (vaddr `0x008A8970`). That region is mapped read-execute and unused, so
it is a usable code cave. We need ~320 bytes.

## The routine

Assembled by [`scripts/saves_in_documents_asm.py`](../scripts/saves_in_documents_asm.py)
(keystone). It uses only functions the game already imports
(`LoadLibraryA`, `GetProcAddress`, `GetEnvironmentVariableA`, `CreateDirectoryA`)
plus the CRT `sprintf` at `0x007C57D2` (derived from the `E8` displacement of the
original call at `0x0078EA0E`: `0x78EA13 + 0x36DBF`; an earlier revision miscomputed
this as `0x007B57D2` — off by `0x10000` — which jumped mid-instruction into an
unrelated function and crashed the game the first time any save path was built):

```c
// entry: ecx = PathCreator*, [esp+4] = dest buffer, ret 4
char documents[0x110], base[0x140];
HMODULE h = LoadLibraryA("shell32.dll");
FARPROC pfn = h ? GetProcAddress(h, "SHGetFolderPathA") : 0;
if (pfn && pfn(0, CSIDL_PERSONAL /*5*/, 0, 0, documents) == S_OK)
    sprintf(base, "%s\\My Games\\Black & White", documents);
else {                                   // fallback
    GetEnvironmentVariableA("USERPROFILE", documents, sizeof documents);
    sprintf(base, "%s\\Documents\\My Games\\Black & White", documents);
}
mkdir_p(base);                           // CreateDirectoryA at each '\' + the leaf
sprintf(dest, "%s\\%s", base, PathCreator->name);
return;                                  // ret 4
```

`mkdir_p` walks `base`, temporarily NUL-terminating at each backslash (after the
`C:\` drive prefix) and calling `CreateDirectoryA`, so the intermediate
`My Games` and `Black & White` folders are created before the game tries to make its
own save subdirectories. The game's existing `CheckAndRecreateSaveGamePaths` then
creates the per-save leaf directories at the new location automatically.

`SHGetFolderPathA` is resolved dynamically because the game only imports
`ShellExecuteA` from `shell32.dll`; resolving at runtime avoids touching the import
table. `CSIDL_PERSONAL` returns the user's real Documents folder even when it has
been relocated; the `%USERPROFILE%\Documents` path is only a fallback.

## Patch

Two `replace` operations (file offsets):

1. **`0x4A8970`** — the assembled routine (109-byte string table + 209-byte code =
   318 bytes). Its `expect` anchor is the full 318-byte zero pad, so the patch
   aborts if that space is not empty (wrong version, or already patched).
2. **`0x38EA00`** (`.text:0x0078EA00`) — overwrite the first 5 bytes with
   `E9 D8 9F 11 00` = `jmp 0x008A89DD` (the routine entry, just past the string
   table). `expect = 8B 41 04 8B 4C` anchors the original `mov eax,[ecx+4];
   mov ecx,…`.

## Limitations

- Offsets assume the **1.20 / no-CD** layout (md5 `174b1a64e74b2321f3c38ccc8a511e78`).
  `bw1patch` verifies the `expect` anchors and refuses to write to any other build.
- Existing saves in the old install-folder location are **not** migrated; the game
  starts fresh in `Documents`. Copy them across manually if you want to keep them.
- The destination buffers the game passes in are ~256 bytes. A normal save name plus
  the new absolute prefix fits comfortably; an extremely long (≈240-char) Documents
  path is the only theoretical overflow case.
