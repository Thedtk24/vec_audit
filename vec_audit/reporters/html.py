"""
vec-audit — reporter HTML v2
Layout : sidebar gauche (résumé + nav) + panel principal (cartes dépliables)
"""

from __future__ import annotations
import html as html_mod
from pathlib import Path

from vec_audit.models import AuditReport, FailureKind, VectorizationStatus
from vec_audit.asm_extractor import AsmBlock, find_function_for_line


_KIND_LABEL: dict[FailureKind, str] = {
    FailureKind.ALIASING:           "Aliasing",
    FailureKind.CONTROL_FLOW:       "Control Flow",
    FailureKind.UNKNOWN_TRIP_COUNT: "Unknown Trip Count",
    FailureKind.DATA_DEPENDENCE:    "Data Dependence",
    FailureKind.NOT_PROFITABLE:     "Not Profitable",
    FailureKind.DATA_ALIGNMENT:     "Data Alignment",
    FailureKind.FUNCTION_CALL:      "Function Call",
    FailureKind.REDUCTION:          "Reduction",
    FailureKind.OUTER_LOOP:         "Outer Loop",
    FailureKind.UNSUPPORTED_TYPE:   "Unsupported Type",
    FailureKind.UNKNOWN_CAUSE:      "Unknown",
}

_KIND_COLOR: dict[FailureKind, str] = {
    FailureKind.ALIASING:           "#c2410c",
    FailureKind.CONTROL_FLOW:       "#b45309",
    FailureKind.UNKNOWN_TRIP_COUNT: "#6d28d9",
    FailureKind.DATA_DEPENDENCE:    "#991b1b",
    FailureKind.NOT_PROFITABLE:     "#374151",
    FailureKind.DATA_ALIGNMENT:     "#1d4ed8",
    FailureKind.FUNCTION_CALL:      "#0f766e",
    FailureKind.REDUCTION:          "#6d28d9",
    FailureKind.OUTER_LOOP:         "#92400e",
    FailureKind.UNSUPPORTED_TYPE:   "#991b1b",
    FailureKind.UNKNOWN_CAUSE:      "#6b7280",
}

_MONO = "font-family:'JetBrains Mono',monospace"


# ---------------------------------------------------------------------------
# Métriques ASM
# ---------------------------------------------------------------------------

def _asm_metrics(block: AsmBlock) -> dict:
    """Extrait des métriques utiles depuis un bloc ASM."""
    total = len(block.lines)
    simd  = len(block.simd_instrs)
    ratio = (simd / total * 100) if total else 0

    # Détecter le registre vectoriel le plus large utilisé
    reg_level = "none"
    joined = " ".join(block.simd_instrs).lower()
    if "zmm" in joined:
        reg_level = "AVX-512 (512-bit)"
    elif "ymm" in joined:
        reg_level = "AVX2 (256-bit)"
    elif "xmm" in joined:
        reg_level = "SSE (128-bit)"
    elif ".4s" in joined or ".2d" in joined or " q" in joined:
        reg_level = "NEON 128-bit"
    elif ".2s" in joined or ".4h" in joined:
        reg_level = "NEON 64-bit"

    return {
        "total":     total,
        "simd":      simd,
        "ratio":     ratio,
        "reg_level": reg_level,
    }


# ---------------------------------------------------------------------------
# Fragments HTML
# ---------------------------------------------------------------------------

def _source_snippet(source_lines: list[str], target: int, ctx: int = 3) -> str:
    if not source_lines or not (0 < target <= len(source_lines)):
        return "<p style='color:#9ca3af;font-size:0.8rem'>Source not available.</p>"
    start = max(0, target - 1 - ctx)
    end   = min(len(source_lines), target + ctx)
    rows  = ""
    for ln, src in enumerate(source_lines[start:end], start=start + 1):
        hl  = "background:#fff5f5;" if ln == target else ""
        ul  = "border-bottom:1px solid #fca5a5;" if ln == target else ""
        esc = html_mod.escape(src) if src.strip() else "&nbsp;"
        rows += (
            f'<div style="{hl}">'
            f'<span style="color:#d1d5db;user-select:none;display:inline-block;'
            f'width:2.5rem;text-align:right;padding-right:0.75rem;'
            f'border-right:1px solid #f3f4f6;margin-right:0.75rem;">{ln}</span>'
            f'<span style="{ul}">{esc}</span></div>\n'
        )
    return (
        f'<div style="background:#f9fafb;border:1px solid #f0f0f0;border-radius:4px;'
        f'overflow-x:auto;padding:1rem;">'
        f'<pre style="margin:0;{_MONO};font-size:0.8rem;line-height:1.75;">{rows}</pre></div>'
    )


