"""
vec-audit — reporter JSON
Export machine-readable pour CI/CD et historique.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from vec_audit.models import AuditReport, FailureKind, VectorizationStatus


_KIND_LABEL = {
    FailureKind.ALIASING:           "aliasing",
    FailureKind.CONTROL_FLOW:       "control_flow",
    FailureKind.UNKNOWN_TRIP_COUNT: "unknown_trip_count",
    FailureKind.DATA_DEPENDENCE:    "data_dependence",
    FailureKind.NOT_PROFITABLE:     "not_profitable",
    FailureKind.DATA_ALIGNMENT:     "data_alignment",
    FailureKind.FUNCTION_CALL:      "function_call",
    FailureKind.REDUCTION:          "reduction",
    FailureKind.OUTER_LOOP:         "outer_loop",
    FailureKind.UNSUPPORTED_TYPE:   "unsupported_type",
    FailureKind.UNKNOWN_CAUSE:      "unknown",
}


def export_json(report: AuditReport, output_path: Path,
                benchmark: dict | None = None,
                compiler_comparison: dict | None = None) -> None:
    loops = []
    for r in report.results:
        rec = r.record
        loc = rec.location
        entry = {
            "file":         loc.file,
            "line":         loc.line,
            "status":       "vectorized" if rec.is_vectorized else "missed",
            "function":     None,
            "failure_kind": _KIND_LABEL.get(rec.failure_kind) if rec.is_missed else None,
            "vector_width": rec.vector_width,
            "compiler":     rec.compiler,
            "raw_message":  rec.raw_message,
            "suggestions":  [
                {
                    "title":       s.title,
                    "fix":         s.fix,
                    "doc_url":     s.doc_url,
                }
                for s in r.suggestions
            ],
        }
        loops.append(entry)

    data = {
        "vec_audit_version": "0.1.0",
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "source_file":       report.source_file,
        "compiler":          report.compiler,
        "compiler_flags":    report.compiler_flags,
        "summary": {
            "total":               report.total,
            "vectorized":          report.vectorized_count,
            "missed":              report.missed_count,
            "vectorization_rate":  round(report.vectorization_rate, 1),
            "failures_by_kind":    {
                _KIND_LABEL.get(k, "unknown"): v
                for k, v in report.missed_by_kind().items()
            },
        },
        "loops":             loops,
    }

    if benchmark:
        data["benchmark"] = benchmark
    if compiler_comparison:
        data["compiler_comparison"] = compiler_comparison

    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )