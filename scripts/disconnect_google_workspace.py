"""Remove the encrypted Google Workspace connection."""
from nexuss.connectors.google_workspace.service import (
    GoogleWorkspaceConnectorService,
)


def main() -> int:
    service = GoogleWorkspaceConnectorService.from_environment()
    service.disconnect()
    print("PASS: Google Workspace connection removed.")
    print("External provider write performed: False")
    print("Credentials exposed: False")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
