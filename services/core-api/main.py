"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from fastapi import FastAPI

app = FastAPI(title="Nexuss Core API", version="0.0.1")


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    return {"status": "ready", "mode": "foundation"}
