# vec-audit

Analyzes the vectorization of your C/C++ code and explains why certain loops are not optimized — with concrete suggestions to fix them.

---

## Installation

```bash
git clone https://github.com/Thedtk24/vec_audit
cd vec_audit
pip install -e .
```

**Prerequisites:** Python 3.11+, GCC or Clang.

On Linux:
```bash
sudo apt install gcc
```

On Mac with Homebrew:
```bash
brew install gcc   # installs gcc-14, gcc-15...
```

---

## Usage

### Main command

```bash
vec-audit audit my_code.c
```

### On Mac (GCC via Homebrew)

```bash
vec-audit audit my_code.c --gcc gcc-15   # use your gcc version
```

### With Clang

```bash
vec-audit audit my_code.c --clang
```

### Export an HTML report

```bash
vec-audit audit my_code.c --gcc gcc-15 --html report.html
```

### Audit an already generated report

```bash
# Generate the report manually
gcc -O3 -march=native -fopt-info-vec-missed -c my_code.c 2> report.txt

# Audit it
vec-audit parse report.txt --source my_code.c
```

---

## What you see in the report

```
✗ my_code.c:24  aliasing
  → Add __restrict__ on pointers

✗ my_code.c:38  control flow
  → Replace the if with a conditional expression

✓ my_code.c:12  vectorized (32 bytes)
```

For each non-vectorized loop, vec-audit tells you:

- The **line** concerned in your code
- The **precise cause** (aliasing, control flow, data dependence...)
- A **suggestion for correction** with a code example
- A **link to the official documentation**

---

## Detected causes

| Cause | Description | Quick solution |
|---|---|---|
| `aliasing` | Two pointers might overlap | Add `__restrict__` |
| `control flow` | `if` inside the loop body | Use a ternary expression |
| `data dependence` | `a[i]` depends on `a[i-1]` | Restructure the algorithm |
| `unknown trip count` | Unknown loop bound | Copy the bound into a local variable |
| `data alignment` | Misaligned data | Use `alignas(32)` |
| `function call` | Non-inlinable function call | Add `inline` or `always_inline` |
| `reduction` | Unrecognized sum/max | Use `-ffast-math` |

---

## Options

```
vec-audit audit <file> [options]

  --gcc BINARY      GCC binary to use (default: gcc)
                    Ex: --gcc gcc-15 on Mac with Homebrew
  --clang           Use Clang instead of GCC
  --html FILE       Export the report in HTML
  --flags FLAG...   Additional compilation flags
  --verbose / -v    Also display vectorized loops

vec-audit parse <report> [options]

  --compiler        gcc or clang (default: gcc)
  --source FILE     Source file to display code snippets
  --html FILE       Export the report in HTML
```

---

## Contributing

The suggestions from vec-audit are based on a pattern catalog in `vec_audit/parsers/gcc.py` and `vec_audit/diagnostics/engine.py`.

If you encounter an unrecognized compiler message (`unknown`), it's an opportunity to contribute:

1. Note the raw message displayed in the report
2. Add the pattern in `_FAILURE_PATTERNS` (parser)
3. Add the suggestion in `_SUGGESTIONS` (engine)
4. Open a Pull Request
