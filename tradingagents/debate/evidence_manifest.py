"""Evidence-manifest helpers for Phase 3B valid-new-evidence tracking.

The Data Quality Gate stores serialized ``EvidenceRecord`` dicts on the state
under ``data_quality_evidence_records``. This module turns that list into an
indexed manifest and applies the deterministic valid-new-evidence rules from
the Phase 3B spec:

An evidence ID counts as new only if all of these hold:

1. it has not previously been cited in the debate;
2. its evidence/validation status is High or Medium;
3. it is explicitly linked to a current claim;
4. it is not a formatting/rephrasing duplicate;
5. ``observed_at`` is parseable and not later than ``target_date``.

A missing or unparseable ``observed_at`` **or** ``target_date`` fails closed:
the record cannot be proven observed on/before the target date, so it never
counts as new. Low evidence may be mentioned as a limitation but never counts
as new. An ID absent from the evidence manifest never counts, nor does an ID
that is not explicitly linked to a current claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

# Quality statuses that count as valid evidence for the "new evidence" rule.
VALID_EVIDENCE_STATUSES = frozenset({"High", "Medium"})

# Manifest entry value for an evidence ID that is present but not High/Medium.
_NOT_VALID = "not-valid"


@dataclass(frozen=True)
class EvidenceManifest:
    """Indexed view of the gate's evidence records keyed by ``evidence_id``."""

    # evidence_id -> quality_status ("" when the ID is absent from the manifest).
    status_by_id: dict[str, str]
    # evidence_id -> observed_at ("" absent)
    observed_at_by_id: dict[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "status_by_id", dict(self.status_by_id))
        object.__setattr__(self, "observed_at_by_id", dict(self.observed_at_by_id))

    @classmethod
    def from_records(cls, records: list[dict[str, Any]] | None) -> EvidenceManifest:
        """Build a manifest from serialized ``EvidenceRecord`` dicts.

        IDs absent from ``records`` are simply not present in the manifest, so a
        later ``is_known`` check returns ``False`` and such an ID never counts.
        """
        status_by_id: dict[str, str] = {}
        observed_at_by_id: dict[str, str] = {}
        for record in records or []:
            if not isinstance(record, dict):
                continue
            evidence_id = str(record.get("evidence_id", ""))
            if not evidence_id:
                continue
            status = str(record.get("quality_status", ""))
            status_by_id[evidence_id] = status
            observed = str(record.get("observed_at", "") or "")
            observed_at_by_id[evidence_id] = observed
        return cls(status_by_id=status_by_id, observed_at_by_id=observed_at_by_id)

    def is_known(self, evidence_id: str) -> bool:
        """True iff the ID is present in the gate's evidence manifest."""
        return evidence_id in self.status_by_id

    def is_valid_status(self, evidence_id: str) -> bool:
        """True iff the ID is present and its status is High or Medium."""
        return self.status_by_id.get(evidence_id, "") in VALID_EVIDENCE_STATUSES

    def observed_at_not_later_than(self, evidence_id: str, target_date: str | None) -> bool:
        """True iff ``observed_at`` is parseable and not later than ``target_date``.

        Fail closed (authoritative): when either ``observed_at`` or
        ``target_date`` is missing or unparseable, the record cannot be proven
        to have been observed on or before the target date, so it does **not**
        qualify as valid new evidence. ``observed_at <= target_date`` must be
        demonstrated, not assumed, before the ID can count.
        """
        target = _parse_date(target_date)
        if target is None:
            return False
        observed = _parse_date(self.observed_at_by_id.get(evidence_id, ""))
        if observed is None:
            return False
        return observed <= target

    @property
    def valid_ids(self) -> tuple[str, ...]:
        """All manifest IDs whose status is High or Medium (sorted, unique)."""
        return tuple(sorted(
            eid for eid, status in self.status_by_id.items() if status in VALID_EVIDENCE_STATUSES
        ))


def _parse_date(value: Any) -> date | None:
    from tradingagents.evidence.policy import to_date

    return to_date(value)


def is_valid_new_evidence(
    *,
    evidence_id: str,
    previously_cited: set[str],
    currently_linked: bool,
    manifest: EvidenceManifest,
    target_date: str | None,
    is_duplicate: bool = False,
) -> bool:
    """Apply the deterministic valid-new-evidence rules to one cited ID.

    Returns ``True`` only if every rule (1)-(5) passes. Low evidence and IDs
    absent from the manifest are never new.
    """
    if not evidence_id or is_duplicate:
        return False
    if evidence_id in previously_cited:
        return False
    if not manifest.is_known(evidence_id):
        return False
    if not manifest.is_valid_status(evidence_id):
        return False
    if not currently_linked:
        return False
    return manifest.observed_at_not_later_than(evidence_id, target_date)


