"""Specialist ownership, not independent authority or a claim of model availability."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentRole:
    name: str
    responsibility: str
    capability: str
    availability: str


ROLES = (
    AgentRole("Research", "Evidence gathering and synthesis", "tas.investigation.evidence", "available"),
    AgentRole("Security", "Credential exposure and access-policy checks", "tas.investigation.boundaries", "available"),
    AgentRole("Engineering", "Source inspection and repair preparation", "tas.investigation.source", "bounded breaker repair preparation requires configured AI and Docker"),
    AgentRole("Risk", "Operational, technical and financial risk assessment", "tas.investigation.risk", "operational checks available; financial analysis pending"),
    AgentRole("Financial", "Financial analysis and accounting workflows", "financial.analysis", "not connected"),
    AgentRole("Internet", "Web research and external information", "internet.research", "not connected to this workflow"),
    AgentRole("Market", "Market data and monitoring", "trading.decisions.read", "recorded TAS decisions available"),
    AgentRole("Social", "Social analytics and communications", "social.analysis", "not connected"),
    AgentRole("Maintenance", "Health monitoring and diagnostics", "tas.investigation.health", "diagnostics available; repairs pending"),
    AgentRole("Validation", "Independent evidence and output checks", "tas.investigation.validate", "evidence checks available; targeted repair tests require a local test image"),
    AgentRole("Data", "Data processing and transformation", "tas.investigation.normalize", "typed evidence processing available"),
    AgentRole("Learning", "Reusable knowledge from completed work", "tas.investigation.receipts", "investigation receipts available; automatic learning pending"),
)


def describe_roles():
    return "Nexuss specialist capabilities:\n" + "\n".join(
        f"{role.name}: {role.responsibility}. {role.availability}." for role in ROLES
    ) + "\nThese roles share Nexuss's controls. TAS retains trading execution authority."
