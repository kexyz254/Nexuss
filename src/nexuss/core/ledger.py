"""In-memory append-only Action Receipt ledger for P1."""

from collections.abc import Iterable
from uuid import UUID

from nexuss.domain.models import ActionReceipt


class InMemoryActionLedger:
    def __init__(self) -> None:
        self._receipts: dict[UUID, ActionReceipt] = {}

    def append(self, receipt: ActionReceipt) -> None:
        if receipt.task_id in self._receipts:
            raise ValueError("An Action Receipt already exists for this task")
        self._receipts[receipt.task_id] = receipt

    def get(self, task_id: UUID) -> ActionReceipt | None:
        return self._receipts.get(task_id)

    def values(self) -> Iterable[ActionReceipt]:
        return tuple(self._receipts.values())
