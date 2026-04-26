"""
vec-audit — audit d'un projet entier (dossier)
Parcourt tous les fichiers C/C++/Fortran et produit un rapport global.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from vec_audit.parsers.gcc      import GCCParser
from vec_audit.parsers.clang    import ClangParser
from vec_audit.diagnostics.engine import DiagnosticEngine
from vec_audit.models import AuditReport


_C_EXTENSIONS   = {".c", ".cpp", ".cc", ".cxx", ".C"}
_F_EXTENSIONS   = {".f", ".f90", ".f95", ".f03", ".F", ".F90"}
_ALL_EXTENSIONS = _C_EXTENSIONS | _F_EXTENSIONS


def find_sources(directory: Path) -> list[Path]:
    """Trouve tous les fichiers source dans un répertoire."""
    sources = []
    for ext in _ALL_EXTENSIONS:
        sources.extend(directory.rglob(f"*{ext}"))
    return sorted(sources)


def audit_file(
    source: Path,
    compiler: str,
    use_clang: bool = False,
) -> AuditReport | None:
    """Audite un fichier source et retourne un AuditReport."""
    try:
        if use_clang:
            raw = subprocess.run(
                ["clang", "-O3", "-march=native",
                 "-Rpass=loop-vectorize",
                 "-Rpass-missed=loop-vectorize",
                 "-c", str(source), "-o", "/dev/null"],
                capture_output=True, text=True, timeout=60,
            ).stderr
            records = ClangParser().parse_text(raw)
            comp    = "clang"
        else:
            raw = subprocess.run(
                [compiler, "-O3", "-march=native", "-fopt-info-vec-all",
                 "-c", str(source), "-o", "/dev/null"],
                capture_output=True, text=True, timeout=60,
            ).stderr
            records = GCCParser().parse_text(raw)
            comp    = compiler

        if not records:
            return None

        engine = DiagnosticEngine()
        report = engine.diagnose_all(records)
        report.source_file    = str(source)
        report.compiler       = comp
        report.compiler_flags = "-O3 -march=native"
        return report

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def audit_project(
    directory: Path,
    compiler: str = "gcc",
    use_clang: bool = False,
) -> list[dict]:
    """
    Audite tous les fichiers d'un projet.
    Retourne une liste de résumés triés par taux de vectorisation (croissant).
    """
    sources = find_sources(directory)
    if not sources:
        return []

    results = []
    for source in sources:
        report = audit_file(source, compiler, use_clang)
        if report is None or report.total == 0:
            continue
        results.append({
            "file":              str(source.relative_to(directory)),
            "total":             report.total,
            "vectorized":        report.vectorized_count,
            "missed":            report.missed_count,
            "rate":              round(report.vectorization_rate, 1),
            "top_causes":        [
                k.name for k in list(report.missed_by_kind().keys())[:3]
            ],
            "report":            report,
        })

    # Trier par taux croissant (les pires en premier)
    return sorted(results, key=lambda x: x["rate"])