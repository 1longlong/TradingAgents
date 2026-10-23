"""Phase 3B offline tests for the evidence-manifest valid-new-evidence rules.

Covers the deterministic citation allowlist and the eligibility / linkage /
date rules: unknown, late, missing-date, unparseable-date, and unlinked IDs
never count; only known, High/Medium, on-or-before-target, linked, previously
unused IDs do.
"""

from __future__ import annotations

import json

import pytest

from tradingagents.debate.evidence_manifest import (
    EvidenceManifest,
    build_citation_allowlist,
    build_evidence_manifest_index,
    collect_valid_new_evidence,
    is_valid_new_evidence,
)

TARGET = "2026-05-13"


def _record(
    evidence_id: str,
    *,
    status: str = "High",
    observed: str | None = "2026-05-01",
    value_raw: str = "105.5",
    metric: str = "close",
    unit: str = "USD",
) -> dict:
    return {
        "evidence_id": evidence_id,
        "quality_status": status,
        "observed_at": observed,
        "value_raw": value_raw,
        "metric_name": metric,
        "unit_normalized": unit,
        "unit_raw": unit,
    }


@pytest.fixture
def manifest() -> EvidenceManifest:
    return EvidenceManifest.from_records(
        [
            _record("ev:close", status="High"),
            _record("ev:volume", status="Medium", observed="2026-05-12"),
            _record("ev:low", status="Low"),
            _record("ev:late", observed="2026-06-01"),
            _record("ev:badrate", observed="not-a-date"),
            _record("ev:missingrate", observed=None),
        ]
    )


class TestIsValidNewEvidence:
    def test_ideal_id_counts(self, manifest):
        assert is_valid_new_evidence(
            evidence_id="ev:close",
            previously_cited=set(),
            currently_linked=True,
            manifest=manifest,
            target_date=TARGET,
        )

    def test_previously_cited_never_counts(self, manifest):
        assert not is_valid_new_evidence(
            evidence_id="ev:close",
            previously_cited={"ev:close"},
            currently_linked=True,
            manifest=manifest,
            target_date=TARGET,
        )

    def test_unknown_id_never_counts(self, manifest):
        assert not is_valid_new_evidence(
            evidence_id="ev:ghost",
            previously_cited=set(),
            currently_linked=True,
            manifest=manifest,
            target_date=TARGET,
        )

    def test_low_status_never_counts(self, manifest):
        assert not is_valid_new_evidence(
            evidence_id="ev:low",
            previously_cited=set(),
            currently_linked=True,
            manifest=manifest,
            target_date=TARGET,
        )

    def test_unlinked_never_counts(self, manifest):
        # A citation alone (currently_linked=False) never counts.
        assert not is_valid_new_evidence(
            evidence_id="ev:close",
            previously_cited=set(),
            currently_linked=False,
            manifest=manifest,
            target_date=TARGET,
        )

    def test_late_never_counts(self, manifest):
        assert not is_valid_new_evidence(
            evidence_id="ev:late",
            previously_cited=set(),
            currently_linked=True,
            manifest=manifest,
            target_date=TARGET,
        )

    def test_unparseable_observed_never_counts(self, manifest):
        assert not is_valid_new_evidence(
            evidence_id="ev:badrate",
            previously_cited=set(),
            currently_linked=True,
            manifest=manifest,
            target_date=TARGET,
        )

    def test_missing_observed_never_counts(self, manifest):
        assert not is_valid_new_evidence(
            evidence_id="ev:missingrate",
            previously_cited=set(),
            currently_linked=True,
            manifest=manifest,
            target_date=TARGET,
        )

    def test_missing_target_date_fails_closed(self, manifest):
        # target_date is None -> cannot prove on-or-before -> never counts.
        assert not is_valid_new_evidence(
            evidence_id="ev:close",
            previously_cited=set(),
            currently_linked=True,
            manifest=manifest,
            target_date=None,
        )

    def test_duplicate_rejected(self, manifest):
        assert not is_valid_new_evidence(
            evidence_id="ev:close",
            previously_cited=set(),
            currently_linked=True,
            manifest=manifest,
            target_date=TARGET,
            is_duplicate=True,
        )

    def test_observed_on_target_counts(self):
        m = EvidenceManifest.from_records([_record("ev:x", observed="2026-05-13")])
        assert is_valid_new_evidence(
            evidence_id="ev:x",
            previously_cited=set(),
            currently_linked=True,
            manifest=m,
            target_date=TARGET,
        )


