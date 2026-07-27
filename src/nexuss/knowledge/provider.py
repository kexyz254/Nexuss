"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Real, bounded, read-only public knowledge acquisition for Nexuss P5.
"""

from __future__ import annotations

import os
from typing import Protocol
from urllib.parse import quote_plus

import httpx

_DEFAULT_CONTACT = "https://github.com/kexyz254peter/nexuss"
_USER_AGENT = (
    f"Nexuss/0.5 "
    f"({os.getenv('NEXUSS_CONTACT', _DEFAULT_CONTACT)}) "
    "httpx"
)


class KnowledgeProviderError(RuntimeError):
    """Raised when a knowledge provider cannot satisfy its evidence contract."""


class KnowledgeProvider(Protocol):
    def research(self, query: str) -> dict[str, object]: ...


def _normalize_query(query: str) -> str:
    normalized = " ".join(query.split()).strip()
    if not normalized or len(normalized) > 240:
        raise KnowledgeProviderError("KNOWLEDGE_QUERY_INVALID")
    return normalized


class WikipediaKnowledgeProvider:
    """Retrieve bounded introductory extracts from the public MediaWiki API."""

    _endpoint = "https://en.wikipedia.org/w/api.php"

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        trust_env: bool = True,
    ) -> None:
        self._transport = transport
        self._trust_env = trust_env

    def research(self, query: str) -> dict[str, object]:
        normalized = _normalize_query(query)
        parameters = {
            "action": "query",
            "generator": "search",
            "gsrsearch": normalized,
            "gsrlimit": "5",
            "prop": "extracts|info",
            "inprop": "url",
            "exintro": "1",
            "explaintext": "1",
            "exsentences": "5",
            "format": "json",
            "formatversion": "2",
        }
        try:
            with httpx.Client(
                timeout=8.0,
                trust_env=self._trust_env,
                follow_redirects=True,
                transport=self._transport,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                response = client.get(self._endpoint, params=parameters)
                if response.status_code == 403:
                    raise KnowledgeProviderError(
                        "KNOWLEDGE_PROVIDER_FORBIDDEN"
                    )
                response.raise_for_status()
                payload: object = response.json()
        except KnowledgeProviderError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise KnowledgeProviderError(
                "KNOWLEDGE_PROVIDER_UNAVAILABLE"
            ) from exc

        pages = self._extract_pages(payload)
        sources = self._build_sources(pages)
        if not sources:
            raise KnowledgeProviderError("KNOWLEDGE_NO_SOURCES")

        brief = "\n\n".join(
            f"{index}. {source['title']}: {source['extract']}"
            for index, source in enumerate(sources[:3], start=1)
        )
        return {
            "source_mode": "live_public_web_readonly",
            "query": normalized,
            "provider": "Wikipedia MediaWiki API",
            "source_count": len(sources),
            "sources": sources,
            "brief": brief,
            "search_url": (
                "https://www.google.com/search?q="
                f"{quote_plus(normalized)}"
            ),
            "memory_saved": False,
            "content_trust": "untrusted_external_source",
        }

    @staticmethod
    def _extract_pages(payload: object) -> list[object]:
        if not isinstance(payload, dict):
            raise KnowledgeProviderError("KNOWLEDGE_RESPONSE_INVALID")
        query_object = payload.get("query")
        if not isinstance(query_object, dict):
            return []
        pages = query_object.get("pages", [])
        if not isinstance(pages, list):
            raise KnowledgeProviderError("KNOWLEDGE_RESPONSE_INVALID")
        return pages

    @staticmethod
    def _build_sources(pages: list[object]) -> list[dict[str, object]]:
        sources: list[dict[str, object]] = []
        for page in pages[:5]:
            if not isinstance(page, dict):
                continue
            title = str(page.get("title", "")).strip()
            extract = str(page.get("extract", "")).strip()
            url = str(page.get("fullurl", "")).strip()
            if (
                not title
                or not extract
                or not url.startswith("https://en.wikipedia.org/")
            ):
                continue
            sources.append(
                {
                    "title": title,
                    "url": url,
                    "extract": extract[:1600],
                    "provider": "Wikipedia",
                    "retrieval_status": "retrieved",
                }
            )
        return sources


class DisabledKnowledgeProvider:
    def research(self, query: str) -> dict[str, object]:
        del query
        raise KnowledgeProviderError("KNOWLEDGE_PROVIDER_NOT_CONFIGURED")
