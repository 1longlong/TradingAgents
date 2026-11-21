"""Web settings with safe defaults for a loopback-only single-user server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_STATIC_DIR = PACKAGE_DIR / "static"


@dataclass(frozen=True)
class WebSettings:
    """Runtime settings for the read-only WebUI.

    ``host`` is deliberately restricted to loopback values. The approved
    deployment has no authentication, so binding anywhere else is a security
    error, not a configuration preference.
    """

    results_dir: Path
    memory_log_path: Path
    data_cache_dir: Path
    host: str = "127.0.0.1"
    static_dir: Path = DEFAULT_STATIC_DIR
    max_report_bytes: int = 5_000_000
    max_zip_bytes: int = 20_000_000
    history_page_size: int = 50

    def __post_init__(self) -> None:
        object.__setattr__(self, "results_dir", Path(self.results_dir))
        object.__setattr__(self, "memory_log_path", Path(self.memory_log_path))
        object.__setattr__(self, "data_cache_dir", Path(self.data_cache_dir))
        object.__setattr__(self, "static_dir", Path(self.static_dir))
        if self.host not in {"127.0.0.1", "localhost"}:
            raise ValueError(
                "WebUI may bind only to 127.0.0.1 or localhost; "
                f"got {self.host!r}"
            )
        if self.max_report_bytes <= 0:
            raise ValueError("max_report_bytes must be positive")
        if self.max_zip_bytes <= 0:
            raise ValueError("max_zip_bytes must be positive")
        if self.history_page_size <= 0:
            raise ValueError("history_page_size must be positive")
