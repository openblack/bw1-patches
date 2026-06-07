//! Inject an `.ico` file into `runblack.exe` as the "AppIcon" group icon.
//!
//! Black & White's main window class (`RegisterWindowClass` at `.text:0x007DBA00`) already
//! does `WNDCLASS.hIcon = LoadIconA(hInstance, "AppIcon")`, but the shipped executable
//! contains **no** icon resources, so that call returns NULL and the window / taskbar /
//! alt-tab fall back to the generic Windows application icon.
//!
//! Adding a `RT_GROUP_ICON` resource named `APPICON` (resource names are case-insensitive,
//! so it matches the `"AppIcon"` the game asks for) plus its `RT_ICON` images makes the
//! *existing* code load it — no executable byte patch is required, and Explorer also shows
//! it as the file icon. See `docs/window_icon.md`.
//!
//! This rewrites the PE resource section and changes the file size, so it is **not** a
//! `bw1patch` byte patch. The injection itself uses the Win32 `BeginUpdateResource` /
//! `UpdateResource` / `EndUpdateResource` APIs and is therefore only available on Windows;
//! `.ico` parsing and group-icon building are platform-independent.

use std::path::Path;

/// One icon image from a `.ico` file (an `ICONDIRENTRY` plus its image bytes).
pub struct IconImage {
    /// Width in pixels (`.ico` stores 0 to mean 256).
    pub w: u8,
    /// Height in pixels (`.ico` stores 0 to mean 256).
    pub h: u8,
    /// Number of colors in the palette (0 for >= 256 / true-color).
    pub colors: u8,
    /// Color planes (may be 0; we fall back to the image's `BITMAPINFOHEADER`).
    pub planes: u16,
    /// Bits per pixel (may be 0; same fallback as `planes`).
    pub bits: u16,
    /// The raw image payload (a DIB or, for Vista+ icons, a PNG).
    pub data: Vec<u8>,
}

fn u16le(b: &[u8], off: usize) -> u16 {
    u16::from_le_bytes([b[off], b[off + 1]])
}

fn u32le(b: &[u8], off: usize) -> u32 {
    u32::from_le_bytes([b[off], b[off + 1], b[off + 2], b[off + 3]])
}

/// Parse a `.ico` file into its list of images.
pub fn parse_ico(data: &[u8]) -> Result<Vec<IconImage>, String> {
    // ICONDIR: reserved(WORD)=0, type(WORD)=1, count(WORD).
    if data.len() < 6 {
        return Err("not a valid .ico file (shorter than its ICONDIR header)".into());
    }
    let reserved = u16le(data, 0);
    let rtype = u16le(data, 2);
    let count = u16le(data, 4) as usize;
    if reserved != 0 || rtype != 1 || count == 0 {
        return Err("not a valid .ico file (bad ICONDIR header)".into());
    }

    let mut images = Vec::with_capacity(count);
    let mut off = 6;
    for _ in 0..count {
        // ICONDIRENTRY (16 bytes): bWidth, bHeight, bColorCount, bReserved,
        // wPlanes, wBitCount, dwBytesInRes, dwImageOffset.
        if off + 16 > data.len() {
            return Err("truncated .ico: directory entry runs past end of file".into());
        }
        let w = data[off];
        let h = data[off + 1];
        let colors = data[off + 2];
        let planes = u16le(data, off + 4);
        let bits = u16le(data, off + 6);
        let size = u32le(data, off + 8) as usize;
        let imgoff = u32le(data, off + 12) as usize;
        off += 16;

        let end = imgoff
            .checked_add(size)
            .ok_or("invalid .ico: image extent overflows")?;
        if end > data.len() {
            return Err("truncated .ico: image data runs past end of file".into());
        }
        images.push(IconImage {
            w,
            h,
            colors,
            planes,
            bits,
            data: data[imgoff..end].to_vec(),
        });
    }
    Ok(images)
}

