"""
vec-audit — reporter HTML (clean)
"""

from __future__ import annotations
import html as html_mod
from pathlib import Path

from vec_audit.models import AuditReport, FailureKind


_KIND_LABEL: dict[FailureKind, str] = {
    FailureKind.ALIASING:           "aliasing",
    FailureKind.CONTROL_FLOW:       "control flow",
    FailureKind.UNKNOWN_TRIP_COUNT: "unknown trip count",
    FailureKind.DATA_DEPENDENCE:    "data dependence",
    FailureKind.NOT_PROFITABLE:     "not profitable",
    FailureKind.DATA_ALIGNMENT:     "data alignment",
    FailureKind.FUNCTION_CALL:      "function call",
    FailureKind.REDUCTION:          "reduction",
    FailureKind.OUTER_LOOP:         "outer loop",
    FailureKind.UNSUPPORTED_TYPE:   "unsupported type",
    FailureKind.UNKNOWN_CAUSE:      "unknown",
}


def _snippet(source_lines: list[str], target: int, ctx: int = 2) -> str:
    if not source_lines or not (0 < target <= len(source_lines)):
        return ""
    start = max(0, target - 1 - ctx)
    end   = min(len(source_lines), target + ctx)
    rows  = ""
    for ln, src in enumerate(source_lines[start:end], start=start + 1):
        hl      = ' style="background:#fff5f5;"' if ln == target else ""
        underline = ' style="border-bottom:1px solid #fca5a5;"' if ln == target else ""
        escaped = html_mod.escape(src) if src.strip() else "&nbsp;"
        rows += (
            f'<div{hl}>'
            f'<span style="color:#d1d5db;user-select:none;display:inline-block;'
            f'width:3rem;text-align:right;padding-right:1rem;'
            f'border-right:1px solid #f3f4f6;">{ln}</span>'
            f'<span{underline}> {escaped}</span>'
            f'</div>\n'
        )
    return (
        f'<div style="background:#f9fafb;border:1px solid #f0f0f0;border-radius:3px;'
        f'padding:1.25rem 1rem;margin-bottom:1.5rem;overflow-x:auto;">'
        f'<pre style="margin:0;font-family:\'JetBrains Mono\',monospace;'
        f'font-size:0.82rem;line-height:1.7;color:#374151;">{rows}</pre></div>'
    )


