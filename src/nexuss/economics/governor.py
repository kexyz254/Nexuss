"""Budget Governor for provider calls.

P6.14 — AI Usage Economics.

The governor enforces configurable soft/hard budgets, paid-call/discovery/
repair limits, budget approval, and economic no-progress detection. It is a
pure policy layer: it never performs provider calls itself and never raises
its own budget.

Nexuss remains authoritative. The governor can only *deny* or *allow*; it
cannot approve itself, expand permissions, or mark work verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class BudgetState(Enum):
    OK = "ok"
    SOFT_EXCEEDED = "soft_exceeded"
    HARD_EXCEEDED = "hard_exceeded"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True)
class BudgetConfig:
    """Configurable budget limits for a mission."""

    soft_budget_usd: Decimal = Decimal("1.00")
    hard_budget_usd: Decimal = Decimal("5.00")
    max_paid_calls: int = 6
    max_discovery_calls: int = 2
    max_repair_calls: int = 3
    require_approval_for_increase: bool = True


@dataclass
class GovernorState:
    """Mutable runtime state tracked by the governor."""

    paid_calls: int = 0
    discovery_calls: int = 0
    repair_calls: int = 0
    spent_usd: Decimal = Decimal("0")
    last_progress_call: Optional[int] = None
    consecutive_no_progress: int = 0


class BudgetGovernor:
    """Enforces economic limits for a single mission."""

    def __init__(self, config: BudgetConfig, state: Optional[GovernorState] = None) -> None:
        self.config = config
        self.state = state or GovernorState()

    def record_spend(self, amount_usd: Decimal) -> None:
        self.state.spent_usd += amount_usd

    def record_call(
        self,
        *,
        kind: str = "paid",
        made_progress: Optional[bool] = None,
    ) -> None:
        """Record a provider call and update no-progress detection."""
        if kind == "discovery":
            self.state.discovery_calls += 1
        elif kind == "repair":
            self.state.repair_calls += 1
        self.state.paid_calls += 1

        if made_progress is True:
            self.state.consecutive_no_progress = 0
            self.state.last_progress_call = self.state.paid_calls
        elif made_progress is False:
            self.state.consecutive_no_progress += 1

    def check(self) -> BudgetState:
        """Return the current budget state."""
        if self.state.spent_usd >= self.config.hard_budget_usd:
            return BudgetState.HARD_EXCEEDED
        if self.state.paid_calls >= self.config.max_paid_calls:
            return BudgetState.HARD_EXCEEDED
        if self.state.spent_usd >= self.config.soft_budget_usd:
            return BudgetState.SOFT_EXCEEDED
        return BudgetState.OK

    def can_call(self, *, kind: str = "paid") -> bool:
        """Return True if another call of ``kind`` is permitted."""
        if self.check() == BudgetState.HARD_EXCEEDED:
            return False
        if kind == "discovery" and self.state.discovery_calls >= self.config.max_discovery_calls:
            return False
        if kind == "repair" and self.state.repair_calls >= self.config.max_repair_calls:
            return False
        return True

    def should_stop_economically(self) -> bool:
        """True when two consecutive paid calls produced no progress."""
        return self.state.consecutive_no_progress >= 2

    def request_budget_increase(self, new_hard_usd: Decimal) -> BudgetState:
        """A budget increase always requires external approval.

        The governor itself never approves an increase; it only reports that
        approval is required.
        """
        if new_hard_usd <= self.config.hard_budget_usd:
            return BudgetState.OK
        if not self.config.require_approval_for_increase:
            # Even without the flag, the governor does not self-approve; it
            # simply reports the requirement. Nexuss is authoritative.
            return BudgetState.APPROVAL_REQUIRED
        return BudgetState.APPROVAL_REQUIRED
