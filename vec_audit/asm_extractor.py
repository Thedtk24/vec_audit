"""
vec-audit — extracteur ASM par fonction
Compatible Linux (x86 GNU objdump) et Mac ARM (Apple objdump / otool)
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


# --- Détection SIMD x86 (ymm/zmm/xmm, instructions AVX) ---
_SIMD_X86 = re.compile(
    r"\b(ymm\d+|zmm\d+|xmm\d+)\b"
    r"|\b(vmovups|vmovaps|vaddps|vaddpd|vmulps|vmulpd"
    r"|vfmadd\w+|vperm\w+|vbroadcast\w+|vzeroupper"
    r"|vaddss|vmovss|vaddsd|vmovsd)\b",
    re.I,
)

# --- Détection SIMD ARM NEON (registres v0-v31, q0-q31, instructions vectorielles) ---
_SIMD_ARM = re.compile(
    r"\b(v\d+\.\d+[bhsd]|q\d+)\b"          # v0.4s, v1.2d, q0, q31...
    r"|\b(fadd\.\w+|fmul\.\w+|fmla\.\w+"   # fadd.4s, fmul.2d...
    r"|ld[1-4]\b|st[1-4]\b"                 # ld1, st1...
    r"|ldr\s+q|str\s+q"                     # ldr q0, str q31
    r"|fmov\s+v|dup\s+v|zip\w*\s+v"        # fmov v0, dup v1...
    r"|trn\w*\s+v|uzp\w*\s+v)\b",
    re.I,
)

# Format GNU objdump x86  : "   0:\tendbr64"
_GNU_INSTR_RE  = re.compile(r"^\s+[0-9a-f]+:\s+(.+)$")
# Format Apple objdump ARM: "       0:      \tcmp\tw3, #0x0"
_APPLE_INSTR_RE = re.compile(r"^\s+[0-9a-f]+:\s+\t(.+)$")

# Fonction GNU  : "deadbeef <func_name>:"
_GNU_FUNC_RE   = re.compile(r"^[0-9a-f]+ <([^>]+)>:$")
# Fonction Apple: "deadbeef <_func_name> or <ltmp0>:"
_APPLE_FUNC_RE = re.compile(r"^[0-9a-f]+ <([^>]+)>:$")


def _detect_simd(line: str, is_arm: bool) -> bool:
    if is_arm:
        return bool(_SIMD_ARM.search(line))
    return bool(_SIMD_X86.search(line))


@dataclass
class AsmBlock:
    function:    str
    lines:       list[str] = field(default_factory=list)
    has_simd:    bool      = False
    simd_instrs: list[str] = field(default_factory=list)
    is_arm:      bool      = False

    def annotated_lines(self) -> list[tuple[str, bool]]:
        return [(l, _detect_simd(l, self.is_arm)) for l in self.lines]


def _is_arm_target(output: str) -> bool:
    """Détecte si la cible est ARM depuis l'en-tête objdump."""
    return "arm64" in output.lower() or "aarch64" in output.lower()


def extract_asm(
    source: Path,
    compiler: str = "gcc",
    extra_flags: list[str] | None = None,
) -> dict[str, AsmBlock]:
    """Compile et extrait l'ASM. Compatible Linux x86 et Mac ARM."""

    if not shutil.which(compiler):
        return {}

    flags = ["-O3", "-march=native", "-g"] + (extra_flags or [])

    with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as tmp:
        obj_path = Path(tmp.name)

    try:
        r = subprocess.run(
            [compiler, *flags, "-c", str(source), "-o", str(obj_path)],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not obj_path.exists():
            return {}

        # objdump universel (GNU sur Linux, Apple sur Mac)
        if shutil.which("objdump"):
            dump = subprocess.run(
                ["objdump", "-d", "--no-show-raw-insn", str(obj_path)],
                capture_output=True, text=True,
            )
            if dump.returncode == 0 and "Disassembly" in dump.stdout:
                is_arm = _is_arm_target(dump.stdout)
                return _parse_objdump(dump.stdout, is_arm=is_arm)

        return {}

    finally:
        obj_path.unlink(missing_ok=True)


def _parse_objdump(output: str, is_arm: bool = False) -> dict[str, AsmBlock]:
    """
    Parse la sortie objdump (GNU et Apple).
    Sur Mac ARM, les fonctions peuvent apparaître comme <ltmp0> ou <_func_name>.
    On garde une table de correspondance ltmpN → nom réel.
    """
    blocks:  dict[str, AsmBlock] = {}
    current: AsmBlock | None     = None

    # Regex d'instruction : Apple a des tabs supplémentaires
    instr_re = _APPLE_INSTR_RE if is_arm else _GNU_INSTR_RE

    for line in output.splitlines():

        # Nouveau bloc fonction
        m = _GNU_FUNC_RE.match(line) or _APPLE_FUNC_RE.match(line)
        if m:
            raw_name = m.group(1)

            # Nettoyer le nom : enlever le préfixe "_" (convention Mac)
            # et ignorer les symboles internes
            name = raw_name.lstrip("_")
            if "@" in name or name.startswith("__"):
                current = None
                continue

            current = AsmBlock(function=name, is_arm=is_arm)
            blocks[name] = current
            continue

        if current is None:
            continue

        # Ligne d'instruction
        m = instr_re.match(line)
        if m:
            instr = m.group(1).strip()
            current.lines.append(instr)
            if _detect_simd(instr, is_arm):
                current.has_simd = True
                current.simd_instrs.append(instr)

    return blocks


def find_function_for_line(
    source_lines: list[str],
    target_line: int,
) -> str | None:
    """
    Trouve le nom de la fonction C/C++ qui contient la ligne cible.
    Parcourt le source en comptant les accolades pour déterminer
    dans quelle fonction on se trouve.
    """
    func_name_re = re.compile(r"\b([a-zA-Z_]\w*)\s*\(")
    keywords = {
        "if", "for", "while", "switch", "else", "do", "return",
        "sizeof", "typedef", "struct", "enum", "union", "alignas",
    }

    brace_depth = 0
    last_func   = None

    for i, line in enumerate(source_lines[:target_line], start=1):
        stripped = line.strip()

        if stripped.startswith("//") or stripped.startswith("*"):
            continue

        # Chercher un nom de fonction quand on est au niveau 0 (pas dans un corps)
        if brace_depth == 0:
            m = func_name_re.search(stripped)
            if m:
                candidate = m.group(1)
                if candidate not in keywords and not stripped.startswith("#"):
                    last_func = candidate

        brace_depth += stripped.count("{") - stripped.count("}")
        brace_depth  = max(0, brace_depth)

    return last_func