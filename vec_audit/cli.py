#!/usr/bin/env python3
"""
vec-audit — CLI principal
===========================
Usage :
  vec-audit audit mon_code.c                        # GCC auto-détecté
  vec-audit audit mon_code.c --gcc gcc-15           # GCC spécifique (Mac/Homebrew)
  vec-audit audit mon_code.c --clang                # Clang natif
  vec-audit audit mon_code.c --html rapport.html    # Export HTML
  vec-audit parse rapport.txt --source mon_code.c   # Rapport déjà généré
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from vec_audit.parsers.gcc   import GCCParser
from vec_audit.parsers.clang import ClangParser
from vec_audit.diagnostics.engine   import DiagnosticEngine
from vec_audit.reporters.terminal   import TerminalReporter
from vec_audit.reporters.html       import HTMLReporter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_source_lines(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None


def _run_gcc(source: Path, gcc_bin: str, extra_flags: list[str]) -> str:
    cmd = [
        gcc_bin, "-O3", "-march=native", "-fopt-info-vec-all",
        "-c", str(source), "-o", "/dev/null",
        *extra_flags,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stderr + r.stdout


def _run_clang(source: Path, extra_flags: list[str]) -> str:
    cmd = [
        "clang", "-O3", "-march=native",
        "-Rpass=loop-vectorize",
        "-Rpass-missed=loop-vectorize",
        "-Rpass-analysis=loop-vectorize",
        "-c", str(source), "-o", "/dev/null",
        *extra_flags,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stderr + r.stdout


def _output_report(report, source_lines, args, compiler_label: str, flags: str) -> int:
    """Affiche dans le terminal et/ou exporte en HTML."""
    report.compiler       = compiler_label
    report.compiler_flags = flags

    # Terminal (toujours)
    reporter = TerminalReporter(source_lines=source_lines, verbose=args.verbose)
    reporter.render(report)

    # HTML (optionnel)
    if getattr(args, "html", None):
        html_path = Path(args.html)
        html_reporter = HTMLReporter(source_lines=source_lines)
        html_reporter.render(report, html_path)
        print(f"\nRapport HTML généré : {html_path.resolve()}")

    return 0 if report.missed_count == 0 else 1


# ---------------------------------------------------------------------------
# Sous-commandes
# ---------------------------------------------------------------------------

def cmd_audit(args: argparse.Namespace) -> int:
    source = Path(args.file)
    if not source.exists():
        print(f"[erreur] Fichier introuvable : {source}", file=sys.stderr)
        return 1

    use_clang = getattr(args, "clang", False)
    engine    = DiagnosticEngine()

    if use_clang:
        # --- Mode Clang ---
        if not shutil.which("clang"):
            print("[erreur] 'clang' introuvable dans le PATH.", file=sys.stderr)
            return 1
        print(f"Compilation de {source} avec clang -O3 -Rpass* ...")
        raw = _run_clang(source, args.flags or [])
        if not raw.strip():
            print("[erreur] Aucun rapport produit. Vérifie que le fichier compile.")
            return 1
        records = ClangParser().parse_text(raw)
        flags   = "-O3 -march=native -Rpass=loop-vectorize -Rpass-missed=loop-vectorize"
        compiler_label = "clang"

    else:
        # --- Mode GCC ---
        gcc_bin = shutil.which(args.gcc)
        if gcc_bin is None:
            print(
                f"[erreur] Binaire GCC introuvable : '{args.gcc}'\n"
                f"  Sur Mac : brew install gcc  puis --gcc gcc-15\n"
                f"  Sur Linux : sudo apt install gcc",
                file=sys.stderr,
            )
            return 1
        print(f"Compilation de {source} avec {args.gcc} -O3 -march=native ...")
        raw = _run_gcc(source, gcc_bin, args.flags or [])
        if not raw.strip():
            print(
                "[erreur] Aucun rapport produit.\n"
                f"  Sur Mac, 'gcc' est souvent Clang. Essaie : --gcc gcc-15 ou --clang"
            )
            return 1
        records = GCCParser().parse_text(raw)
        flags   = f"-O3 -march=native -fopt-info-vec-all"
        compiler_label = args.gcc

    if not records:
        print("Aucune boucle détectée dans le rapport.")
        return 0

    report = engine.diagnose_all(records)
    report.source_file = str(source)
    source_lines = _read_source_lines(source)
    return _output_report(report, source_lines, args, compiler_label, flags)


def cmd_parse(args: argparse.Namespace) -> int:
    report_path = Path(args.report)
    if not report_path.exists():
        print(f"[erreur] Fichier introuvable : {report_path}", file=sys.stderr)
        return 1

    compiler = getattr(args, "compiler", "gcc").lower()
    if compiler == "clang":
        records = ClangParser().parse_file(report_path)
    else:
        records = GCCParser().parse_file(report_path)

    if not records:
        print("Aucune boucle détectée dans le rapport.")
        return 0

    engine = DiagnosticEngine()
    report = engine.diagnose_all(records)
    report.source_file = str(report_path)

    source_lines = _read_source_lines(Path(args.source)) if args.source else None
    return _output_report(report, source_lines, args, compiler, "")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vec-audit",
        description="Analyse la vectorisation GCC/Clang et suggère des optimisations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  vec-audit audit mon_code.c --gcc gcc-15\n"
            "  vec-audit audit mon_code.c --clang\n"
            "  vec-audit audit mon_code.c --clang --html rapport.html\n"
            "  vec-audit parse rapport.txt --compiler clang --source mon_code.c\n"
        ),
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Afficher aussi les boucles vectorisées")

    sub = parser.add_subparsers(dest="command", required=True)

    # --- audit ---
    p_audit = sub.add_parser("audit", help="Compile et audite un fichier C/C++")
    p_audit.add_argument("file", help="Fichier source à auditer")
    p_audit.add_argument("--gcc", default="gcc", metavar="BINAIRE",
                         help="Binaire GCC (défaut: gcc). Ex: --gcc gcc-15")
    p_audit.add_argument("--clang", action="store_true",
                         help="Utiliser Clang au lieu de GCC")
    p_audit.add_argument("--html", metavar="FICHIER",
                         help="Exporter le rapport en HTML (ex: --html rapport.html)")
    p_audit.add_argument("--flags", nargs="*", metavar="FLAG",
                         help="Flags supplémentaires (ex: --flags -ffast-math)")
    p_audit.set_defaults(func=cmd_audit)

    # --- parse ---
    p_parse = sub.add_parser("parse", help="Audite un rapport déjà généré")
    p_parse.add_argument("report", help="Fichier rapport du compilateur")
    p_parse.add_argument("--compiler", default="gcc", choices=["gcc", "clang"],
                         help="Compilateur source (défaut: gcc)")
    p_parse.add_argument("--source", metavar="FICHIER",
                         help="Fichier source pour afficher les extraits de code")
    p_parse.add_argument("--html", metavar="FICHIER",
                         help="Exporter le rapport en HTML")
    p_parse.set_defaults(func=cmd_parse)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()