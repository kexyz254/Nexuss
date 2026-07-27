"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from datetime import UTC, datetime
from uuid import UUID

from nexuss.core.service import CoreSimulatorService
from nexuss.domain.models import (
    Channel,
    IdentitySession,
    TaskRequest,
    TaskState,
)
from tests.fakes import FakeDeviceNodeClient

SESSION = UUID("00000000-0000-0000-0000-000000000950")


class FakeKnowledge:
    def research(self, query: str) -> dict[str, object]:
        return {
            "query": query,
            "source_mode": "live_public_web_readonly",
            "sources": [
                {
                    "title": "Forex",
                    "url": "https://example.test/forex",
                    "extract": "Market",
                }
            ],
            "source_count": 1,
            "brief": "Forex market",
            "memory_saved": False,
        }


class FakeYouTube:
    def discover(self, query: str) -> dict[str, object]:
        return {
            "query": query,
            "configured": True,
            "source_mode": "live_youtube_data_api",
            "search_url": (
                "https://www.youtube.com/results?search_query=test"
            ),
            "results": [
                {
                    "video_id": "M7lc1UVf-VE",
                    "title": "Demo",
                    "channel_title": "YouTube",
                    "thumbnail_url": "",
                    "watch_url": (
                        "https://www.youtube.com/watch?v=M7lc1UVf-VE"
                    ),
                    "confidence": 0.99,
                }
            ],
        }


def request(request_id: str, utterance: str) -> TaskRequest:
    return TaskRequest(
        request_id=UUID(request_id),
        channel=Channel.TEXT,
        utterance=utterance,
        user_session_id=SESSION,
        target_devices=[],
        requested_at=datetime.now(UTC),
        client_context={},
    )


def service() -> CoreSimulatorService:
    return CoreSimulatorService(
        device_client=FakeDeviceNodeClient(),
        knowledge_provider=FakeKnowledge(),
        youtube_provider=FakeYouTube(),
    )


def identity() -> IdentitySession:
    return IdentitySession(
        session_id=SESSION,
        authenticated=True,
    )


def test_research_and_media_complete_with_verified_evidence() -> None:
    research = service().create_task(
        request(
            "00000000-0000-0000-0000-000000000951",
            "Research forex",
        ),
        identity(),
    )
    media = service().create_task(
        request(
            "00000000-0000-0000-0000-000000000952",
            "Play demo video",
        ),
        identity(),
    )

    assert research.state is TaskState.COMPLETED
    assert media.state is TaskState.COMPLETED


def test_phone_youtube_is_allowlisted_and_queued_without_approval() -> None:
    core = service()
    task = core.create_task(
        request(
            "00000000-0000-0000-0000-000000000953",
            "Open YouTube on my phone and search forex",
        ),
        identity(),
    )

    assert task.state is TaskState.COMPLETED
    assert task.approval is None
    assert task.policy_decisions[0].outcome.value == "allow"

    handoffs = core.list_phone_handoffs(SESSION)
    assert len(handoffs) == 1
    assert handoffs[0].task_id == task.task_id
    assert handoffs[0].launch_url.startswith(
        "https://www.youtube.com/results?search_query="
    )