def _asm_view(block: AsmBlock | None, is_missed: bool) -> str:
    if not block or not block.lines:
        return "<p style='color:#9ca3af;font-size:0.8rem'>Assembly not available.</p>"

    m = _asm_metrics(block)

    # Metrics bar
    simd_pct  = m["ratio"]
    bar_color = "#16a34a" if not is_missed else "#9ca3af"
    metrics_bar = (
        f'<div style="display:flex;gap:1.5rem;margin-bottom:0.75rem;'
        f'font-size:0.72rem;color:#6b7280;align-items:center;flex-wrap:wrap;">'
        f'<span>{m["total"]} instructions</span>'
        f'<span style="color:{"#16a34a" if not is_missed else "#6b7280"};">'
        f'{m["simd"]} SIMD ({simd_pct:.0f}%)</span>'
        f'<span style="color:#9ca3af;">|</span>'
        f'<span style="color:{"#1d4ed8" if m["reg_level"] != "none" else "#9ca3af"};">'
        f'{m["reg_level"] if m["reg_level"] != "none" else "No vector registers"}</span>'
        f'<div style="flex:1;height:3px;background:#f3f4f6;border-radius:2px;min-width:60px;">'
        f'<div style="width:{simd_pct:.1f}%;height:100%;background:{bar_color};border-radius:2px;"></div>'
        f'</div></div>'
    )

    rows = ""
    for line, is_simd in block.annotated_lines():
        if is_simd:
            rows += (
                f'<div style="background:#f0fdf4;">'
                f'<span style="color:#86efac;user-select:none;padding:0 0.5rem;">›</span>'
                f'<span style="color:#15803d;font-weight:500;">{html_mod.escape(line)}</span>'
                f'</div>\n'
            )
        else:
            rows += (
                f'<div>'
                f'<span style="color:#e5e7eb;user-select:none;padding:0 0.5rem;"> </span>'
                f'<span style="color:#6b7280;">{html_mod.escape(line)}</span>'
                f'</div>\n'
            )

    return (
        metrics_bar
        + f'<div style="background:#f9fafb;border:1px solid #f0f0f0;border-radius:4px;'
        f'overflow-x:auto;max-height:340px;overflow-y:auto;padding:1rem;">'
        f'<pre style="margin:0;{_MONO};font-size:0.78rem;line-height:1.65;">{rows}</pre></div>'
    )


def _recommendation(result) -> str:
    s = result.suggestions[0] if result.suggestions else None
    if not s:
        return ""
    ex = ""
    if s.example:
        ex = (
            f'<div style="margin-top:1rem;">'
            f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.4rem;">Example fix</div>'
            f'<div style="background:#f9fafb;border:1px solid #f0f0f0;border-radius:4px;'
            f'overflow-x:auto;padding:1rem;">'
            f'<pre style="margin:0;{_MONO};font-size:0.78rem;line-height:1.65;color:#374151;">'
            f'{html_mod.escape(s.example)}</pre></div></div>'
        )
    doc = ""
    if s.doc_url:
        doc = (
            f'<p style="margin-top:0.5rem;font-size:0.72rem;">'
            f'<a href="{s.doc_url}" target="_blank" '
            f'style="color:#6b7280;text-decoration:underline;">{s.doc_url}</a></p>'
        )
    return (
        f'<div style="margin-bottom:0;">'
        f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.5rem;">What to do</div>'
        f'<p style="font-size:0.875rem;color:#374151;margin-bottom:0.5rem;line-height:1.7;">'
        f'{html_mod.escape(s.explanation)}</p>'
        f'<div style="border-left:2px solid #1a1a1a;padding-left:1rem;">'
        f'<p style="font-size:0.875rem;color:#6b7280;font-style:italic;margin:0;">'
        f'{html_mod.escape(s.fix)}</p></div>'
        f'{ex}{doc}</div>'
    )


