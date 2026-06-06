//! bw1patch — apply the openblack Black & White 1 binary patches to an executable.

mod patch;

use clap::Parser;
use patch::{hex, load_dir, load_embedded, Patch, Warning};
use std::path::PathBuf;
use std::process::ExitCode;

/// Apply the Black & White 1 / Creature Isle binary patches to an unprotected executable.
///
/// By default every patch is applied. Use --skip to leave some out, or --only to apply a
/// specific set. Each edit verifies the bytes it is about to overwrite, so pointing this
/// at the wrong file fails loudly instead of corrupting it.
#[derive(Parser)]
#[command(name = "bw1patch", version, about, long_about = None)]
struct Cli {
    /// The source executable to patch (e.g. runblack.exe).
    #[arg(required_unless_present = "list")]
    input: Option<PathBuf>,

    /// Where to write the patched executable.
    #[arg(short, long, required_unless_present_any = ["list", "dry_run", "in_place"])]
    output: Option<PathBuf>,

    /// Overwrite the input file in place instead of writing a separate output.
    #[arg(long, conflicts_with = "output")]
    in_place: bool,

    /// Apply only these patches (comma-separated names). Mutually exclusive with --skip.
    #[arg(long, value_delimiter = ',', conflicts_with = "skip")]
    only: Vec<String>,

    /// Apply every patch except these (comma-separated names).
    #[arg(long, value_delimiter = ',')]
    skip: Vec<String>,

    /// Load patch definitions from this directory instead of the ones built into the tool.
    #[arg(long)]
    patches_dir: Option<PathBuf>,

    /// List the available patches and exit.
    #[arg(long)]
    list: bool,

    /// Verify and report what would change, but do not write any output.
    #[arg(long)]
    dry_run: bool,

    /// Apply patches even when the verification bytes don't match (dangerous).
    #[arg(long)]
    force: bool,
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("error: {msg}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let cli = Cli::parse();

    let patches = match &cli.patches_dir {
        Some(dir) => load_dir(dir).map_err(|e| e.to_string())?,
        None => load_embedded().map_err(|e| e.to_string())?,
    };

    if cli.list {
        list_patches(&patches);
        return Ok(());
    }

    let selected = select_patches(&patches, &cli.only, &cli.skip)?;

    let input = cli
        .input
        .as_ref()
        .expect("clap guarantees input is present");

    // Only apply patches whose `target` matches the input file name. This keeps the
    // runblack.exe patches and the LHMultiplayerR.dll patch(es) from firing on the wrong
    // binary (where their `expect` anchors would mismatch anyway).
    let input_name = input
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    let selected: Vec<&Patch> = selected
        .into_iter()
        .filter(|p| p.target.eq_ignore_ascii_case(&input_name))
        .collect();
    if selected.is_empty() {
        let mut targets: Vec<&str> = patches.iter().map(|p| p.target.as_str()).collect();
        targets.sort_unstable();
        targets.dedup();
        return Err(format!(
            "no selected patch targets {input_name:?}. Patches in this set target: {}.",
            targets.join(", ")
        ));
    }

    let mut buf = std::fs::read(input).map_err(|e| format!("cannot read {input:?}: {e}"))?;

    println!("Loaded {:?} ({} bytes)", input, buf.len());
    println!("Applying {} patch(es):\n", selected.len());

    let mut warnings: Vec<Warning> = Vec::new();
    for p in &selected {
        let reports = p
            .apply(&mut buf, cli.force, &mut warnings)
            .map_err(|e| e.to_string())?;
        println!("  ✓ {} — {}", p.title, p.summary);
        for r in &reports {
            println!(
                "      0x{:06X}: {}  ->  {}",
                r.offset,
                hex(&r.old),
                hex(&r.new)
            );
        }
    }

    for Warning(w) in &warnings {
        eprintln!("  ! warning: {w}");
    }

    if cli.dry_run {
        println!("\nDry run — no file written.");
        return Ok(());
    }

    let output: PathBuf = if cli.in_place {
        input.clone()
    } else {
        cli.output
            .clone()
            .expect("clap guarantees output when not in-place/dry-run")
    };

    std::fs::write(&output, &buf).map_err(|e| format!("cannot write {output:?}: {e}"))?;
    println!("\nDone. Wrote patched executable to {output:?}");
    Ok(())
}

fn list_patches(patches: &[Patch]) {
    println!("Available patches ({}):\n", patches.len());
    for p in patches {
        println!("  {:<26} {}  [{}]", p.name, p.title, p.target);
        if !p.summary.is_empty() {
            println!("  {:<26} {}", "", p.summary);
        }
        if let Some(doc) = &p.doc {
            println!("  {:<26} see {}", "", doc);
        }
        println!();
    }
}

/// Resolve the set of patches to apply, validating that every `--only`/`--skip` name exists.
fn select_patches<'a>(
    patches: &'a [Patch],
    only: &[String],
    skip: &[String],
) -> Result<Vec<&'a Patch>, String> {
    let known = |name: &str| patches.iter().any(|p| p.name == name);

    for name in only.iter().chain(skip.iter()) {
        if !known(name) {
            return Err(format!(
                "unknown patch '{name}'. Run with --list to see the available patches."
            ));
        }
    }

    let selected: Vec<&Patch> = if !only.is_empty() {
        patches.iter().filter(|p| only.contains(&p.name)).collect()
    } else {
        patches.iter().filter(|p| !skip.contains(&p.name)).collect()
    };

    if selected.is_empty() {
        return Err("no patches selected".to_string());
    }
    Ok(selected)
}
