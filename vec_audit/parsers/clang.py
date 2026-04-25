"""
vec-audit — parser Clang/LLVM
==============================
Parse la sortie de Clang générée avec :
  -Rpass=loop-vectorize          (boucles vectorisées)
  -Rpass-missed=loop-vectorize   (boucles ratées)
  -Rpass-analysis=loop-vectorize (analyse détaillée)

Format des messages Clang :
  <fichier>:<ligne>:<col>: remark: <message> [-Rpass=loop-vectorize]
  <fichier>:<ligne>:<col>: remark: <message> [-Rpass-missed=loop-vectorize]

Exemples réels (Clang/Apple sur Mac) :
  foo.c:12:5: remark: vectorized loop (vectorization width: 4, ...) [-Rpass=loop-vectorize]
  foo.c:24:5: remark: loop not vectorized [-Rpass-missed=loop-vectorize]
  foo.c:24:5: remark: loop not vectorized: memory write that may alias [-Rpass-analysis=...]
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from vec_audit.models import (
    FailureKind,
    SourceLocation,
    VectorizationRecord,
    VectorizationStatus,
)


# ---------------------------------------------------------------------------
# Patterns regex Clang
# ---------------------------------------------------------------------------

# Ligne principale Clang : fichier:ligne:col: remark: message [-Rflag]
_LINE_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s+"
    r"remark:\s+"
    r"(?P<message>.+?)"
    r"(?:\s+\[-R(?P<flag>[^\]]+)\])?$"
)

# Succès : "vectorized loop (vectorization width: 4, interleaved with 1 instructions)"
_VECTORIZED_RE = re.compile(r"vectorized loop", re.I)

# Largeur vectorielle Clang : "vectorization width: 4"
_WIDTH_RE = re.compile(r"vectorization width:\s*(?P<width>\d+)", re.I)

# Message "chapeau" Clang sans cause réelle
_HEADER_RE = re.compile(r"^loop not vectorized$", re.I)

# ---------------------------------------------------------------------------
# Catalogue FailureKind pour Clang — messages différents de GCC
# ---------------------------------------------------------------------------

_FAILURE_PATTERNS: list[tuple[re.Pattern, FailureKind]] = [
    (re.compile(r"alias|may alias|unsafe dependent memory",         re.I), FailureKind.ALIASING),
    (re.compile(r"dependenc",                                       re.I), FailureKind.DATA_DEPENDENCE),
    (re.compile(r"loop control flow|switch statement|control flow", re.I), FailureKind.CONTROL_FLOW),
    (re.compile(r"loop count.*unknown|trip count",                  re.I), FailureKind.UNKNOWN_TRIP_COUNT),
    (re.compile(r"not beneficial|not profitable",                   re.I), FailureKind.NOT_PROFITABLE),
    (re.compile(r"align",                                           re.I), FailureKind.DATA_ALIGNMENT),
    (re.compile(r"call.*loop|function.*not.*inline",                re.I), FailureKind.FUNCTION_CALL),
    (re.compile(r"reduction",                                       re.I), FailureKind.REDUCTION),
    (re.compile(r"outer loop",                                      re.I), FailureKind.OUTER_LOOP),
    (re.compile(r"unsupported|not understood",                      re.I), FailureKind.UNSUPPORTED_TYPE),
]


def _classify_failure(message: str) -> FailureKind:
    for pattern, kind in _FAILURE_PATTERNS:
        if pattern.search(message):
            return kind
    return FailureKind.UNKNOWN_CAUSE


def _parse_vector_width(message: str) -> int | None:
    m = _WIDTH_RE.search(message)
    # Clang donne le nombre d'éléments, pas les bytes.
    # On retourne le nombre d'éléments directement (float = ×4 pour bytes).
    return int(m.group("width")) if m else None


def _is_success_flag(flag: str | None) -> bool:
    return flag is not None and "Rpass" in flag and "missed" not in flag and "analysis" not in flag


def _is_missed_flag(flag: str | None) -> bool:
    return flag is not None and ("missed" in flag or "analysis" in flag)


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------

class ClangParser:
    """
    Parse les rapports de vectorisation produits par Clang/LLVM.

    Stratégie :
    - Les flags [-Rpass=...] et [-Rpass-missed=...] déterminent le statut.
    - Les messages "loop not vectorized" seuls sont des chapeaux :
      on attend le message d'analyse suivant pour la cause.
    - Compatible avec Apple Clang et LLVM Clang.
    """

    def parse_lines(self, lines: Iterable[str]) -> list[VectorizationRecord]:
        records: list[VectorizationRecord] = []
        pending_header: VectorizationRecord | None = None

        for raw_line in lines:
            line = raw_line.rstrip()
            m = _LINE_RE.match(line)
            if not m:
                continue

            message = m.group("message").strip()
            flag    = m.group("flag")
            loc = SourceLocation(
                file   = m.group("file"),
                line   = int(m.group("line")),
                column = int(m.group("col")),
            )

            # --- Succès ---
            if _VECTORIZED_RE.search(message) and not _is_missed_flag(flag):
                pending_header = None
                records.append(VectorizationRecord(
                    location     = loc,
                    status       = VectorizationStatus.VECTORIZED,
                    raw_message  = message,
                    vector_width = _parse_vector_width(message),
                    compiler     = "clang",
                ))
                continue

            # --- Échec ---
            if _is_missed_flag(flag) or (flag is None and "not vectorized" in message.lower()):

                if _HEADER_RE.match(message):
                    # Chapeau sans cause — on attend la suivante
                    pending_header = VectorizationRecord(
                        location     = loc,
                        status       = VectorizationStatus.MISSED,
                        raw_message  = message,
                        failure_kind = FailureKind.UNKNOWN_CAUSE,
                        compiler     = "clang",
                    )
                    continue

                # Message avec la cause réelle
                failure_kind = _classify_failure(message)

                if pending_header is not None and pending_header.location.line == loc.line:
                    record = VectorizationRecord(
                        location     = pending_header.location,
                        status       = VectorizationStatus.MISSED,
                        raw_message  = message,
                        failure_kind = failure_kind,
                        compiler     = "clang",
                    )
                    pending_header = None
                else:
                    if pending_header is not None:
                        records.append(pending_header)
                        pending_header = None
                    record = VectorizationRecord(
                        location     = loc,
                        status       = VectorizationStatus.MISSED,
                        raw_message  = message,
                        failure_kind = failure_kind,
                        compiler     = "clang",
                    )
                records.append(record)

        if pending_header is not None:
            records.append(pending_header)

        return _deduplicate(records)

    def parse_text(self, text: str) -> list[VectorizationRecord]:
        return self.parse_lines(text.splitlines())

    def parse_file(self, path: Path) -> list[VectorizationRecord]:
        return self.parse_lines(path.read_text(encoding="utf-8").splitlines())


def _deduplicate(records: list[VectorizationRecord]) -> list[VectorizationRecord]:
    seen: dict[tuple, VectorizationRecord] = {}
    for rec in records:
        key = (rec.location.file, rec.location.line)
        if key not in seen:
            seen[key] = rec
        else:
            existing = seen[key]
            if existing.failure_kind == FailureKind.UNKNOWN_CAUSE \
                    and rec.failure_kind != FailureKind.UNKNOWN_CAUSE:
                seen[key] = rec
    return list(seen.values())