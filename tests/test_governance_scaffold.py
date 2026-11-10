"""Tests for the offline governance/schema validator (CS5351 scaffold).

These unit tests import ``scripts/validate/validate_requirements.py`` directly
so they run in the default offline ``pytest -q`` suite without network or a
paid API. They verify the deterministic validator logic and the exact stable-ID
/schema-version patterns in the real ``docs/req/req-schema.json``.

When ``jsonschema`` is installed, they also run the requirements against the
real draft-2020-12 schema (the same path CI enforces); when it is absent, the
deterministic subset fallback is exercised and the jsonschema test is skipped
(so it is clear the real schema is only enforced where jsonschema is present).

Traceability: NFR-SEC-001 (secret scan), NFR-OFF-001 (offline harness
count-and-fail logic); also verifies the mapped-test traceability governance
regression (tag resolution) without inventing acceptance or new IDs.
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


def _duplicate_id_requirements():
    """Two requirements sharing an ID but with DIFFERING objects.

    ``uniqueItems`` alone does not reject this (the objects differ), so the
    shared semantic ID-uniqueness check must catch it on BOTH entry paths.
    """
    return {
        "project": {
            "name": "x",
            "branch": "b",
            "schema_version": "v1.0",
            "deliverable_slide_sources": ["src/"],
            "canonical_source_trees": ["tradingagents/"],
        },
        "requirements": [
            {
                "id": "NFR-DET-001",
                "type": "NonFunctional",
                "title": "first",
                "description": "first description",
                "priority": "Must",
                "source_files": ["a.py"],
                "design_artifacts": ["adr.md"],
                "tests": ["t.py"],
                "verification_evidence": ["obs-1"],
            },
            {
                "id": "NFR-DET-001",
                "type": "NonFunctional",
                "title": "second",
                "description": "a different description",
                "priority": "Should",
                "source_files": ["b.py"],
                "design_artifacts": ["adr.md"],
                "tests": ["t2.py"],
                "verification_evidence": ["obs-2"],
            },
        ],
    }


@pytest.mark.unit
class TestDuplicateIdSemanticValidation:
    """Regression (2026-11-10): shared ID uniqueness on real + fallback paths.

    The real ``jsonschema`` path accepted duplicate requirement IDs while the
    deterministic fallback rejected them. ``uniqueItems`` alone is insufficient
    because two objects with the same ``id`` can differ in every other field.
    Both actual entry paths must reject a duplicate ID via the same shared check.
    """

    def test_fallback_rejects_duplicate_differing_objects(self):
        errors = validate_requirements.validate_requirements(
            _duplicate_id_requirements(), {"type": "object"}
        )
        assert any("duplicate" in e for e in errors), errors

    def test_real_schema_path_rejects_duplicate_differing_objects(self):
        import importlib.util

        if importlib.util.find_spec("jsonschema") is None:
            pytest.skip("jsonschema not installed; real-schema path unavailable here")
        errors = validate_requirements.validate_against_schema(
            _duplicate_id_requirements(), load_real_schema()
        )
        assert any("duplicate" in e for e in errors), errors

    def test_semantic_uniqueness_helper_accepts_valid_registry(self):
        # The real registry has unique IDs; the shared check must not reject it.
        assert (
            validate_requirements.validate_unique_requirement_ids(
                load_real_requirements()
            )
            == []
        )

    def test_semantic_uniqueness_helper_flags_duplicate(self):
        errors = validate_requirements.validate_unique_requirement_ids(
            _duplicate_id_requirements()
        )
        assert any("duplicate" in e for e in errors), errors

    def test_semantic_uniqueness_helper_handles_malformed_rows(self):
        # A non-list registry, non-dict rows, and missing/non-string IDs must not
        # crash; only genuine duplicates are uniqueness errors.
        assert (
            validate_requirements.validate_unique_requirement_ids(
                {"requirements": "not-a-list"}
            )
            == []
        )
        assert (
            validate_requirements.validate_unique_requirement_ids(
                {"requirements": ["x", 5, {"title": "no id"}]}
            )
            == []
        )
        dup = validate_requirements.validate_unique_requirement_ids(
            {"requirements": [{"id": "NFR-DET-001"}, {"id": "NFR-DET-001"}]}
        )
        assert any("duplicate" in e for e in dup), dup

    def test_real_registry_passes_both_paths(self):
        # The actual 22-ID registry must remain valid (no duplicates) on both the
        # semantic check and the real-schema dispatcher.
        assert (
            validate_requirements.validate_against_schema(
                load_real_requirements(), load_real_schema()
            )
            == []
        )

    def test_real_schema_rejects_duplicate_with_id_in_error(self):
        import importlib.util

        if importlib.util.find_spec("jsonschema") is None:
            pytest.skip("jsonschema not installed; real-schema path unavailable here")
        errors = validate_requirements.validate_against_schema(
            _duplicate_id_requirements(), load_real_schema()
        )
        # The shared check reports the duplicated ID for traceability.
        assert any("NFR-DET-001" in e for e in errors), errors


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

    def test_inventory_includes_current_adrs_prompt_and_proposals(self):
        # The current v1.3 prompt, proposed ADR-004/005, and the permission/CI/
        # human-rule PROPOSALS must be in the required-artifact inventory. Presence
        # and parse only — this does NOT mean enforcement or implementation.
        req = set(validate_requirements.REQUIRED_FILES)
        for rel in (
            "prompts/prompt_v1.3.yaml",
            "docs/architecture/adr/004-governance-context-design.proposed.md",
            "docs/architecture/adr/005-blocked-output-multiline-containment.md",
            "docs/code-governance/agent-permissions-proposal.yaml",
            "docs/code-governance/ci-gate-matrix.md",
            "docs/code-governance/human-rules-proposal.md",
        ):
            assert rel in req, rel

    def test_yaml_inventory_parses(self):
        import yaml

        for rel in validate_requirements.YAML_FILES:
            path = ROOT / rel
            assert path.exists(), rel
            yaml.safe_load(path.read_text(encoding="utf-8"))  # must not raise


_TAG_RE = re.compile(r"(?:FR-(?:DQG|DDT)-\d{3}|NFR-[A-Z]+-\d{3}|INV-\d+)")


def _declared_traceability_tags(text):
    """Tags declared on/after a ``Traceability:`` line (not incidental literals).

    Mapped tests declare their traceability starting on an explicit
    ``Traceability:`` line and continuing over wrapped lines until a blank line or
    the end of the docstring. An unrelated ID literal in a negative test fixture
    (e.g. a fake ``NFR-NOPE-001``) is never mistaken for a claimed mapping.
    """
    tags = set()
    collecting = False
    for line in text.splitlines():
        stripped = line.strip()
        # A declaration STARTs with "Traceability:" (not a prose mention of the
        # word inside a docstring/comment), and stops at a blank line or the end
        # of the enclosing docstring.
        if stripped.startswith("Traceability:"):
            collecting = True
            tags |= set(_TAG_RE.findall(line))
            continue
        if collecting:
            if not stripped or '"""' in line or "'''" in line:
                collecting = False
                continue
            tags |= set(_TAG_RE.findall(line))
    return tags


