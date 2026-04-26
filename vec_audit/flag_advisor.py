"""
vec-audit — conseiller de flags de compilation
Analyse les causes d'échec et suggère des flags supplémentaires
qui pourraient débloquer la vectorisation.
"""
from __future__ import annotations
import subprocess
from pathlib import Path

from vec_audit.models import AuditReport, FailureKind


# Mapping cause → flags à essayer + explication
_FLAG_SUGGESTIONS: list[tuple[set[FailureKind], str, str, str]] = [
    (
        {FailureKind.REDUCTION},
        "-ffast-math",
        "Allows floating-point reassociation, enabling reduction vectorization.",
        "Warning: may slightly change floating-point results (relaxes IEEE 754).",
    ),
    (
        {FailureKind.UNKNOWN_TRIP_COUNT, FailureKind.NOT_PROFITABLE},
        "-funroll-loops",
        "Unrolls loops with unknown bounds, helping the vectorizer find opportunities.",
        None,
    ),
    (
        {FailureKind.DATA_ALIGNMENT},
        "-mprefer-vector-width=256",
        "Prefers 256-bit vectors (AVX2) even for small loops, improving alignment flexibility.",
        None,
    ),
    (
        {FailureKind.ALIASING, FailureKind.DATA_DEPENDENCE},
        "-fvect-cost-model=unlimited",
        "Removes the cost model gate — forces vectorization even when the compiler "
        "thinks it may not be profitable.",
        "Warning: may slow down very small loops. Benchmark before and after.",
    ),
    (
        {FailureKind.CONTROL_FLOW},
        "-ftree-loop-if-convert",
        "Converts if-else inside loops into conditional moves (cmov), "
        "enabling vectorization of loops with simple branches.",
        None,
    ),
    (
        {FailureKind.FUNCTION_CALL},
        "-finline-functions",
        "Aggressively inlines function calls, removing barriers to vectorization.",
        None,
    ),
    (
        {FailureKind.OUTER_LOOP},
        "-floop-nest-optimize",
        "Enables loop nest optimizer (Graphite), allowing outer-loop vectorization "
        "and loop interchange.",
        None,
    ),
]


def advise_flags(report: AuditReport) -> list[dict]:
    """
    Retourne une liste de suggestions de flags basées sur les causes d'échec.
    Chaque suggestion contient le flag, l'explication, et un avertissement optionnel.
    """
    if report.missed_count == 0:
        return []

    # Collecter les causes présentes
    present_kinds = {r.record.failure_kind for r in report.results if r.record.is_missed}

    suggestions = []
    for kinds, flag, explanation, warning in _FLAG_SUGGESTIONS:
        if present_kinds & kinds:
            suggestions.append({
                "flag":        flag,
                "explanation": explanation,
                "warning":     warning,
                "targets":     [k.name for k in (present_kinds & kinds)],
            })

    return suggestions


def try_flag(source: Path, compiler: str, base_flags: list[str],
             extra_flag: str) -> tuple[int, int]:
    """
    Compile avec un flag supplémentaire et retourne
    (vectorized_count, missed_count) pour comparer.
    """
    from vec_audit.parsers.gcc import GCCParser

    cmd = [compiler, *base_flags, extra_flag,
           "-fopt-info-vec-all", "-c", str(source), "-o", "/dev/null"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    raw = r.stderr + r.stdout

    records = GCCParser().parse_text(raw)
    vecs    = sum(1 for r in records if r.is_vectorized)
    missed  = sum(1 for r in records if r.is_missed)
    return vecs, missed