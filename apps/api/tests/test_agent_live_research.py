"""Unit tests for the live website research feature.

Tests scrape_live_context (services/scraping/live_research.py) which
fetches a lead's homepage and extracts context for the agent draft node.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from outreach_os.services.scraping.live_research import scrape_live_context


class TestScrapeLiveContext:
    def test_returns_empty_for_no_domain(self) -> None:
        assert scrape_live_context(None) == ""
        assert scrape_live_context("") == ""

    @patch("outreach_os.services.scraping.live_research.get_settings")
    def test_returns_empty_when_disabled(self, mock_settings: MagicMock) -> None:
        mock_settings.return_value.scraping_live_research_enabled = False
        assert scrape_live_context("acme.com") == ""

    @patch("outreach_os.services.scraping.live_research._fetch")
    @patch("outreach_os.services.scraping.live_research.get_settings")
    def test_extracts_title_and_description(self, mock_settings: MagicMock, mock_fetch: MagicMock) -> None:
        mock_settings.return_value.scraping_live_research_enabled = True
        mock_settings.return_value.scraping_live_research_max_chars = 2000
        html = """
        <html>
        <head>
            <title>Acme Corp | Building the Future</title>
            <meta name="description" content="Acme Corp builds AI tools for enterprises.">
        </head>
        <body>
            <h1>Welcome to Acme</h1>
            <p>We make great products.</p>
        </body>
        </html>
        """
        mock_fetch.return_value = (200, html)
        result = scrape_live_context("acme.com")
        assert "Acme Corp" in result
        assert "AI tools" in result

    @patch("outreach_os.services.scraping.live_research._fetch")
    @patch("outreach_os.services.scraping.live_research.get_settings")
    def test_returns_empty_on_fetch_failure(self, mock_settings: MagicMock, mock_fetch: MagicMock) -> None:
        mock_settings.return_value.scraping_live_research_enabled = True
        mock_settings.return_value.scraping_live_research_max_chars = 2000
        mock_fetch.return_value = (0, "")
        assert scrape_live_context("acme.com") == ""

    @patch("outreach_os.services.scraping.live_research._fetch")
    @patch("outreach_os.services.scraping.live_research.get_settings")
    def test_returns_empty_on_403(self, mock_settings: MagicMock, mock_fetch: MagicMock) -> None:
        mock_settings.return_value.scraping_live_research_enabled = True
        mock_settings.return_value.scraping_live_research_max_chars = 2000
        mock_fetch.return_value = (403, "")
        assert scrape_live_context("acme.com") == ""

    @patch("outreach_os.services.scraping.live_research._fetch")
    @patch("outreach_os.services.scraping.live_research.get_settings")
    def test_truncates_to_max_chars(self, mock_settings: MagicMock, mock_fetch: MagicMock) -> None:
        mock_settings.return_value.scraping_live_research_enabled = True
        mock_settings.return_value.scraping_live_research_max_chars = 50
        html = "<html><head><title>Long Title Here</title></head><body><p>Hello</p></body></html>"
        mock_fetch.return_value = (200, html)
        result = scrape_live_context("acme.com")
        assert len(result) <= 50

    @patch("outreach_os.services.scraping.live_research._fetch")
    @patch("outreach_os.services.scraping.live_research.get_settings")
    def test_exception_does_not_raise(self, mock_settings: MagicMock, mock_fetch: MagicMock) -> None:
        mock_settings.return_value.scraping_live_research_enabled = True
        mock_settings.return_value.scraping_live_research_max_chars = 2000
        mock_fetch.side_effect = Exception("network error")
        assert scrape_live_context("acme.com") == ""