/// Build the `GRPICONDIR` + `GRPICONDIRENTRY[]` blob (the `RT_GROUP_ICON` resource) that
/// ties the `RT_ICON` images together, numbering them `first_id`, `first_id + 1`, ….
pub fn build_group_icon(images: &[IconImage], first_id: u16) -> Vec<u8> {
    // GRPICONDIR: reserved=0, type=1 (icon), count.
    let mut out = Vec::with_capacity(6 + images.len() * 14);
    out.extend_from_slice(&0u16.to_le_bytes());
    out.extend_from_slice(&1u16.to_le_bytes());
    out.extend_from_slice(&(images.len() as u16).to_le_bytes());

    for (i, im) in images.iter().enumerate() {
        let mut planes = im.planes;
        let mut bits = im.bits;
        // If the directory entry didn't carry planes/bitcount, read them from the image's
        // BITMAPINFOHEADER (biPlanes @ +12, biBitCount @ +14). PNG-compressed icons
        // (Vista+) keep whatever the entry stated.
        let is_png = im.data.len() >= 4 && im.data[..4] == *b"\x89PNG";
        if (planes == 0 || bits == 0) && !is_png && im.data.len() >= 16 {
            if planes == 0 {
                planes = u16le(&im.data, 12);
            }
            if bits == 0 {
                bits = u16le(&im.data, 14);
            }
        }
        // GRPICONDIRENTRY (14 bytes): note the id is a WORD here, where the file's
        // ICONDIRENTRY had a DWORD image offset instead.
        out.push(im.w);
        out.push(im.h);
        out.push(im.colors);
        out.push(0); // reserved
        out.extend_from_slice(&planes.to_le_bytes());
        out.extend_from_slice(&bits.to_le_bytes());
        out.extend_from_slice(&(im.data.len() as u32).to_le_bytes());
        out.extend_from_slice(&(first_id + i as u16).to_le_bytes());
    }
    out
}

/// Render the icon sizes (e.g. `16x16@32, 32x32@32`) for human-readable reporting.
pub fn describe(images: &[IconImage]) -> String {
    images
        .iter()
        .map(|im| {
            let w = if im.w == 0 { 256 } else { im.w as u32 };
            let h = if im.h == 0 { 256 } else { im.h as u32 };
            format!("{w}x{h}@{}", im.bits)
        })
        .collect::<Vec<_>>()
        .join(", ")
}

const RT_ICON: u16 = 3;
const RT_GROUP_ICON: u16 = 14;

/// Inject `images` into `exe_path` as `RT_ICON` resources plus one `RT_GROUP_ICON` named
/// `name`, using the Win32 resource-update APIs. Existing resources are preserved.
#[cfg(windows)]
pub fn inject(
    exe_path: &Path,
    images: &[IconImage],
    name: &str,
    lang: u16,
    first_id: u16,
) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::GetLastError;
    use windows_sys::Win32::System::LibraryLoader::{
        BeginUpdateResourceW, EndUpdateResourceW, UpdateResourceW,
    };

    let wpath: Vec<u16> = exe_path
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let wname: Vec<u16> = name.encode_utf16().chain(std::iter::once(0)).collect();
    let group = build_group_icon(images, first_id);

    // SAFETY: every pointer passed below points into a buffer that outlives the call, and
    // the integer "names" are MAKEINTRESOURCE-style values (a small int cast to a pointer).
    unsafe {
        let h = BeginUpdateResourceW(wpath.as_ptr(), 0);
        if h.is_null() {
            return Err(format!(
                "BeginUpdateResourceW failed (error {}) — is {exe_path:?} a writable PE file?",
                GetLastError()
            ));
        }

        // Each image becomes one RT_ICON with a numeric id (MAKEINTRESOURCE).
        for (i, im) in images.iter().enumerate() {
            let id = first_id + i as u16;
            let ok = UpdateResourceW(
                h,
                RT_ICON as usize as *const u16,
                id as usize as *const u16,
                lang,
                im.data.as_ptr() as *const core::ffi::c_void,
                im.data.len() as u32,
            );
            if ok == 0 {
                let err = GetLastError();
                EndUpdateResourceW(h, 1); // discard
                return Err(format!("UpdateResourceW(RT_ICON #{id}) failed (error {err})"));
            }
        }

        // A single RT_GROUP_ICON, named (a wide-string pointer rather than an int id).
        let ok = UpdateResourceW(
            h,
            RT_GROUP_ICON as usize as *const u16,
            wname.as_ptr(),
            lang,
            group.as_ptr() as *const core::ffi::c_void,
            group.len() as u32,
        );
        if ok == 0 {
            let err = GetLastError();
            EndUpdateResourceW(h, 1); // discard
            return Err(format!(
                "UpdateResourceW(RT_GROUP_ICON \"{name}\") failed (error {err})"
            ));
        }

        if EndUpdateResourceW(h, 0) == 0 {
            return Err(format!("EndUpdateResourceW failed (error {})", GetLastError()));
        }
    }
    Ok(())
}

