# vec-audit

Analyse la vectorisation de ton code C/C++ et t'explique pourquoi certaines boucles ne sont pas optimisées — avec des suggestions concrètes pour les corriger.

---

## Installation

```bash
git clone https://github.com/Thedtk24/vec-audit
cd vec-audit
pip install -e .
```

**Prérequis :** Python 3.11+, GCC ou Clang.

Sur Linux :
```bash
sudo apt install gcc  
```

---

## Utilisation

### Commande principale

```bash
vec-audit audit mon_code.c
```

Sur Mac

```bash
vec-audit audit mon_code.c --gcc gcc-15 # Mettez votre version de gcc
```

### Avec Clang

```bash
vec-audit audit mon_code.c --clang
```

### Exporter un rapport HTML

```bash
vec-audit audit mon_code.c --gcc gcc-15 --html rapport.html
```

### Auditer un rapport déjà généré

```bash
# Générer le rapport manuellement
gcc -O3 -march=native -fopt-info-vec-missed -c mon_code.c 2> rapport.txt

# L'auditer
vec-audit parse rapport.txt --source mon_code.c
```

---

## Ce que tu vois dans le rapport

```
✗ mon_code.c:24  aliasing
  → Ajouter __restrict__ sur les pointeurs

✗ mon_code.c:38  control flow
  → Remplacer le if par une expression conditionnelle

✓ mon_code.c:12  vectorisée (32 bytes)
```

Pour chaque boucle non vectorisée, vec-audit t'indique :
- la **ligne** concernée dans ton code
- la **cause** précise (aliasing, control flow, data dependence...)
- une **suggestion de correction** avec exemple de code
- un **lien vers la documentation** officielle

---

## Causes détectées

| Cause | Description | Solution rapide |
|---|---|---|
| `aliasing` | Deux pointeurs peuvent se chevaucher | Ajouter `__restrict__` |
| `control flow` | `if` dans le corps de la boucle | Utiliser une expression ternaire |
| `data dependence` | `a[i]` dépend de `a[i-1]` | Restructurer l'algorithme |
| `unknown trip count` | Borne de boucle inconnue | Copier la borne dans une variable locale |
| `data alignment` | Données mal alignées | Utiliser `alignas(32)` |
| `function call` | Appel de fonction non inlinable | Ajouter `inline` ou `always_inline` |
| `reduction` | Somme/max non reconnue | Utiliser `-ffast-math` |

---

## Options

```
vec-audit audit <fichier> [options]

  --gcc BINAIRE     Binaire GCC à utiliser (défaut: gcc)
                    Ex: --gcc gcc-15 sur Mac avec Homebrew
  --clang           Utiliser Clang au lieu de GCC
  --html FICHIER    Exporter le rapport en HTML
  --flags FLAG...   Flags de compilation supplémentaires
  --verbose / -v    Afficher aussi les boucles vectorisées

vec-audit parse <rapport> [options]

  --compiler        gcc ou clang (défaut: gcc)
  --source FICHIER  Fichier source pour afficher les extraits de code
  --html FICHIER    Exporter le rapport en HTML
```

---

## Contribuer

Les suggestions de vec-audit sont basées sur un catalogue de patterns dans `vec_audit/parsers/gcc.py` et `vec_audit/diagnostics/engine.py`.

Si tu rencontres un message de compilateur non reconnu (`unknown`), c'est une opportunité de contribution :

1. Note le message brut affiché dans le rapport
2. Ajoute le pattern dans `_FAILURE_PATTERNS` (parser)
3. Ajoute la suggestion dans `_SUGGESTIONS` (engine)
4. Ouvre une Pull Request

---

## Licence

MIT