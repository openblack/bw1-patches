# Fix SWAP_CREATURE Shrinking

> Machine-readable definition: [`patches/fix_swap_creature_shrink.toml`](../patches/fix_swap_creature_shrink.toml) — apply it with the [`bw1patch`](../tool) tool.

The CHL scripting function **`SWAP_CREATURE`** shrinks the creature a little every time it
runs. Spamming swap (e.g. in a challenge that swaps repeatedly) shrinks the creature fast.
The cause is a rounding bug — sizes are rescaled by truncation, which has a constant
downward bias.

## Call chain

| step | vaddr | role |
|------|-------|------|
| `SWAP_CREATURE` handler | `GScript::SwapCreature` `0x006F48A0` | resolves the two script creatures, calls the swap worker |
| swap worker | `0x0047BEE0` | swaps names / mind / beliefs / size, and **rescales the dimension array** |
| size getter | `0x004F8CA0` | returns `baseTable[i] * creature[+0x37C]` (`+0x37C` = float scale) |

The creature's float scale itself is copied losslessly. The damage is in the worker's loop
that rescales the creature's **integer** dimension array (`creature[+0x164] + 0x17D3C …
0x17DE0`, 41 entries of 4 bytes).

## The bug

For each dimension the loop computes `dim * ratio`, where `ratio = sizeB / sizeA` (`1.0`
when `sizeA == 0`), and converts the result back to an integer with the MSVC `__ftol`
helper — which **truncates toward zero**:

```nasm
.text:0047C399  fild  qword ptr [esp+1Ch]   ; (double) dimension
.text:0047C39D  fmul  st, st(1)             ; * ratio  (sizeB/sizeA)
.text:0047C39F  call  __ftol                ; (int) TRUNCATE toward zero   <-- bug
.text:0047C3A4  fstp  st(0)                  ; pop the ratio
 ...
.text:0047C3B4  mov   [edi], eax             ; store the truncated dimension
```

Truncation is not invertible: `trunc(trunc(x·r) / r) ≤ x`. So even swapping back and forth
with reciprocal ratios never restores the original value — every conversion discards the
fractional part and the integer dimensions only ever lose ground. Repeated swaps ratchet
them down and the creature visibly shrinks. (Round-to-nearest has zero mean bias and would
not drift.)

## Patch

Convert with the FPU's **round-to-nearest** mode instead of truncating. Replace the
`call __ftol` with an `fistp` that stores the rounded integer straight to the destination
(`edi` already points at the current element, from `lea edi,[esi+eax]` at `0x0047C38A`), and
NOP the now-redundant integer store:

```
.text:0047C39F  E8 5C 50 32 00   call __ftol          ->  DB 1F 90 90 90  fistp dword [edi] ; nop×3
.text:0047C3B4  89 07            mov  [edi], eax       ->  90 90           nop ; nop
```

File offsets `0x7C39F` and `0x7C3B4`. The trailing `fstp st(0)` at `0x0047C3A4` still pops
the ratio, so the x87 stack stays balanced, and `eax` (now unused here) is reloaded at the
top of the next iteration.

This relies on the x87 rounding mode being round-to-nearest, which is the default and is
never changed in this routine (there is no `fldcw`/`fnstcw` here). The original code used
`__ftol` precisely *because* the default mode rounds rather than truncates, so `fistp` gives
exactly the round-to-nearest behaviour we want.

## Related

The same `__ftol` truncation idiom rebuilds this dimension array from `(int)(table[i] *
scale)` in a sibling routine around `0x0047DF20` (used when a creature's size is
(re)initialised, e.g. on load). It is not part of the swap path and is **not** changed by
this patch; applying the same round-to-nearest treatment there would additionally make size
stable across save/reload, but it isn't needed to stop the swap-spam shrink.