def _registry_ids(requirements):
    return {req["id"] for req in requirements["requirements"]}


def _invariant_ids():
    text = (ROOT / "docs/architecture/invariants.md").read_text(encoding="utf-8")
    return set(re.findall(r"^## (INV-\d+)", text, re.MULTILINE))


@pytest.mark.unit
class TestMappedTestTraceability:
    """Governance regression (2026-11-10): the mapped test files are traceable.

    The 29 test files referenced by the 22 requirement entries must carry an
    accurate, resolvable requirement/invariant tag; a tag is only valid if it
    names a real registry or invariant ID. This pins traceability mechanically
    without inventing acceptance, metrics, or new IDs.
    """

    def test_registry_keeps_exactly_22_ids(self):
        # The repair batch must not invent or drop requirement IDs.
        assert len(_registry_ids(load_real_requirements())) == 22

    def test_invariants_register_ids_resolve(self):
        # INV-11/12 stay unmapped, INV-14 stays proposed: assert honest status
        # rather than fabricating enforcement.
        inv = _invariant_ids()
        assert {"INV-11", "INV-12", "INV-14"} <= inv

    def test_every_mapped_test_file_is_tagged_and_tags_resolve(self):
        requirements = load_real_requirements()
        registry = _registry_ids(requirements)
        invariants = _invariant_ids()
        mapped = []
        for req in requirements["requirements"]:
            for rel in req.get("tests", []):
                if rel not in mapped:
                    mapped.append(rel)
        assert mapped, "requirements.yaml must map at least one test file"
        for rel in mapped:
            path = ROOT / rel
            assert path.exists(), f"mapped test file missing: {rel}"
            assert path.stat().st_size > 0, f"mapped test file empty: {rel}"
            tags = _declared_traceability_tags(path.read_text(encoding="utf-8"))
            assert tags, f"mapped test file has no declared Traceability tag: {rel}"
            unresolved = {
                t
                for t in tags
                if t not in registry and t not in invariants
            }
            assert not unresolved, f"{rel} has unresolved tags: {sorted(unresolved)}"

    def test_each_mapping_declares_the_requirements_own_id(self):
        # Stronger than "any resolved tag": for every (requirement, mapped file)
        # pair, the file's DECLARED Traceability block must include that
        # requirement's OWN ID (an unrelated resolved tag is not enough). This is
        # true for the current tree; if a file legitimately verifies a requirement
        # only via an invariant, that must be added here explicitly with a reason.
        requirements = load_real_requirements()
        for req in requirements["requirements"]:
            for rel in req.get("tests", []):
                tags = _declared_traceability_tags(
                    (ROOT / rel).read_text(encoding="utf-8")
                )
                assert req["id"] in tags, (
                    f"{req['id']} mapped to {rel} but its own ID is not in the "
                    f"declared Traceability block (declared: {sorted(tags)})"
                )

    def test_governance_scaffold_itself_is_tagged(self):
        # This file verifies NFR-SEC-001 (secret scan) and NFR-OFF-001 (harness);
        # it must carry resolvable declared tags too.
        tags = _declared_traceability_tags(Path(__file__).read_text(encoding="utf-8"))
        assert "NFR-SEC-001" in tags
        assert "NFR-OFF-001" in tags


