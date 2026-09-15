"""Signed supervisory client. No trading or remote-shell transport."""
import hashlib
import hmac
import ipaddress
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import HTTPException, Request


class TradingClient:
    def __init__(self, url, secret, transport=None):
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("Bridge URL must be an origin without credentials")
        private_http = False
        try:
            address = ipaddress.ip_address(parsed.hostname or "")
            private_http = address.is_loopback or address in ipaddress.ip_network("100.64.0.0/10")
        except ValueError:
            pass
        if parsed.scheme != "https" and not (parsed.scheme == "http" and private_http):
            raise ValueError("Use HTTPS or a loopback/Tailscale IP")
        if len(secret) < 32:
            raise ValueError("Bridge secret must contain at least 32 bytes")
        self.url, self.secret, self.transport = url.rstrip("/"), secret, transport

    def request(self, method, target, payload=None):
        allowed = (method == "GET" and target.startswith("/agent/v1/evidence/")) or (
            method == "POST" and target == "/agent/v1/feedback") or (
            method == "GET" and target in {"/agent/v1/capabilities", "/agent/v1/worker/status"}) or (
            method == "GET" and target.startswith("/agent/v1/observations?"))
        if not allowed:
            raise ValueError("Operation not supported")
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        if len(body) > 65536:
            raise ValueError("Feedback too large")
        timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
        digest = hashlib.sha256(body).hexdigest()
        message = f"v1\n{method}\n{target}\n{timestamp}\n{nonce}\n{digest}".encode()
        signature = hmac.new(self.secret, message, hashlib.sha256).hexdigest()
        headers = {"X-Nexuss-Time": timestamp, "X-Nexuss-Nonce": nonce,
                   "X-Nexuss-Signature": signature, "Content-Type": "application/json"}
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False,
                          transport=self.transport) as client:
            with client.stream(method, self.url + target, headers=headers, content=body) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 1_000_000:
                        raise ValueError("Bridge response too large")
        return json.loads(raw)

    def evidence(self, resource, symbol="BTC/USDT"):
        if resource not in {"health", "status", "decisions"}:
            raise ValueError("Unknown evidence resource")
        return self.request("GET", "/agent/v1/evidence/" + resource + "?" + urlencode({"symbol": symbol}))

    def observations(self, after=0, limit=100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid observation cursor or limit")
        return self.request("GET", "/agent/v1/observations?" + urlencode({"after": after, "limit": limit}))


def register_trading_routes(app, require_local_control):
    def client():
        try:
            return TradingClient(os.environ["NEXUSS_TAS_BRIDGE_URL"],
                                 Path(os.environ["NEXUSS_TAS_SECRET_FILE"]).read_bytes().strip())
        except (KeyError, OSError, ValueError):
            raise HTTPException(503, "Trading bridge not configured") from None

    @app.get("/v1/trading/evidence/{resource}")
    def evidence(resource: str, request: Request, symbol: str = "BTC/USDT"):
        require_local_control(request)
        try:
            return client().evidence(resource, symbol)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Trading evidence unavailable") from None

    @app.get("/v1/trading/worker/status")
    def worker_status(request: Request):
        require_local_control(request)
        try:
            return client().request("GET", "/agent/v1/worker/status")
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Trading worker unavailable") from None

    @app.get("/v1/trading/observations")
    def observations(request: Request, after: int = 0, limit: int = 100):
        require_local_control(request)
        if after < 0 or not 1 <= limit <= 100:
            raise HTTPException(422, "Invalid observation cursor or limit")
        try:
            return client().observations(after, limit)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Trading observations unavailable") from None

    @app.post("/v1/trading/feedback")
    def feedback(payload: dict, request: Request):
        require_local_control(request)
        try:
            return client().request("POST", "/agent/v1/feedback", payload)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Trading feedback not accepted") from None
