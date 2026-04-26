#!/usr/bin/env python3
"""
vec-audit — CLI principal
=========================
Usage :
  vec-audit audit my_code.c --gcc gcc-15
  vec-audit audit my_code.c --clang
  vec-audit audit my_code.c --gcc gcc-15 --html report.html
  vec-audit audit my_code.c --gcc gcc-15 --html report.html --bench --compare --json out.json
  vec-audit audit src/                    # projet entier
  vec-audit parse report.txt --source my_code.c
  vec-audit history my_code.c
  vec-audit debug-asm my_code.c --gcc gcc-15
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from vec_audit.parsers.gcc        import GCCParser
from vec_audit.parsers.clang      import ClangParser
from vec_audit.diagnostics.engine import DiagnosticEngine
from vec_audit.reporters.terminal import TerminalReporter
from vec_audit.reporters.html     import HTMLReporter, render_full
from vec_audit.reporters.json_reporter import export_json
from vec_audit.asm_extractor      import extract_asm
from vec_audit.flag_advisor        import advise_flags
from vec_audit.benchmark           import run_benchmark
from vec_audit.compiler_compare    import compare_compilers
from vec_audit.history             import save_to_history, load_previous, diff_reports, list_history
from vec_audit.project_audit       import audit_project, find_sources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_source_lines(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None


def _run_gcc(source: Path, gcc_bin: str, extra_flags: list[str]) -> str:
    cmd = [gcc_bin, "-O3", "-march=native", "-fopt-info-vec-all",
           "-c", str(source), "-o", "/dev/null", *extra_flags]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stderr + r.stdout


def _run_clang(source: Path, extra_flags: list[str]) -> str:
    cmd = ["clang", "-O3", "-march=native",
           "-Rpass=loop-vectorize",
           "-Rpass-missed=loop-vectorize",
           "-Rpass-analysis=loop-vectorize",
           "-c", str(source), "-o", "/dev/null", *extra_flags]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stderr + r.stdout


# ---------------------------------------------------------------------------
# cmd_audit
# ---------------------------------------------------------------------------

def cmd_audit(args: argparse.Namespace) -> int:
    source_arg = Path(args.file)

    # --- Mode projet (dossier) ---
    if source_arg.is_dir():
        return _audit_project(source_arg, args)

    # --- Mode fichier unique ---
    source = source_arg
    if not source.exists():
        print(f"[error] File not found: {source}", file=sys.stderr)
        return 1

    use_clang  = getattr(args, "clang", False)
    engine     = DiagnosticEngine()

    if use_clang:
        if not shutil.which("clang"):
            print("[error] 'clang' not found in PATH.", file=sys.stderr)
            return 1
        print(f"Compiling {source} with clang -O3 ...")
        raw      = _run_clang(source, args.flags or [])
        records  = ClangParser().parse_text(raw)
        flags    = "-O3 -march=native -Rpass=loop-vectorize -Rpass-missed"
        comp     = "clang"
    else:
        gcc_bin = shutil.which(args.gcc)
        if not gcc_bin:
            print(f"[error] GCC binary not found: '{args.gcc}'", file=sys.stderr)
            return 1
        print(f"Compiling {source} with {args.gcc} -O3 -march=native ...")
        raw      = _run_gcc(source, gcc_bin, args.flags or [])
        records  = GCCParser().parse_text(raw)
        flags    = "-O3 -march=native -fopt-info-vec-all"
        comp     = args.gcc

    if not records:
        print("No loops detected in the report.")
        return 0

    report = engine.diagnose_all(records)
    report.source_file    = str(source)
    report.compiler       = comp
    report.compiler_flags = flags

    source_lines = _read_source_lines(source)

    # Terminal
    TerminalReporter(source_lines=source_lines, verbose=args.verbose).render(report)

    # --- Features optionnelles ---
    asm_blocks          = {}
    benchmark_results   = []
    comparison          = None
    history_diff_result = None
    flag_suggestions    = []

    if getattr(args, "html", None) or getattr(args, "bench", False) \
            or getattr(args, "compare", False) or getattr(args, "json_out", None):

        compiler_bin = "clang" if use_clang else args.gcc
        asm_blocks   = extract_asm(source, compiler=compiler_bin)

        # Benchmark
        if getattr(args, "bench", False) and source_lines:
            print("\nRunning benchmark (vectorized vs scalar)...")
            benchmark_results = run_benchmark(source, compiler_bin, source_lines)
            if benchmark_results:
                print(f"  {'Function':<25} {'Vec':>8} {'Scalar':>8} {'Speedup':>8}")
                for b in benchmark_results:
                    print(f"  {b['function']:<25} {b['time_vec_ms']:>6.2f}ms "
                          f"{b['time_novec_ms']:>6.2f}ms "
                          f"{b['speedup']:>7.2f}×")

        # Comparaison GCC vs Clang
        if getattr(args, "compare", False):
            print("\nComparing GCC vs Clang...")
            comparison = compare_compilers(source, args.gcc)
            if comparison:
                g = comparison["gcc"]
                c = comparison["clang"]
                rec = comparison["recommendation"]
                print(f"  GCC:   {g['rate']:.0f}% vectorized ({g['vectorized']}/{g['total']})")
                print(f"  Clang: {c['rate']:.0f}% vectorized ({c['vectorized']}/{c['total']})")
                print(f"  Recommendation: {rec.upper()}")
                if comparison["divergences"]:
                    print(f"  Divergences: {len(comparison['divergences'])} loops differ")

        # Suggestions de flags
        flag_suggestions = advise_flags(report)

    # Export JSON
    json_path = None
    if getattr(args, "json_out", None):
        json_path = Path(args.json_out)
        export_json(
            report, json_path,
            benchmark={"results": benchmark_results} if benchmark_results else None,
            compiler_comparison=comparison,
        )
        print(f"\nJSON exported: {json_path.resolve()}")

        # Historique
        saved = save_to_history(json_path, str(source))
        prev  = load_previous(str(source), skip=1)
        if prev:
            cur_data       = json.loads(json_path.read_text())
            history_diff_result = diff_reports(cur_data, prev)
            delta = history_diff_result["delta"]
            trend = history_diff_result["trend"]
            sign  = "+" if delta >= 0 else ""
            print(f"  vs previous run: {sign}{delta:.1f}% ({trend})")

    # Export HTML
    if getattr(args, "html", None):
        html_path = Path(args.html)
        render_full(
            report,
            html_path,
            source_lines=source_lines,
            asm_blocks=asm_blocks,
            benchmark=benchmark_results,
            compiler_comparison=comparison,
            history_diff=history_diff_result,
            flag_suggestions=flag_suggestions,
        )
        print(f"\nHTML report: {html_path.resolve()}")

    return 0 if report.missed_count == 0 else 1


def _audit_project(directory: Path, args) -> int:
    """Audit d'un projet entier."""
    print(f"Auditing project: {directory}")
    use_clang = getattr(args, "clang", False)
    results   = audit_project(directory, compiler=args.gcc, use_clang=use_clang)

    if not results:
        print("No vectorizable source files found.")
        return 0

    print(f"\n{'File':<45} {'Rate':>6} {'Vec':>5} {'Miss':>5}")
    print("-" * 65)
    for r in results:
        rate_color = ""
        print(f"{r['file']:<45} {r['rate']:>5.0f}% {r['vectorized']:>5} {r['missed']:>5}")

    worst = results[0]
    print(f"\nLowest vectorization rate: {worst['file']} ({worst['rate']:.0f}%)")
    print(f"Run: vec-audit audit " + str(directory / worst['file']) + " for details.")
    return 0