def _priority_badge(result) -> str:
    """Badge de priorité basé sur la cause (impact potentiel)."""
    high_impact = {FailureKind.ALIASING, FailureKind.DATA_ALIGNMENT, FailureKind.FUNCTION_CALL}
    med_impact  = {FailureKind.CONTROL_FLOW, FailureKind.UNKNOWN_TRIP_COUNT, FailureKind.REDUCTION}
    k = result.record.failure_kind
    if k in high_impact:
        return '<span style="font-size:0.6rem;font-weight:600;color:#92400e;background:#fef3c7;border:1px solid #fde68a;border-radius:3px;padding:0.1rem 0.4rem;">HIGH IMPACT</span>'
    if k in med_impact:
        return '<span style="font-size:0.6rem;font-weight:600;color:#1e40af;background:#dbeafe;border:1px solid #bfdbfe;border-radius:3px;padding:0.1rem 0.4rem;">MEDIUM</span>'
    return '<span style="font-size:0.6rem;font-weight:600;color:#374151;background:#f3f4f6;border:1px solid #e5e7eb;border-radius:3px;padding:0.1rem 0.4rem;">LOW</span>'


def _card(idx: int, result, source_lines, asm_blocks) -> str:
    rec  = result.record
    loc  = rec.location
    is_missed = rec.is_missed

    func  = find_function_for_line(source_lines or [], loc.line)
    block = asm_blocks.get(func) if func else None

    kind_label = _KIND_LABEL.get(rec.failure_kind, "unknown") if is_missed else "Vectorized"
    kind_color = _KIND_COLOR.get(rec.failure_kind, "#6b7280") if is_missed else "#15803d"
    dot_color  = "#f87171" if is_missed else "#22c55e"
    w_label    = f" · {rec.vector_width}B" if rec.vector_width else ""

    priority   = _priority_badge(result) if is_missed else ""

    # Tabs: Source | Assembly | (Fix si missed)
    tab_ids    = [f"t{idx}-src", f"t{idx}-asm"]
    tab_labels = ["Source", "Assembly"]
    if is_missed and result.suggestions:
        tab_ids.append(f"t{idx}-fix")
        tab_labels.append("How to fix")

    tabs_nav = ""
    tabs_body = ""
    for i, (tid, tlabel) in enumerate(zip(tab_ids, tab_labels)):
        active_nav  = "border-bottom:2px solid #1a1a1a;color:#1a1a1a;" if i == 0 else "border-bottom:2px solid transparent;color:#9ca3af;"
        active_body = "block" if i == 0 else "none"
        tabs_nav += (
            f'<button onclick="showTab(\'{idx}\',\'{tid}\')" id="btn-{tid}" '
            f'style="background:none;border:none;cursor:pointer;padding:0.5rem 0;'
            f'margin-right:1.5rem;font-size:0.78rem;font-weight:600;{active_nav}">'
            f'{tlabel}</button>'
        )
        if tid == f"t{idx}-src":
            content = _source_snippet(source_lines or [], loc.line)
        elif tid == f"t{idx}-asm":
            content = _asm_view(block, is_missed)
        else:
            content = _recommendation(result)

        tabs_body += (
            f'<div id="{tid}" style="display:{active_body};">{content}</div>'
        )

    return f"""<div id="card-{idx}" style="border:1px solid #e5e7eb;border-radius:8px;
         margin-bottom:0.5rem;overflow:hidden;scroll-margin-top:1rem;">

  <!-- Header -->
  <div onclick="toggleCard('{idx}')"
       style="display:flex;align-items:center;gap:0.6rem;padding:0.875rem 1.25rem;
              cursor:pointer;user-select:none;"
       onmouseover="this.style.background='#fafafa'"
       onmouseout="this.style.background=''">
    <span style="height:7px;width:7px;border-radius:50%;background:{dot_color};
                 flex-shrink:0;display:inline-block;"></span>
    <span style="{_MONO};font-size:0.8rem;color:#374151;flex-shrink:0;">
      {html_mod.escape(loc.file)}:{loc.line}</span>
    <span style="font-size:0.7rem;font-weight:600;color:#fff;background:{kind_color};
                 padding:0.15rem 0.5rem;border-radius:3px;text-transform:uppercase;
                 white-space:nowrap;">{kind_label}{html_mod.escape(w_label)}</span>
    {priority}
    <span style="margin-left:auto;font-size:0.7rem;color:#9ca3af;white-space:nowrap;">
      {html_mod.escape(func + "()" if func else "")}</span>
    <span id="chev-{idx}" style="color:#d1d5db;font-size:0.7rem;
                 transition:transform 0.2s;display:inline-block;margin-left:0.5rem;">▾</span>
  </div>

  <!-- Body -->
  <div id="body-{idx}" style="display:none;border-top:1px solid #f3f4f6;">
    <!-- Tab nav -->
    <div style="padding:0 1.25rem;border-bottom:1px solid #f3f4f6;">
      {tabs_nav}
    </div>
    <!-- Tab content -->
    <div style="padding:1.25rem;">
      {tabs_body}
    </div>
  </div>
</div>
"""


