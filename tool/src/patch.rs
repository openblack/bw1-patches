//! Patch model, TOML loading, and application logic.

use serde::Deserialize;
use std::fmt;
use std::path::Path;

/// Default `target` for patches that don't specify one: the main game executable.
fn default_target() -> String {
    "runblack.exe".to_string()
}

/// A single patch, loaded from one `patches/<name>.toml` file.
#[derive(Debug, Deserialize)]
pub struct Patch {
    /// Stable identifier, also used by `--only` / `--skip`.
    pub name: String,
    /// Human-readable title.
    pub title: String,
    /// One-line description of what the patch does.
    #[serde(default)]
    pub summary: String,
    /// File name of the binary this patch targets, matched case-insensitively against the
    /// input file. Defaults to `runblack.exe` (the original patch set); DLL patches such
    /// as `online_relay` set this to e.g. `LHMultiplayerR.dll` so they only apply to it.
    #[serde(default = "default_target")]
    pub target: String,
    /// Optional path (relative to repo root) to the reverse-engineering writeup.
    #[serde(default)]
    pub doc: Option<String>,
    /// The byte operations that make up this patch.
    #[serde(rename = "op", default)]
    pub ops: Vec<Op>,
}

/// A single byte operation within a patch.
///
/// `offset` is a **file offset** into the executable (not a virtual address).
#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum Op {
    /// Overwrite `len` bytes at `offset` with `fill` (default `0x90`, the x86 NOP).
    Nop {
        offset: u64,
        len: u64,
        /// Fill byte; defaults to `0x90`.
        fill: Option<u8>,
        /// Optional hex bytes expected at `offset` (a prefix anchor, may be shorter
        /// than `len`). Mismatch aborts the run unless `--force` is given.
        expect: Option<String>,
        #[allow(dead_code)]
        note: Option<String>,
    },
    /// Overwrite the bytes at `offset` with `bytes`.
    Replace {
        offset: u64,
        /// Replacement bytes as a hex string, e.g. `"B8 01 00 00 00 C3"`.
        bytes: String,
        /// Optional hex bytes expected at `offset`. When present its length must equal
        /// `bytes`. Mismatch aborts the run unless `--force` is given.
        expect: Option<String>,
        #[allow(dead_code)]
        note: Option<String>,
    },
}

impl Op {
    fn offset(&self) -> u64 {
        match self {
            Op::Nop { offset, .. } => *offset,
            Op::Replace { offset, .. } => *offset,
        }
    }
}

/// What a single op did, for reporting.
pub struct OpReport {
    pub offset: u64,
    pub old: Vec<u8>,
    pub new: Vec<u8>,
}

/// A non-fatal note produced while applying (e.g. a forced mismatch).
pub struct Warning(pub String);

#[derive(Debug)]
pub enum PatchError {
    /// `offset + len` runs past the end of the file.
    OutOfBounds {
        name: String,
        offset: u64,
        len: u64,
        file_len: usize,
    },
    /// The bytes at `offset` did not match the patch's `expect` anchor.
    Mismatch {
        name: String,
        offset: u64,
        expected: Vec<u8>,
        found: Vec<u8>,
    },
    /// A patch file was malformed.
    Spec(String),
}

impl fmt::Display for PatchError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PatchError::OutOfBounds {
                name,
                offset,
                len,
                file_len,
            } => write!(
                f,
                "patch '{name}': op at 0x{offset:X} (+{len} bytes) is past the end of the \
                 file (0x{file_len:X} bytes). Is this the right executable?",
            ),
            PatchError::Mismatch {
                name,
                offset,
                expected,
                found,
            } => write!(
                f,
                "patch '{name}': bytes at 0x{offset:X} are {} but expected {}. The \
                 executable is not the version these patches target (or it is already \
                 patched). Re-run with --force to apply anyway.",
                hex(found),
                hex(expected),
            ),
            PatchError::Spec(msg) => write!(f, "{msg}"),
        }
    }
}

impl std::error::Error for PatchError {}

/// Parse a hex string such as `"B8 01 00 00 00 C3"` (whitespace optional) into bytes.
pub fn parse_hex(s: &str) -> Result<Vec<u8>, String> {
    let cleaned: String = s.chars().filter(|c| !c.is_whitespace()).collect();
    if cleaned.len() % 2 != 0 {
        return Err(format!("hex string has an odd number of digits: {s:?}"));
    }
    (0..cleaned.len())
        .step_by(2)
        .map(|i| {
            u8::from_str_radix(&cleaned[i..i + 2], 16)
                .map_err(|_| format!("invalid hex byte near {:?} in {s:?}", &cleaned[i..i + 2]))
        })
        .collect()
}

/// Render bytes as space-separated uppercase hex, e.g. `B8 01 00`.
pub fn hex(bytes: &[u8]) -> String {
    bytes
        .iter()
        .map(|b| format!("{b:02X}"))
        .collect::<Vec<_>>()
        .join(" ")
}

