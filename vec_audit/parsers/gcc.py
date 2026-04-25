"""
vec-audit — parser GCC
========================
Parse la sortie de GCC générée avec :
  -fopt-info-vec-missed   (boucles ratées)
  -fopt-info-vec          (boucles vectorisées)
  -fopt-info-vec-all      (tout)

Format des messages GCC :
  <fichier>:<ligne>:<col>: <niveau>: <message>

Exemples réels :
  foo.c:12:5: optimized: loop vectorized using 16 byte vectors
  foo.c:24:5: missed: couldn't vectorize loop
  foo.c:24:9: missed: not vectorized: possible aliasing problem
  foo.c:38:5: missed: not vectorized: number of iterations cannot be computed
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
# Patterns regex
# ---------------------------------------------------------------------------

_LINE_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<level>optimized|missed|note):\s+"
    r"(?P<message>.+)$"
)

_VECTORIZED_RE = re.compile(r"loop vectorized")
_WIDTH_RE      = re.compile(r"using (?P<width>\d+) byte vectors?")

# Messages "chapeau" qui ne contiennent pas la vraie cause —
# ils seront fusionnés avec le record suivant qui lui la contient.
_HEADER_MESSAGES = re.compile(
    r"couldn't vectorize loop"
    r"|vectorized \d+ loops? in function",
    re.I,
)

# Messages de bruit interne GCC à ignorer complètement
_NOISE_MESSAGES = re.compile(
    r"^\*{3,}"           # ***** Analysis failed...
    r"|^Re-trying"
    r"|^Skipping vector",
    re.I,
)

# ---------------------------------------------------------------------------
# Catalogue FailureKind — du plus spécifique au plus général
# ---------------------------------------------------------------------------

_FAILURE_PATTERNS: list[tuple[re.Pattern, FailureKind]] = [
    (re.compile(r"dependence between data|data dependenc",  re.I), FailureKind.DATA_DEPENDENCE),
    (re.compile(r"alias",                                   re.I), FailureKind.ALIASING),
    (re.compile(r"number of iterations",                    re.I), FailureKind.UNKNOWN_TRIP_COUNT),
    (re.compile(r"control flow",                            re.I), FailureKind.CONTROL_FLOW),
    (re.compile(r"not profitable",                          re.I), FailureKind.NOT_PROFITABLE),
    (re.compile(r"align",                                   re.I), FailureKind.DATA_ALIGNMENT),
    (re.compile(r"function call",                           re.I), FailureKind.FUNCTION_CALL),
    (re.compile(r"reduction",                               re.I), FailureKind.REDUCTION),
    (re.compile(r"outer loop",                              re.I), FailureKind.OUTER_LOOP),
    (re.compile(r"unsupported|not supported",               re.I), FailureKind.UNSUPPORTED_TYPE),
]


def _classify_failure(message: str) -> FailureKind:
    for pattern, kind in _FAILURE_PATTERNS:
        if pattern.search(message):
            return kind
    return FailureKind.UNKNOWN_CAUSE


def _parse_vector_width(message: str) -> int | None:
    m = _WIDTH_RE.search(message)
    return int(m.group("width")) if m else None


def _is_header(message: str) -> bool:
    """Vrai si ce message est un 'chapeau' sans cause réelle."""
    return bool(_HEADER_MESSAGES.search(message))


def _is_noise(message: str) -> bool:
    """Vrai si ce message est du bruit interne GCC à ignorer."""
    return bool(_NOISE_MESSAGES.search(message))


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------

class GCCParser:
    """
    Parse les rapports de vectorisation produits par GCC.

    Stratégie :
    - Les messages "chapeau" (couldn't vectorize loop) sont mis en attente.
    - Le premier message "missed: not vectorized: <cause>" qui suit
      est fusionné avec le chapeau pour produire un seul record propre.
    - Les notes sont attachées au dernier record produit.
    - Les doublons (même fichier+fonction, cause identique) sont supprimés.
    """

    def parse_lines(self, lines: Iterable[str]) -> list[VectorizationRecord]:
        records: list[VectorizationRecord] = []
        # Record "chapeau" en attente d'une cause réelle
        pending_header: VectorizationRecord | None = None

        for raw_line in lines:
            line = raw_line.rstrip()
            m = _LINE_RE.match(line)
            if not m:
                continue

            level   = m.group("level")
            message = m.group("message").strip()

            # Ignorer le bruit interne GCC
            if _is_noise(message):
                continue

            loc = SourceLocation(
                file   = m.group("file"),
                line   = int(m.group("line")),
                column = int(m.group("col")),
            )

            # --- Notes : contexte additionnel pour le dernier record ---
            if level == "note":
                if _is_noise(message):
                    continue
                if records:
                    records[-1] = _attach_note(records[-1], message)
                continue

            # --- Succès ---
            if level == "optimized" and _VECTORIZED_RE.search(message):
                pending_header = None
                records.append(VectorizationRecord(
                    location     = loc,
                    status       = VectorizationStatus.VECTORIZED,
                    raw_message  = message,
                    vector_width = _parse_vector_width(message),
                    compiler     = "gcc",
                ))
                continue

            # --- Échec ---
            if level == "missed":

                if _is_header(message):
                    # Mettre le chapeau en attente — on attend la vraie cause
                    pending_header = VectorizationRecord(
                        location     = loc,
                        status       = VectorizationStatus.MISSED,
                        raw_message  = message,
                        failure_kind = FailureKind.UNKNOWN_CAUSE,
                        compiler     = "gcc",
                    )
                    continue

                # Message avec la cause réelle
                failure_kind = _classify_failure(message)

                if pending_header is not None:
                    # Fusionner avec le chapeau : on garde la localisation
                    # du chapeau (plus précise) et on enrichit avec la cause
                    record = VectorizationRecord(
                        location     = pending_header.location,
                        status       = VectorizationStatus.MISSED,
                        raw_message  = message,
                        failure_kind = failure_kind,
                        compiler     = "gcc",
                    )
                    pending_header = None
                else:
                    record = VectorizationRecord(
                        location     = loc,
                        status       = VectorizationStatus.MISSED,
                        raw_message  = message,
                        failure_kind = failure_kind,
                        compiler     = "gcc",
                    )

                records.append(record)

        # S'il reste un chapeau sans cause (boucle vraiment non diagnostiquée)
        if pending_header is not None:
            records.append(pending_header)

        return _deduplicate(records)

    def parse_text(self, text: str) -> list[VectorizationRecord]:
        return self.parse_lines(text.splitlines())

    def parse_file(self, path: Path) -> list[VectorizationRecord]:
        return self.parse_lines(path.read_text(encoding="utf-8").splitlines())


def _attach_note(record: VectorizationRecord, note: str) -> VectorizationRecord:
    return VectorizationRecord(
        location     = record.location,
        status       = record.status,
        raw_message  = record.raw_message,
        failure_kind = record.failure_kind,
        vector_width = record.vector_width,
        note         = (record.note + " | " + note) if record.note else note,
        compiler     = record.compiler,
    )


def _deduplicate(records: list[VectorizationRecord]) -> list[VectorizationRecord]:
    """
    Supprime les doublons : même fichier + ligne.
    On garde le record avec la cause la plus informative.
    """
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