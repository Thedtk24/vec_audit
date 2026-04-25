"""
vec-audit — moteur de diagnostic
==================================
Prend un VectorizationRecord et produit un DiagnosticResult enrichi
avec des Suggestion concrètes et actionnables.

C'est ici que réside la valeur ajoutée de vec-audit par rapport
aux rapports bruts des compilateurs.
"""

from __future__ import annotations

from vec_audit.models import (
    AuditReport,
    DiagnosticResult,
    FailureKind,
    Suggestion,
    VectorizationRecord,
    VectorizationStatus,
)


# ---------------------------------------------------------------------------
# Catalogue de suggestions par FailureKind
# ---------------------------------------------------------------------------

_SUGGESTIONS: dict[FailureKind, Suggestion] = {

    FailureKind.ALIASING: Suggestion(
        title="Possible aliasing de pointeurs",
        explanation=(
            "Le compilateur ne peut pas prouver que deux pointeurs ne pointent "
            "pas vers la même zone mémoire (aliasing). Par sécurité, il refuse "
            "de vectoriser car réordonner les accès pourrait changer le résultat."
        ),
        fix=(
            "Ajouter le qualificateur `__restrict__` sur les paramètres pointeurs "
            "pour indiquer au compilateur qu'ils ne se chevauchent pas. "
            "Alternativement, utiliser `#pragma GCC ivdep` avant la boucle."
        ),
        example=(
            "// Avant :\n"
            "void add(float *a, float *b, float *c, int n) { ... }\n\n"
            "// Après (__restrict__) :\n"
            "void add(float * __restrict__ a,\n"
            "         float * __restrict__ b,\n"
            "         float * __restrict__ c, int n) { ... }\n\n"
            "// Ou avec pragma (moins sûr — toi qui garantis l'absence d'alias) :\n"
            "#pragma GCC ivdep\n"
            "for (int i = 0; i < n; i++) { c[i] = a[i] + b[i]; }"
        ),
        doc_url="https://gcc.gnu.org/onlinedocs/gcc/Restricted-Pointers.html",
    ),

    FailureKind.CONTROL_FLOW: Suggestion(
        title="Branchement conditionnel dans la boucle",
        explanation=(
            "La présence d'un `if`, `switch`, ou `break` à l'intérieur du corps "
            "de la boucle empêche la vectorisation directe. Les instructions SIMD "
            "opèrent sur toutes les lanes simultanément et n'acceptent pas de chemins "
            "d'exécution divergents."
        ),
        fix=(
            "Remplacer la condition par une opération de sélection (masque). "
            "Utiliser des opérations arithmétiques inconditionnelles avec masquage, "
            "ou restructurer la boucle pour séparer les cas."
        ),
        example=(
            "// Avant (non vectorisable) :\n"
            "for (int i = 0; i < n; i++) {\n"
            "    if (a[i] > 0) b[i] = a[i] * 2.0f;\n"
            "}\n\n"
            "// Après (vectorisable — expression conditionnelle) :\n"
            "for (int i = 0; i < n; i++) {\n"
            "    b[i] = (a[i] > 0) ? a[i] * 2.0f : b[i];\n"
            "}\n\n"
            "// Ou avec un masque arithmétique :\n"
            "for (int i = 0; i < n; i++) {\n"
            "    float mask = (float)(a[i] > 0);\n"
            "    b[i] += mask * a[i] * 2.0f;\n"
            "}"
        ),
        doc_url="https://llvm.org/docs/Vectorizers.html#if-conversion",
    ),

    FailureKind.UNKNOWN_TRIP_COUNT: Suggestion(
        title="Borne de boucle inconnue à la compilation",
        explanation=(
            "Le compilateur ne peut pas déterminer statiquement le nombre "
            "d'itérations. Cela empêche le calcul du prologue/épilogue scalaire "
            "nécessaire pour gérer les restes de division (ex: n non multiple de 4)."
        ),
        fix=(
            "Copier la borne de la boucle dans une variable locale `const` avant "
            "la boucle. Éviter les bornes lues depuis des pointeurs ou des "
            "champs de structures complexes. Ajouter `__builtin_expect` si pertinent."
        ),
        example=(
            "// Avant (borne possiblement indirecte) :\n"
            "for (int i = 0; i < obj->size; i++) { ... }\n\n"
            "// Après (borne locale, plus analysable) :\n"
            "const int n = obj->size;\n"
            "for (int i = 0; i < n; i++) { ... }"
        ),
        doc_url="https://gcc.gnu.org/projects/tree-ssa/vectorization.html",
    ),

    FailureKind.DATA_DEPENDENCE: Suggestion(
        title="Dépendance entre itérations",
        explanation=(
            "Une itération dépend du résultat d'une itération précédente "
            "(ex: `a[i] = a[i-1] + x`). Vectoriser reviendrait à calculer "
            "plusieurs itérations simultanément, ce qui produirait un résultat incorrect."
        ),
        fix=(
            "Si la dépendance est 'fausse' (tu sais que les zones mémoire ne se "
            "chevauchent pas), utiliser `#pragma GCC ivdep`. Sinon, envisager de "
            "restructurer l'algorithme (ex: prefix sum parallèle)."
        ),
        example=(
            "// Dépendance vraie — ne peut pas être vectorisée simplement :\n"
            "for (int i = 1; i < n; i++) { a[i] = a[i-1] + b[i]; }\n\n"
            "// Si dépendance fausse (tu le sais) :\n"
            "#pragma GCC ivdep\n"
            "for (int i = 0; i < n; i++) { ... }"
        ),
        doc_url="https://gcc.gnu.org/projects/tree-ssa/vectorization.html",
    ),

    FailureKind.NOT_PROFITABLE: Suggestion(
        title="Vectorisation jugée non rentable",
        explanation=(
            "Le compilateur estime que le coût de mise en place de la vectorisation "
            "(prologue, épilogue, conversions) dépasse le bénéfice attendu. "
            "Cela arrive souvent avec de petites boucles ou des types mixtes."
        ),
        fix=(
            "Vérifier que `-O3` est bien utilisé (pas seulement `-O2`). "
            "Augmenter la taille des données traitées. "
            "Utiliser `-fvec-cost-model=unlimited` pour forcer la vectorisation "
            "même quand le compilateur hésite (à utiliser avec mesure)."
        ),
        example=(
            "// Forcer avec un flag de compilation :\n"
            "gcc -O3 -march=native -fvec-cost-model=unlimited mon_code.c"
        ),
        doc_url="https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html",
    ),

    FailureKind.DATA_ALIGNMENT: Suggestion(
        title="Données non alignées en mémoire",
        explanation=(
            "Les instructions SIMD sont plus efficaces (parfois obligatoires) "
            "quand les données sont alignées sur 16, 32, ou 64 bytes selon "
            "l'extension (SSE, AVX, AVX-512). Des données mal alignées forcent "
            "le compilateur à générer du code scalaire ou des accès non-alignés lents."
        ),
        fix=(
            "Aligner les tableaux avec `alignas(32)` (C11/C++11) ou "
            "`__attribute__((aligned(32)))`. "
            "Pour les allocations dynamiques, utiliser `aligned_alloc()` ou "
            "`posix_memalign()`."
        ),
        example=(
            "// Tableaux statiques :\n"
            "alignas(32) float a[1024];\n\n"
            "// Allocation dynamique :\n"
            "float *a = (float*)aligned_alloc(32, n * sizeof(float));\n\n"
            "// Indiquer au compilateur qu'un pointeur est aligné :\n"
            "float *a_aligned = (float*)__builtin_assume_aligned(a, 32);"
        ),
        doc_url="https://gcc.gnu.org/onlinedocs/gcc/Vector-Extensions.html",
    ),

    FailureKind.FUNCTION_CALL: Suggestion(
        title="Appel de fonction non inlinable",
        explanation=(
            "La présence d'un appel de fonction dans le corps de la boucle "
            "bloque la vectorisation. Le compilateur ne peut pas vectoriser "
            "une fonction dont il ne voit pas le corps (liaison externe, "
            "fonction complexe non inlinée)."
        ),
        fix=(
            "Marquer la fonction appelée avec `inline` ou "
            "`__attribute__((always_inline))`. "
            "Si c'est une fonction de bibliothèque (ex: `sqrt`, `exp`), "
            "utiliser `-ffast-math` pour activer les versions vectorisées "
            "ou les intrinsèques SIMD directement."
        ),
        example=(
            "// Avant :\n"
            "float compute(float x) { return x * x + 1.0f; }\n"
            "for (int i = 0; i < n; i++) { b[i] = compute(a[i]); }\n\n"
            "// Après :\n"
            "static inline __attribute__((always_inline))\n"
            "float compute(float x) { return x * x + 1.0f; }\n\n"
            "// Pour fonctions math standard :\n"
            "gcc -O3 -ffast-math mon_code.c  // active sqrtf vectorisé, etc."
        ),
        doc_url="https://gcc.gnu.org/onlinedocs/gcc/Inline.html",
    ),

    FailureKind.REDUCTION: Suggestion(
        title="Réduction non vectorisée",
        explanation=(
            "Les opérations de réduction (somme, produit, min, max sur tous "
            "les éléments) sont vectorisables mais nécessitent que le compilateur "
            "reconnaisse le pattern. Avec `-O2` seul ou des types mixtes, "
            "il peut échouer à identifier la réduction."
        ),
        fix=(
            "Utiliser `-ffast-math` pour autoriser la réassociation flottante "
            "(attention : change légèrement les résultats numériques). "
            "Ou restructurer explicitement avec des accumulateurs locaux."
        ),
        example=(
            "// Avant (peut échouer) :\n"
            "double sum = 0.0;\n"
            "for (int i = 0; i < n; i++) sum += a[i] * b[i];\n\n"
            "// Avec -ffast-math : GCC vectorisera automatiquement.\n\n"
            "// Sans -ffast-math, accumulateurs multiples :\n"
            "double s0=0, s1=0, s2=0, s3=0;\n"
            "for (int i = 0; i < n-3; i+=4) {\n"
            "    s0 += a[i]*b[i]; s1 += a[i+1]*b[i+1];\n"
            "    s2 += a[i+2]*b[i+2]; s3 += a[i+3]*b[i+3];\n"
            "}\n"
            "double sum = s0 + s1 + s2 + s3;"
        ),
        doc_url="https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html#index-ffast-math",
    ),

    FailureKind.OUTER_LOOP: Suggestion(
        title="Boucle externe non vectorisée",
        explanation=(
            "GCC vectorise principalement les boucles internes. "
            "Si la boucle externe est signalée comme non vectorisée, "
            "c'est souvent parce que la boucle interne a déjà été vectorisée "
            "ou que la structure de données ne s'y prête pas."
        ),
        fix=(
            "Vérifier d'abord si la boucle interne est vectorisée. "
            "Si tu vises la vectorisation de la boucle externe, utiliser "
            "`-floop-nest-optimize` ou restructurer en boucle interne "
            "(loop interchange / tiling)."
        ),
        example=(
            "// Loop interchange : échanger boucles i et j si possible\n"
            "// pour que la boucle interne accède à la mémoire de façon contiguë.\n\n"
            "// Avant (accès colonne par colonne — mauvais) :\n"
            "for (int i = 0; i < N; i++)\n"
            "  for (int j = 0; j < M; j++) c[i] += a[j][i];\n\n"
            "// Après (accès ligne par ligne — bon) :\n"
            "for (int j = 0; j < M; j++)\n"
            "  for (int i = 0; i < N; i++) c[i] += a[j][i];"
        ),
        doc_url="https://gcc.gnu.org/projects/tree-ssa/vectorization.html",
    ),

    FailureKind.UNSUPPORTED_TYPE: Suggestion(
        title="Type de données non supporté",
        explanation=(
            "Le type utilisé dans la boucle (ex: `char`, `int8_t`, `long double`, "
            "ou un type structuré) n'est pas supporté par le vectoriseur pour "
            "cette cible ou ces flags de compilation."
        ),
        fix=(
            "Vérifier que `-march=native` est utilisé pour activer toutes les "
            "extensions disponibles sur ta machine. "
            "Si possible, utiliser `float` plutôt que `double` (2× plus de lanes). "
            "Éviter les types de largeur variable ou les types C++ avec opérateurs."
        ),
        example=(
            "// Préférer float à double pour maximiser le parallélisme SIMD :\n"
            "// float  : 8 valeurs / registre AVX2 (256 bits)\n"
            "// double : 4 valeurs / registre AVX2 (256 bits)\n\n"
            "gcc -O3 -march=native mon_code.c  // active SSE4, AVX2, AVX-512 si dispo"
        ),
        doc_url="https://gcc.gnu.org/projects/tree-ssa/vectorization.html",
    ),

    FailureKind.UNKNOWN_CAUSE: Suggestion(
        title="Cause non identifiée",
        explanation=(
            "Le rapport du compilateur ne correspond à aucun pattern "
            "connu dans le catalogue de vec-audit. "
            "La boucle n'est pas vectorisée mais la raison exacte n'a pas pu "
            "être classifiée automatiquement."
        ),
        fix=(
            "Consulter le message brut ci-dessous. "
            "Essayer `-fopt-info-vec-all` pour un rapport plus verbeux. "
            "Utiliser Compiler Explorer (godbolt.org) pour inspecter le code "
            "assembleur généré et identifier manuellement le problème."
        ),
        example="",
        doc_url="https://gcc.gnu.org/projects/tree-ssa/vectorization.html",
    ),
}