def _render(report: AuditReport, source_lines: list[str] | None) -> str:
    missed = [r for r in report.results if r.record.is_missed]
    vecs   = [r for r in report.results if r.record.is_vectorized]
    rate   = report.vectorization_rate
    fname  = report.source_file.split("/")[-1]

    # --- Missed sections ---
    sections = ""
    for i, result in enumerate(missed):
        rec   = result.record
        loc   = rec.location
        kind  = _KIND_LABEL.get(rec.failure_kind, "unknown")
        s     = result.suggestions[0] if result.suggestions else None

        recommendation = ""
        if s:
            ex = ""
            if s.example:
                ex = (
                    f'<pre style="margin:0.75rem 0 0;background:#f9fafb;border:1px solid #f0f0f0;'
                    f'border-radius:3px;padding:0.75rem 1rem;font-family:\'JetBrains Mono\',monospace;'
                    f'font-size:0.8rem;color:#374151;overflow-x:auto;white-space:pre;">'
                    f'{html_mod.escape(s.example)}</pre>'
                )
            doc = ""
            if s.doc_url:
                doc = (
                    f'<p style="font-size:0.72rem;color:#9ca3af;margin-top:0.5rem;">'
                    f'<a href="{s.doc_url}" style="color:#9ca3af;" target="_blank">{s.doc_url}</a></p>'
                )
            recommendation = (
                f'<div style="border-left:2px solid #1a1a1a;padding-left:1.5rem;padding-top:0.1rem;">'
                f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:0.1em;margin-bottom:0.4rem;">Recommendation</div>'
                f'<p style="font-size:0.875rem;color:#6b7280;font-style:italic;margin:0;">'
                f'{html_mod.escape(s.fix)}</p>{ex}{doc}</div>'
            )

        divider = (
            '<div style="height:1px;background:#f0f0f0;margin:0 0 3.5rem;"></div>'
            if i < len(missed) - 1 else ""
        )

        sections += (
            f'<section style="margin-bottom:3.5rem;">'
            f'<div style="display:flex;align-items:baseline;gap:1rem;margin-bottom:1rem;flex-wrap:wrap;">'
            f'<h2 style="font-size:1.15rem;font-weight:500;margin:0;">Loop at line {loc.line}</h2>'
            f'<span style="font-size:0.75rem;color:#9ca3af;">'
            f'in {html_mod.escape(loc.file)}</span>'
            f'<span style="margin-left:auto;font-size:0.65rem;font-weight:700;'
            f'background:#fff5f5;color:#dc2626;padding:0.2rem 0.6rem;'
            f'border-radius:3px;text-transform:uppercase;">{kind}</span>'
            f'</div>'
            f'<p style="font-size:0.875rem;color:#6b7280;line-height:1.7;margin-bottom:1.5rem;">'
            f'Vectorization failed due to a '
            f'<strong style="color:#1a1a1a;">{kind}</strong> issue.</p>'
            f'{_snippet(source_lines or [], loc.line)}'
            f'{recommendation}'
            f'</section>'
            f'{divider}'
        )

    # --- Vectorized (compact list) ---
    if vecs:
        if missed:
            sections += '<div style="height:1px;background:#f0f0f0;margin:0 0 3.5rem;"></div>'
        items = "".join(
            f'<div style="display:flex;align-items:baseline;gap:1rem;'
            f'margin-bottom:1.25rem;flex-wrap:wrap;">'
            f'<h2 style="font-size:1.15rem;font-weight:500;margin:0;">'
            f'Loop at line {r.record.location.line}</h2>'
            f'<span style="font-size:0.75rem;color:#9ca3af;">'
            f'in {html_mod.escape(r.record.location.file)}</span>'
            f'<span style="margin-left:auto;font-size:0.65rem;font-weight:700;'
            f'background:#f0fdf4;color:#16a34a;padding:0.2rem 0.6rem;'
            f'border-radius:3px;text-transform:uppercase;">'
            f'VECTORIZED'
            f'{"&nbsp;·&nbsp;" + str(r.record.vector_width) + "B" if r.record.vector_width else ""}'
            f'</span></div>'
            for r in vecs
        )
        sections += f'<section>{items}</section>'

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>vec-audit | {html_mod.escape(fname)}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: \'Inter\', -apple-system, sans-serif;
    background: #fff;
    color: #1a1a1a;
    font-size: 14px;
    line-height: 1.6;
    padding: 3rem;
    max-width: 820px;
    margin: 0 auto;
  }}
  a {{ color: inherit; }}
</style>
</head>
<body>

  <!-- Header -->
  <header style="border-bottom:1px solid #f0f0f0;padding-bottom:1.25rem;margin-bottom:3rem;">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;">
      <span style="font-size:0.875rem;font-weight:600;letter-spacing:-0.01em;text-transform:uppercase;">
        vec-audit <span style="color:#9ca3af;font-weight:300;">/ {html_mod.escape(fname)}</span>
      </span>
      <div style="display:flex;gap:1.5rem;font-size:0.75rem;font-weight:500;align-items:center;">
        <div style="display:flex;align-items:center;gap:0.4rem;">
          <span style="height:7px;width:7px;border-radius:50%;background:#22c55e;display:inline-block;"></span>
          {report.vectorized_count} vectorized
        </div>
        <div style="display:flex;align-items:center;gap:0.4rem;">
          <span style="height:7px;width:7px;border-radius:50%;background:#f87171;display:inline-block;"></span>
          {report.missed_count} failed
        </div>
        <span style="color:#d1d5db;">|</span>
        <span style="color:#9ca3af;font-weight:300;">{rate:.0f}%</span>
      </div>
    </div>
    <div style="margin-top:0.4rem;font-size:0.7rem;color:#9ca3af;font-style:italic;">
      {html_mod.escape(report.compiler)} &nbsp; {html_mod.escape(report.compiler_flags or "")}
    </div>
  </header>

  <!-- Content -->
  <main>
    {sections}
  </main>

</body>
</html>'''


class HTMLReporter:

    def __init__(self, source_lines: list[str] | None = None):
        self.source_lines = source_lines

    def render(self, report: AuditReport, output_path: Path) -> None:
        output_path.write_text(_render(report, self.source_lines), encoding="utf-8")