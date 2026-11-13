from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "examples" / "logs"
RECORDED = ROOT / "examples" / "recorded"


@pytest.fixture
def logs() -> Path:
    return LOGS


@pytest.fixture
def recorded() -> Path:
    return RECORDED


@pytest.fixture(autouse=True)
def _no_ollama(monkeypatch, request):
    """Tests never reach a real model unless marked live."""
    if "live" in request.keywords:
        return
    from cianalyst.opscore import llm
    monkeypatch.setattr(llm.Ollama, "available", lambda self: False)
