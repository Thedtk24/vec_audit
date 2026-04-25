"""
vec-audit — reporter HTML (light theme)
"""

from __future__ import annotations
import html as html_mod
from pathlib import Path

from vec_audit.models import AuditReport, FailureKind, VectorizationStatus


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

_KIND_COLOR: dict[FailureKind, str] = {
    FailureKind.ALIASING:           "#c0392b",
    FailureKind.CONTROL_FLOW:       "#e67e22",
    FailureKind.UNKNOWN_TRIP_COUNT: "#8e44ad",
    FailureKind.DATA_DEPENDENCE:    "#c0392b",
    FailureKind.NOT_PROFITABLE:     "#7f8c8d",
    FailureKind.DATA_ALIGNMENT:     "#2980b9",
    FailureKind.FUNCTION_CALL:      "#16a085",
    FailureKind.REDUCTION:          "#8e44ad",
    FailureKind.OUTER_LOOP:         "#d35400",
    FailureKind.UNSUPPORTED_TYPE:   "#c0392b",
    FailureKind.UNKNOWN_CAUSE:      "#95a5a6",
}

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 14px;
    line-height: 1.6;
    color: #1a1a1a;
    background: #f7f7f5;
    padding: 2.5rem 1.5rem;
}

.page { max-width: 860px; margin: 0 auto; }