# ---------------------------------------------------------------------------
# cmd_parse
# ---------------------------------------------------------------------------

def cmd_parse(args: argparse.Namespace) -> int:
    report_path = Path(args.report)
    if not report_path.exists():
        print(f"[error] File not found: {report_path}", file=sys.stderr)
        return 1

    compiler = getattr(args, "compiler", "gcc").lower()
    records  = (ClangParser() if compiler == "clang" else GCCParser()).parse_file(report_path)

    if not records:
        print("No loops detected in the report.")
        return 0

    engine = DiagnosticEngine()
    report = engine.diagnose_all(records)
    report.source_file = str(report_path)
    report.compiler    = compiler

    source_lines = _read_source_lines(Path(args.source)) if args.source else None
    asm_blocks   = {}
    if args.source and Path(args.source).exists():
        asm_blocks = extract_asm(Path(args.source), compiler=compiler)

    TerminalReporter(source_lines=source_lines, verbose=args.verbose).render(report)

    if getattr(args, "html", None):
        render_full(
            report, Path(args.html),
            source_lines=source_lines,
            asm_blocks=asm_blocks,
            flag_suggestions=advise_flags(report),
        )
        print(f"\nHTML report: {Path(args.html).resolve()}")

    return 0 if report.missed_count == 0 else 1


# ---------------------------------------------------------------------------
# cmd_history
# ---------------------------------------------------------------------------

