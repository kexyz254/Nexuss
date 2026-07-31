from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexuss.commitments.api import register_commitment_routes
from nexuss.commitments.models import (
    CommitmentHealth,
    PrepareDayRequest,
    WorkdayBrief,
)


class ServiceStub:
    def health(self):
        return CommitmentHealth(
            google_workspace_connected=False,
            trusted_mobile_feed_available=False,
        )

    def prepare_day(self, request: PrepareDayRequest):
        return WorkdayBrief(
            planning_date=request.planning_date,
            timezone=request.timezone,
            connected_google_account=None,
            source_status={
                "gmail": False,
                "calendar": False,
                "contacts": False,
                "mobile": False,
            },
            commitments=(),
            calendar_events=(),
            conflicts=(),
            focus_blocks=(),
            urgent_count=0,
            overdue_count=0,
            responses_needed=0,
        )


def test_prepare_day_requires_authenticated_session() -> None:
    app = FastAPI()
    register_commitment_routes(
        app,
        lambda request: None,
        service=ServiceStub(),
    )
    response = TestClient(app).post(
        "/v1/commitments/prepare-day",
        headers={
            "X-Nexuss-Session-ID": str(uuid4()),
            "X-Nexuss-Session-Authenticated": "false",
        },
        json={
            "planning_date": datetime.now(UTC).date().isoformat(),
            "timezone": "UTC",
            "include_mobile": True,
            "gmail_days_back": 14,
        },
    )
    assert response.status_code == 401