impl Patch {
    /// Parse a patch from TOML source.
    pub fn from_toml(src: &str) -> Result<Patch, PatchError> {
        toml::from_str(src).map_err(|e| PatchError::Spec(format!("invalid patch TOML: {e}")))
    }

    /// Apply this patch to `buf` in place.
    ///
    /// Returns a report of each op. On a verification or bounds failure nothing in `buf`
    /// is left half-written for that op, but earlier ops in the same patch will already
    /// have been applied — callers that need atomicity should patch a scratch buffer.
    pub fn apply(
        &self,
        buf: &mut [u8],
        force: bool,
        warnings: &mut Vec<Warning>,
    ) -> Result<Vec<OpReport>, PatchError> {
        let mut reports = Vec::new();
        for op in &self.ops {
            let offset = op.offset();
            let off = offset as usize;

            let (new_bytes, fill_len) = match op {
                Op::Nop { len, fill, .. } => {
                    (vec![fill.unwrap_or(0x90); *len as usize], *len as usize)
                }
                Op::Replace { bytes, .. } => {
                    let b = parse_hex(bytes)
                        .map_err(|e| PatchError::Spec(format!("patch '{}': {e}", self.name)))?;
                    let len = b.len();
                    (b, len)
                }
            };

            if off + fill_len > buf.len() {
                return Err(PatchError::OutOfBounds {
                    name: self.name.clone(),
                    offset,
                    len: fill_len as u64,
                    file_len: buf.len(),
                });
            }

            // Verification anchor.
            if let Some(expect_hex) = op_expect(op) {
                let expected = parse_hex(expect_hex)
                    .map_err(|e| PatchError::Spec(format!("patch '{}': {e}", self.name)))?;
                if let Op::Replace { .. } = op {
                    if expected.len() != fill_len {
                        return Err(PatchError::Spec(format!(
                            "patch '{}': replace `expect` is {} bytes but `bytes` is {} bytes",
                            self.name,
                            expected.len(),
                            fill_len
                        )));
                    }
                }
                let found = &buf[off..off + expected.len()];
                if found != expected.as_slice() {
                    if force {
                        warnings.push(Warning(format!(
                            "patch '{}': bytes at 0x{offset:X} are {} not {} — applying anyway (--force)",
                            self.name,
                            hex(found),
                            hex(&expected),
                        )));
                    } else {
                        return Err(PatchError::Mismatch {
                            name: self.name.clone(),
                            offset,
                            expected,
                            found: found.to_vec(),
                        });
                    }
                }
            }

            let old = buf[off..off + fill_len].to_vec();
            buf[off..off + fill_len].copy_from_slice(&new_bytes);
            reports.push(OpReport {
                offset,
                old,
                new: new_bytes,
            });
        }
        Ok(reports)
    }
}

fn op_expect(op: &Op) -> Option<&str> {
    match op {
        Op::Nop { expect, .. } => expect.as_deref(),
        Op::Replace { expect, .. } => expect.as_deref(),
    }
}

/// Patches baked into the binary at compile time (the repo's `patches/` directory).
static EMBEDDED: include_dir::Dir<'_> = include_dir::include_dir!("$CARGO_MANIFEST_DIR/../patches");

/// Load every patch from the embedded copy of `patches/`, sorted by name.
pub fn load_embedded() -> Result<Vec<Patch>, PatchError> {
    let mut patches = Vec::new();
    for file in EMBEDDED.files() {
        if file.path().extension().and_then(|e| e.to_str()) == Some("toml") {
            let src = file
                .contents_utf8()
                .ok_or_else(|| PatchError::Spec(format!("{:?} is not UTF-8", file.path())))?;
            patches.push(Patch::from_toml(src)?);
        }
    }
    patches.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(patches)
}

