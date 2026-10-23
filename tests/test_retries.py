import httpx
import pytest

from pharma_scope.agent import Limits, ResearchAgent
from pharma_scope.providers import Model, TransientModelError
from pharma_scope.schemas import obj, S
from pharma_scope.store import Store
from test_agent import FakeModel, FakeWeb


def test_503_reports_temporary_failure_not_bad_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    monkeypatch.setenv("PHARMA_MODEL", "test-model")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Response(503, headers={"retry-after": "4"}))
    with pytest.raises(TransientModelError) as error:
        Model("gemini").generate("test", obj(value=S), {})
    assert "temporarily unavailable" in str(error.value)
    assert "check account" not in str(error.value)
    assert error.value.retry_after == 4


def test_retries_count_against_model_budget_and_report_progress(tmp_path, monkeypatch):
    class OnceUnavailable(FakeModel):
        def __init__(self):
            super().__init__()
            self.first = True
        def generate(self, *a, **kw):
            if self.first:
                self.first = False
                raise TransientModelError("Gemini HTTP 503: temporarily unavailable")
            return super().generate(*a, **kw)
    sleeps = []
    monkeypatch.setattr("pharma_scope.agent.time.sleep", lambda delay: sleeps.append(delay))
    store = Store(tmp_path / "data")
    try:
        model = OnceUnavailable()
        run = ResearchAgent(store, model, FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
        assert sleeps == [2]
        assert run["usage"]["model_calls"] == len(model.calls) + 1
        assert any(e["stage"] == "retry" for e in run["events"])
        assert any(e["message"].startswith("Starting resolve") for e in run["events"])
    finally:
        store.close()


def test_retries_stop_and_checkpoint_is_retained(tmp_path, monkeypatch):
    class Unavailable(FakeModel):
        def generate(self, *a, **kw):
            raise TransientModelError("Gemini HTTP 503: temporarily unavailable")
    monkeypatch.setattr("pharma_scope.agent.time.sleep", lambda delay: None)
    store = Store(tmp_path / "data")
    try:
        with pytest.raises(TransientModelError):
            ResearchAgent(store, Unavailable(), FakeWeb(), Limits(seconds=120)).run("EXAMPLE")
        row = store.db.execute("SELECT id FROM agent_states").fetchone()
        state = store.agent_state(row[0])
        assert state["usage"]["model_calls"] == 3
        assert state["next_stage"] == "resolve"
        assert state["status"] == "failed"
    finally:
        store.close()
