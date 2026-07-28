from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.client import GitHubApiClient
from nexuss.connectors.github.device_flow import GitHubDeviceFlowClient
from nexuss.connectors.github.models import (
    GitHubAccount,
    GitHubConnectionProfile,
    GitHubConnectState,
    OAuthTokenBundle,
    RepositoryCreateApproval,
)
from nexuss.connectors.github.service import GitHubConnectorService
from nexuss.connectors.vault import InMemorySecretVault


def user_payload() -> dict[str, object]:
    return {
        "id": 42,
        "login": "kexyz254",
        "type": "User",
        "html_url": "https://github.com/kexyz254",
        "avatar_url": "https://avatars.githubusercontent.com/u/42",
    }


def repo_payload() -> dict[str, object]:
    return {
        "id": 101,
        "node_id": "R_kgDOExample",
        "name": "Nexuss-AI",
        "full_name": "kexyz254/Nexuss-AI",
        "owner": {"login": "kexyz254"},
        "private": True,
        "archived": False,
        "disabled": False,
        "fork": False,
        "html_url": "https://github.com/kexyz254/Nexuss-AI",
        "url": "https://api.github.com/repos/kexyz254/Nexuss-AI",
        "default_branch": "main",
        "size": 0,
        "open_issues_count": 0,
        "created_at": "2026-07-28T10:00:00Z",
        "updated_at": "2026-07-28T10:00:00Z",
        "pushed_at": None,
        "permissions": {"admin": True, "push": True, "pull": True},
    }


def connected_service(handler) -> GitHubConnectorService:
    now = datetime(2026, 7, 28, tzinfo=UTC)
    vault = InMemorySecretVault()
    token = OAuthTokenBundle(
        access_token=SecretStr("ghu_secret"),
        access_token_expires_at=now + timedelta(days=1),
        refresh_token=SecretStr("ghr_secret"),
        refresh_token_expires_at=now + timedelta(days=30),
    )
    profile = GitHubConnectionProfile(
        client_id="client-id",
        account=GitHubAccount(
            account_id=42,
            login="kexyz254",
            account_type="User",
            html_url="https://github.com/kexyz254",
        ),
        connected_at=now,
        token_expires_at=token.access_token_expires_at,
    )
    vault.put_json("github:user:token", token.to_vault_payload())
    vault.put_json("github:user:profile", profile.model_dump(mode="json"))
    return GitHubConnectorService(
        vault=vault,
        api_transport=httpx.MockTransport(handler),
    )


def test_vault_round_trip() -> None:
    vault = InMemorySecretVault()
    vault.put_json("secret", {"token": "value"})
    assert vault.get_json("secret") == {"token": "value"}
    vault.delete("secret")
    assert vault.get_json("secret") is None


