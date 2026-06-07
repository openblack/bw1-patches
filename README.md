# bw1-patches

A collection of binary patches for **Black & White (2001)** and its expansion pack
**Creature Isle**, plus a small Rust command-line tool, [`bw1patch`](tool), that applies
them to an unprotected game executable and writes out a patched copy.

By default the game ships packed with SecuROM; these patches target the **unprotected**
binary (extracting it is out of scope here).

> Looking for a ready-made build? Check out the unofficial patch on
> [www.bwgame.net](https://www.bwgame.net/downloads/black-white-unofficial-patch-v1-42.1418/).  
> This repository version-tracks the individual changes and now lets you reproduce that build yourself.

## Quick start

You need the [Rust toolchain](https://rustup.rs) (1.86+).

```sh
# Build the tool
cd tool
cargo build --release
# binary is at tool/target/release/bw1patch(.exe)

# Apply every patch to your unprotected executable
./target/release/bw1patch runblack.exe -o runblack-patched.exe
```

That's it — `runblack-patched.exe` now has all the fixes below baked in.

### Common usage

```sh
# List every available patch
bw1patch --list

# Apply everything except one patch
bw1patch runblack.exe -o out.exe --skip skip_tutorial

# Apply only a specific set
bw1patch runblack.exe -o out.exe --only windowed_mode,low_res_textures

# See exactly what would change without writing a file
bw1patch runblack.exe --dry-run

# Patch the file in place (make a backup first!)
bw1patch runblack.exe --in-place

# Give the window/taskbar a Black & White icon (Windows only; see Window Icon below)
bw1patch icon runblack.exe blackwhite.ico -o runblack-iconned.exe
```

Before writing any byte, `bw1patch` verifies that the bytes it is about to overwrite
match what the patch expects. If you point it at the wrong executable (or one that's
already patched) it stops with a clear error instead of corrupting the file. Override
this with `--force` only if you know what you're doing.

## Patch list

| Patch | What it does |
|-------|--------------|
| [Windowed Mode](docs/windowed_mode.md) | Makes the game respect the windowed-mode registry option instead of forcing fullscreen. |
| [Low Resolution Textures](docs/low_res_textures.md) | Stops a signed-int VRAM overflow from forcing low-res textures on cards with 2GB+ VRAM. |
| [Fix Detail Level](docs/fix_detail_level.md) | Defaults to Maximum detail, blocks the broken Custom level, and removes the faulty CPU-speed auto-detect. |
| [Landscape Draw Distance](docs/landscape_draw_distance.md) | Removes the CPU-family check that capped landscape LOD draw distance on modern CPUs. |
| [Addons / Extra Features](docs/extra_features.md) | Fixes the official addons (Football, Villager Banter, MP3) on Windows Vista and newer. |
| [Skip Tutorial](docs/skip_tutorial.md) | Always offers the "skip tutorial" prompt on a new game. |
| [Secret Creatures](docs/secret_creatures.md) | Unlocks every secret creature (Gorilla, Horse, Leopard, Mandrill + the hidden Rhino). |
| [Saves in Documents](docs/saves_in_documents.md) | Redirects all saves/profiles to `Documents\My Games\Black & White` instead of the (often read-only) install folder. |
| [Widescreen Loading Screen](docs/widescreen_loading.md) | Fixes the loading screen on widescreen displays: 4:3 tip image, tip text back on-screen. |
| [Widescreen Intro Logos](docs/widescreen_logos.md) | Stops the intro logo screens (Lionhead/EA stills, pre-intro video) stretching on widescreen displays. |
| [Widescreen Cinematic Bars](docs/widescreen_cinema_bars.md) | Brings back the cinematic letterbox bars in cutscenes on widescreen displays. |
| [Windowed Screen Capture](docs/windowed_screen_capture.md) | Fixes save-game pictures (and snapshots) saving as solid pink in windowed mode by grabbing the back buffer instead of the emulated front buffer. |
| [Remove Menu Bar](docs/remove_menu_bar.md) | Removes the non-functional Options menu bar (Fullscreen, FPS, ...) shown on the windowed-mode window. |
| [Remove Intel Logo](docs/remove_intel_logo.md) | Removes the Intel Pentium 4 badge the 3D logo/intro screen overlays bottom-left on some CPUs (CPUID-gated). |
| [Max Resolution Fix](docs/max_resolution_fix.md) † | Allows resolutions above 2048px (1440p/4K). |

† Not an executable patch and **not applied by `bw1patch`** — it's a separate runtime proxy DLL, documented here for completeness.