@pytest.mark.unit
class TestDispatcherForcedFallback:
    """Regression (2026-11-10): force the ACTUAL dispatcher fallback path.

    ``validate_against_schema`` calls ``_detect_jsonschema()`` every time, which
    would reset ``_JSSCHEMA_AVAILABLE`` back to True — so merely monkeypatching
    the flag does NOT force the fallback. These tests patch ``_detect_jsonschema``
    itself (so availability stays as set), spy on the fallback helper to prove it
    actually ran, and make the real ``jsonschema`` validator raise if it is ever
    reached in a fallback test. Malformed (non-string) IDs are driven through the
    same real dispatcher.
    """

    @pytest.fixture()
    def force_fallback(self, monkeypatch):
        """Force the dispatcher's fallback branch and prove it is the one used."""
        monkeypatch.setattr(
            validate_requirements, "_detect_jsonschema", lambda: None
        )
        monkeypatch.setattr(validate_requirements, "_JSSCHEMA_AVAILABLE", False)
        calls = {"fallback": 0, "real": 0}

        real_fallback = validate_requirements.validate_requirements

        def _spy_fallback(requirements, schema):
            calls["fallback"] += 1
            return real_fallback(requirements, schema)

        monkeypatch.setattr(
            validate_requirements, "validate_requirements", _spy_fallback
        )

        # If the real validator is ever reached, fail loudly (it must not be).
        try:
            import jsonschema

            def _boom(*a, **k):
                calls["real"] += 1
                raise AssertionError("real jsonschema validator reached in fallback test")

            monkeypatch.setattr(jsonschema, "Draft202012Validator", _boom)
        except ImportError:
            pass
        return calls

    def test_forced_fallback_actually_invokes_fallback(self, force_fallback):
        errors = validate_requirements.validate_against_schema(
            load_real_requirements(), load_real_schema()
        )
        assert force_fallback["fallback"] >= 1, "fallback helper not invoked"
        assert force_fallback["real"] == 0, "real validator was reached"
        assert errors == [], errors

    def test_real_branch_vs_forced_fallback_agree_on_valid_registry(self, monkeypatch):
        good = load_real_requirements()
        schema = load_real_schema()

        # --- Branch 1: force the fallback in an isolated context and prove it. ---
        with monkeypatch.context() as mp:
            mp.setattr(validate_requirements, "_detect_jsonschema", lambda: None)
            mp.setattr(validate_requirements, "_JSSCHEMA_AVAILABLE", False)
            fallback_calls = {"n": 0}
            real_fallback = validate_requirements.validate_requirements

            def _spy_fallback(requirements, s):
                fallback_calls["n"] += 1
                return real_fallback(requirements, s)

            mp.setattr(validate_requirements, "validate_requirements", _spy_fallback)
            try:
                import jsonschema

                def _boom(*a, **k):
                    raise AssertionError("real validator reached in forced-fallback branch")

                mp.setattr(jsonschema, "Draft202012Validator", _boom)
            except ImportError:
                pass
            fallback = validate_requirements.validate_against_schema(good, schema)
            assert fallback_calls["n"] >= 1, "fallback branch not reached"
            assert fallback == [], fallback

        # --- Branch 2: real schema in a SEPARATE restored context and prove it. ---
        import importlib.util

        if importlib.util.find_spec("jsonschema") is None:
            pytest.skip("jsonschema not installed; real branch unavailable here")
        with monkeypatch.context() as mp:
            mp.setattr(validate_requirements, "_detect_jsonschema", lambda: None)
            mp.setattr(validate_requirements, "_JSSCHEMA_AVAILABLE", True)
            real_calls = {"n": 0}

            def _spy_fallback_unused(requirements, s):
                raise AssertionError("fallback used in real-schema branch")

            mp.setattr(validate_requirements, "validate_requirements", _spy_fallback_unused)

            import jsonschema

            original = jsonschema.Draft202012Validator

            def _spy_validator(*a, **k):
                real_calls["n"] += 1
                return original(*a, **k)

            mp.setattr(jsonschema, "Draft202012Validator", _spy_validator)
            real = validate_requirements.validate_against_schema(good, schema)
            assert real_calls["n"] >= 1, "real validator branch not reached"
            assert real == [], real

    def test_forced_fallback_rejects_bad_id(self, force_fallback):
        bad = load_real_requirements()
        bad["requirements"][0]["id"] = "FR-DQG"
        errors = validate_requirements.validate_against_schema(bad, load_real_schema())
        assert force_fallback["fallback"] >= 1
        assert force_fallback["real"] == 0
        assert any("id" in e for e in errors), errors

    def test_forced_fallback_rejects_duplicate_differing_objects(self, force_fallback):
        errors = validate_requirements.validate_against_schema(
            _duplicate_id_requirements(), {"type": "object"}
        )
        assert force_fallback["fallback"] >= 1
        assert any("duplicate" in e for e in errors), errors

    def test_forced_fallback_rejects_non_string_id(self, force_fallback):
        # A non-string ID (int, list, bool) must be rejected, not crash.
        for bad_id in (123, ["x"], True, None):
            bad = load_real_requirements()
            bad["requirements"][0]["id"] = bad_id
            errors = validate_requirements.validate_against_schema(bad, {})
            assert force_fallback["fallback"] >= 1
            assert any("id" in e for e in errors), (bad_id, errors)

    def test_forced_fallback_handles_malformed_input_safely(self, force_fallback):
        # Malformed registries must not crash the forced-fallback dispatcher.
        for bad in (None, "not-a-dict", {"requirements": "not-a-list"},
                    {"requirements": ["x", 5, {"title": "no id"}]}):
            errors = validate_requirements.validate_against_schema(bad, {})
            assert isinstance(errors, list)
        assert force_fallback["fallback"] >= 1

    def test_real_schema_path_also_runs_reference_check(self):
        import importlib.util

        if importlib.util.find_spec("jsonschema") is None:
            pytest.skip("jsonschema not installed; real-schema path unavailable here")
        bad = load_real_requirements()
        # Point a real priority at a non-existent requirement ID.
        bad["product"]["priorities"][0]["requirement_id"] = "FR-DQG-999"
        errors = validate_requirements.validate_against_schema(bad, load_real_schema())
        assert any("does not resolve" in e for e in errors), errors


