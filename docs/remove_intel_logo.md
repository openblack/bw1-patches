# Remove Intel Logo

> Machine-readable definition: [`patches/remove_intel_logo.toml`](../patches/remove_intel_logo.toml) — apply it with the [`bw1patch`](../tool) tool.

The 3D "particle logo" intro screen sometimes shows a small **Intel logo in the bottom-left
corner**, on top of the normal Lionhead/Black & White logo. It is not part of the logo image
(`data\lhlogo.raw` / `userlogo.raw`); it's a separate overlay, and it only appears on some
machines. This patch removes it.

## What it actually is

The overlay is the **Intel Pentium 4 badge**, textured from `data\Textures\p4.raw`
(material `0x004DBAAC`, created in the texture-init function at `.text:0x0080BBD0` alongside
`p4t.raw`, `smoke.raw` and `s_fire.raw`). The logo screen's per-frame render function
(entry `.text:0x005F89F0`) draws it just before `FinishFrame` as a drop-shadow quad plus the
badge, positioned at roughly `x = 20·(screenW/800)`, `y = screenH − 104·scale` — i.e. hard
against the bottom-left corner.

## Why it's intermittent — a CPUID gate

The badge is drawn only when `byte [0x00E83A30] != 0`. That flag comes from a CPU check:

* `.text:0x008A2610` runs `CPUID(eax=1)`, takes the **base family** `(eax >> 8) & 0x0F`, and
  writes a tier code to `[0x00FAC840]` — `0x200` for base family `0x0F` **with SSE2**
  (Pentium 4 / NetBurst), smaller codes for family 6 (PII/PIII), family 5 (Pentium), etc.
* The dispatcher `.text:0x007ACA00` sets `byte [0x00E83A30] = 1` **only** for the top tier
  (value ≥ `0x200`, i.e. base family `0x0F` + SSE2). Every other CPU leaves it `0`.

So the badge appears only when the host reports CPU **base family `0x0F`** with SSE2. In 2001
that meant a Pentium 4; note that some later non-Intel CPUs also report base family `0x0F`,
while modern Intel Core CPUs report family `6` — which is why whether you see it depends on
the exact machine. It is a CPU gate, not a random chance or a config option.

(The nearby `CPUCheck` / `GenuineIntel` / `AuthenticAMD` code only *logs* a CPU model string
like `"Intel P4 or some variant"`; it does no drawing.)

## Patch

The block that draws the shadow + badge is guarded by a single conditional jump that skips it
when the gate flag is clear. Make that jump unconditional so the badge is never drawn:

```
.text:005F9BBF  0F 84 DD 01 00 00   je  0x005F9DA2     ; skip badge when [0x4BDA30] == 0
            ->  E9 DE 01 00 00 90   jmp 0x005F9DA2 ; + nop   (always skip)
```

This is file offset `0x1F9BBF`. The `jmp` lands on the exact instruction the original `je`
targeted (`0x005F9DA2`, just past the badge block), and a trailing `NOP` keeps the
instruction length identical. The `p4.raw` material is referenced nowhere else, so nothing
but the badge is affected, on any CPU.