def collect_valid_new_evidence(
    *,
    cited_ids: list[str],
    previously_cited: set[str],
    manifest: EvidenceManifest,
    target_date: str | None,
    eligible_ids: list[str] | None = None,
    evidence_manifest_index: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return ``(new_valid_ids, cited_ids)` for a turn, applying every rule.

    ``eligible_ids`` is the list of IDs the speaker **explicitly linked to a
    new claim** (rule 3). Failing closed: when ``None`` or empty, no ID is
    treated as linked, so *nothing* counts as new — a citation alone is never
    sufficient. ``evidence_manifest_index`` is an optional map of
    ``evidence_id -> normalized_text`` used to reject a formatting/rephrasing
    duplicate; an ID whose text matches an already-cited ID (case/whitespace
    folded) is treated as a duplicate.
    """
    linked = set(eligible_ids) if eligible_ids else set()
    new_valid: list[str] = []
    seen: set[str] = set()
    for evidence_id in cited_ids:
        if not evidence_id or evidence_id in seen:
            continue
        seen.add(evidence_id)
        is_duplicate = _is_text_duplicate(
            evidence_id, previously_cited, evidence_manifest_index
        )
        if is_valid_new_evidence(
            evidence_id=evidence_id,
            previously_cited=previously_cited,
            currently_linked=evidence_id in linked,
            manifest=manifest,
            target_date=target_date,
            is_duplicate=is_duplicate,
        ):
            new_valid.append(evidence_id)
    # Keep deterministic order while preserving caller intent.
    return new_valid, list(cited_ids)


def _is_text_duplicate(
    evidence_id: str,
    previously_cited: set[str],
    index: dict[str, str] | None,
) -> bool:
    """True iff the ID is a rephrasing duplicate of a previously cited ID.

    Without a text index we cannot detect a rephrasing duplicate, so this
    returns ``False`` (only the exact-ID rule applies).
    """
    if not index:
        return False
    known = any(index.get(prev, "").strip().lower() == index.get(evidence_id, "").strip().lower()
                for prev in previously_cited if prev != evidence_id)
    return known


def build_evidence_manifest_index(records: list[dict[str, Any]] | None) -> dict[str, str]:
    """Build ``evidence_id -> normalized value text`` for duplicate detection."""
    index: dict[str, str] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        evidence_id = str(record.get("evidence_id", ""))
        # A value present here is the natural identity to compare for a
        # rephrasing duplicate; fall back to the metric name + source.
        if not evidence_id:
            continue
        value_raw = str(record.get("value_raw", "") or "")
        metric = str(record.get("metric_name", "") or "")
        index[evidence_id] = f"{metric}:{value_raw}".strip().lower()
    return index


def build_citation_allowlist(
    records: list[dict[str, Any]] | None,
    target_date: str | None,
    *,
    limit: int = 16,
) -> str:
    """A bounded, deterministic allowlist of citable evidence IDs for a prompt.

    Only IDs that are valid (High/Medium) **and** proven observed on/before the
    target date are listed, each with its metric name, value, unit, and status
    so a Bull/Bear researcher can cite real, auditable IDs. Unknown or invalid
    IDs are simply absent, so a citation channel cannot fabricate an ID: the
    caller never sees an ID that would not count as valid. ``limit`` bounds the
    allowlist so a prompt cannot carry hundreds of records.
    """
    records = records or []
    manifest = EvidenceManifest.from_records(records)
    order = sorted(manifest.valid_ids)
    entries: list[str] = []
    cutoff = max(1, int(limit))
    for evidence_id in order:
        if not manifest.observed_at_not_later_than(evidence_id, target_date):
            continue
        record = _first_record(records, evidence_id)
        metric = str(record.get("metric_name", "") or "") if record else ""
        value_raw = str(record.get("value_raw", "") or "") if record else ""
        unit = str(record.get("unit_normalized", "") or record.get("unit_raw", "") or "")
        unit_suffix = f" {unit}" if unit else ""
        status = str(manifest.status_by_id.get(evidence_id, ""))
        entries.append(
            f"- {evidence_id}: {metric} = {value_raw}{unit_suffix} "
            f"[quality: {status}]"
        )
        if len(entries) >= cutoff:
            break
    if not entries:
        return (
            "[Data Quality Gate] No validated, on-or-before-target evidence IDs "
            "are available to cite in this run."
        )
    header = (
        "[Data Quality Gate] You may cite ONLY these validated evidence IDs "
        "(each is High/Medium and observed on or before the target date):"
    )
    return header + "\n" + "\n".join(entries)


def _first_record(records: list[dict[str, Any]], evidence_id: str) -> dict[str, Any] | None:
    for record in records:
        if isinstance(record, dict) and str(record.get("evidence_id", "")) == evidence_id:
            return record
    return None
