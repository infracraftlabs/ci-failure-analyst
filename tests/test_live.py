"""Optional: one real case against a local Ollama. Run with `pytest -m live`."""
import pytest

from cianalyst.analyse import analyse, prepare
from cianalyst.opscore.llm import Ollama


@pytest.mark.live
def test_live_dependency_failure(logs):
    model = Ollama()
    if not model.available():
        pytest.skip(f"{model.model} not available at {model.host}")
    a = analyse(prepare((logs / "gha-npm-dependency.log").read_text(), "x"), model)
    assert a.report.mode == "ai"
    assert a.category == "dependency"
    assert a.report.finding.summary
