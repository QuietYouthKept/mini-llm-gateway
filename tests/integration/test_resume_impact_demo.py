from __future__ import annotations

from scripts.resume_impact_demo import run


def test_resume_impact_demo_is_offline_deterministic_and_auditable() -> None:
    result = run()

    assert result["mode"] == "offline"
    assert result["paid_provider_used"] is False
    assert result["readiness"]["status"] == "ready"
    scenarios = {scenario["name"]: scenario for scenario in result["scenarios"]}
    assert set(scenarios) == {"normal", "provider-fallback", "streaming"}
    assert scenarios["normal"]["audit_status"] == "success"
    assert scenarios["provider-fallback"]["fallback_used"] is True
    assert scenarios["provider-fallback"]["audit_status"] == "success"
    assert scenarios["streaming"]["events"][-2:] == ["usage", "done"]
    assert scenarios["streaming"]["audit_status"] == "completed"
    assert "prompts" in result["privacy"]