def _sidebar(report: AuditReport, by_kind) -> str:
    rate   = report.vectorization_rate
    circle = min(rate, 100)

    # Causes list
    causes_html = ""
    for kind, count in sorted(by_kind.items(), key=lambda x: -x[1]):
        label = _KIND_LABEL.get(kind, "unknown")
        color = _KIND_COLOR.get(kind, "#6b7280")
        causes_html += (
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'padding:0.35rem 0;border-bottom:1px solid #f9fafb;">'
            f'<div style="display:flex;align-items:center;gap:0.5rem;">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:{color};'
            f'display:inline-block;flex-shrink:0;"></span>'
            f'<span style="font-size:0.78rem;color:#374151;">{label}</span></div>'
            f'<span style="font-size:0.78rem;font-weight:600;color:#374151;">{count}</span>'
            f'</div>\n'
        )

    # Prioritized actions
    actions_html = _priority_actions(report)

    return f'''
<aside style="width:220px;flex-shrink:0;position:sticky;top:2rem;align-self:flex-start;">

  <!-- Score -->
  <div style="text-align:center;margin-bottom:2rem;">
    <svg width="100" height="100" viewBox="0 0 100 100">
      <circle cx="50" cy="50" r="40" fill="none" stroke="#f3f4f6" stroke-width="8"/>
      <circle cx="50" cy="50" r="40" fill="none"
              stroke="{"#16a34a" if rate >= 80 else "#f59e0b" if rate >= 50 else "#dc2626"}"
              stroke-width="8"
              stroke-dasharray="{circle * 2.513:.1f} 251.3"
              stroke-dashoffset="62.8"
              stroke-linecap="round"
              transform="rotate(-90 50 50)"/>
      <text x="50" y="46" text-anchor="middle"
            style="font-family:-apple-system,sans-serif;font-size:18px;font-weight:600;fill:#1a1a1a;">
        {rate:.0f}%</text>
      <text x="50" y="62" text-anchor="middle"
            style="font-family:-apple-system,sans-serif;font-size:9px;fill:#9ca3af;">vectorized</text>
    </svg>
    <div style="display:flex;justify-content:center;gap:1rem;font-size:0.72rem;color:#6b7280;">
      <span><strong style="color:#16a34a;">{report.vectorized_count}</strong> ok</span>
      <span><strong style="color:#dc2626;">{report.missed_count}</strong> failed</span>
      <span><strong style="color:#374151;">{report.total}</strong> total</span>
    </div>
  </div>

  <!-- Causes -->
  {"" if not by_kind else f'<div style="margin-bottom:1.5rem;"><div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.5rem;">Failure causes</div>' + causes_html + '</div>'}

  <!-- Priority actions -->
  {actions_html}

  <!-- Compiler info -->
  <div style="margin-top:1.5rem;padding:0.75rem;background:#f9fafb;border-radius:6px;">
    <div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;
                letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.4rem;">Compiler</div>
    <div style="font-size:0.75rem;color:#374151;">{html_mod.escape(report.compiler)}</div>
    <div style="font-size:0.7rem;color:#9ca3af;margin-top:0.2rem;
                {_MONO};word-break:break-all;">{html_mod.escape(report.compiler_flags or "")}</div>
  </div>

</aside>'''


