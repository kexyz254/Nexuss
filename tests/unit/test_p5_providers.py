"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

import httpx

from nexuss.knowledge.provider import WikipediaKnowledgeProvider
from nexuss.media.youtube import (
    YouTubeDataProvider,
    extract_youtube_video_id,
)


def test_wikipedia_provider_returns_bounded_sources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "title": "Foreign exchange market",
                            "extract": "Forex is a global market.",
                            "fullurl": (
                                "https://en.wikipedia.org/wiki/"
                                "Foreign_exchange_market"
                            ),
                        }
                    ]
                }
            },
        )

    report = WikipediaKnowledgeProvider(
        transport=httpx.MockTransport(handler)
    ).research("forex")

    assert report["source_count"] == 1
    assert report["memory_saved"] is False


def test_youtube_direct_url_and_unconfigured_state() -> None:
    assert (
        extract_youtube_video_id(
            "https://www.youtube.com/watch?v=M7lc1UVf-VE"
        )
        == "M7lc1UVf-VE"
    )

    direct = YouTubeDataProvider(api_key="").discover(
        "https://youtu.be/M7lc1UVf-VE"
    )
    direct_results = direct["results"]
    assert isinstance(direct_results, list)
    assert direct_results[0]["video_id"] == "M7lc1UVf-VE"
    assert direct["selection_state"] == "exact_match"

    state = YouTubeDataProvider(api_key="").discover(
        "Silence by Popcaan"
    )
    assert state["configured"] is False
    assert state["results"] == []


def test_youtube_api_preserves_intent_and_ranks_exact_official_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "key" not in request.url.params
        assert request.headers["x-goog-api-key"] == "test-key"

        if request.url.path.endswith("/search"):
            assert request.url.params["type"] == "video"
            assert request.url.params["videoEmbeddable"] == "true"
            assert request.url.params["q"] == "Popcaan Silence"
            assert request.url.params["maxResults"] == "10"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": {"videoId": "REMIX000001"},
                            "snippet": {
                                "title": "Popcaan - Silence Remix Reaction",
                                "channelTitle": "Random Reactions",
                                "description": "A reaction remix.",
                                "publishedAt": "2025-01-01T00:00:00Z",
                                "liveBroadcastContent": "none",
                                "thumbnails": {
                                    "high": {
                                        "url": (
                                            "https://i.ytimg.com/vi/"
                                            "REMIX000001/hqdefault.jpg"
                                        )
                                    }
                                },
                            },
                        },
                        {
                            "id": {"videoId": "M7lc1UVf-VE"},
                            "snippet": {
                                "title": "Popcaan - Silence (Official Video)",
                                "channelTitle": "Popcaan",
                                "description": "Official music video.",
                                "publishedAt": "2018-07-04T00:00:00Z",
                                "liveBroadcastContent": "none",
                                "thumbnails": {
                                    "high": {
                                        "url": (
                                            "https://i.ytimg.com/vi/"
                                            "M7lc1UVf-VE/hqdefault.jpg"
                                        )
                                    }
                                },
                            },
                        },
                    ]
                },
            )

        assert request.url.path.endswith("/videos")
        assert request.url.params["part"] == "contentDetails,statistics,status"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "REMIX000001",
                        "contentDetails": {"duration": "PT8M1S"},
                        "statistics": {"viewCount": "1500"},
                        "status": {"embeddable": True},
                    },
                    {
                        "id": "M7lc1UVf-VE",
                        "contentDetails": {"duration": "PT3M44S"},
                        "statistics": {"viewCount": "100000000"},
                        "status": {"embeddable": True},
                    },
                ]
            },
        )

    result = YouTubeDataProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    ).discover("Silence by Popcaan")

    assert result["configured"] is True
    assert result["query"] == "Silence by Popcaan"
    assert result["search_query"] == "Popcaan Silence"
    assert result["parsed_title"] == "Silence"
    assert result["parsed_artist"] == "Popcaan"
    assert result["selection_state"] == "exact_match"

    results = result["results"]
    assert isinstance(results, list)
    assert results[0]["video_id"] == "M7lc1UVf-VE"
    assert results[0]["title"] == "Popcaan - Silence (Official Video)"
    assert results[0]["duration_label"] == "3:44"
    assert results[0]["view_count_label"] == "100.0M views"
    assert results[0]["confidence"] > results[1]["confidence"]
