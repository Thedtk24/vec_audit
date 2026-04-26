"""
vec-audit — comparaison multi-compilateurs
Lance GCC et Clang sur le même fichier et compare les résultats.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from vec_audit.parsers.gcc   import GCCParser
from vec_audit.parsers.clang import ClangParser
from vec_audit.models import VectorizationStatus


def compare_compilers(
    source: Path,
    gcc_bin: str = "gcc",
) -> dict | None:
    """
    Compare GCC et Clang sur le même fichier.
    Retourne un dict avec les divergences ou None si un compilateur est absent.
    """
    has_gcc   = bool(shutil.which(gcc_bin))
    has_clang = bool(shutil.which("clang"))

    if not has_gcc or not has_clang:
        return None

    # --- GCC ---
    gcc_raw = subprocess.run(
        [gcc_bin, "-O3", "-march=native", "-fopt-info-vec-all",
         "-c", str(source), "-o", "/dev/null"],
        capture_output=True, text=True,
    ).stderr
    gcc_records = GCCParser().parse_text(gcc_raw)

    # --- Clang ---
    clang_raw = subprocess.run(
        ["clang", "-O3", "-march=native",
         "-Rpass=loop-vectorize",
         "-Rpass-missed=loop-vectorize",
         "-Rpass-analysis=loop-vectorize",
         "-c", str(source), "-o", "/dev/null"],
        capture_output=True, text=True,
    ).stderr
    clang_records = ClangParser().parse_text(clang_raw)

    # Indexer par ligne
    gcc_by_line   = {r.location.line: r for r in gcc_records}
    clang_by_line = {r.location.line: r for r in clang_records}

    all_lines = sorted(set(gcc_by_line) | set(clang_by_line))

    gcc_vec   = sum(1 for r in gcc_records   if r.is_vectorized)
    clang_vec = sum(1 for r in clang_records if r.is_vectorized)
    gcc_tot   = len(gcc_records)
    clang_tot = len(clang_records)

    # Divergences : une boucle vectorisée par l'un mais pas l'autre
    divergences = []
    for line in all_lines:
        g = gcc_by_line.get(line)
        c = clang_by_line.get(line)
        if g is None or c is None:
            continue
        g_vec = g.status == VectorizationStatus.VECTORIZED
        c_vec = c.status == VectorizationStatus.VECTORIZED
        if g_vec != c_vec:
            divergences.append({
                "line":           line,
                "gcc_vectorized":   g_vec,
                "clang_vectorized": c_vec,
                "winner":         "gcc" if g_vec else "clang",
                "note": (
                    f"GCC vectorizes, Clang does not" if g_vec
                    else f"Clang vectorizes, GCC does not"
                ),
            })

    return {
        "gcc": {
            "binary":          gcc_bin,
            "vectorized":      gcc_vec,
            "missed":          gcc_tot - gcc_vec,
            "total":           gcc_tot,
            "rate":            round(gcc_vec / gcc_tot * 100, 1) if gcc_tot else 0,
        },
        "clang": {
            "binary":          "clang",
            "vectorized":      clang_vec,
            "missed":          clang_tot - clang_vec,
            "total":           clang_tot,
            "rate":            round(clang_vec / clang_tot * 100, 1) if clang_tot else 0,
        },
        "divergences": divergences,
        "recommendation": (
            "clang" if clang_vec > gcc_vec else
            "gcc"   if gcc_vec > clang_vec else
            "equivalent"
        ),
    }