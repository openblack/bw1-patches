# Landscape Draw Distance

Black & White morphs it's landscape at far distances, this is a simple technique called level of detail.
It's a way for the game to display as much as possible as fast as possible by skipping out on details
it deems too far away to matter. On older hardware it adjusts it's view distance automatically to be
lower then that of newer hardware. It does so by checking if:

* The detail level is set to `Maximum Detail.`
* Processor's family id is exactly `15` (__asm { cpuid })

## Procedure

The problem is the processor check which returns falsely on newer hardware even though the CPUs are more
than capable of handling it.

```
.text:00804E60 sub_804E60 proc near
.text:00804E60 		mov     al, bGoodCPU
.text:00804E65      test    al, al
.text:00804E67      jz      short loc_804E81
.text:00804E69      cmp     Detail_Index, 4
.text:00804E70      jnz     short loc_804E81
.text:00804E72      mov     eax, bUnusedGraphicsOptionAlwaysOne
.text:00804E77      test    eax, eax
.text:00804E79      jz      short loc_804E81
.text:00804E7B      mov     eax, 1
.text:00804E80      retn
.text:00804E81
.text:00804E81 loc_804E81:
.text:00804E81 		xor     eax, eax
.text:00804E83      retn
```

Can be represented as:

```
BOOL sub_804E60()
{
  return bGoodCPU && DetailIdx == 4 && bUnusedGraphicsOptionAlwaysOne;
}
```

## Patch

We can ignore the processor check by nopping out the following instructions: `.text:00804E60` to `.text:00804E68`
and `.text:00804E72` to `.text:00804E7A` this turns our function into the following:

```
BOOL sub_804E60()
{
	return DetailIdx == 4
}
```

If we wanted to we could further increase drawing distance by editing values set that xref `sub_804E60`.