"""Safe downloads from read-only artifacts.

The browser never supplies a path. Every candidate is resolved from the
artifact index and validated to remain under the artifact directory.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from .index import Artifact

_SECTION_RE = re.compile(r"^[A-Za-z0-9_/-]+$")
_TEXT_SUFFIXES = {".md", ".txt", ".log", ".json", ".yaml", ".yml"}


class FileTooLarge(Exception):
    """A requested artifact exceeds the configured response limit."""


class ArtifactUnavailable(Exception):
    """The requested artifact or section does not exist."""


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def complete_report(artifact: Artifact) -> Path:
    candidates = [artifact.path / "complete_report.md"]
    if artifact.source == "run":
        candidates.append(artifact.path / "reports" / "complete_report.md")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ArtifactUnavailable("complete report is not available")


def section_file(artifact: Artifact, section: str) -> Path:
    if not _SECTION_RE.fullmatch(section) or ".." in section.split("/"):
        raise ArtifactUnavailable("invalid section")
    candidates: list[Path] = []
    if artifact.source == "run":
        candidates.append(artifact.path / "reports" / f"{section}.md")
    if artifact.source == "saved":
        candidates.append(artifact.path / f"{section}.md")
        if "/" in section:
            candidates.append(artifact.path / section)
    for candidate in candidates:
        if candidate.is_file() and _inside(candidate, artifact.path):
            return candidate
    raise ArtifactUnavailable("section is not available")


def read_text(path: Path, max_bytes: int) -> str:
    if path.stat().st_size > max_bytes:
        raise FileTooLarge("requested artifact exceeds the response limit")
    return path.read_text(encoding="utf-8", errors="replace")


def archive_bytes(artifact: Artifact, max_bytes: int, redact) -> bytes:
    if not artifact.path.is_dir():
        raise ArtifactUnavailable("archive is not available")
    files = [path for path in artifact.path.rglob("*") if path.is_file()]
    total = sum(path.stat().st_size for path in files)
    if total > max_bytes:
        raise FileTooLarge("requested archive exceeds the response limit")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            relative = path.relative_to(artifact.path).as_posix()
            if path.suffix.lower() in _TEXT_SUFFIXES:
                content = redact(path.read_text(encoding="utf-8", errors="replace"))
                archive.writestr(relative, content)
            else:
                archive.write(path, relative)
    return buffer.getvalue()
