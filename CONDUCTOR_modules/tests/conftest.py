from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


for package in sorted((PROJECT_ROOT / ".claude" / "skills").glob("cs-*/python")):
    if str(package) not in sys.path:
        sys.path.insert(0, str(package))

TOOLS = PROJECT_ROOT / "CONDUCTOR_modules" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
