"""Canonical product language for terminal UX.

Keeping high-frequency terms here prevents command modules from drifting back
to internal implementation language such as "HITL" or "control plane".
"""

TAGLINE = "Secure access for production AI agents"

HUMAN_APPROVALS = "Human approvals"
GOVERNED_HISTORY = "Governed history"
LOCAL_MODE = "Local development"
GATEWAY_MODE = "Gateway Mode"

LOCAL_SECURITY_NOTE = "Local Mode uses your provider key only inside the local process."
GATEWAY_SECURITY_NOTE = (
    "Gateway Mode gives the agent a short-lived capability, not a provider credential."
)
NEW_PROJECT_SECURITY_NOTE = "Your provider secret stays out of project files."