def test_device_flow_pending_and_success_token_hidden() -> None:
    responses = iter(
        [
            {
                "device_code": "device-secret",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
            {"error": "authorization_pending"},
            {
                "access_token": "ghu_super_secret",
                "expires_in": 28800,
                "refresh_token": "ghr_refresh_secret",
                "refresh_token_expires_in": 15897600,
                "token_type": "bearer",
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    client = GitHubDeviceFlowClient(transport=httpx.MockTransport(handler))
    now = datetime(2026, 7, 28, tzinfo=UTC)
    challenge = client.begin("client-id", now=now)
    pending = client.poll(
        "client-id",
        challenge.device_code.get_secret_value(),
        interval_seconds=5,
        now=now,
    )
    connected = client.poll(
        "client-id",
        challenge.device_code.get_secret_value(),
        interval_seconds=5,
        now=now,
    )
    assert pending.state is GitHubConnectState.PENDING
    assert connected.token is not None
    assert "ghu_super_secret" not in repr(connected.token)


def test_api_payload_is_private_and_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer token"
        assert request.headers["x-github-api-version"] == "2026-03-10"
        assert request.read().decode() == '{"name":"Nexuss-AI","private":true,"auto_init":false}'
        return httpx.Response(201, json=repo_payload())

    repository = GitHubApiClient(
        "token",
        transport=httpx.MockTransport(handler),
    ).create_repository(
        {"name": "Nexuss-AI", "private": True, "auto_init": False}
    )
    assert repository.private
    assert repository.name == "Nexuss-AI"


def test_prepare_preserves_requested_and_exact_name() -> None:
    service = connected_service(lambda request: httpx.Response(500))
    prepared = service.prepare_private_repository("Nexuss AI")
    assert prepared.requested_name == "Nexuss AI"
    assert prepared.repository_name == "Nexuss-AI"
    assert prepared.payload == {
        "name": "Nexuss-AI",
        "private": True,
        "auto_init": False,
    }
    assert len(prepared.payload_sha256) == 64


def test_exact_approval_hash_required() -> None:
    service = connected_service(lambda request: httpx.Response(500))
    now = datetime(2026, 7, 28, tzinfo=UTC)
    prepared = service.prepare_private_repository("Nexuss AI", now=now)
    approval = RepositoryCreateApproval(
        approval_id=uuid4(),
        request_id=prepared.request_id,
        account_login="kexyz254",
        payload_sha256="0" * 64,
        approved_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    with pytest.raises(ConnectorError) as raised:
        service.create_private_repository(prepared, approval, now=now)
    assert raised.value.code == "GITHUB_APPROVAL_PAYLOAD_MISMATCH"


def test_create_is_verified_private_and_empty() -> None:
    counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        counts[key] = counts.get(key, 0) + 1
        if request.url.path == "/user":
            return httpx.Response(200, json=user_payload())
        if request.url.path == "/repos/kexyz254/Nexuss-AI":
            if counts[key] == 1:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json=repo_payload())
        if request.url.path == "/user/repos":
            return httpx.Response(201, json=repo_payload())
        if request.url.path == "/repos/kexyz254/Nexuss-AI/commits":
            return httpx.Response(409, json={"message": "Git Repository is empty."})
        return httpx.Response(500)

    service = connected_service(handler)
    now = datetime(2026, 7, 28, tzinfo=UTC)
    prepared = service.prepare_private_repository("Nexuss AI", now=now)
    approval = RepositoryCreateApproval(
        approval_id=uuid4(),
        request_id=prepared.request_id,
        account_login="kexyz254",
        payload_sha256=prepared.payload_sha256,
        approved_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    verified = service.create_private_repository(
        prepared,
        approval,
        now=now + timedelta(seconds=10),
    )
    assert verified.private_verified
    assert verified.empty_repository_verified
    assert verified.owner_verified
    assert verified.name_verified


def test_connection_stores_identity_without_leaking_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "github.com":
            if request.url.path == "/login/device/code":
                return httpx.Response(
                    200,
                    json={
                        "device_code": "device-secret",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": "https://github.com/login/device",
                        "expires_in": 900,
                        "interval": 5,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "access_token": "ghu_secret",
                    "expires_in": 28800,
                    "refresh_token": "ghr_secret",
                    "refresh_token_expires_in": 15897600,
                    "token_type": "bearer",
                },
            )
        if request.url.path == "/user":
            return httpx.Response(200, json=user_payload())
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    vault = InMemorySecretVault()
    service = GitHubConnectorService(
        vault=vault,
        device_flow=GitHubDeviceFlowClient(transport=transport),
        api_transport=transport,
    )
    now = datetime(2026, 7, 28, tzinfo=UTC)
    challenge = service.begin_connection("client-id", now=now)
    result = service.poll_connection(challenge.flow_id, now=now + timedelta(seconds=6))
    assert result.profile is not None
    assert result.profile.account.login == "kexyz254"
    assert vault.exists("github:user:token")
    assert "ghu_secret" not in result.profile.model_dump_json()