@pytest.mark.unit
class TestRequirementReferenceValidation:
    """Narrow dangling-reference validation (2026-11-10).

    The real JSON Schema only checks the PATTERN of a product ``requirement_id``
    reference; the combined entry point also resolves it against the registry.
    """

    def test_real_registry_has_no_dangling_references(self):
        assert (
            validate_requirements.validate_requirement_references(
                load_real_requirements()
            )
            == []
        )

    def test_dangling_priority_reference_flagged(self):
        bad = load_real_requirements()
        bad["product"]["priorities"].append(
            {"requirement_id": "NFR-NOPE-001", "priority": "Must", "rationale": "x"}
        )
        errors = validate_requirements.validate_requirement_references(bad)
        assert any("NFR-NOPE-001" in e for e in errors), errors

    def test_dangling_tradeoff_reference_flagged(self):
        bad = load_real_requirements()
        bad["product"]["tradeoffs"][0]["requirement_id"] = "FR-DDT-999"
        errors = validate_requirements.validate_requirement_references(bad)
        assert any("FR-DDT-999" in e for e in errors), errors

    def test_minimal_registry_without_product_references_is_compatible(self):
        # Minimal schemas/registries used by older tests must remain valid: no
        # product block -> reference check is a no-op.
        minimal = {
            "requirements": [
                {"id": "NFR-DET-001", "title": "t", "description": "d"}
            ]
        }
        assert validate_requirements.validate_requirement_references(minimal) == []
        assert validate_requirements.validate_requirement_references({}) == []
        assert validate_requirements.validate_requirement_references("bad") == []

    def test_malformed_reference_blocks_do_not_crash(self):
        for bad in (
            {"requirements": [{"id": "NFR-DET-001"}], "product": {"priorities": "x"}},
            {"requirements": [{"id": "NFR-DET-001"}], "product": {"priorities": [None, 5, {}]}},
            {"requirements": "nope", "product": {"priorities": [{"requirement_id": "X"}]}},
        ):
            out = validate_requirements.validate_requirement_references(bad)
            assert isinstance(out, list)


