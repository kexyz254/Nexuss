"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

In-memory append-only Action Receipt ledger for the P3 prototype.
"""

from collections.abc import Iterable
from uuid import UUID

from nexuss.domain.models import ActionReceipt


class InMemoryActionLedger:
    def __init__(self) -> None:
        self._receipts: dict[UUID, list[ActionReceipt]] = {}

    def append(self, receipt: ActionReceipt) -> None:
        history = self._receipts.setdefault(receipt.task_id, [])
        expected_version = len(history) + 1
        if receipt.receipt_version != expected_version:
            raise ValueError(
                f"Receipt version {receipt.receipt_version} does not match {expected_version}"
            )
        history.append(receipt.model_copy(deep=True))

    def get(self, task_id: UUID) -> ActionReceipt | None:
        history = self._receipts.get(task_id)
        if not history:
            return None
        return history[-1].model_copy(deep=True)

    def history(self, task_id: UUID) -> tuple[ActionReceipt, ...]:
        return tuple(receipt.model_copy(deep=True) for receipt in self._receipts.get(task_id, []))

    def values(self) -> Iterable[ActionReceipt]:
        return tuple(history[-1].model_copy(deep=True) for history in self._receipts.values())