# ---------------------------------------------------------------------------
# Moteur de diagnostic
# ---------------------------------------------------------------------------

class DiagnosticEngine:
    """
    Enrichit les VectorizationRecord avec des suggestions concrètes.
    """

    def diagnose(self, record: VectorizationRecord) -> DiagnosticResult:
        """Produit un DiagnosticResult pour un record unique."""
        suggestions: list[Suggestion] = []

        if record.status == VectorizationStatus.VECTORIZED:
            # Boucle vectorisée : pas de suggestion, mais on peut noter la largeur
            return DiagnosticResult(record=record, suggestions=[])

        suggestion = _SUGGESTIONS.get(record.failure_kind)
        if suggestion:
            suggestions.append(suggestion)

        return DiagnosticResult(record=record, suggestions=suggestions)

    def diagnose_all(self, records: list[VectorizationRecord]) -> AuditReport:
        """
        Produit un AuditReport complet depuis une liste de records.
        Le source_file et le compiler sont déduits du premier record.
        """
        source_file = records[0].location.file if records else "unknown"
        compiler    = records[0].compiler if records else "unknown"

        results = [self.diagnose(r) for r in records]

        return AuditReport(
            source_file    = source_file,
            compiler       = compiler,
            compiler_flags = "",   # sera rempli par le CLI
            results        = results,
        )