def _priority_actions(report: AuditReport) -> str:
    """Liste d'actions triées par impact potentiel."""
    high = {FailureKind.ALIASING, FailureKind.DATA_ALIGNMENT, FailureKind.FUNCTION_CALL}
    med  = {FailureKind.CONTROL_FLOW, FailureKind.UNKNOWN_TRIP_COUNT, FailureKind.REDUCTION}

    missed = [r for r in report.results if r.record.is_missed]
    if not missed:
        return ""

    by_impact: list[tuple[int, str]] = []
    for r in missed:
        k     = r.record.failure_kind
        label = _KIND_LABEL.get(k, "unknown")
        loc   = r.record.location
        impact = 0 if k in high else 1 if k in med else 2
        fix_short = r.suggestions[0].fix[:60] + "…" if r.suggestions else "See details"
        by_impact.append((impact, loc.line, label, fix_short))

    by_impact.sort(key=lambda x: (x[0], x[1]))

    items = ""
    for impact, line, label, fix_short in by_impact[:5]:
        dot = "#f59e0b" if impact == 0 else "#60a5fa" if impact == 1 else "#d1d5db"
        items += (
            f'<div style="padding:0.5rem 0;border-bottom:1px solid #f9fafb;">'
            f'<div style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.2rem;">'
            f'<span style="width:5px;height:5px;border-radius:50%;background:{dot};'
            f'flex-shrink:0;display:inline-block;"></span>'
            f'<span style="font-size:0.72rem;font-weight:600;color:#374151;">line {line} — {label}</span>'
            f'</div>'
            f'<p style="font-size:0.7rem;color:#9ca3af;margin:0;padding-left:0.9rem;">'
            f'{html_mod.escape(fix_short)}</p>'
            f'</div>'
        )

    return (
        f'<div style="margin-bottom:1.5rem;">'
        f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.5rem;">Priority actions</div>'
        f'{items}</div>'
    )


_JS = """
function toggleCard(id) {
    const body = document.getElementById('body-' + id);
    const chev = document.getElementById('chev-' + id);
    const open = body.style.display === 'block';
    body.style.display     = open ? 'none' : 'block';
    chev.style.transform   = open ? 'rotate(0deg)' : 'rotate(180deg)';
}

function showTab(cardId, tabId) {
    // Hide all tabs in this card
    const body = document.getElementById('body-' + cardId);
    body.querySelectorAll('[id^="t' + cardId + '-"]').forEach(el => {
        el.style.display = 'none';
    });
    // Reset all tab buttons
    body.querySelectorAll('button[id^="btn-t' + cardId + '"]').forEach(btn => {
        btn.style.borderBottomColor = 'transparent';
        btn.style.color = '#9ca3af';
    });
    // Show selected
    document.getElementById(tabId).style.display = 'block';
    const btn = document.getElementById('btn-' + tabId);
    btn.style.borderBottomColor = '#1a1a1a';
    btn.style.color = '#1a1a1a';
}
"""


def _render(
    report: AuditReport,
    source_lines: list[str] | None,
    asm_blocks: dict[str, AsmBlock],
) -> str:
    missed = [r for r in report.results if r.record.is_missed]
    vecs   = [r for r in report.results if r.record.is_vectorized]
    fname  = report.source_file.split("/")[-1]
    by_kind = report.missed_by_kind()

    # Cards
    cards_html = ""
    if missed:
        cards_html += (
            f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.75rem;">'
            f'Failed ({len(missed)})</div>'
        )
        for i, result in enumerate(missed):
            cards_html += _card(i, result, source_lines, asm_blocks)

    if vecs:
        cards_html += (
            f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.08em;color:#9ca3af;margin:{("2rem" if missed else "0")} 0 0.75rem;">'
            f'Vectorized ({len(vecs)})</div>'
        )
        for j, result in enumerate(vecs):
            cards_html += _card(len(missed) + j, result, source_lines, asm_blocks)

    sidebar = _sidebar(report, by_kind)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>vec-audit | {html_mod.escape(fname)}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{
    font-family:'Inter',-apple-system,sans-serif;
    background:#f9fafb; color:#1a1a1a;
    font-size:14px; line-height:1.6;
    min-height:100vh;
  }}
  a {{ color:inherit; }}
</style>
</head>
<body>

  <!-- Top bar -->
  <header style="background:#fff;border-bottom:1px solid #e5e7eb;
                 padding:0.875rem 2.5rem;position:sticky;top:0;z-index:10;">
    <div style="max-width:1100px;margin:0 auto;display:flex;
                align-items:center;justify-content:space-between;gap:1rem;">
      <span style="font-size:0.875rem;font-weight:600;letter-spacing:-0.01em;text-transform:uppercase;">
        vec-audit
        <span style="color:#9ca3af;font-weight:300;">
          / {html_mod.escape(fname)}
        </span>
      </span>
      <span style="font-size:0.72rem;color:#9ca3af;">
        Click any loop to expand source, assembly and fix
      </span>
    </div>
  </header>

  <!-- Layout -->
  <div style="max-width:1100px;margin:0 auto;padding:2rem 2.5rem;
              display:flex;gap:3rem;align-items:flex-start;">

    {sidebar}

    <!-- Main -->
    <main style="flex:1;min-width:0;">
      {cards_html}
    </main>

  </div>

  <script>{_JS}</script>
