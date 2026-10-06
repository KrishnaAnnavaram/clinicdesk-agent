"""Streamlit chat UI. Run with ``clinicdesk ui`` (needs ``pip install clinicdesk-agent[ui]``).

The UI holds no business logic: sign-in goes through :class:`PatientRegistry`,
messages through :class:`Orchestrator`, and the confirm/decline buttons call
the same code paths as typing "yes"/"no".
"""

from __future__ import annotations

import streamlit as st

from clinicdesk_agent.agent.tools import Session
from clinicdesk_agent.app import build_clinic_desk
from clinicdesk_agent.config import ConfigError, Settings, load_dotenv_if_present
from clinicdesk_agent.safety import TRIAGE_DISCLAIMER
from clinicdesk_agent.scheduling.errors import AuthError


@st.cache_resource
def _desk():
    load_dotenv_if_present()
    return build_clinic_desk(Settings.from_env())


def _sign_in(desk) -> None:
    st.subheader("Sign in")
    handle = st.text_input("Patient handle", max_chars=32)
    passcode = st.text_input("Passcode", type="password")
    col1, col2 = st.columns(2)
    try:
        if col1.button("Sign in", use_container_width=True):
            patient = desk.patients.authenticate(handle, passcode)
        elif col2.button("Register", use_container_width=True):
            patient = desk.patients.register(handle, passcode)
        else:
            return
    except AuthError as exc:
        st.error(str(exc))
        return
    st.session_state.session = Session(patient.patient_id, patient.handle)
    st.session_state.transcript = []
    st.rerun()


def _chat(desk) -> None:
    session: Session = st.session_state.session
    transcript: list[tuple[str, str]] = st.session_state.transcript
    with st.sidebar:
        st.write(f"Signed in as **{session.handle}**")
        if st.button("Sign out"):
            for key in ("session", "transcript"):
                st.session_state.pop(key, None)
            st.rerun()

    for role, text in transcript:
        with st.chat_message(role):
            st.markdown(text)

    if session.pending is not None:
        st.info(f"Waiting for your confirmation: {session.pending.summary}")
        col1, col2 = st.columns(2)
        if col1.button("Confirm", type="primary", use_container_width=True):
            transcript.append(("assistant", desk.orchestrator.confirm(session).text))
            st.rerun()
        if col2.button("Keep as is", use_container_width=True):
            transcript.append(("assistant", desk.orchestrator.decline(session).text))
            st.rerun()

    text = st.chat_input("Describe your symptoms or ask for an appointment")
    if text:
        transcript.append(("user", text))
        transcript.append(("assistant", desk.orchestrator.handle(session, text).text))
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Clinic front desk", page_icon=":hospital:")
    st.title("Clinic front desk")
    st.caption(TRIAGE_DISCLAIMER + " In an emergency, call your local emergency number.")
    try:
        desk = _desk()
    except ConfigError as exc:
        st.error(f"Configuration error: {exc}")
        return
    if not desk.db.path.exists():
        st.warning("No database found. Run `clinicdesk init-db` first.")
        return
    if "session" not in st.session_state:
        _sign_in(desk)
    else:
        _chat(desk)


main()
