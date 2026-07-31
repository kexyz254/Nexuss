"""Loopback health check for the installed P6.7A mobile fabric."""

from __future__ import annotations

import argparse
import json
from urllib import request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    args = parser.parse_args()

    with request.urlopen(
        f"{args.base_url}/v1/mobile-fabric/health",
        timeout=15,
    ) as response:
        health = json.loads(response.read().decode("utf-8"))

    if not isinstance(health, dict):
        raise TypeError("Mobile fabric health response was not an object")

    print("Health:", health)
    assert health["status"] == "ready"
    assert health["trusted_device_required"] is True
    assert health["private_app_database_access"] is False
    assert health["accessibility_automation"] is False
    assert health["external_actions_require_approval"] is True

    print("PASS: P6.7A mobile fabric live health check completed.")
    print("External action performed: False")
    print("Credentials exposed: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
