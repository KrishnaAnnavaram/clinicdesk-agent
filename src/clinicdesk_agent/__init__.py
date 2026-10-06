"""clinicdesk-agent: a safe, deterministic clinic front-desk assistant.

The language model only *proposes* actions through a small set of typed tools.
Every read and write goes through the scheduling service, which enforces the
booking rules in code (see ``clinicdesk_agent.scheduling``).
"""

__version__ = "0.1.0"