def cmd_history(args: argparse.Namespace) -> int:
    entries = list_history(args.file)
    if not entries:
        print(f"No history found for '{args.file}'.")
        print("Run 'vec-audit audit' with --json to start tracking.")
        return 0

    print(f"\nHistory for {args.file}:")
    print(f"{'Timestamp':<25} {'Rate':>6} {'Vec':>5} {'Miss':>5}")
    print("-" * 45)
    for e in entries:
        ts = e["timestamp"][:19].replace("T", " ")
        print(f"{ts:<25} {e['rate']:>5.0f}% {e['vectorized']:>5} {e['missed']:>5}")
    return 0


# ---------------------------------------------------------------------------
# cmd_debug_asm
# ---------------------------------------------------------------------------

def cmd_debug_asm(args: argparse.Namespace) -> int:
    source = Path(args.file)
    if not source.exists():
        print(f"[error] File not found: {source}", file=sys.stderr)
        return 1

    compiler = args.gcc if not getattr(args, "clang", False) else "clang"
    print(f"Compiler : {compiler}")
    print(f"objdump  : {shutil.which('objdump')}")
    print(f"otool    : {shutil.which('otool')}")
    print()

    import tempfile
    flags = ["-O3", "-march=native", "-g"]
    with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as tmp:
        obj_path = Path(tmp.name)

    subprocess.run([compiler, *flags, "-c", str(source), "-o", str(obj_path)],
                   capture_output=True)

    tool = "objdump" if shutil.which("objdump") else "otool"
    if tool == "objdump":
        r = subprocess.run(["objdump", "-d", "--no-show-raw-insn", str(obj_path)],
                           capture_output=True, text=True)
    else:
        r = subprocess.run(["otool", "-tv", str(obj_path)],
                           capture_output=True, text=True)

    print(f"=== {tool} (first 30 lines) ===")
    for line in r.stdout.splitlines()[:30]:
        print(repr(line))

    print()
    from vec_audit.asm_extractor import extract_asm
    blocks = extract_asm(source, compiler=compiler)
    print("=== ASM blocks ===")
    if not blocks:
        print("NONE — parsing failed")
    for name, block in blocks.items():
        print(f"  '{name}': {len(block.lines)} lines, SIMD={block.has_simd}")

    obj_path.unlink(missing_ok=True)
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vec-audit",
        description="Vectorization audit for C/C++ code — GCC and Clang.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  vec-audit audit my_code.c --gcc gcc-15 --html report.html --bench --compare\n"
            "  vec-audit audit src/          # entire project\n"
            "  vec-audit history my_code.c   # show run history\n"
            "  vec-audit parse report.txt --source my_code.c\n"
        ),
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Also show vectorized loops")

    sub = parser.add_subparsers(dest="command", required=True)

    # --- audit ---
    p_audit = sub.add_parser("audit", help="Compile and audit a C/C++ file or directory")
    p_audit.add_argument("file",    help="Source file or directory to audit")
    p_audit.add_argument("--gcc",   default="gcc", metavar="BIN",
                         help="GCC binary (default: gcc). Ex: --gcc gcc-15")
    p_audit.add_argument("--clang", action="store_true",
                         help="Use Clang instead of GCC")
    p_audit.add_argument("--html",  metavar="FILE",
                         help="Export HTML report")
    p_audit.add_argument("--json",  dest="json_out", metavar="FILE",
                         help="Export JSON report (enables history tracking)")
    p_audit.add_argument("--bench", action="store_true",
                         help="Benchmark vectorized vs scalar performance")
    p_audit.add_argument("--compare", action="store_true",
                         help="Compare GCC vs Clang vectorization")
    p_audit.add_argument("--flags", nargs="*", metavar="FLAG",
                         help="Extra compilation flags")
    p_audit.set_defaults(func=cmd_audit)

    # --- parse ---
    p_parse = sub.add_parser("parse", help="Audit an already-generated compiler report")
    p_parse.add_argument("report",   help="Compiler report file")
    p_parse.add_argument("--compiler", default="gcc", choices=["gcc", "clang"])
    p_parse.add_argument("--source", metavar="FILE",
                         help="Original source file (for code snippets)")
    p_parse.add_argument("--html",  metavar="FILE", help="Export HTML report")
    p_parse.set_defaults(func=cmd_parse)

    # --- history ---
    p_hist = sub.add_parser("history", help="Show run history for a source file")
    p_hist.add_argument("file", help="Source file name")
    p_hist.set_defaults(func=cmd_history)

    # --- debug-asm ---
    p_debug = sub.add_parser("debug-asm", help="Debug: show extracted ASM blocks")
    p_debug.add_argument("file", help="Source file")
    p_debug.add_argument("--gcc",   default="gcc", metavar="BIN")
    p_debug.add_argument("--clang", action="store_true")
    p_debug.set_defaults(func=cmd_debug_asm)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()