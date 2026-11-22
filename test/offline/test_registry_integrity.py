"""Deterministic integrity checks for the merged AUL and requirements registries."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
AUL = ROOT / "docs" / "ai-use-log.yaml"
REQ = ROOT / "docs" / "req" / "requirements.yaml"

WEB_IDS = {
    "REQ-WEB-001", "REQ-WEB-002", "REQ-WEB-003", "REQ-WEB-004", "REQ-WEB-005",
    "REQ-WEB-006", "REQ-WEB-007", "REQ-WEB-008", "REQ-WEB-009", "REQ-WEB-010",
    "REQ-WEB-011", "REQ-WEB-012", "REQ-WEB-013", "REQ-WEB-014", "REQ-WEB-020",
    "REQ-WEB-021", "REQ-WEB-022", "REQ-WEB-023", "REQ-WEB-024", "REQ-WEB-025",
    "REQ-WEB-026", "REQ-WEB-027", "REQ-WEB-028", "REQ-WEB-029", "REQ-WEB-030",
    "REQ-WEB-031",
}
PERSONAL_IDS = {
    "FR-ANL-001", "FR-ANL-002", "FR-ANL-003", "FR-ANL-004", "FR-ANL-005",
    "FR-ANL-006", "FR-ANL-008", "FR-ANL-009", "FR-ANL-010",
    "FR-OBS-001", "FR-OBS-002", "FR-OBS-003", "FR-OBS-004", "FR-OBS-005",
    "FR-HAR-001", "FR-HAR-002", "FR-HAR-003", "FR-CAM-001",
    "NFR-VER-001", "NFR-VER-002",
}


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys."""


def _construct_mapping(loader, node):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _strict_load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=_StrictLoader)


def _entries(document):
    return document if isinstance(document, list) else document["entries"]


def _ids(rows):
    return [row["id"] for row in rows]


def test_aul_ids_are_unique_and_distinct_events_are_preserved():
    rows = _entries(_strict_load(AUL))
    ids = _ids(rows)
    assert len(ids) == len(set(ids)), "duplicate active AUL id"
    assert len(ids) >= 154
    # One canonical Release event and one personal event must both survive.
    assert {"AUL-071", "AUL-072", "AUL-073"} <= set(ids)
    assert {"AUL-106", "AUL-107", "AUL-108"} <= set(ids)


def test_aul_duplicate_ids_are_rejected():
    rows = _entries(_strict_load(AUL))
    ids = _ids(rows) + [_ids(rows)[0]]
    with pytest.raises(AssertionError, match="duplicate active AUL id"):
        assert len(ids) == len(set(ids)), "duplicate active AUL id"


def test_duplicate_yaml_keys_are_rejected(tmp_path):
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("entries:\n  - id: A\n    id: B\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate YAML key"):
        _strict_load(duplicate)


def test_requirements_completeness_and_uniqueness():
    document = _strict_load(REQ)
    rows = document["requirements"]
    ids = _ids(rows)
    assert len(ids) == len(set(ids)), "duplicate requirement id"
    assert set(ids) >= WEB_IDS, sorted(WEB_IDS - set(ids))
    assert set(ids) >= PERSONAL_IDS, sorted(PERSONAL_IDS - set(ids))
    assert len(ids) >= 78
    for row in rows:
        assert row["fit_criteria"], row["id"]
        assert row["statement"], row["id"]


def test_trace_matrix_mentions_every_webui_requirement():
    trace = (ROOT / "docs" / "architecture" / "trace-matrix.md").read_text(encoding="utf-8")
    missing = sorted(web for web in WEB_IDS if web not in trace)
    assert not missing, missing
