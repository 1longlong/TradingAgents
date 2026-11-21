# ADR-012-error-handling-merge-integration.md: contract typing/security, NFR-BC-001, INV-1.
from typing import Any

CLI_CONFIG: dict[str, Any] = {
    # Announcements
    "announcements_url": "https://api.tauric.ai/v1/announcements",
    "announcements_timeout": 1.0,
    "announcements_fallback": "[cyan]For more information, please visit[/cyan] [link=https://github.com/TauricResearch]https://github.com/TauricResearch[/link]",
}
