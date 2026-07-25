from __future__ import annotations

from agent.scenario_chat import GeminiScenarioAdvisor
from config import GeminiSettings


def test_scenario_advisor_receives_whole_project_context_and_extracts_changes() -> None:
    captured: dict[str, object] = {}

    def generate(prompt: str, schema: dict) -> dict:
        captured["prompt"] = prompt
        captured["schema"] = schema
        return {
            "intent": "simulate",
            "rainfall_change_percent": -30,
            "budget_change_percent": 20,
            "answer": "I will test those changes.",
            "context_sections": ["weather", "financial_projection"],
        }

    advisor = GeminiScenarioAdvisor(
        GeminiSettings(api_key="test-key", model="test-gemini"),
        generate=generate,
    )
    result = advisor.respond(
        "বৃষ্টি ৩০% কম আর বাজেট ২০% বেশি হলে কী হবে?",
        project_context={
            "farm_profile": {"confirmed_facts": {"soil_class": "loam"}},
            "selected_crop_plan": {"crop_id": "lentil"},
            "financial_projection": {"budget_bdt": 20_000},
            "weather": {"source_id": "open_meteo"},
        },
        history=[{"role": "assistant", "content": "Ask a scenario."}],
    )

    assert result["intent"] == "simulate"
    assert result["rainfall_change_percent"] == -30
    assert result["budget_change_percent"] == 20
    prompt = str(captured["prompt"])
    assert "loam" in prompt
    assert "lentil" in prompt
    assert "open_meteo" in prompt
    assert "PREVIOUS SCENARIO CHAT" in prompt


def test_scenario_advisor_fails_closed_when_simulation_has_no_supported_change() -> None:
    advisor = GeminiScenarioAdvisor(
        GeminiSettings(api_key="test-key", model="test-gemini"),
        generate=lambda _prompt, _schema: {
            "intent": "simulate",
            "rainfall_change_percent": None,
            "budget_change_percent": None,
            "answer": "I will simulate it.",
            "context_sections": ["project"],
        },
    )
    result = advisor.respond(
        "What if things change?",
        project_context={},
        history=[],
    )
    assert result["intent"] == "clarify"
    assert "percentage change" in result["answer"]
