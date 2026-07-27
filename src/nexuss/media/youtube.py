"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Official YouTube discovery, entity-aware ranking, and strict URL handling.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html import unescape
from typing import Protocol, TypedDict
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
_TOKEN = re.compile(r"[a-z0-9]+")
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}
_UNREQUESTED_VARIANTS = {
    "cover",
    "karaoke",
    "reaction",
    "remix",
    "nightcore",
    "slowed",
    "reverb",
    "instrumental",
    "live",
    "lyrics",
}


class MediaProviderError(RuntimeError):
    """Raised when media discovery cannot satisfy its evidence contract."""


class YouTubeSearchResult(TypedDict):
    """Typed public metadata returned by the YouTube search connector."""

    video_id: str
    title: str
    channel_title: str
    thumbnail_url: str
    watch_url: str
    confidence: float
    description: str
    published_at: str
    duration_seconds: int
    duration_label: str
    view_count: int
    view_count_label: str
    live_broadcast_content: str
    match_reason: str


class YouTubeProvider(Protocol):
    def discover(self, query: str) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class ParsedMediaQuery:
    original: str
    search_text: str
    title: str
    artist: str
    version: str


def _normalize_query(query: str) -> str:
    normalized = " ".join(query.split()).strip(" :.-")
    if not normalized or len(normalized) > 240:
        raise MediaProviderError("YOUTUBE_QUERY_INVALID")
    return normalized


def _tokens(value: str) -> set[str]:
    return set(_TOKEN.findall(unescape(value).casefold()))


def _normalized_phrase(value: str) -> str:
    return " ".join(_TOKEN.findall(unescape(value).casefold()))


def _parse_media_query(query: str) -> ParsedMediaQuery:
    normalized = _normalize_query(query)
    title = ""
    artist = ""

    by_match = re.match(
        r"^(?P<title>.+?)\s+by\s+(?P<artist>.+)$",
        normalized,
        re.IGNORECASE,
    )
    dash_match = re.match(
        r"^(?P<artist>.+?)\s+-\s+(?P<title>.+)$",
        normalized,
    )
    match = by_match or dash_match
    if match:
        title = match.group("title").strip(" \"'")
        artist = match.group("artist").strip(" \"'")

    lowered = normalized.casefold()
    version = next(
        (
            candidate
            for candidate in (
                "official video",
                "official audio",
                "lyrics",
                "live",
                "remix",
            )
            if candidate in lowered
        ),
        "",
    )
    search_text = f"{artist} {title}".strip() if title and artist else normalized
    return ParsedMediaQuery(
        original=normalized,
        search_text=search_text,
        title=title,
        artist=artist,
        version=version,
    )


def youtube_search_url(query: str) -> str:
    normalized = _normalize_query(query)
    return "https://www.youtube.com/results?search_query=" f"{quote_plus(normalized)}"


def extract_youtube_video_id(value: str) -> str | None:
    candidate = value.strip()
    if _VIDEO_ID.fullmatch(candidate):
        return candidate

    parsed = urlparse(candidate)
    host = (parsed.hostname or "").casefold()
    video_id: str | None = None

    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/")):
            parts = parsed.path.strip("/").split("/")
            video_id = parts[1] if len(parts) > 1 else None

    if video_id and _VIDEO_ID.fullmatch(video_id):
        return video_id
    return None


def _thumbnail_url(snippet: dict[object, object]) -> str:
    thumbnails = snippet.get("thumbnails")
    if not isinstance(thumbnails, dict):
        return ""
    selected = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default")
    if not isinstance(selected, dict):
        return ""
    return str(selected.get("url", ""))


def _parse_duration(value: object) -> int:
    if not isinstance(value, str):
        return 0
    match = _ISO_DURATION.fullmatch(value)
    if match is None:
        return 0
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return (((days * 24) + hours) * 60 + minutes) * 60 + seconds


def _duration_label(seconds: int) -> str:
    if seconds <= 0:
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, final_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{final_seconds:02d}"
    return f"{minutes}:{final_seconds:02d}"


def _view_count(value: object) -> int:
    try:
        return max(0, int(str(value)))
    except ValueError:
        return 0


