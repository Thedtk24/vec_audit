"""
vec-audit — historique et diff entre deux runs
Sauvegarde les rapports JSON et compare avec le précédent.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


_HISTORY_DIR = Path.home() / ".vec-audit" / "history"


def save_to_history(report_path: Path, source_file: str) -> Path:
    """Sauvegarde un rapport JSON dans l'historique local."""
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    # Nom de fichier basé sur le source et le timestamp
    stem    = Path(source_file).stem
    ts      = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest    = _HISTORY_DIR / f"{stem}_{ts}.json"

    dest.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def load_previous(source_file: str, skip: int = 0) -> dict | None:
    """Charge le rapport précédent pour un fichier source donné."""
    if not _HISTORY_DIR.exists():
        return None

    stem    = Path(source_file).stem
    matches = sorted(
        [f for f in _HISTORY_DIR.glob(f"{stem}_*.json")],
        reverse=True,
    )

    # skip=0 → dernier, skip=1 → avant-dernier (utile pour comparer avec l'actuel)
    if len(matches) <= skip:
        return None

    try:
        return json.loads(matches[skip].read_text(encoding="utf-8"))
    except Exception:
        return None


def diff_reports(current: dict, previous: dict) -> dict:
    """
    Compare deux rapports JSON et retourne les changements.
    """
    cur_rate  = current["summary"]["vectorization_rate"]
    prev_rate = previous["summary"]["vectorization_rate"]
    delta     = round(cur_rate - prev_rate, 1)

    # Loops par ligne dans chaque rapport
    cur_by_line  = {l["line"]: l for l in current["loops"]}
    prev_by_line = {l["line"]: l for l in previous["loops"]}

    newly_vectorized = []
    newly_missed     = []
    unchanged        = []

    for line, loop in cur_by_line.items():
        prev = prev_by_line.get(line)
        if prev is None:
            continue
        if loop["status"] == "vectorized" and prev["status"] == "missed":
            newly_vectorized.append({"line": line, "file": loop["file"]})
        elif loop["status"] == "missed" and prev["status"] == "vectorized":
            newly_missed.append({"line": line, "file": loop["file"]})
        else:
            unchanged.append(line)

    return {
        "current_rate":       cur_rate,
        "previous_rate":      prev_rate,
        "delta":              delta,
        "trend":              "improved" if delta > 0 else "regressed" if delta < 0 else "stable",
        "newly_vectorized":   newly_vectorized,
        "newly_missed":       newly_missed,
        "previous_timestamp": previous.get("timestamp", "unknown"),
    }


def list_history(source_file: str) -> list[dict]:
    """Liste l'historique des runs pour un fichier source."""
    if not _HISTORY_DIR.exists():
        return []

    stem    = Path(source_file).stem
    matches = sorted(
        [f for f in _HISTORY_DIR.glob(f"{stem}_*.json")],
        reverse=True,
    )

    result = []
    for f in matches[:10]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({
                "file":      str(f),
                "timestamp": data.get("timestamp", "unknown"),
                "rate":      data["summary"]["vectorization_rate"],
                "vectorized":data["summary"]["vectorized"],
                "missed":    data["summary"]["missed"],
            })
        except Exception:
            pass
    return result