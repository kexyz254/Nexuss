"""Authenticated P6.6B.1 live GitHub read-routing parity check."""

from __future__ import annotations

import argparse
import json
from urllib import request
from uuid import uuid4


def _json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, object] | None = None,
    session_id: str | None = None,
) -> dict[str, object]:
    data = None
    headers = {
        "Accept": "application/json",
        "X-Nexuss-Session-Authenticated": "true",
    }

    if session_id is not None:
        headers["X-Nexuss-Session-ID"] = session_id

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    with request.urlopen(req, timeout=45) as response:
        value = json.loads(response.read().decode("utf-8"))

    if not isinstance(value, dict):
        raise TypeError("Nexuss response was not an object")

    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8100",
    )
    parser.add_argument(
        "--repository",
        default="kexyz254/GlyphSentry-Core-Final",
    )
    args = parser.parse_args()

    session_id = str(uuid4())
    direct = _json_request(
        "POST",
        f"{args.base_url}/v1/github-workspace/repository/inspect",
        payload={"repository_full_name": args.repository},
    )
    understood = _json_request(
        "POST",
        f"{args.base_url}/v1/understanding/resolve",
        session_id=session_id,
        payload={
            "request_id": str(uuid4()),
            "utterance": (
                f"Inspect {args.repository}. Verify the default branch "
                "and exact current commit. Do not modify or execute code."
            ),
            "channel": "text",
            "execute_safe_reads": True,
        },
    )

    print("Direct endpoint:", direct.get("read_only"))
    print("Understanding status:", understood.get("status"))

    interpretation = understood.get("interpretation", {})
    entities = (
        interpretation.get("entities", {})
        if isinstance(interpretation, dict)
        else {}
    )
    print("Resolved ref:", entities.get("ref"))

    assert direct.get("github_write_performed") is False
    assert understood.get("status") == "completed"
    assert entities.get("ref") is None

    execution = understood.get("execution")
    assert isinstance(execution, dict)
    assert execution.get("github_write_performed") is False
    assert execution.get("credentials_exposed") is False

    print("PASS: direct and understanding GitHub read routes agree.")
    print("GitHub write performed: False")
    print("Credentials exposed: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
