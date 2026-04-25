"""
vec-audit — reporter terminal (Rich)
======================================
Affiche le rapport d'audit dans le terminal avec couleurs et mise en forme.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich import box
from rich.text import Text
from rich.syntax import Syntax

from vec_audit.models import (
    AuditReport,
    DiagnosticResult,
    FailureKind,
    VectorizationStatus,
)


_STATUS_STYLE: dict[VectorizationStatus, tuple[str, str]] = {
    VectorizationStatus.VECTORIZED: ("✓", "bold green"),
    VectorizationStatus.MISSED:     ("✗", "bold red"),
    VectorizationStatus.PARTIAL:    ("~", "bold yellow"),
    VectorizationStatus.UNKNOWN:    ("?", "dim"),
}

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


class TerminalReporter:
    """Affiche un AuditReport dans le terminal avec Rich."""

    def __init__(self, source_lines: list[str] | None = None, verbose: bool = False):
        self.console = Console()
        self.source_lines = source_lines  # lignes du fichier source (optionnel)
        self.verbose = verbose

    def render(self, report: AuditReport) -> None:
        c = self.console

        # --- En-tête ---
        c.print()
        c.print(Rule(f"[bold]vec-audit[/bold]  {report.source_file}", style="blue"))
        c.print(f"  Compilateur : [cyan]{report.compiler}[/cyan]   "
                f"Flags : [dim]{report.compiler_flags or '(non spécifiés)'}[/dim]")
        c.print()

        # --- Statistiques globales ---
        self._render_summary(report)
        c.print()

        # --- Résultats détaillés ---
        if report.missed_count == 0:
            c.print("[bold green]Toutes les boucles détectées sont vectorisées ![/bold green]")
        else:
            c.print(Rule("Boucles non vectorisées", style="red"))
            c.print()
            for result in report.results:
                if result.record.is_missed:
                    self._render_result(result)

        # --- Boucles vectorisées (en mode verbose) ---
        if self.verbose and report.vectorized_count > 0:
            c.print()
            c.print(Rule("Boucles vectorisées", style="green"))
            c.print()
            for result in report.results:
                if result.record.is_vectorized:
                    self._render_vectorized(result)

    def _render_summary(self, report: AuditReport) -> None:
        c = self.console

        table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold")
        table.add_column("Métrique", style="dim")
        table.add_column("Valeur", justify="right")

        table.add_row("Boucles analysées",    str(report.total))
        table.add_row("Vectorisées",
                      f"[green]{report.vectorized_count}[/green]")
        table.add_row("Non vectorisées",
                      f"[red]{report.missed_count}[/red]")
        table.add_row("Taux de vectorisation",
                      f"[bold]{report.vectorization_rate:.0f}%[/bold]")

        c.print(table)

        # Répartition des causes d'échec
        by_kind = report.missed_by_kind()
        if by_kind:
            c.print("  Causes d'échec :")
            for kind, count in sorted(by_kind.items(), key=lambda x: -x[1]):
                label = _KIND_LABEL.get(kind, str(kind))
                c.print(f"    [red]✗[/red] {label} : [bold]{count}[/bold]")

    def _render_result(self, result: DiagnosticResult) -> None:
        c = self.console
        rec = result.record
        loc = rec.location
        icon, style = _STATUS_STYLE[rec.status]
        kind_label  = _KIND_LABEL.get(rec.failure_kind, "?")

        # Ligne de localisation
        c.print(f"[{style}]{icon}[/{style}] "
                f"[bold]{loc.file}[/bold]:[cyan]{loc.line}[/cyan]  "
                f"[yellow]{kind_label}[/yellow]")

        # Extrait du code source si disponible
        if self.source_lines and 0 < loc.line <= len(self.source_lines):
            snippet = self._get_snippet(loc.line)
            if snippet:
                c.print(Syntax(snippet, "c", theme="monokai",
                               line_numbers=True,
                               start_line=max(1, loc.line - 1),
                               highlight_lines={loc.line}))

        # Message brut
        c.print(f"  [dim]Rapport compilateur :[/dim] {rec.raw_message}")
        if rec.note:
            c.print(f"  [dim]Note :[/dim] {rec.note}")

        # Suggestions
        for suggestion in result.suggestions:
            self._render_suggestion(suggestion)

        c.print()

    def _render_vectorized(self, result: DiagnosticResult) -> None:
        c = self.console
        rec = result.record
        loc = rec.location
        width_info = f" ({rec.vector_width} bytes)" if rec.vector_width else ""
        c.print(f"[green]✓[/green] [bold]{loc.file}[/bold]:[cyan]{loc.line}[/cyan]"
                f"  vectorisée{width_info}")

    def _render_suggestion(self, suggestion) -> None:
        c = self.console

        c.print(Panel(
            f"[bold]{suggestion.title}[/bold]\n\n"
            f"{suggestion.explanation}\n\n"
            f"[bold cyan]→ Correction :[/bold cyan] {suggestion.fix}"
            + (f"\n\n[dim]{suggestion.doc_url}[/dim]" if suggestion.doc_url else ""),
            border_style="yellow",
            padding=(0, 1),
        ))

        if suggestion.example:
            c.print(Syntax(suggestion.example, "c", theme="monokai",
                           line_numbers=False))

    def _get_snippet(self, line: int, context: int = 2) -> str:
        """Extrait quelques lignes de code autour de la ligne cible."""
        if not self.source_lines:
            return ""
        start = max(0, line - 1 - context)
        end   = min(len(self.source_lines), line + context)
        return "\n".join(self.source_lines[start:end])
