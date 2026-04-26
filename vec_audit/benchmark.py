"""
vec-audit — benchmark avant/après vectorisation
Compare les performances avec et sans vectorisation pour chaque fonction.
Utilise clock_gettime via un harness C généré automatiquement.
"""
from __future__ import annotations

import subprocess
import tempfile
import re
from pathlib import Path


_HARNESS_TEMPLATE = '''
#include <time.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define N 1000000
#define RUNS 50

static double now_ms(void) {{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}}

/* Include the source under test */
{include_line}

int main(void) {{
    /* Allocate aligned arrays */
    float *a = (float*)aligned_alloc(64, N * sizeof(float));
    float *b = (float*)aligned_alloc(64, N * sizeof(float));
    float *c = (float*)aligned_alloc(64, N * sizeof(float));

    for (int i = 0; i < N; i++) {{
        a[i] = (float)i * 0.001f;
        b[i] = (float)(N - i) * 0.001f;
        c[i] = 0.0f;
    }}

    /* Warm-up */
    {call_line}

    double best = 1e18;
    for (int r = 0; r < RUNS; r++) {{
        double t0 = now_ms();
        {call_line}
        double t1 = now_ms();
        double elapsed = t1 - t0;
        if (elapsed < best) best = elapsed;
    }}

    printf("%.4f\\n", best);

    free(a); free(b); free(c);
    return 0;
}}
'''

# Fonctions que l'on sait benchmarker automatiquement
# (signature connue avec float*, float*, float*, int)
_KNOWN_SIGNATURES: dict[str, str] = {
    r"void\s+(\w+)\s*\(\s*float\s*\*[^,]*,\s*float\s*\*[^,]*,\s*float\s*\*[^,]*,\s*int": "abc_n",
    r"void\s+(\w+)\s*\(\s*float\s*\*[^,]*,\s*float\s*\*[^,]*,\s*int":                    "ab_n",
    r"void\s+(\w+)\s*\(\s*float\s*\*[^,]*,\s*int":                                         "a_n",
}


def _detect_benchmarkable(source_lines: list[str]) -> list[tuple[str, str]]:
    """Retourne [(nom_fonction, signature_type)] pour les fonctions benchmarkables."""
    source = "\n".join(source_lines)
    results = []
    for pattern, sig_type in _KNOWN_SIGNATURES.items():
        for m in re.finditer(pattern, source):
            name = m.group(1)
            if name not in [n for n, _ in results]:
                results.append((name, sig_type))
    return results


def _call_for_sig(name: str, sig_type: str) -> str:
    if sig_type == "abc_n":
        return f"{name}(a, b, c, N);"
    if sig_type == "ab_n":
        return f"{name}(a, b, N);"
    if sig_type == "a_n":
        return f"{name}(a, N);"
    return ""


def _run_bench(source: Path, compiler: str, flags: list[str],
               func_name: str, call_line: str) -> float | None:
    """
    Compile et exécute un harness de benchmark.
    Retourne le temps minimal en ms, ou None si échec.
    """
    harness = _HARNESS_TEMPLATE.format(
        include_line=f'#include "{source.resolve()}"',
        call_line=call_line,
    )

    with tempfile.NamedTemporaryFile(suffix=".c", mode="w",
                                     delete=False) as f:
        f.write(harness)
        harness_path = Path(f.name)

    exe_path = harness_path.with_suffix("")

    try:
        r = subprocess.run(
            [compiler, *flags, str(harness_path), "-o", str(exe_path), "-lm"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return None

        r2 = subprocess.run(
            [str(exe_path)], capture_output=True, text=True, timeout=15,
        )
        if r2.returncode != 0:
            return None

        return float(r2.stdout.strip())

    except (subprocess.TimeoutExpired, ValueError):
        return None
    finally:
        harness_path.unlink(missing_ok=True)
        exe_path.unlink(missing_ok=True)


def run_benchmark(
    source: Path,
    compiler: str,
    source_lines: list[str],
) -> list[dict]:
    """
    Benchmark chaque fonction détectée avec et sans vectorisation.
    Retourne une liste de résultats avec speedup calculé.
    """
    functions = _detect_benchmarkable(source_lines)
    if not functions:
        return []

    base_flags   = ["-O3", "-march=native"]
    novec_flags  = ["-O3", "-march=native", "-fno-tree-vectorize"]

    results = []
    for func_name, sig_type in functions:
        call_line = _call_for_sig(func_name, sig_type)
        if not call_line:
            continue

        print(f"  Benchmarking {func_name}()...")

        t_vec   = _run_bench(source, compiler, base_flags,  func_name, call_line)
        t_novec = _run_bench(source, compiler, novec_flags, func_name, call_line)

        if t_vec is None or t_novec is None:
            continue

        speedup = t_novec / t_vec if t_vec > 0 else 1.0

        results.append({
            "function":       func_name,
            "time_vec_ms":    round(t_vec, 4),
            "time_novec_ms":  round(t_novec, 4),
            "speedup":        round(speedup, 2),
            "improvement_pct": round((speedup - 1) * 100, 1),
        })

    return sorted(results, key=lambda x: -x["speedup"])