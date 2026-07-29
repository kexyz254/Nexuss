from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from nexuss.archive.workflow import ArchiveImportCoordinator
from nexuss.domain.models import TaskState


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resume an already-approved durable Nexuss ZIP import without "
            "creating another repository or approval."
        )
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--task-id", type=UUID)
    selector.add_argument("--repository")
    args = parser.parse_args()

    coordinator = ArchiveImportCoordinator.from_environment()
    candidates = coordinator.list_recoverable_tasks()
    if args.task_id is not None:
        selected = next(
            (item for item in candidates if item.task_id == args.task_id),
            None,
        )
    else:
        wanted = args.repository.strip().rstrip(".").casefold()
        selected = next(
            (
                item
                for item in candidates
                if str(item.intent.entities.get("repository_name", ""))
                .strip()
                .rstrip(".")
                .casefold()
                == wanted
            ),
            None,
        )

    if selected is None:
        print(json.dumps({
            "status": "not_found",
            "recoverable": [
                {
                    "task_id": str(item.task_id),
                    "repository": item.intent.entities.get("repository_name"),
                    "state": item.state.value,
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in candidates
            ],
        }, indent=2))
        return 3

    result = coordinator.resume_interrupted_task(selected.task_id)
    output = {
        "task_id": str(result.task_id),
        "state": result.state.value,
        "repository": result.intent.entities.get("repository_name"),
        "events": [
            {
                "sequence": event.sequence,
                "type": event.event_type,
                "state": event.state.value,
                "detail": event.detail,
            }
            for event in result.events[-10:]
        ],
        "results": [
            {
                "capability": item.capability_id,
                "status": item.status.value,
                "error_code": item.error_code,
                "evidence": [record.attributes for record in item.evidence],
            }
            for item in result.results[-3:]
        ],
    }
    print(json.dumps(output, indent=2, default=str))
    return 0 if result.state is TaskState.COMPLETED else 2


if __name__ == "__main__":
    sys.exit(main())