class TestCollectValidNewEvidence:
    def test_linked_new_id_counts(self, manifest):
        new, _ = collect_valid_new_evidence(
            cited_ids=["ev:close"],
            previously_cited=set(),
            manifest=manifest,
            target_date=TARGET,
            eligible_ids=["ev:close"],
        )
        assert new == ["ev:close"]

    def test_unlinked_id_does_not_count_even_if_cited(self, manifest):
        # The ID is cited in prose but not linked to a claim -> never counts.
        new, _ = collect_valid_new_evidence(
            cited_ids=["ev:close"],
            previously_cited=set(),
            manifest=manifest,
            target_date=TARGET,
            eligible_ids=["ev:other"],
        )
        assert new == []

    def test_no_eligible_ids_nothing_counts(self, manifest):
        new, _ = collect_valid_new_evidence(
            cited_ids=["ev:close"],
            previously_cited=set(),
            manifest=manifest,
            target_date=TARGET,
            eligible_ids=None,
        )
        assert new == []

    def test_empty_eligible_ids_nothing_counts(self, manifest):
        new, _ = collect_valid_new_evidence(
            cited_ids=["ev:close"],
            previously_cited=set(),
            manifest=manifest,
            target_date=TARGET,
            eligible_ids=[],
        )
        assert new == []

    def test_mixed_ids_only_valid_count(self, manifest):
        new, _ = collect_valid_new_evidence(
            cited_ids=["ev:close", "ev:low", "ev:ghost", "ev:late"],
            previously_cited=set(),
            manifest=manifest,
            target_date=TARGET,
            eligible_ids=["ev:close", "ev:low", "ev:ghost", "ev:late"],
        )
        assert new == ["ev:close"]

    def test_duplicate_cited_ids_dedup(self, manifest):
        new, _ = collect_valid_new_evidence(
            cited_ids=["ev:close", "ev:close"],
            previously_cited=set(),
            manifest=manifest,
            target_date=TARGET,
            eligible_ids=["ev:close"],
        )
        assert new == ["ev:close"]

    def test_text_duplicate_rejected_via_index(self, manifest):
        index = build_evidence_manifest_index(
            [_record("ev:a", value_raw="105.5", metric="close"), _record("ev:b", value_raw="105.5", metric="close")]
        )
        new, _ = collect_valid_new_evidence(
            cited_ids=["ev:b"],
            previously_cited={"ev:a"},
            manifest=manifest,
            target_date=TARGET,
            eligible_ids=["ev:b"],
            evidence_manifest_index=index,
        )
        assert new == []


class TestBuildCitationAllowlist:
    def test_allowlist_only_valid_and_on_target(self, manifest):
        allow = build_citation_allowlist(manifest_serialized(), TARGET)
        assert "ev:close" in allow
        assert "ev:volume" in allow
        # Low, late, unparseable, missing-date, and unknown IDs are never listed.
        assert "ev:low" not in allow
        assert "ev:late" not in allow
        assert "ev:badrate" not in allow
        assert "ev:missingrate" not in allow
        assert "ev:ghost" not in allow

    def test_allowlist_excludes_on_target_absent(self, manifest):
        allow = build_citation_allowlist(manifest_serialized(), "2026-01-01")
        assert "no validated, on-or-before-target evidence" in allow.lower()
        assert "ev:close" not in allow

    def test_allowlist_is_deterministic(self, manifest):
        a = build_citation_allowlist(manifest_serialized(), TARGET)
        b = build_citation_allowlist(manifest_serialized(), TARGET)
        assert a == b
        # JSON-safe plain string.
        assert json.dumps(a)

    def test_allowlist_is_bounded(self):
        records = [_record(f"ev:{i}") for i in range(50)]
        allow = build_citation_allowlist(records, TARGET, limit=5)
        # At most `limit` entries; each entry starts with ``- ``.
        entries = [line for line in allow.splitlines() if line.startswith("- ")]
        assert len(entries) == 5

    def test_allowlist_carries_metadata(self, manifest):
        allow = build_citation_allowlist(manifest_serialized(), TARGET)
        assert "close" in allow
        assert "105.5" in allow
        assert "USD" in allow
        assert "[quality: High]" in allow

    def test_empty_records_fails_closed(self):
        allow = build_citation_allowlist([], TARGET)
        assert "no validated, on-or-before-target evidence" in allow.lower()


def manifest_serialized():
    return [
        _record("ev:close", status="High"),
        _record("ev:volume", status="Medium", observed="2026-05-12"),
        _record("ev:low", status="Low"),
        _record("ev:late", observed="2026-06-01"),
        _record("ev:badrate", observed="not-a-date"),
        _record("ev:missingrate", observed=None),
    ]
