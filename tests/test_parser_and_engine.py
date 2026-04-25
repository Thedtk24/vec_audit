"""
Tests pour le parser GCC et le moteur de diagnostic.
Lance avec : python3 -m pytest tests/ -v
"""

import pytest
from pathlib import Path

from vec_audit.parsers.gcc import GCCParser
from vec_audit.diagnostics.engine import DiagnosticEngine
from vec_audit.models import (
    FailureKind,
    VectorizationStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def parser() -> GCCParser:
    return GCCParser()


@pytest.fixture
def engine() -> DiagnosticEngine:
    return DiagnosticEngine()


# ---------------------------------------------------------------------------
# Tests parser GCC — cas unitaires (chaînes inline)
# ---------------------------------------------------------------------------

class TestGCCParserUnit:

    def test_parse_vectorized_loop(self, parser):
        text = "foo.c:12:5: optimized: loop vectorized using 16 byte vectors"
        records = parser.parse_text(text)
        assert len(records) == 1
        r = records[0]
        assert r.status       == VectorizationStatus.VECTORIZED
        assert r.location.line == 12
        assert r.vector_width  == 16
        assert r.compiler      == "gcc"

    def test_parse_vectorized_avx(self, parser):
        text = "bar.c:8:3: optimized: loop vectorized using 32 byte vectors"
        records = parser.parse_text(text)
        assert records[0].vector_width == 32

    def test_parse_missed_aliasing(self, parser):
        text = (
            "foo.c:24:5: missed: couldn't vectorize loop\n"
            "foo.c:24:9: missed: not vectorized: possible aliasing problem\n"
        )
        records = parser.parse_text(text)
        # Après déduplication, on attend 1 record (même ligne, même statut)
        assert len(records) == 1
        r = records[0]
        assert r.status       == VectorizationStatus.MISSED
        assert r.failure_kind == FailureKind.ALIASING
        assert r.location.line == 24

    def test_parse_missed_control_flow(self, parser):
        text = "foo.c:30:5: missed: not vectorized: control flow in loop\n"
        records = parser.parse_text(text)
        assert records[0].failure_kind == FailureKind.CONTROL_FLOW

    def test_parse_missed_unknown_trip_count(self, parser):
        text = "foo.c:38:5: missed: not vectorized: number of iterations cannot be computed\n"
        records = parser.parse_text(text)
        assert records[0].failure_kind == FailureKind.UNKNOWN_TRIP_COUNT

    def test_parse_missed_data_dependence(self, parser):
        text = "foo.c:50:5: missed: not vectorized: data dependence\n"
        records = parser.parse_text(text)
        assert records[0].failure_kind == FailureKind.DATA_DEPENDENCE

    def test_parse_missed_alignment(self, parser):
        text = "foo.c:60:5: missed: not vectorized: bad data alignment\n"
        records = parser.parse_text(text)
        assert records[0].failure_kind == FailureKind.DATA_ALIGNMENT

    def test_parse_ignored_note_lines(self, parser):
        """Les lignes 'note' sont ignorées ou rattachées, pas comptées comme records."""
        text = (
            "foo.c:8:6: note: vectorized 1 loops in function.\n"
            "foo.c:12:5: optimized: loop vectorized using 16 byte vectors\n"
        )
        records = parser.parse_text(text)
        assert len(records) == 1
        assert records[0].status == VectorizationStatus.VECTORIZED

    def test_parse_mixed_report(self, parser):
        """Un rapport mixte (succès + échecs) est parsé correctement."""
        text = (
            "src.c:10:5: optimized: loop vectorized using 32 byte vectors\n"
            "src.c:20:5: missed: couldn't vectorize loop\n"
            "src.c:20:9: missed: not vectorized: possible aliasing problem\n"
            "src.c:30:5: missed: not vectorized: control flow in loop\n"
        )
        records = parser.parse_text(text)
        vectorized = [r for r in records if r.is_vectorized]
        missed     = [r for r in records if r.is_missed]
        assert len(vectorized) >= 1
        assert len(missed)     >= 2

    def test_parse_empty_input(self, parser):
        assert parser.parse_text("") == []

    def test_parse_garbage_input(self, parser):
        text = "ceci n'est pas un rapport de compilateur\nrandom stuff: foo bar baz"
        assert parser.parse_text(text) == []

    def test_source_location_fields(self, parser):
        text = "myfile.c:42:7: missed: not vectorized: possible aliasing problem"
        records = parser.parse_text(text)
        loc = records[0].location
        assert loc.file   == "myfile.c"
        assert loc.line   == 42
        assert loc.column == 7


# ---------------------------------------------------------------------------
# Tests parser GCC — fixture réelle générée par GCC
# ---------------------------------------------------------------------------

class TestGCCParserFixture:

    def test_parse_real_gcc_report(self, parser):
        report_path = FIXTURE_DIR / "reports" / "gcc_example.txt"
        if not report_path.exists():
            pytest.skip("Fixture GCC non générée (lance make fixtures d'abord)")
        records = parser.parse_file(report_path)
        # On sait que prefix_sum crée au moins un missed
        assert len(records) >= 1
        missed = [r for r in records if r.is_missed]
        assert len(missed) >= 1

    def test_parse_real_full_report_has_vectorized(self, parser):
        report_path = FIXTURE_DIR / "reports" / "gcc_example_full.txt"
        if not report_path.exists():
            pytest.skip("Fixture complète non générée")
        records = parser.parse_file(report_path)
        vectorized = [r for r in records if r.is_vectorized]
        assert len(vectorized) >= 1, "Au moins add_vectors doit être vectorisée"


# ---------------------------------------------------------------------------
# Tests moteur de diagnostic
# ---------------------------------------------------------------------------

class TestDiagnosticEngine:

    def test_vectorized_no_suggestions(self, parser, engine):
        text = "foo.c:10:5: optimized: loop vectorized using 32 byte vectors"
        records = parser.parse_text(text)
        result = engine.diagnose(records[0])
        assert result.has_suggestions is False

    def test_aliasing_has_suggestion(self, parser, engine):
        text = "foo.c:24:9: missed: not vectorized: possible aliasing problem"
        records = parser.parse_text(text)
        result = engine.diagnose(records[0])
        assert result.has_suggestions
        assert "restrict" in result.suggestions[0].fix.lower() \
            or "ivdep"    in result.suggestions[0].fix.lower()

    def test_control_flow_has_suggestion(self, parser, engine):
        text = "foo.c:30:5: missed: not vectorized: control flow in loop"
        records = parser.parse_text(text)
        result = engine.diagnose(records[0])
        assert result.has_suggestions
        s = result.suggestions[0]
        assert "masque" in s.fix.lower() or "if" in s.explanation.lower()

    def test_unknown_trip_count_suggestion_mentions_local(self, parser, engine):
        text = "foo.c:38:5: missed: not vectorized: number of iterations cannot be computed"
        records = parser.parse_text(text)
        result = engine.diagnose(records[0])
        assert result.has_suggestions
        assert "locale" in result.suggestions[0].fix.lower() \
            or "local" in result.suggestions[0].fix.lower()

    def test_diagnose_all_returns_audit_report(self, parser, engine):
        text = (
            "src.c:10:5: optimized: loop vectorized using 32 byte vectors\n"
            "src.c:20:9: missed: not vectorized: possible aliasing problem\n"
        )
        records = parser.parse_text(text)
        report  = engine.diagnose_all(records)
        assert report.total           >= 1
        assert report.vectorized_count >= 1
        assert report.missed_count    >= 1
        assert 0 < report.vectorization_rate <= 100

    def test_missed_by_kind_counts(self, parser, engine):
        text = (
            "a.c:10:5: missed: not vectorized: possible aliasing problem\n"
            "a.c:20:5: missed: not vectorized: possible aliasing problem\n"
            "a.c:30:5: missed: not vectorized: control flow in loop\n"
        )
        records = parser.parse_text(text)
        report  = engine.diagnose_all(records)
        by_kind = report.missed_by_kind()
        assert by_kind.get(FailureKind.ALIASING,      0) == 2
        assert by_kind.get(FailureKind.CONTROL_FLOW,  0) == 1
