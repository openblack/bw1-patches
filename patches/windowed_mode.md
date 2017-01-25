# Windowed Mode

By default the game reads the registry value for if the game should be in windowed mode,
acts appropriately, but then forces fullscreen mode afterwards making the option useless.

## Procedure

The following lines of assembly are from the procedure from `.text:00642D80` to `.text:006433FE`.
The procedure is compiled from `PCMain.cpp` and is responsible for loading the registry configuration.

```
.text:00643045	push    edi
.text:00643046	mov    	ecx, offset window
.text:0064304B	call	SetWindowStyle
```

These lines of assembly can be translated into `SetWindowStyle(&window, 1);` as `edi` is always `1` in this case.
There is no condition for this call so it will always be called regardless of the user configuration. The following
code exists further up the procedure:

```
if ( RegistryRetrieveULong("Software\Lionhead Studios Ltd\Black & White\BWSetup", "FullScreen", &regDetailIdx) )
	SetWindowStyle(&window, 1);
```

As such we can deduce that the function call is for making the game fullscreen. So in order to get windowed mode to
work properly, we simply remove the secondary non-conditioned call to `SetWindowStyle(&window, 1);`.

## Patch

We only need to remove 3 instructions so we NOP out the following addresses: `.text:00643045` to `.text:0064304F`
This translates to the exe's binary position of `0x243045` to `0x24304F` which we fill with `0x90`.

After these changes the game's windowed function works as intended and respects the registry option.