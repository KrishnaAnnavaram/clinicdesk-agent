"""``clinicdesk`` command-line entry point.

    clinicdesk init-db [--seed N] [--days N]   create + seed the demo database
    clinicdesk chat --handle NAME [--register] chat in the terminal
    clinicdesk eval [--json PATH]              run the scripted-dialogue evaluation
    clinicdesk ui                              launch the Streamlit app (needs the [ui] extra)
"""

from __future__ import annotations

import argparse
import getpass
import json
import subprocess
import sys
from pathlib import Path

from clinicdesk_agent.agent.tools import Session
from clinicdesk_agent.app import build_clinic_desk
from clinicdesk_agent.config import ConfigError, Settings, load_dotenv_if_present
from clinicdesk_agent.db.seed import seed_database
from clinicdesk_agent.safety import TRIAGE_DISCLAIMER
from clinicdesk_agent.scheduling.errors import AuthError


def _cmd_init_db(settings: Settings, args: argparse.Namespace) -> int:
    desk = build_clinic_desk(settings)
    summary = seed_database(desk.db, seed=args.seed if args.seed is not None else settings.seed,
                            today=settings.clinic_now().date(), days=args.days or settings.seed_days)
    print(f"Database ready at {desk.db.path}")
    print(f"{summary.doctors} doctors, {summary.slots} slots ({summary.booked} pre-booked) "
          f"from {summary.first_day} to {summary.last_day}")
    return 0


def _cmd_chat(settings: Settings, args: argparse.Namespace) -> int:
    desk = build_clinic_desk(settings)
    if not desk.db.path.exists():
        print("No database yet. Run `clinicdesk init-db` first.", file=sys.stderr)
        return 1
    passcode = getpass.getpass("Passcode: ")
    try:
        patient = (desk.patients.register(args.handle, passcode) if args.register
                   else desk.patients.authenticate(args.handle, passcode))
    except AuthError as exc:
        print(f"Sign-in failed: {exc}", file=sys.stderr)
        return 1
    session = Session(patient.patient_id, patient.handle)
    print(f"Signed in as {patient.handle}. Model: {settings.llm_provider}. Type 'quit' to leave.")
    print(TRIAGE_DISCLAIMER)
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text.lower() in {"quit", "exit"}:
            return 0
        reply = desk.orchestrator.handle(session, text)
        print(f"desk> {reply.text}\n")


def _cmd_eval(settings: Settings, args: argparse.Namespace) -> int:
    from clinicdesk_agent.app import build_model
    from clinicdesk_agent.evaluation import run_evaluation

    report = run_evaluation(lambda: build_model(settings))
    summary = report.summary()
    print(json.dumps(summary, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if report.dialogues_passed == report.dialogues and not report.invariant_violations else 1


def _cmd_ui(settings: Settings, args: argparse.Namespace) -> int:
    script = Path(__file__).with_name("ui") / "streamlit_app.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(script)])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clinicdesk", description="Clinic front-desk scheduling assistant")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-db", help="create and seed the demo database (wipes existing demo data)")
    init.add_argument("--seed", type=int, default=None)
    init.add_argument("--days", type=int, default=None)
    chat = sub.add_parser("chat", help="chat in the terminal")
    chat.add_argument("--handle", required=True)
    chat.add_argument("--register", action="store_true", help="create the patient handle first")
    ev = sub.add_parser("eval", help="run the scripted-dialogue evaluation")
    ev.add_argument("--json", default=None, help="also write the summary to this file")
    sub.add_parser("ui", help="launch the Streamlit app")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv_if_present()
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    handlers = {"init-db": _cmd_init_db, "chat": _cmd_chat, "eval": _cmd_eval, "ui": _cmd_ui}
    return handlers[args.command](settings, args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