#[cfg(not(windows))]
pub fn inject(
    _exe_path: &Path,
    _images: &[IconImage],
    _name: &str,
    _lang: u16,
    _first_id: u16,
) -> Result<(), String> {
    Err("icon injection uses the Win32 UpdateResource APIs and is only available on Windows".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a minimal one-image `.ico` (a 2x2 32-bit DIB) for round-trip testing.
    fn sample_ico() -> Vec<u8> {
        let img: Vec<u8> = {
            // 40-byte BITMAPINFOHEADER with biPlanes=1, biBitCount=32, then a tiny payload.
            let mut v = vec![0u8; 40];
            v[0] = 40; // biSize
            v[12] = 1; // biPlanes (low byte)
            v[14] = 32; // biBitCount (low byte)
            v.extend_from_slice(&[0xAA; 32]); // XOR + AND masks (contents irrelevant)
            v
        };
        let mut ico = Vec::new();
        ico.extend_from_slice(&0u16.to_le_bytes()); // reserved
        ico.extend_from_slice(&1u16.to_le_bytes()); // type = icon
        ico.extend_from_slice(&1u16.to_le_bytes()); // count
                                                     // ICONDIRENTRY
        ico.push(2); // w
        ico.push(2); // h
        ico.push(0); // colors
        ico.push(0); // reserved
        ico.extend_from_slice(&0u16.to_le_bytes()); // planes (0 -> fallback to BIH)
        ico.extend_from_slice(&0u16.to_le_bytes()); // bits   (0 -> fallback to BIH)
        ico.extend_from_slice(&(img.len() as u32).to_le_bytes());
        ico.extend_from_slice(&(22u32).to_le_bytes()); // image offset (6 + 16)
        ico.extend_from_slice(&img);
        ico
    }

    #[test]
    fn parse_round_trip() {
        let images = parse_ico(&sample_ico()).unwrap();
        assert_eq!(images.len(), 1);
        assert_eq!(images[0].w, 2);
        assert_eq!(images[0].data.len(), 72);
    }

    #[test]
    fn rejects_bad_header() {
        assert!(parse_ico(&[0, 0, 0, 0, 0, 0]).is_err());
        assert!(parse_ico(&[]).is_err());
    }

    #[test]
    fn rejects_truncated_image() {
        let mut ico = sample_ico();
        ico.truncate(ico.len() - 10); // chop off part of the image payload
        assert!(parse_ico(&ico).is_err());
    }

    #[test]
    fn group_icon_layout_and_plane_fallback() {
        let images = parse_ico(&sample_ico()).unwrap();
        let grp = build_group_icon(&images, 1);
        // GRPICONDIR (6) + one GRPICONDIRENTRY (14).
        assert_eq!(grp.len(), 20);
        assert_eq!(u16le(&grp, 0), 0); // reserved
        assert_eq!(u16le(&grp, 2), 1); // type = icon
        assert_eq!(u16le(&grp, 4), 1); // count
                                       // entry: planes/bits were 0 in the dir, filled from the BITMAPINFOHEADER.
        assert_eq!(u16le(&grp, 6 + 4), 1); // wPlanes
        assert_eq!(u16le(&grp, 6 + 6), 32); // wBitCount
        assert_eq!(u32le(&grp, 6 + 8), images[0].data.len() as u32); // dwBytesInRes
        assert_eq!(u16le(&grp, 6 + 12), 1); // id == first_id
    }
}
