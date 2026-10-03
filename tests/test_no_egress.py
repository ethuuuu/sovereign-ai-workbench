"""The static half of the sovereignty proof.

Run this live on stage. It takes two seconds and anyone in the room can
check it, which makes it the most convincing thing in the demo.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The only two modules allowed to touch the network stack.
EXEMPT = {
    Path("inference/client.py"),
    Path("guard/egress.py"),
    Path("tests/test_no_egress.py"),
    Path("scripts/preflight.py"),
}

FORBIDDEN = re.compile(
    r"^\s*(?:import|from)\s+"
    r"(requests|httpx|urllib|urllib3|aiohttp|socket|http\.client|ftplib|"
    r"telnetlib|smtplib|tavily|boto3|google\.cloud)\b",
    re.MULTILINE,
)

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "models", "workspace", "node_modules"}


def python_files() -> list[Path]:
    out = []
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return out


def test_no_network_imports_outside_the_client() -> None:
    offenders = []
    for path in python_files():
        relative = path.relative_to(REPO_ROOT)
        if relative in EXEMPT:
            continue
        for match in FORBIDDEN.finditer(path.read_text(encoding="utf-8")):
            offenders.append(f"{relative}: {match.group(0).strip()}")

    assert not offenders, (
        "Networking imported outside inference/client.py and guard/egress.py:\n"
        + "\n".join(offenders)
    )


# XML namespace URIs are identifiers, not endpoints: they are compared as
# strings and never fetched. The OOXML ones appear in kb/chunking.py, which
# reads .docx with the stdlib precisely so it does not have to import lxml.
NAMESPACE_HOSTS = (
    "schemas.openxmlformats.org",
    "schemas.microsoft.com",
    "www.w3.org",
    "purl.org",
)


def test_no_hardcoded_external_urls() -> None:
    pattern = re.compile(r"https?://(?!127\.0\.0\.1|localhost)[\w.-]+", re.IGNORECASE)
    offenders = []
    for path in python_files():
        relative = path.relative_to(REPO_ROOT)
        if relative in EXEMPT:
            continue
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            url = match.group(0)
            if any(host in url for host in NAMESPACE_HOSTS):
                continue
            offenders.append(f"{relative}: {url}")
    assert not offenders, "External URLs found in source:\n" + "\n".join(offenders)
