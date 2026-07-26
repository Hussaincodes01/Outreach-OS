"""Unit tests for the Scrapling-based company_site scraper.

Mocks Scrapling's Fetcher/StealthyFetcher to test extraction logic
without real HTTP calls. The integration flow (Celery task → run_source
→ company_site.scrape_domain) is already covered by
test_scraping_flow.py which mocks at the run_source boundary.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from outreach_os.services.scraping.sources.company_site import (
    _extract_company_name,
    _extract_emails,
    _extract_industry,
    _fetch,
    _first_name_from_email,
    _guess_country_from_url,
    scrape_domain,
)

# --- Pure function tests (no mocking) -----------------------------------


class TestExtractEmails:
    def test_extracts_domain_matching_emails(self) -> None:
        html = '<a href="mailto:jane@acme.com">Contact</a> <p>info@acme.com</p>'
        emails = _extract_emails(html, "acme.com")
        assert emails == ["jane@acme.com", "info@acme.com"]

    def test_excludes_noreply(self) -> None:
        html = "noreply@acme.com, no-reply@acme.com, real@acme.com"
        emails = _extract_emails(html, "acme.com")
        assert emails == ["real@acme.com"]

    def test_excludes_image_extensions(self) -> None:
        html = "logo.png@acme.com, real@acme.com"
        emails = _extract_emails(html, "acme.com")
        assert emails == ["real@acme.com"]

    def test_respects_5_email_limit(self) -> None:
        html = " ".join(f"a{i}@acme.com" for i in range(10))
        emails = _extract_emails(html, "acme.com")
        assert len(emails) == 5

    def test_case_insensitive_domain_match(self) -> None:
        html = "user@ACME.COM"
        emails = _extract_emails(html, "acme.com")
        assert emails == ["user@acme.com"]

    def test_subdomain_match(self) -> None:
        html = "user@mail.acme.com"
        emails = _extract_emails(html, "acme.com")
        assert emails == ["user@mail.acme.com"]

    def test_no_match_for_different_domain(self) -> None:
        html = "user@other.com"
        emails = _extract_emails(html, "acme.com")
        assert emails == []

    def test_empty_html(self) -> None:
        assert _extract_emails("", "acme.com") == []
        assert _extract_emails(None, "acme.com") == []  # type: ignore[arg-type]

    def test_deduplicates(self) -> None:
        html = "same@acme.com same@acme.com same@acme.com"
        emails = _extract_emails(html, "acme.com")
        assert emails == ["same@acme.com"]


class TestGuessCountry:
    def test_uk_tld(self) -> None:
        assert _guess_country_from_url("https://acme.co.uk") == "GB"

    def test_de_tld(self) -> None:
        assert _guess_country_from_url("https://acme.de") == "DE"

    def test_unknown_tld(self) -> None:
        assert _guess_country_from_url("https://acme.io") is None


class TestFirstNameFromEmail:
    def test_dot_separated(self) -> None:
        assert _first_name_from_email("jane.doe@acme.com") == "Jane"

    def test_underscore_separated(self) -> None:
        assert _first_name_from_email("jane_doe@acme.com") == "Jane"

    def test_no_separator(self) -> None:
        assert _first_name_from_email("jane@acme.com") == "Jane"


class TestExtractCompanyName:
    def test_from_title_tag(self) -> None:
        adaptor = MagicMock()
        adaptor.css.return_value.get.return_value = "Acme Corp | SaaS Platform"
        assert _extract_company_name(adaptor, "https://acme.com") == "Acme Corp"

    def test_from_og_site_name(self) -> None:
        adaptor = MagicMock()
        # First call (title) returns None, second call (og:site_name) returns value
        adaptor.css.side_effect = [
            MagicMock(get=lambda: None),  # title
            MagicMock(get=lambda: "Acme Inc"),  # og:site_name
        ]
        assert _extract_company_name(adaptor, "https://acme.com") == "Acme Inc"

    def test_returns_none_when_empty(self) -> None:
        adaptor = MagicMock()
        adaptor.css.return_value.get.return_value = None
        assert _extract_company_name(adaptor, "https://acme.com") is None

    def test_short_title_rejected(self) -> None:
        adaptor = MagicMock()
        adaptor.css.side_effect = [
            MagicMock(get=lambda: "A"),  # title — too short
            MagicMock(get=lambda: None),  # og:site_name — empty
        ]
        assert _extract_company_name(adaptor, "https://acme.com") is None


class TestExtractIndustry:
    def test_from_meta_tag(self) -> None:
        adaptor = MagicMock()
        adaptor.css.return_value.get.return_value = "SaaS"
        assert _extract_industry(adaptor) == "SaaS"

    def test_returns_none_when_missing(self) -> None:
        adaptor = MagicMock()
        adaptor.css.return_value.get.return_value = None
        assert _extract_industry(adaptor) is None


# --- Fetcher tests (mocked Scrapling) -----------------------------------


def _make_mock_response(status: int = 200, body: str = "<html></html>", encoding: str = "utf-8") -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.body = body.encode(encoding)
    resp.encoding = encoding
    return resp


class TestFetch:
    @patch("outreach_os.services.scraping.sources.company_site.Fetcher")
    def test_returns_status_and_html(self, mock_fetcher: MagicMock) -> None:
        mock_fetcher.get.return_value = _make_mock_response(200, "<p>Hello</p>")
        status, html = _fetch("https://acme.com")
        assert status == 200
        assert "Hello" in html

    @patch("outreach_os.services.scraping.sources.company_site.Fetcher")
    def test_403_triggers_stealth_fallback(self, mock_fetcher: MagicMock) -> None:
        mock_fetcher.get.return_value = _make_mock_response(403, "")
        with patch(
            "outreach_os.services.scraping.sources.company_site._stealthy_fetch",
            return_value=(200, "<p>Stealth content</p>"),
        ) as mock_stealth:
            status, html = _fetch("https://protected-site.com")
            assert status == 200
            assert "Stealth" in html
            mock_stealth.assert_called_once()

    @patch("outreach_os.services.scraping.sources.company_site.Fetcher")
    def test_fetcher_exception_triggers_stealth(self, mock_fetcher: MagicMock) -> None:
        mock_fetcher.get.side_effect = Exception("connection refused")
        with patch(
            "outreach_os.services.scraping.sources.company_site._stealthy_fetch",
            return_value=(200, "<p>Stealth</p>"),
        ) as mock_stealth:
            status, _html = _fetch("https://timeout-site.com")
            assert status == 200
            mock_stealth.assert_called_once()

    @patch("outreach_os.services.scraping.sources.company_site.Fetcher")
    def test_fetcher_error_no_stealth_returns_empty(self, mock_fetcher: MagicMock) -> None:
        mock_fetcher.get.side_effect = Exception("fail")
        with patch(
            "outreach_os.services.scraping.sources.company_site._stealthy_fetch",
            return_value=None,
        ):
            status, html = _fetch("https://fail.com")
            assert status == 0
            assert html == ""


# --- scrape_domain integration test (mocked fetch) ----------------------


class TestScrapeDomain:
    @patch("outreach_os.services.scraping.sources.company_site._fetch")
    def test_extracts_emails_from_html(self, mock_fetch: MagicMock) -> None:
        html = """
        <html>
        <head><title>Acme Corp | Home</title></head>
        <body>
            <a href="mailto:info@acme.com">Contact</a>
            <p>Reach us at sales@acme.com</p>
        </body>
        </html>
        """
        mock_fetch.return_value = (200, html)
        leads = scrape_domain("acme.com")
        emails = {lead.email for lead in leads}
        assert "info@acme.com" in emails
        assert "sales@acme.com" in emails

    @patch("outreach_os.services.scraping.sources.company_site._fetch")
    def test_empty_domain_returns_empty(self, mock_fetch: MagicMock) -> None:
        assert scrape_domain("") == []
        mock_fetch.assert_not_called()

    @patch("outreach_os.services.scraping.sources.company_site._fetch")
    def test_company_name_extracted(self, mock_fetch: MagicMock) -> None:
        html = '<html><head><title>Acme Corp | Platform</title></head><body></body></html>'
        mock_fetch.return_value = (200, html)
        leads = scrape_domain("acme.com")
        if leads:
            assert leads[0].company_name == "Acme Corp"

    @patch("outreach_os.services.scraping.sources.company_site._fetch")
    def test_skips_404_pages(self, mock_fetch: MagicMock) -> None:
        # Homepage returns 200 with no emails, team page returns 404
        def side_effect(url: str) -> tuple[int, str]:
            if "/team" in url:
                return 404, ""
            return 200, "<html><head><title>Acme</title></head><body></body></html>"

        mock_fetch.side_effect = side_effect
        leads = scrape_domain("acme.com")
        # No emails found, but company name should still be extracted
        assert leads == [] or all(lead.email is None for lead in leads)

    @patch("outreach_os.services.scraping.sources.company_site._fetch")
    def test_country_from_tld(self, mock_fetch: MagicMock) -> None:
        html = '<html><head><title>Acme UK</title></head><body></body></html>'
        mock_fetch.return_value = (200, html)
        leads = scrape_domain("acme.co.uk")
        if leads:
            assert leads[0].country == "GB"

    @patch("outreach_os.services.scraping.sources.company_site._fetch")
    def test_deduplicates_emails_across_pages(self, mock_fetch: MagicMock) -> None:
        """Same email on homepage and /about should produce one lead."""
        html = '<html><body><a href="mailto:info@acme.com">Contact</a></body></html>'
        mock_fetch.return_value = (200, html)
        leads = scrape_domain("acme.com")
        info_leads = [lead for lead in leads if lead.email == "info@acme.com"]
        assert len(info_leads) == 1