</body>
</html>'''


class HTMLReporter:

    def __init__(self, source_lines: list[str] | None = None,
                 asm_blocks: dict | None = None):
        self.source_lines = source_lines
        self.asm_blocks   = asm_blocks or {}

    def render(self, report: AuditReport, output_path: Path) -> None:
        output_path.write_text(
            _render(report, self.source_lines, self.asm_blocks),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Extensions HTML pour les nouvelles features
# ---------------------------------------------------------------------------

def _benchmark_section(benchmark: list[dict]) -> str:
    if not benchmark:
        return ""
    rows = ""
    for b in benchmark:
        speedup     = b["speedup"]
        bar_width   = min(speedup / 8 * 100, 100)
        bar_color   = "#16a34a" if speedup >= 2 else "#f59e0b" if speedup >= 1.2 else "#9ca3af"
        speedup_str = f"{speedup:.2f}×"
        rows += (
            f'<tr style="border-bottom:1px solid #f3f4f6;">'
            f'<td style="padding:0.6rem 0;{_MONO};font-size:0.8rem;">{html_mod.escape(b["function"])}()</td>'
            f'<td style="padding:0.6rem 0.5rem;font-size:0.78rem;color:#6b7280;">{b["time_vec_ms"]:.2f} ms</td>'
            f'<td style="padding:0.6rem 0.5rem;font-size:0.78rem;color:#6b7280;">{b["time_novec_ms"]:.2f} ms</td>'
            f'<td style="padding:0.6rem 0;">'
            f'<div style="display:flex;align-items:center;gap:0.5rem;">'
            f'<div style="width:80px;height:4px;background:#f3f4f6;border-radius:2px;">'
            f'<div style="width:{bar_width:.0f}%;height:100%;background:{bar_color};border-radius:2px;"></div>'
            f'</div>'
            f'<span style="font-size:0.8rem;font-weight:600;color:{bar_color};">{speedup_str}</span>'
            f'</div></td></tr>\n'
        )
    return (
        f'<div style="margin-top:1.5rem;">'
        f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.75rem;">Benchmark — vectorized vs scalar</div>'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr style="border-bottom:1px solid #e5e7eb;">'
        f'<th style="text-align:left;font-size:0.7rem;color:#9ca3af;font-weight:500;padding-bottom:0.4rem;">Function</th>'
        f'<th style="text-align:left;font-size:0.7rem;color:#9ca3af;font-weight:500;padding-bottom:0.4rem;">Vec</th>'
        f'<th style="text-align:left;font-size:0.7rem;color:#9ca3af;font-weight:500;padding-bottom:0.4rem;">Scalar</th>'
        f'<th style="text-align:left;font-size:0.7rem;color:#9ca3af;font-weight:500;padding-bottom:0.4rem;">Speedup</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div>'
    )


def _comparison_section(comp: dict) -> str:
    if not comp:
        return ""
    gcc   = comp["gcc"]
    clang = comp["clang"]
    rec   = comp["recommendation"]
    winner_color = "#16a34a"

    gcc_color   = winner_color if rec == "gcc"   else "#374151"
    clang_color = winner_color if rec == "clang" else "#374151"

    divs = ""
    for div in comp.get("divergences", []):
        winner = div["winner"].upper()
        divs += (
            f'<div style="font-size:0.75rem;color:#374151;padding:0.3rem 0;'
            f'border-bottom:1px solid #f9fafb;">'
            f'<span style="{_MONO};">line {div["line"]}</span>'
            f' — <span style="font-weight:600;color:#16a34a;">{winner}</span>'
            f' vectorizes, the other does not</div>\n'
        )

    rec_text = (
        f'Use <strong>{rec.upper()}</strong> for better vectorization on this file.'
        if rec != "equivalent" else "Both compilers produce equivalent vectorization."
    )

    return (
        f'<div style="margin-top:1.5rem;">'
        f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.75rem;">GCC vs Clang</div>'
        f'<div style="display:flex;gap:1rem;margin-bottom:1rem;">'
        f'<div style="flex:1;background:#f9fafb;border-radius:6px;padding:0.75rem;text-align:center;">'
        f'<div style="font-size:1.2rem;font-weight:600;color:{gcc_color};">{gcc["rate"]:.0f}%</div>'
        f'<div style="font-size:0.7rem;color:#9ca3af;">GCC</div></div>'
        f'<div style="flex:1;background:#f9fafb;border-radius:6px;padding:0.75rem;text-align:center;">'
        f'<div style="font-size:1.2rem;font-weight:600;color:{clang_color};">{clang["rate"]:.0f}%</div>'
        f'<div style="font-size:0.7rem;color:#9ca3af;">Clang</div></div>'
        f'</div>'
        f'<p style="font-size:0.8rem;color:#374151;margin-bottom:0.5rem;">{rec_text}</p>'
        f'{"<div>" + divs + "</div>" if divs else ""}'
        f'</div>'
    )


def _history_section(diff: dict | None) -> str:
    if not diff:
        return ""
    delta = diff["delta"]
    trend = diff["trend"]
    color = "#16a34a" if trend == "improved" else "#dc2626" if trend == "regressed" else "#9ca3af"
    arrow = "↑" if trend == "improved" else "↓" if trend == "regressed" else "→"
    delta_str = f"{arrow} {abs(delta):.1f}%"

    new_vec = diff.get("newly_vectorized", [])
    new_miss = diff.get("newly_missed", [])

    items = ""
    for l in new_vec:
        items += f'<div style="font-size:0.75rem;color:#16a34a;padding:0.2rem 0;">+ line {l["line"]} now vectorized</div>'
    for l in new_miss:
        items += f'<div style="font-size:0.75rem;color:#dc2626;padding:0.2rem 0;">− line {l["line"]} regression</div>'

    return (
        f'<div style="margin-top:1.5rem;">'
        f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.5rem;">vs previous run</div>'
        f'<div style="display:flex;align-items:baseline;gap:0.5rem;margin-bottom:0.5rem;">'
        f'<span style="font-size:1.5rem;font-weight:600;color:{color};">{delta_str}</span>'
        f'<span style="font-size:0.75rem;color:#9ca3af;">'
        f'{diff["previous_rate"]:.0f}% → {diff["current_rate"]:.0f}%</span>'
        f'</div>'
        f'{items}'
        f'</div>'
    )


def _flags_section(flags: list[dict]) -> str:
    if not flags:
        return ""
    items = ""
    for f in flags:
        warn = (
            f'<p style="font-size:0.72rem;color:#92400e;margin-top:0.3rem;">'
            f'⚠ {html_mod.escape(f["warning"])}</p>'
        ) if f.get("warning") else ""
        items += (
            f'<div style="padding:0.6rem 0;border-bottom:1px solid #f3f4f6;">'
            f'<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.2rem;">'
            f'<code style="{_MONO};font-size:0.78rem;background:#f3f4f6;'
            f'padding:0.1rem 0.4rem;border-radius:3px;">{html_mod.escape(f["flag"])}</code>'
            f'</div>'
            f'<p style="font-size:0.78rem;color:#374151;margin:0;">'
            f'{html_mod.escape(f["explanation"])}</p>'
            f'{warn}</div>\n'
        )
    return (
        f'<div style="margin-top:1.5rem;">'
        f'<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.5rem;">Suggested flags</div>'
        f'{items}</div>'
    )


def render_full(
    report: AuditReport,
    output_path: Path,
    source_lines: list[str] | None = None,
    asm_blocks: dict | None = None,
    benchmark: list[dict] | None = None,
    compiler_comparison: dict | None = None,
    history_diff: dict | None = None,
    flag_suggestions: list[dict] | None = None,
) -> None:
    """
    Point d'entrée complet avec toutes les features optionnelles.
    Génère le HTML enrichi dans output_path.
    """
    # Construire le rapport de base
    base_html = _render(report, source_lines, asm_blocks or {})

    # Injecter les sections supplémentaires avant </aside>
    extras = ""
    extras += _benchmark_section(benchmark or [])
    extras += _comparison_section(compiler_comparison or {})
    extras += _history_section(history_diff)
    extras += _flags_section(flag_suggestions or [])

    if extras:
        # Injecter juste avant la fermeture de la sidebar
        base_html = base_html.replace(
            "</aside>",
            extras + "\n</aside>",
        )

    output_path.write_text(base_html, encoding="utf-8")