/* En-tête */
.header { margin-bottom: 2.5rem; }
.header h1 { font-size: 1.25rem; font-weight: 600; letter-spacing: -0.01em; }
.header .meta { margin-top: 0.25rem; color: #6b7280; font-size: 0.8rem; }
.header .meta code {
    font-family: 'SF Mono', 'Fira Code', monospace;
    background: #ebebeb;
    padding: 0.1rem 0.35rem;
    border-radius: 3px;
}

/* Statistiques */
.stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1px;
    background: #e5e5e3;
    border: 1px solid #e5e5e3;
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 1.5rem;
}
.stat {
    background: #fff;
    padding: 1rem 1.25rem;
    text-align: center;
}
.stat .value { font-size: 1.75rem; font-weight: 700; letter-spacing: -0.02em; }
.stat .label { font-size: 0.7rem; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.1rem; }
.stat.green .value { color: #16a34a; }
.stat.red   .value { color: #dc2626; }
.stat.blue  .value { color: #2563eb; }
.stat.gray  .value { color: #374151; }

/* Barre de progression */
.progress {
    height: 4px;
    background: #e5e7eb;
    border-radius: 2px;
    margin-bottom: 2rem;
    overflow: hidden;
}
.progress .fill {
    height: 100%;
    background: #16a34a;
    border-radius: 2px;
}

/* Section titre */
.section-title {
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #9ca3af;
    margin-bottom: 0.75rem;
}

/* Badges causes */
.causes { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 2rem; }
.cause-badge {
    display: inline-flex; align-items: center; gap: 0.35rem;
    padding: 0.2rem 0.6rem;
    border-radius: 4px;
    font-size: 0.75rem;
    background: #fff;
    border: 1px solid #e5e5e3;
    color: #374151;
}
.cause-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }

/* Cards résultats */
.card {
    background: #fff;
    border: 1px solid #e5e5e3;
    border-radius: 8px;
    margin-bottom: 0.75rem;
    overflow: hidden;
}

.card-header {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.75rem 1rem;
    cursor: pointer;
    user-select: none;
}
.card-header:hover { background: #fafaf9; }

.status-dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
}
.missed-dot   { background: #dc2626; }
.success-dot  { background: #16a34a; }

.loc {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.8rem;
    color: #374151;
}

.kind-pill {
    font-size: 0.7rem;
    font-weight: 500;
    padding: 0.15rem 0.5rem;
    border-radius: 3px;
    color: #fff;
}

.spacer { flex: 1; }

.chevron {
    font-size: 0.7rem;
    color: #d1d5db;
    transition: transform 0.15s;
}
.chevron.open { transform: rotate(180deg); }

/* Corps de la card */
.card-body { display: none; border-top: 1px solid #f3f4f6; }
.card-body.open { display: block; }

/* Code snippet */
.code-wrap {
    overflow-x: auto;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.775rem;
    line-height: 1.65;
    background: #fafaf9;
    border-bottom: 1px solid #f3f4f6;
}
.code-wrap table { border-collapse: collapse; width: 100%; }
.code-wrap td { padding: 0 1rem; white-space: pre; }
.code-wrap .ln {
    color: #d1d5db;
    text-align: right;
    user-select: none;
    width: 3rem;
    border-right: 1px solid #f3f4f6;
    padding-right: 0.75rem;
}
.code-wrap .hl { background: #fef2f2; }
.code-wrap .hl .ln { color: #fca5a5; border-color: #fecaca; }

/* Section diagnostic */
.diagnostic { padding: 1rem 1.25rem; }

.raw {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.75rem;
    color: #9ca3af;
    margin-bottom: 1rem;
}

.suggestion { }

.suggestion h3 {
    font-size: 0.85rem;
    font-weight: 600;
    margin-bottom: 0.3rem;
}

.suggestion .expl {
    font-size: 0.825rem;
    color: #4b5563;
    margin-bottom: 0.6rem;
}

.fix-box {
    font-size: 0.8rem;
    background: #f0f9ff;
    border-left: 3px solid #3b82f6;
    padding: 0.5rem 0.75rem;
    border-radius: 0 4px 4px 0;
    color: #1e40af;
    margin-bottom: 0.75rem;
}

.example pre {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.75rem;
    background: #fafaf9;
    border: 1px solid #e5e5e3;
    border-radius: 4px;
    padding: 0.75rem 1rem;
    overflow-x: auto;
    white-space: pre;
    color: #374151;
    margin-bottom: 0.75rem;
}

.doc-link { font-size: 0.75rem; color: #9ca3af; }
.doc-link a { color: #6b7280; }

/* Boucles vectorisées */
.vec-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    padding: 1rem;
}
.vec-chip {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.75rem;
    padding: 0.2rem 0.6rem;
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 4px;
    color: #15803d;
}

@media (max-width: 600px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
}
"""

_JS = """
function toggle(id) {
    document.getElementById('b' + id).classList.toggle('open');
    document.getElementById('c' + id).classList.toggle('open');
}
"""


class HTMLReporter:

    def __init__(self, source_lines: list[str] | None = None):
        self.source_lines = source_lines

    def render(self, report: AuditReport, output_path: Path) -> None:
        output_path.write_text(self._build(report), encoding="utf-8")

    def _build(self, report: AuditReport) -> str:
        missed = [r for r in report.results if r.record.is_missed]
        vecs   = [r for r in report.results if r.record.is_vectorized]
        rate   = report.vectorization_rate

        # Badges causes
        by_kind = report.missed_by_kind()
        badges = ""
        for kind, count in sorted(by_kind.items(), key=lambda x: -x[1]):
            color = _KIND_COLOR.get(kind, "#9ca3af")
            label = _KIND_LABEL.get(kind, "unknown")
            badges += (
                f'<span class="cause-badge">'
                f'<span class="cause-dot" style="background:{color}"></span>'
                f'{label} &times;{count}</span>\n'
            )

        # Cards missed
        missed_cards = ""
        for i, result in enumerate(missed):
            missed_cards += self._card(result, i)

        # Chips vectorisées
        vec_chips = ""
        for r in vecs:
            loc = r.record.location
            w = f" ·{r.record.vector_width}B" if r.record.vector_width else ""
            vec_chips += f'<span class="vec-chip">{loc.file}:{loc.line}{w}</span>\n'

        vec_section = ""
        if vec_chips:
            vec_section = f"""
<div class="section-title" style="margin-top:2rem">Vectorisées ({len(vecs)})</div>
<div class="card">
  <div class="vec-grid">{vec_chips}</div>
</div>"""

        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>vec-audit — {html_mod.escape(report.source_file)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page">

  <div class="header">
    <h1>vec-audit</h1>
    <div class="meta">
      <code>{html_mod.escape(report.source_file)}</code> &nbsp;·&nbsp;
      <code>{html_mod.escape(report.compiler)}</code> &nbsp;·&nbsp;
      <code>{html_mod.escape(report.compiler_flags or '—')}</code>
    </div>
  </div>

  <div class="stats">
    <div class="stat gray"><div class="value">{report.total}</div><div class="label">Total</div></div>
    <div class="stat green"><div class="value">{report.vectorized_count}</div><div class="label">Vectorisées</div></div>
    <div class="stat red"><div class="value">{report.missed_count}</div><div class="label">Ratées</div></div>
    <div class="stat {"green" if rate >= 80 else "red" if rate < 50 else "blue"}">
      <div class="value">{rate:.0f}%</div><div class="label">Taux</div>
    </div>
  </div>

  <div class="progress"><div class="fill" style="width:{rate:.1f}%"></div></div>

  {('<div class="causes">' + badges + '</div>') if badges else ''}

  <div class="section-title">Non vectorisées ({len(missed)})</div>
  {missed_cards or '<p style="color:#16a34a;font-size:0.875rem;padding:0.5rem 0">Toutes les boucles sont vectorisées.</p>'}

  {vec_section}

</div>
<script>{_JS}</script>
</body>
</html>"""

    def _card(self, result, idx: int) -> str:
        rec  = result.record
        loc  = rec.location
        color = _KIND_COLOR.get(rec.failure_kind, "#9ca3af")
        label = _KIND_LABEL.get(rec.failure_kind, "unknown")

        suggestions_html = ""
        for s in result.suggestions:
            ex = ""
            if s.example:
                ex = f'<div class="example"><pre>{html_mod.escape(s.example)}</pre></div>'
            doc = ""
            if s.doc_url:
                doc = f'<p class="doc-link"><a href="{s.doc_url}" target="_blank">{s.doc_url}</a></p>'
            suggestions_html += f"""<div class="suggestion">
  <h3>{html_mod.escape(s.title)}</h3>
  <p class="expl">{html_mod.escape(s.explanation)}</p>
  <div class="fix-box">{html_mod.escape(s.fix)}</div>
  {ex}{doc}
</div>"""

        return f"""<div class="card">
  <div class="card-header" onclick="toggle({idx})">
    <span class="status-dot missed-dot"></span>
    <span class="loc">{html_mod.escape(loc.file)}:{loc.line}</span>
    <span class="kind-pill" style="background:{color}">{label}</span>
    <span class="spacer"></span>
    <span class="chevron open" id="c{idx}">▾</span>
  </div>
  <div class="card-body open" id="b{idx}">
    {self._snippet(loc.line)}
    <div class="diagnostic">
      <div class="raw">{html_mod.escape(rec.raw_message)}</div>
      {suggestions_html}
    </div>
  </div>
</div>
"""

    def _snippet(self, target: int, ctx: int = 3) -> str:
        if not self.source_lines:
            return ""
        start = max(0, target - 1 - ctx)
        end   = min(len(self.source_lines), target + ctx)
        rows  = ""
        for i, src in enumerate(self.source_lines[start:end], start=start + 1):
            hl  = ' class="hl"' if i == target else ""
            rows += f'<tr{hl}><td class="ln">{i}</td><td>{html_mod.escape(src) or "&nbsp;"}</td></tr>\n'
        return f'<div class="code-wrap"><table>{rows}</table></div>\n'