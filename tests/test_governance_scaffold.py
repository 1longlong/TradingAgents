"""Tests for the offline governance/schema validator (CS5351 scaffold).

These unit tests import ``scripts/validate/validate_requirements.py`` directly
so they run in the default offline ``pytest -q`` suite without network or a
paid API. They verify the deterministic validator logic and the exact stable-ID
/schema-version patterns in the real ``docs/req/req-schema.json``.

When ``jsonschema`` is installed, they also run the requirements against the
real draft-2020-12 schema (the same path CI enforces); when it is absent, the
deterministic subset fallback is exercised and the jsonschema test is skipped
(so it is clear the real schema is only enforced where jsonschema is present).
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate/validate_requirements.py"
SCHEMA_PATH = ROOT / "docs/req/req-schema.json"
REQUIREMENTS_PATH = ROOT / "docs/req/requirements.yaml"

spec = importlib.util.spec_from_file_location("validate_requirements", VALIDATOR)
validate_requirements = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate_requirements)


def load_real_schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_real_requirements():
    import yaml

    with open(REQUIREMENTS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Reuse the exact patterns from the real schema so the test cannot drift from it.
SCHEMA_VERSION_PATTERN = load_real_schema()["properties"]["project"]["properties"][
    "schema_version"
]["pattern"]
ID_PATTERN = load_real_schema()["$defs"]["requirement"]["properties"]["id"]["pattern"]


@pytest.mark.unit
class TestSchemaVersionPattern:
    def test_schema_version_match(self):
        # The pattern must decode to ^v[0-9]+\.[0-9]+$ with a single backslash.
        assert SCHEMA_VERSION_PATTERN == r"^v[0-9]+\.[0-9]+$"
        assert SCHEMA_VERSION_PATTERN.count("\\") == 1
        assert re.fullmatch(SCHEMA_VERSION_PATTERN, "v1.0")
        assert re.fullmatch(SCHEMA_VERSION_PATTERN, "v2.1")

    def test_schema_version_reject(self):
        assert not re.fullmatch(SCHEMA_VERSION_PATTERN, "1.0")
        assert not re.fullmatch(SCHEMA_VERSION_PATTERN, "v1")
        assert not re.fullmatch(SCHEMA_VERSION_PATTERN, "v1.0.0")


@pytest.mark.unit
class TestStableIdPattern:
    def test_accepts_exact_required_forms(self):
        # Exact requested forms: FR-DQG-NNN, FR-DDT-NNN, NFR-CATEGORY-NNN.
        for rid in ("FR-DQG-001", "FR-DQG-002", "FR-DDT-001", "FR-DDT-004",
                    "NFR-DET-001", "NFR-FC-001", "NFR-OFF-001"):
            assert re.fullmatch(ID_PATTERN, rid), rid

    def test_rejects_malformed_ids(self):
        # No extra segment, no digits, wrong category form, lowercase, etc.
        for rid in ("FR-DQG", "FR-DQG-1", "FR-DQG-001-002", "FR-DT-001",
                    "FR-XYZ-001", "NFR-DET", "nfr-det-001", "NFR-DET-001-002"):
            assert not re.fullmatch(ID_PATTERN, rid), rid


@pytest.mark.unit
class TestJsoncParsing:
    def test_strips_line_and_block_comments(self):
        text = '{\n  // line comment\n  "a": 1, /* block */ "b": 2\n}\n'
        assert validate_requirements.parse_jsonc(text) == {"a": 1, "b": 2}

    def test_parses_actual_permissions_file(self):
        path = ROOT / ".opencode/permissions.jsonc"
        assert isinstance(validate_requirements.parse_jsonc(path.read_text()), dict)


@pytest.mark.unit
class TestSchemeValidation:
    def test_well_formed_requirements_pass(self):
        reqs = {
            "project": {"name": "x", "branch": "b", "schema_version": "v1.0",
                        "deliverable_slide_sources": ["src/"],
                        "canonical_source_trees": ["tradingagents/"]},
            "requirements": [
                {"id": "FR-DQG-001", "type": "Feature", "title": "t",
                 "description": "d", "priority": "Must",
                 "source_files": ["a.py"], "design_artifacts": ["adr.md"],
                 "tests": ["t.py"], "verification_evidence": ["obs"]},
            ],
        }
        schema = {"type": "object"}
        assert validate_requirements.validate_requirements(reqs, schema) == []

    def test_duplicate_id_rejected(self):
        reqs = {
            "project": {"name": "x", "branch": "b", "schema_version": "v1.0",
                        "deliverable_slide_sources": ["s"], "canonical_source_trees": ["c"]},
            "requirements": [
                {"id": "NFR-DET-001", "type": "NonFunctional", "title": "a",
                 "description": "b", "priority": "Must", "source_files": ["a"],
                 "design_artifacts": ["d"], "tests": [], "verification_evidence": ["e"]},
                {"id": "NFR-DET-001", "type": "NonFunctional", "title": "a",
                 "description": "b", "priority": "Must", "source_files": ["a"],
                 "design_artifacts": ["d"], "tests": [], "verification_evidence": ["e"]},
            ],
        }
        errors = validate_requirements.validate_requirements(reqs, {})
        assert any("duplicate" in e for e in errors)


@pytest.mark.unit
class TestDispatcherAgainstRealSchema:
    def test_real_requirements_pass_real_schema(self):
        errors = validate_requirements.validate_against_schema(
            load_real_requirements(), load_real_schema()
        )
        assert errors == []

    def test_real_schema_rejects_bad_id(self):
        bad = load_real_requirements()
        bad["requirements"][0]["id"] = "FR-DQG"  # missing -NNN
        errors = validate_requirements.validate_against_schema(bad, load_real_schema())
        assert any("id" in e for e in errors)

    def test_real_schema_rejects_bad_schema_version(self):
        bad = load_real_requirements()
        bad["project"]["schema_version"] = "1.0"
        errors = validate_requirements.validate_against_schema(bad, load_real_schema())
        assert errors, "schema_version '1.0' must be rejected"

    def test_jsonschema_is_used_when_available(self):
        # If jsonschema is installed, the dispatcher must use it (not the subset).
        import importlib.util

        if importlib.util.find_spec("jsonschema") is None:
            pytest.skip("jsonschema not installed; real-schema test skipped here")
        assert validate_requirements._JSSCHEMA_AVAILABLE is True
        # A property the draft-2020-12 schema rejects (extra top-level key) must
        # be caught by the real validator, proving it is in force.
        bad = load_real_requirements()
        bad["unexpected_top_level"] = True
        errors = validate_requirements.validate_against_schema(bad, load_real_schema())
        assert errors


@pytest.mark.unit
class TestSecretScan:
    def test_flags_real_looking_secret(self):
        hits = validate_requirements.scan_secrets("api_key = 'sk-abcdefghijklm123456'\n")
        assert len(hits) == 1

    def test_allows_placeholders(self):
        hits = validate_requirements.scan_secrets("OPENAI_API_KEY=your-key-here\n")
        assert hits == []

    def test_does_not_flag_the_validator_itself(self):
        text = VALIDATOR.read_text()
        # The validator's own scanner must not match its own regex literals as secrets.
        assert validate_requirements.scan_secrets(text) == []


@pytest.mark.unit
class TestRequiredArtifactPresence:
    def test_required_files_exist_and_nonempty(self):
        for rel in validate_requirements.REQUIRED_FILES:
            path = ROOT / rel
            assert path.exists(), rel
            assert path.stat().st_size > 0, rel