def _view_count_label(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B views"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M views"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K views"
    return f"{value} views" if value else ""


def _score_result(
    query: ParsedMediaQuery,
    title: str,
    channel: str,
) -> tuple[float, str]:
    result_phrase = _normalized_phrase(f"{title} {channel}")
    result_tokens = _tokens(result_phrase)
    query_tokens = _tokens(query.search_text)
    coverage = len(query_tokens & result_tokens) / max(1, len(query_tokens))
    score = 0.30 + (0.34 * coverage)
    reasons: list[str] = []

    title_phrase = _normalized_phrase(query.title)
    result_title_phrase = _normalized_phrase(title)
    if title_phrase and title_phrase in result_title_phrase:
        score += 0.24
        reasons.append("title match")

    artist_tokens = _tokens(query.artist)
    if artist_tokens:
        artist_coverage = len(artist_tokens & result_tokens) / len(artist_tokens)
        score += 0.18 * artist_coverage
        if artist_coverage == 1.0:
            reasons.append("artist match")

    lowered_result = f"{title} {channel}".casefold()
    if "official" in lowered_result:
        score += 0.08
        reasons.append("official source signal")

    requested_variants = _tokens(query.version)
    for variant in _UNREQUESTED_VARIANTS:
        if variant in lowered_result and variant not in requested_variants:
            score -= 0.18

    if title_phrase and result_title_phrase in {
        title_phrase,
        f"{_normalized_phrase(query.artist)} {title_phrase}".strip(),
        f"{title_phrase} {_normalized_phrase(query.artist)}".strip(),
    }:
        score += 0.08
        reasons.append("exact title structure")

    bounded = round(max(0.0, min(0.99, score)), 3)
    reason = ", ".join(reasons) if reasons else "query token relevance"
    return bounded, reason


class YouTubeDataProvider:
    """Discover and rank embeddable videos using official YouTube APIs."""

    _search_endpoint = "https://www.googleapis.com/youtube/v3/search"
    _videos_endpoint = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        trust_env: bool = True,
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else os.getenv("NEXUSS_YOUTUBE_API_KEY", "")
        )
        self._transport = transport
        self._trust_env = trust_env
        self._region_code = os.getenv("NEXUSS_YOUTUBE_REGION_CODE", "").strip().upper()
        self._language = os.getenv("NEXUSS_YOUTUBE_LANGUAGE", "").strip()

    def discover(self, query: str) -> dict[str, object]:
        normalized = _normalize_query(query)
        direct_id = extract_youtube_video_id(normalized)
        if direct_id:
            return self._direct_result(normalized, direct_id)

        parsed_query = _parse_media_query(normalized)
        search_url = youtube_search_url(parsed_query.original)
        if not self._api_key:
            return {
                "source_mode": "youtube_connector_unconfigured",
                "configured": False,
                "query": parsed_query.original,
                "search_query": parsed_query.search_text,
                "search_url": search_url,
                "results": [],
                "reason_code": "YOUTUBE_API_KEY_NOT_CONFIGURED",
            }

        with httpx.Client(
            timeout=10.0,
            trust_env=self._trust_env,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            search_payload = self._search_api(client, parsed_query.search_text)
            search_items = search_payload.get("items")
            if not isinstance(search_items, list):
                raise MediaProviderError("YOUTUBE_RESPONSE_INVALID")

            video_ids = self._extract_video_ids(search_items)
            details = self._video_details(client, video_ids)

        results = self._build_results(parsed_query, search_items, details)
        results.sort(
            key=lambda item: (item["confidence"], item["view_count"]),
            reverse=True,
        )
        top_confidence = results[0]["confidence"] if results else 0.0
        margin = (
            top_confidence - results[1]["confidence"]
            if len(results) > 1
            else top_confidence
        )
        selection_state = (
            "exact_match"
            if top_confidence >= 0.86 and margin >= 0.05
            else "review_required"
        )
        return {
            "source_mode": "live_youtube_data_api",
            "configured": True,
            "query": parsed_query.original,
            "search_query": parsed_query.search_text,
            "search_url": search_url,
            "parsed_title": parsed_query.title,
            "parsed_artist": parsed_query.artist,
            "parsed_version": parsed_query.version,
            "results": results,
            "result_count": len(results),
            "selection_state": selection_state,
            "top_confidence": top_confidence,
            "confidence_margin": round(margin, 3),
        }

    def _headers(self) -> dict[str, str]:
        return {"X-Goog-Api-Key": self._api_key}

    def _search_api(
        self,
        client: httpx.Client,
        query: str,
    ) -> dict[object, object]:
        parameters = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoEmbeddable": "true",
            "safeSearch": "moderate",
            "maxResults": "10",
        }
        if self._region_code:
            parameters["regionCode"] = self._region_code
        if self._language:
            parameters["relevanceLanguage"] = self._language

        payload = self._request_json(
            client,
            self._search_endpoint,
            parameters,
        )
        return payload

    def _video_details(
        self,
        client: httpx.Client,
        video_ids: list[str],
    ) -> dict[str, dict[object, object]]:
        if not video_ids:
            return {}
        payload = self._request_json(
            client,
            self._videos_endpoint,
            {
                "part": "contentDetails,statistics,status",
                "id": ",".join(video_ids),
                "maxResults": str(len(video_ids)),
            },
        )
        items = payload.get("items")
        if not isinstance(items, list):
            return {}

        details: dict[str, dict[object, object]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("id", ""))
            if _VIDEO_ID.fullmatch(video_id):
                details[video_id] = item
        return details

    def _request_json(
        self,
        client: httpx.Client,
        endpoint: str,
        parameters: dict[str, str],
    ) -> dict[object, object]:
        try:
            response = client.get(
                endpoint,
                params=parameters,
                headers=self._headers(),
            )
            response.raise_for_status()
            payload: object = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MediaProviderError("YOUTUBE_PROVIDER_UNAVAILABLE") from exc

        if not isinstance(payload, dict):
            raise MediaProviderError("YOUTUBE_RESPONSE_INVALID")
        return payload

    @staticmethod
    def _extract_video_ids(items: list[object]) -> list[str]:
        video_ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            identifier = item.get("id")
            if not isinstance(identifier, dict):
                continue
            video_id = str(identifier.get("videoId", ""))
            if _VIDEO_ID.fullmatch(video_id):
                video_ids.append(video_id)
        return video_ids

    @staticmethod
    def _direct_result(query: str, video_id: str) -> dict[str, object]:
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        return {
            "source_mode": "direct_user_supplied_youtube_url",
            "configured": True,
            "query": query,
            "search_query": query,
            "search_url": watch_url,
            "parsed_title": "",
            "parsed_artist": "",
            "parsed_version": "",
            "results": [
                {
                    "video_id": video_id,
                    "title": "User-selected YouTube video",
                    "channel_title": "YouTube",
                    "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                    "watch_url": watch_url,
                    "confidence": 1.0,
                    "description": "",
                    "published_at": "",
                    "duration_seconds": 0,
                    "duration_label": "",
                    "view_count": 0,
                    "view_count_label": "",
                    "live_broadcast_content": "none",
                    "match_reason": "direct user-selected URL",
                }
            ],
            "result_count": 1,
            "selection_state": "exact_match",
            "top_confidence": 1.0,
            "confidence_margin": 1.0,
        }

    @staticmethod
    def _build_results(
        query: ParsedMediaQuery,
        items: list[object],
        details: dict[str, dict[object, object]],
    ) -> list[YouTubeSearchResult]:
        results: list[YouTubeSearchResult] = []
        for item in items[:10]:
            if not isinstance(item, dict):
                continue
            identifier = item.get("id")
            snippet = item.get("snippet")
            if not isinstance(identifier, dict) or not isinstance(snippet, dict):
                continue

            video_id = str(identifier.get("videoId", ""))
            if not _VIDEO_ID.fullmatch(video_id):
                continue

            title = unescape(str(snippet.get("title", ""))).strip()
            channel = unescape(str(snippet.get("channelTitle", ""))).strip()
            if not title:
                continue

            detail = details.get(video_id, {})
            content_details = detail.get("contentDetails")
            statistics = detail.get("statistics")
            status = detail.get("status")
            duration_seconds = (
                _parse_duration(content_details.get("duration"))
                if isinstance(content_details, dict)
                else 0
            )
            views = (
                _view_count(statistics.get("viewCount"))
                if isinstance(statistics, dict)
                else 0
            )
            embeddable = (
                bool(status.get("embeddable", True))
                if isinstance(status, dict)
                else True
            )
            if not embeddable:
                continue

            confidence, match_reason = _score_result(query, title, channel)
            results.append(
                {
                    "video_id": video_id,
                    "title": title,
                    "channel_title": channel,
                    "thumbnail_url": _thumbnail_url(snippet),
                    "watch_url": f"https://www.youtube.com/watch?v={video_id}",
                    "confidence": confidence,
                    "description": unescape(str(snippet.get("description", ""))).strip(),
                    "published_at": str(snippet.get("publishedAt", "")),
                    "duration_seconds": duration_seconds,
                    "duration_label": _duration_label(duration_seconds),
                    "view_count": views,
                    "view_count_label": _view_count_label(views),
                    "live_broadcast_content": str(
                        snippet.get("liveBroadcastContent", "none")
                    ),
                    "match_reason": match_reason,
                }
            )
        return results
