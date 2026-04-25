"""
vec-audit — modèles de données centraux
========================================
Ces dataclasses représentent le résultat normalisé d'un rapport de
vectorisation, indépendamment du compilateur source (GCC, Clang, ICC).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path


class VectorizationStatus(Enum):
    """Résultat de la tentative de vectorisation d'une boucle."""
    VECTORIZED   = auto()   # boucle vectorisée avec succès
    MISSED       = auto()   # boucle non vectorisée (raison connue)
    PARTIAL      = auto()   # vectorisation partielle (ex: peeling, remainder)
    UNKNOWN      = auto()   # statut non déterminable depuis le rapport


class FailureKind(Enum):
    """
    Catalogue normalisé des causes d'échec de vectorisation.
    Chaque valeur correspond à une ou plusieurs règles de diagnostic.
    """
    ALIASING          = auto()   # possible chevauchement de pointeurs
    CONTROL_FLOW      = auto()   # if/switch dans le corps de boucle
    UNKNOWN_TRIP_COUNT= auto()   # borne de boucle inconnue à la compile
    DATA_DEPENDENCE   = auto()   # dépendance entre itérations (ex: a[i] = a[i-1])
    NOT_PROFITABLE    = auto()   # compilateur estime le gain insuffisant
    DATA_ALIGNMENT    = auto()   # données non alignées en mémoire
    FUNCTION_CALL     = auto()   # appel de fonction non inlinable dans la boucle
    UNSUPPORTED_TYPE  = auto()   # type de données non supporté (ex: int8 avec certains flags)
    REDUCTION         = auto()   # réduction complexe non reconnue
    OUTER_LOOP        = auto()   # boucle externe non vectorisée (inner only)
    UNKNOWN_CAUSE     = auto()   # cause non identifiée dans notre catalogue


@dataclass
class SourceLocation:
    """Localisation précise dans le fichier source."""
    file:   str        # chemin du fichier source
    line:   int        # numéro de ligne (1-indexed)
    column: int = 0    # colonne (optionnel, pas toujours présent)

    def __str__(self) -> str:
        base = f"{self.file}:{self.line}"
        return f"{base}:{self.column}" if self.column else base


@dataclass
class VectorizationRecord:
    """
    Représente le résultat de vectorisation d'UNE boucle.
    C'est l'unité atomique de vec-audit.
    """
    location:     SourceLocation
    status:       VectorizationStatus
    raw_message:  str                           # message brut du compilateur
    failure_kind: FailureKind = FailureKind.UNKNOWN_CAUSE
    vector_width: int | None  = None            # largeur vectorielle (bytes), si connue
    note:         str         = ""              # message de contexte additionnel
    compiler:     str         = "unknown"       # "gcc", "clang", "icc"

    @property
    def is_vectorized(self) -> bool:
        return self.status == VectorizationStatus.VECTORIZED

    @property
    def is_missed(self) -> bool:
        return self.status in (VectorizationStatus.MISSED, VectorizationStatus.PARTIAL)


@dataclass
class Suggestion:
    """
    Suggestion de correction produite par le moteur de diagnostic.
    """
    title:       str         # titre court (affiché dans le rapport)
    explanation: str         # explication détaillée du problème
    fix:         str         # suggestion concrète de modification du code
    example:     str = ""    # exemple de code corrigé (optionnel)
    doc_url:     str = ""    # lien vers documentation de référence


@dataclass
class DiagnosticResult:
    """
    Résultat enrichi pour un VectorizationRecord : le record original
    plus les suggestions produites par le moteur de diagnostic.
    """
    record:      VectorizationRecord
    suggestions: list[Suggestion] = field(default_factory=list)

    @property
    def location(self) -> SourceLocation:
        return self.record.location

    @property
    def has_suggestions(self) -> bool:
        return bool(self.suggestions)


@dataclass
class AuditReport:
    """
    Rapport complet d'un audit vec-audit sur un fichier ou projet.
    Contient tous les DiagnosticResult et des statistiques globales.
    """
    source_file:    str
    compiler:       str
    compiler_flags: str
    results:        list[DiagnosticResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def vectorized_count(self) -> int:
        return sum(1 for r in self.results if r.record.is_vectorized)

    @property
    def missed_count(self) -> int:
        return sum(1 for r in self.results if r.record.is_missed)

    @property
    def vectorization_rate(self) -> float:
        return (self.vectorized_count / self.total * 100) if self.total else 0.0

    def missed_by_kind(self) -> dict[FailureKind, int]:
        """Retourne le compte des échecs par catégorie."""
        counts: dict[FailureKind, int] = {}
        for r in self.results:
            if r.record.is_missed:
                k = r.record.failure_kind
                counts[k] = counts.get(k, 0) + 1
        return counts