@pytest.mark.unit
class TestStrictOfflineHarness:
    """NFR-OFF-001 count-and-fail harness logic (2026-11-10).

    These assert the recorder COUNTS every forbidden attempt and fails closed,
    without spawning a subprocess or touching the network. They pin the harness
    behavior that NFR-OFF-001 relies on; they do NOT claim the full run makes
    zero attempts (the known baseline attempt stays OPEN).
    """

    def _harness(self):
        import sys

        harness_path = ROOT / "scripts/validate/strict_offline_harness.py"
        spec = importlib.util.spec_from_file_location("strict_offline_harness", harness_path)
        module = importlib.util.module_from_spec(spec)
        # Register before exec so dataclasses can resolve the defining module.
        sys.modules["strict_offline_harness"] = module
        spec.loader.exec_module(module)
        return module

    def test_recorder_counts_and_fails_closed(self):
        harness = self._harness()
        recorder = harness.SocketAttemptRecorder()
        assert recorder.count == 0
        for _ in range(2):
            with pytest.raises(OSError):
                recorder("host", 443)
        assert recorder.count == 2
        with pytest.raises(AssertionError):
            recorder.assert_no_attempts()

    def test_recorder_passes_when_no_attempt(self):
        harness = self._harness()
        recorder = harness.SocketAttemptRecorder()
        recorder.assert_no_attempts()
        assert recorder.count == 0

    def test_nfr_off_001_reference_present(self):
        # The requirement must point at the harness (traceability).
        reqs = load_real_requirements()
        by_id = {r["id"]: r for r in reqs["requirements"]}
        cmd = by_id["NFR-OFF-001"]["fit_criterion"]["verification"]["command"]
        assert "strict_offline_harness.py" in cmd


@pytest.mark.unit
class TestPermissionProposalConsistency:
    """Proposal-only consistency (2026-11-10): read-before-edit holds.

    This reads the NON-ACTIVE proposal YAML and asserts every editable path is
    also readable (excluding human-only/frozen), and that the required docs are
    readable. It does NOT claim enforcement; the proposal's
    ``active_configuration`` stays false.
    """

    def _proposal(self):
        import yaml

        path = ROOT / "docs/code-governance/agent-permissions-proposal.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_proposal_is_inactive(self):
        assert self._proposal()["active_configuration"] is False

    def test_builder_edits_are_readable(self):
        proposal = self._proposal()
        frozen = set(proposal["always_denied"]["edit"])
        builder = proposal["roles"]["builder"]
        reads = builder["read"]
        for edit in builder.get("edit", []):
            if edit in frozen:
                continue
            covered = False
            for rd in reads:
                if edit == rd:
                    covered = True
                    break
                if rd.endswith("/**") and edit.startswith(rd[:-3]):
                    covered = True
                    break
            assert covered, f"builder edit {edit!r} is not readable by builder"

    def test_required_docs_readable_by_all_roles(self):
        proposal = self._proposal()
        for role in ("planner", "builder", "verifier"):
            reads = proposal["roles"][role]["read"]
            for doc in (".agent/rules.md", "AGENTS.md", "architecture-blueprint.md",
                        "Prompt.md", "README.md", "Report.md"):
                assert doc in reads, f"{role} cannot read {doc}"