/// Load every `*.toml` patch from a directory on disk, sorted by name.
pub fn load_dir(dir: &Path) -> Result<Vec<Patch>, PatchError> {
    let mut patches = Vec::new();
    let entries = std::fs::read_dir(dir)
        .map_err(|e| PatchError::Spec(format!("cannot read patches dir {dir:?}: {e}")))?;
    for entry in entries {
        let path = entry.map_err(|e| PatchError::Spec(format!("{e}")))?.path();
        if path.extension().and_then(|e| e.to_str()) == Some("toml") {
            let src = std::fs::read_to_string(&path)
                .map_err(|e| PatchError::Spec(format!("cannot read {path:?}: {e}")))?;
            patches.push(Patch::from_toml(&src)?);
        }
    }
    patches.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(patches)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hex_roundtrip() {
        assert_eq!(
            parse_hex("B8 01 00 00 00 C3").unwrap(),
            vec![0xB8, 1, 0, 0, 0, 0xC3]
        );
        assert_eq!(parse_hex(" eb ").unwrap(), vec![0xEB]);
        assert!(parse_hex("ABC").is_err());
        assert!(parse_hex("ZZ").is_err());
    }

    #[test]
    fn nop_applies_and_verifies() {
        let patch = Patch::from_toml(
            r#"
            name = "t"
            title = "t"
            [[op]]
            kind = "nop"
            offset = 0x2
            len = 3
            expect = "57"
            "#,
        )
        .unwrap();
        let mut buf = vec![0x00, 0x11, 0x57, 0x22, 0x33, 0x44];
        let mut warns = Vec::new();
        patch.apply(&mut buf, false, &mut warns).unwrap();
        assert_eq!(buf, vec![0x00, 0x11, 0x90, 0x90, 0x90, 0x44]);
        assert!(warns.is_empty());
    }

    #[test]
    fn replace_applies() {
        let patch = Patch::from_toml(
            r#"
            name = "t"
            title = "t"
            [[op]]
            kind = "replace"
            offset = 0x1
            expect = "75"
            bytes = "EB"
            "#,
        )
        .unwrap();
        let mut buf = vec![0x00, 0x75, 0x00];
        let mut warns = Vec::new();
        patch.apply(&mut buf, false, &mut warns).unwrap();
        assert_eq!(buf, vec![0x00, 0xEB, 0x00]);
    }

    #[test]
    fn mismatch_aborts_without_force() {
        let patch = Patch::from_toml(
            r#"
            name = "t"
            title = "t"
            [[op]]
            kind = "replace"
            offset = 0x0
            expect = "75"
            bytes = "EB"
            "#,
        )
        .unwrap();
        let mut buf = vec![0xAA];
        let mut warns = Vec::new();
        assert!(matches!(
            patch.apply(&mut buf, false, &mut warns),
            Err(PatchError::Mismatch { .. })
        ));
        assert_eq!(buf, vec![0xAA]); // untouched
    }

    #[test]
    fn mismatch_with_force_warns_and_applies() {
        let patch = Patch::from_toml(
            r#"
            name = "t"
            title = "t"
            [[op]]
            kind = "replace"
            offset = 0x0
            expect = "75"
            bytes = "EB"
            "#,
        )
        .unwrap();
        let mut buf = vec![0xAA];
        let mut warns = Vec::new();
        patch.apply(&mut buf, true, &mut warns).unwrap();
        assert_eq!(buf, vec![0xEB]);
        assert_eq!(warns.len(), 1);
    }

    #[test]
    fn out_of_bounds_aborts() {
        let patch = Patch::from_toml(
            r#"
            name = "t"
            title = "t"
            [[op]]
            kind = "nop"
            offset = 0x10
            len = 4
            "#,
        )
        .unwrap();
        let mut buf = vec![0x00; 8];
        let mut warns = Vec::new();
        assert!(matches!(
            patch.apply(&mut buf, false, &mut warns),
            Err(PatchError::OutOfBounds { .. })
        ));
    }

    #[test]
    fn embedded_patches_parse() {
        let patches = load_embedded().unwrap();
        assert!(
            patches.len() >= 7,
            "expected the repo's patches to be embedded"
        );
        for p in &patches {
            assert!(!p.name.is_empty());
            assert!(!p.ops.is_empty(), "patch {} has no ops", p.name);
        }
    }

    /// No two patches that target the same binary may write overlapping byte ranges —
    /// otherwise applying them together is order-dependent and the second one's `expect`
    /// anchor fails (e.g. two code caves claiming the same spot in the .text zero pad).
    #[test]
    fn embedded_patches_do_not_overlap() {
        let patches = load_embedded().unwrap();
        // (target, start, end-exclusive, patch name)
        let mut ranges: Vec<(String, u64, u64, &str)> = Vec::new();
        for p in &patches {
            for op in &p.ops {
                let (offset, len) = match op {
                    Op::Nop { offset, len, .. } => (*offset, *len),
                    Op::Replace { offset, bytes, .. } => {
                        (*offset, parse_hex(bytes).unwrap().len() as u64)
                    }
                };
                ranges.push((
                    p.target.to_ascii_lowercase(),
                    offset,
                    offset + len,
                    &p.name,
                ));
            }
        }
        ranges.sort();
        // Sweep with a running high-water mark per target so nested ranges are
        // caught too, not just adjacent pairs.
        let mut prev: Option<&(String, u64, u64, &str)> = None;
        for r in &ranges {
            if let Some(p) = prev {
                if p.0 == r.0 && p.3 != r.3 && r.1 < p.2 {
                    panic!(
                        "patches '{}' and '{}' overlap in {}: [0x{:X}..0x{:X}) vs [0x{:X}..0x{:X})",
                        p.3, r.3, p.0, p.1, p.2, r.1, r.2,
                    );
                }
            }
            // Keep whichever range reaches further as the comparison point.
            prev = match prev {
                Some(p) if p.0 == r.0 && p.2 > r.2 => Some(p),
                _ => Some(r),
            };
        }
    }
}
