"""Problems 8 and 10 (evaluation, configuration) plus patient authentication."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinicdesk_agent.agent.llm import AssistantTurn, ScriptedChatModel
from clinicdesk_agent.agent.openai_adapter import OpenAIChatModel
from clinicdesk_agent.app import build_model
from clinicdesk_agent.agent.offline import RuleBasedChatModel
from clinicdesk_agent.config import ConfigError, Settings
from clinicdesk_agent.evaluation import load_dialogues, run_evaluation
from clinicdesk_agent.scheduling.errors import AuthError
from clinicdesk_agent.scheduling.patients import hash_passcode, verify_passcode


def test_offline_model_passes_every_scripted_dialogue():
    report = run_evaluation()
    summary = report.summary()
    assert summary["failures"] == []
    assert report.dialogues == len(load_dialogues()) >= 10
    assert summary["routing_accuracy"] == summary["booking_outcome_accuracy"] == 1.0
    assert summary["invariant_violations"] == 0


def test_harness_detects_a_bad_model():
    report = run_evaluation(lambda: ScriptedChatModel(lambda m, t: AssistantTurn(text="Booked!")))
    assert report.dialogues_passed < report.dialogues
    assert report.summary()["routing_accuracy"] < 1.0


def test_settings_from_env_resolves_absolute_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings.from_env({"CLINICDESK_DB_PATH": "rel/clinic.db", "CLINICDESK_TIMEZONE": "Europe/Berlin"})
    assert settings.db_path.is_absolute() and settings.db_path == (tmp_path / "rel" / "clinic.db").resolve()
    assert settings.llm_provider == "offline" and isinstance(build_model(settings), RuleBasedChatModel)


@pytest.mark.parametrize("env", [
    {"CLINICDESK_LLM_PROVIDER": "openai"},  # no key, no local base URL
    {"CLINICDESK_LLM_PROVIDER": "gemini"},
    {"CLINICDESK_TIMEZONE": "Mars/Olympus"},
    {"CLINICDESK_MAX_TOOL_STEPS": "zero"},
])
def test_invalid_settings(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_api_key_not_in_repr():
    settings = Settings.from_env({"CLINICDESK_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test-value-123"})
    assert "test-value-123" not in repr(settings)


def test_openai_adapter_parses_tool_calls_with_fake_client():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="search_slots",
                                                                 arguments='{"specialty": "Cardiology"}'))
        bad = SimpleNamespace(id="c2", function=SimpleNamespace(name="request_booking", arguments="{not json"))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[call, bad]))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    model = OpenAIChatModel("test-model", client=client)
    turn = model.complete([{"role": "user", "content": "hi"}], [{"name": "search_slots", "parameters": {}}])
    assert turn.tool_calls[0].arguments == {"specialty": "Cardiology"}
    assert turn.tool_calls[1].arguments is None
    assert captured["temperature"] == 0 and captured["tools"][0]["type"] == "function"


def test_passcodes_are_salted_hashes():
    first, second = hash_passcode("open-sesame"), hash_passcode("open-sesame")
    assert first != second and "open-sesame" not in first
    assert verify_passcode("open-sesame", first) and not verify_passcode("open-sesamE", first)
    assert not verify_passcode("x", "garbage")


def test_register_and_authenticate(desk):
    patient = desk.patients.register("Patient-C", "long-passcode")
    assert desk.patients.authenticate("patient-c", "long-passcode").patient_id == patient.patient_id
    with pytest.raises(AuthError):
        desk.patients.authenticate("patient-c", "wrong-passcode")
    with pytest.raises(AuthError):
        desk.patients.register("patient-c", "another-one")
    with pytest.raises(AuthError):
        desk.patients.register("pd", "long-passcode")  # handle too short
    with pytest.raises(AuthError):
        desk.patients.register("patient-d", "123")  # passcode too short


def test_env_example_lists_names_only():
    root = Path(__file__).resolve().parents[1]
    for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            assert name.isupper() and value == ""


def test_dialogue_file_is_valid_json():
    assert all("id" in d and d["turns"] for d in load_dialogues())
    json.dumps(load_dialogues())
