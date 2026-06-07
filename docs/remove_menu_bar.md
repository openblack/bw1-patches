# Remove Menu Bar

> Machine-readable definition: [`patches/remove_menu_bar.toml`](../patches/remove_menu_bar.toml) — apply it with the [`bw1patch`](../tool) tool.

In windowed mode the game window has a menu bar with a single **Options** menu containing
*Fullscreen*, *FPS*, *Dump Bitmap*, *Log Properties* and *Pause*. These are leftover
developer/debug commands and none of them do anything useful in a retail build, so the bar
is just clutter. This patch removes it.

## Where the menu comes from

The main window is created by `RegisterWindowClass` at `.text:0x007DBA00`, which builds a
`WNDCLASSA` on the stack and registers it. The relevant field is `lpszMenuName`
(`WNDCLASS+0x20`):

```nasm
.text:007DBA44  mov  dword ptr [esp+0x2C], offset aAppMenu   ; lpszMenuName = "AppMenu"
.text:007DBA4C  mov  dword ptr [esp+0x30], offset aLionhead  ; lpszClassName = "LIONHEAD"
.text:007DBA54  call RegisterClassA
```

`"AppMenu"` (`0x00C311C8`) names the `APPMENU` menu resource:

```
APPMENU MENU {
  POPUP "&Options" {
    MENUITEM "Fullscreen\tAlt Enter",     ICM_FULLSCREEN
    MENUITEM "FPS\tCtrl Alt F",            ICM_FPS
    MENUITEM "&Dump Bitmap\tCtrl Alt D",   ICM_DUMP_BITMAP
    MENUITEM "&Log Properties\tCtrl Alt L",ICM_LOG_PROPERTIES
    MENUITEM "Pause\tCtrl Alt P",          ICM_PAUSE
  }
}
```

The subsequent `CreateWindowExA` call passes `hMenu = NULL`, so when the window is created
Windows falls back to the **class** menu named by `lpszMenuName`. That is the only thing
that puts the menu bar on screen.

## Patch

Overwrite the `lpszMenuName` pointer with `NULL`, leaving the rest of the `mov` intact:

```
.text:007DBA44  C7 44 24 2C C8 11 C3 00   mov [esp+2C], 0x00C311C8   ; "AppMenu"
            ->  C7 44 24 2C 00 00 00 00   mov [esp+2C], 0x00000000   ; NULL
```

This translates to file offset `0x3DBA44`. With no class menu and `hMenu = NULL` at
creation time, the window has no menu bar.

The `APPMENU` menu resource and the `APPACCEL` accelerators are left untouched; they simply
become unreferenced (the accelerators still post their `WM_COMMAND`s, which the game already
ignores). Fullscreen mode never showed the bar, so it is unaffected.
