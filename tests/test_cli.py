"""The ``clinicdesk`` command: argument checks and the offline commands."""

import json
import sqlite3

import pytest

from clinicdesk_agent.cli import build_parser, main


@pytest.mark.parametrize("days", ["0", "-2", "two"])
def test_init_db_rejects_days_below_one(days, capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["init-db", "--days", days])
    assert exc.value.code == 2
    assert "--days" in capsys.readouterr().err


def test_init_db_and_eval_run_offline(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("CLINICDESK_DB_PATH", str(db_path))
    monkeypatch.setenv("CLINICDESK_LLM_PROVIDER", "offline")
    assert main(["init-db", "--seed", "3", "--days", "2"]) == 0
    assert "Database ready" in capsys.readouterr().out
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] == 20
    summary_path = tmp_path / "summary.json"
    assert main(["eval", "--json", str(summary_path)]) == 0
    assert json.loads(summary_path.read_text(encoding="utf-8"))["invariant_violations"] == 0


def test_configuration_error_exits_with_code_2(monkeypatch, capsys):
    monkeypatch.setenv("CLINICDESK_LLM_PROVIDER", "nonsense")
    assert main(["eval"]) == 2
    assert "Configuration error" in capsys.readouterr().err
