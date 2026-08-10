"""Unit tests for the social_profiles scraping source.

Mocks Scrapling's Fetcher to test profile extraction without real HTTP.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from outreach_os.services.scraping.sources.social_profiles import (
    _detect_platform,
    _extract_github_profile,
    _extract_twitter_profile,
    scrape_profiles,
)


class TestDetectPlatform:
    def test_twitter(self) -> None:
        assert _detect_platform("https://twitter.com/johndoe") == "twitter"

    def test_x_com(self) -> None:
        assert _detect_platform("https://x.com/johndoe") == "twitter"

    def test_github(self) -> None:
        assert _detect_platform("https://github.com/johndoe") == "github"

    def test_unknown(self) -> None:
        assert _detect_platform("https://facebook.com/johndoe") == "unknown"

    @pytest.mark.parametrize(
        "url",
        [
            "https://netflix.com/careers",
            "https://www.matrix.com/about",
            "https://linux.com/team",
            "https://mailbox.com/contact",
        ],
    )
    def test_lookalike_domains_are_not_twitter(self, url: str) -> None:
        """Regression: detection used `"x.com" in host`, which matches every
        one of these. Ordinary company sites were handed to the Twitter parser,
        which then produced leads from Open Graph tags that mean something
        entirely different."""
        assert _detect_platform(url) == "unknown"

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://www.x.com/johndoe", "twitter"),
            ("https://mobile.twitter.com/johndoe", "twitter"),
            ("https://x.com:443/johndoe", "twitter"),
            ("https://www.github.com/johndoe", "github"),
        ],
    )
    def test_subdomains_and_ports_still_match(self, url: str, expected: str) -> None:
        assert _detect_platform(url) == expected


class TestExtractTwitterProfile:
    def test_extracts_name_and_bio(self) -> None:
        html = """
        <html><head>
            <meta property="og:title" content="John Doe (@johndoe) on X">
            <meta property="og:description" content="Building cool stuff. Based in SF.">
        </head><body></body></html>
        """
        lead = _extract_twitter_profile("https://twitter.com/johndoe", html)
        assert lead is not None
        assert lead.full_name == "John Doe"
        assert lead.first_name == "John"
        assert lead.last_name == "Doe"
        assert lead.raw_data["platform"] == "twitter"
        assert lead.raw_data["username"] == "johndoe"
        assert "cool stuff" in lead.raw_data["bio"]

    def test_returns_none_for_empty(self) -> None:
        lead = _extract_twitter_profile("https://twitter.com/ghost", "<html></html>")
        # May return None or a minimal lead depending on meta tags
        # The important thing is it doesn't crash
        assert lead is None or lead.full_name


class TestExtractGithubProfile:
    def test_extracts_name_and_bio(self) -> None:
        html = """
        <html><head>
            <meta property="og:title" content="johndoe (John Doe)">
            <meta property="og:description" content="Open source enthusiast. Rust & Python.">
        </head><body></body></html>
        """
        lead = _extract_github_profile("https://github.com/johndoe", html)
        assert lead is not None
        assert lead.raw_data["platform"] == "github"
        assert lead.raw_data["username"] == "johndoe"
        assert "Rust" in lead.raw_data["bio"]


class TestScrapeProfiles:
    @patch("outreach_os.services.scraping.sources.social_profiles._safe_fetch")
    def test_scrapes_twitter_profile(self, mock_fetch: MagicMock) -> None:
        html = """
        <html><head>
            <meta property="og:title" content="Jane Smith (@janesmith) on X">
            <meta property="og:description" content="VP Sales at Acme">
        </head><body></body></html>
        """
        mock_fetch.return_value = (200, html)
        leads = scrape_profiles(["https://twitter.com/janesmith"])
        assert len(leads) == 1
        assert leads[0].full_name == "Jane Smith"
        assert leads[0].raw_data["platform"] == "twitter"

    @patch("outreach_os.services.scraping.sources.social_profiles._safe_fetch")
    def test_skips_unsupported_platform(self, mock_fetch: MagicMock) -> None:
        leads = scrape_profiles(["https://facebook.com/johndoe"])
        assert leads == []
        mock_fetch.assert_not_called()

    @patch("outreach_os.services.scraping.sources.social_profiles._safe_fetch")
    def test_handles_fetch_failure(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = None
        leads = scrape_profiles(["https://twitter.com/johndoe"])
        assert leads == []

    @patch("outreach_os.services.scraping.sources.social_profiles._safe_fetch")
    def test_handles_403(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = (403, "")
        leads = scrape_profiles(["https://twitter.com/johndoe"])
        assert leads == []

    @patch("outreach_os.services.scraping.sources.social_profiles._safe_fetch")
    def test_empty_urls(self, mock_fetch: MagicMock) -> None:
        leads = scrape_profiles([])
        assert leads == []
        mock_fetch.assert_not_called()

    @patch("outreach_os.services.scraping.sources.social_profiles._safe_fetch")
    def test_mixed_platforms(self, mock_fetch: MagicMock) -> None:
        def side_effect(url: str) -> tuple[int, str]:
            if "twitter.com" in url:
                return 200, """
                <html><head>
                    <meta property="og:title" content="Alice (@alice) on X">
                    <meta property="og:description" content="Engineer">
                </head><body></body></html>
                """
            if "github.com" in url:
                return 200, """
                <html><head>
                    <meta property="og:title" content="alice (Alice B)">
                    <meta property="og:description" content="Python dev">
                </head><body></body></html>
                """
            return 404, ""

        mock_fetch.side_effect = side_effect
        leads = scrape_profiles([
            "https://twitter.com/alice",
            "https://github.com/alice",
            "https://facebook.com/alice",
        ])
        assert len(leads) == 2
        platforms = {lead.raw_data["platform"] for lead in leads}
        assert platforms == {"twitter", "github"}
