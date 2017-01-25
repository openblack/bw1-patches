# Low Resolution Textures

On modern machines all textures in the game appear at a much lower resolution then originally intended.
This is due to an overflow in the integer used to store how much VRAM is avaliable on the client.
The game detects a high amount of VRAM as too little VRAM due to the overflow and forces low resolution
textures.

## Procedure

The following lines of assembly are from the procedure from `.text:00642D80` to `.text:006433FE`.
The procedure is compiled from `PCMain.cpp` and is responsible for loading the registry configuration.

```
.text:0064302E	mov     ecx, offset window
.text:00643033	call    GetTextureAvaliable
.text:00643038	cmp     eax, 13000000
.text:0064303D	jge     short loc_643045
.text:0064303F	mov     UseLowResTexture, edi
.text:00643045
.text:00643045 loc_643045:
```

This can be translated to the following C style code:

```
if ( GetTextureAvaliable() < 13000000 )
    UseLowResTexture = 1;
```

This is the equivalent of checking for under 13MB of VRAM. However the return value of `GetTextureAvaliable()`
is a signed integer, if you exceed `2147483647 bytes` or `2GB` the integer will overflow and the statement will
become positive setting the `UseLowResTexture` global to true.

## Patch

We can simply remove the instructions as the default value for the global value `UseLowResTexture` is 0 and most
modern systems using this patch will not want the low resolution textures.

Simply NOP out the following addresses: `.text:0064302E` to `.text:00643045`.

This fixes the issue with clients with over 2GB of VRAM having low resolution textures.