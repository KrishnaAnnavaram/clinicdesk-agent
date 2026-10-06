"""Composition root: wire settings, database, services, model and orchestrator together."""

from __future__ import annotations

from dataclasses import dataclass

from clinicdesk_agent.agent.llm import ChatModel
from clinicdesk_agent.agent.offline import RuleBasedChatModel
from clinicdesk_agent.agent.orchestrator import Orchestrator
from clinicdesk_agent.agent.tools import Toolbox
from clinicdesk_agent.config import Settings
from clinicdesk_agent.db import Database
from clinicdesk_agent.scheduling import BookingService, PatientRegistry
from clinicdesk_agent.scheduling.booking import Clock


@dataclass
class ClinicDesk:
    settings: Settings
    db: Database
    bookings: BookingService
    patients: PatientRegistry
    toolbox: Toolbox
    orchestrator: Orchestrator


def build_model(settings: Settings) -> ChatModel:
    if settings.llm_provider == "openai":
        from clinicdesk_agent.agent.openai_adapter import OpenAIChatModel

        return OpenAIChatModel(settings.llm_model, api_key=settings.openai_api_key, base_url=settings.llm_base_url)
    return RuleBasedChatModel()


def build_clinic_desk(settings: Settings, *, model: ChatModel | None = None, clock: Clock | None = None) -> ClinicDesk:
    db = Database(settings.db_path)
    clock = clock or settings.clinic_now
    bookings = BookingService(db, clock, max_active_bookings=settings.max_active_bookings)
    toolbox = Toolbox(db, bookings, clock, emergency_number=settings.emergency_number)
    orchestrator = Orchestrator(model or build_model(settings), toolbox, timezone=settings.timezone,
                                max_steps=settings.max_tool_steps, emergency_number=settings.emergency_number)
    return ClinicDesk(settings, db, bookings, PatientRegistry(db), toolbox, orchestrator)
