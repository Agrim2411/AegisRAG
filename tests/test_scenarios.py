import pytest


def test_payments_scenario_runs_end_to_end(state):
    from aegis_rag.generation import GroundedExtractiveProvider
    from aegis_rag.incidents import IncidentCommander
    from aegis_rag.retrieval import HybridRetriever
    from aegis_rag.scenarios import ScenarioRunner
    from aegis_rag.workflow import AgenticRAGWorkflow

    workflow = AgenticRAGWorkflow(
        HybridRetriever(state.store, state.embedder), GroundedExtractiveProvider()
    )
    runner = ScenarioRunner(
        state.store,
        state.embedder,
        IncidentCommander(workflow),
    )
    result = runner.run("acme-payments", "payments-pool-exhaustion", "req_scenario_test")
    assert result.status == "incident_created"
    assert result.generated_events == 6
    assert result.alert_triggered is True
    assert result.expected_outcome_verified is True
    assert result.incident is not None
    assert result.incident.approval_required is True
    assert result.incident.workflow.verification_passed is True
    assert "Connection pool exhaustion" in result.incident.hypotheses[0].hypothesis
    assert any(entry.kind == "alert.triggered" for entry in result.timeline)
    stored = state.store.get_incident("acme-payments", result.incident.incident_id)
    assert stored is not None
    assert stored.run_id == result.run_id
    assert state.store.get_incident("globex-commerce", result.incident.incident_id) is None


def test_healthy_scenario_does_not_open_incident(state):
    from aegis_rag.generation import GroundedExtractiveProvider
    from aegis_rag.incidents import IncidentCommander
    from aegis_rag.retrieval import HybridRetriever
    from aegis_rag.scenarios import ScenarioRunner
    from aegis_rag.workflow import AgenticRAGWorkflow

    workflow = AgenticRAGWorkflow(
        HybridRetriever(state.store, state.embedder), GroundedExtractiveProvider()
    )
    runner = ScenarioRunner(
        state.store,
        state.embedder,
        IncidentCommander(workflow),
    )
    result = runner.run("acme-payments", "healthy-payments-deployment", "req_healthy_test")
    assert result.status == "no_incident"
    assert result.incident is None
    assert result.expected_outcome_verified is True


def test_scenario_cannot_run_under_another_tenant(state):
    from aegis_rag.generation import GroundedExtractiveProvider
    from aegis_rag.incidents import IncidentCommander
    from aegis_rag.retrieval import HybridRetriever
    from aegis_rag.scenarios import ScenarioRunner
    from aegis_rag.workflow import AgenticRAGWorkflow

    runner = ScenarioRunner(
        state.store,
        state.embedder,
        IncidentCommander(
            AgenticRAGWorkflow(
                HybridRetriever(state.store, state.embedder),
                GroundedExtractiveProvider(),
            )
        ),
    )
    with pytest.raises(PermissionError):
        runner.run("globex-commerce", "payments-pool-exhaustion", "req_wrong_tenant")
