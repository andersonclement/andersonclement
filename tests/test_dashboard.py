"""Dashboard integration tests using Playwright.

Spins up a mock HTTP server that serves known JSON payloads on /data,
then loads the dashboard HTML in a real browser and verifies DOM rendering.
"""

import json
import os
import threading
import time
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import playwright.sync_api as pw

DASHBOARD_PATH = Path(__file__).parent.parent / "SmartTrader_Dashboard.html"

MOCK_DATA_ACTIVE = {
    "status": "ACTIF",
    "balance": 10250.50,
    "equity": 10300.00,
    "openPL": 49.50,
    "growth": 2.50,
    "drawdown": 0.85,
    "trades": 5,
    "winRate": 60.0,
    "winTrades": 3,
    "lossTrades": 2,
    "martingale": "Normal",
    "losses": 0,
    "currentCAS": "CAS1_TENDANCE",
    "initialBalance": 10000.00,
    "peakEquity": 10350.00,
    "prices": {
        "XAUUSDm": {
            "price": 2345.67,
            "change": 12.50,
            "cas": "CAS1_TENDANCE",
            "history": [2340.0, 2341.5, 2343.0, 2345.67],
        },
        "XAGUSDm": {
            "price": 29.45,
            "change": -0.12,
            "cas": "CAS3_RANGE",
            "history": [29.50, 29.48, 29.46, 29.45],
        },
    },
    "signal": {
        "asset": "XAUUSDm",
        "type": "BUY",
        "score": 85,
        "cas": "CAS1_TENDANCE",
        "reasons": [
            {"ok": True, "text": "EMA alignees haussiere"},
            {"ok": True, "text": "ADX confirme tendance"},
            {"ok": False, "text": "RSI neutre"},
        ],
    },
    "lastAction": "OUVERT BUY CAS1 XAUUSDm lot=0.05 SL=2320.00 TP=2380.00",
    "positions": [
        {
            "asset": "XAUUSDm",
            "dir": "BUY",
            "type": "CAS1_TENDANCE BUY",
            "lot": 0.05,
            "entry": 2340.00,
            "sl": 2320.00,
            "tp": 2380.00,
            "pl": 5.67,
        }
    ],
    "log": [
        {"time": "14:30:00", "type": "INFO", "msg": "SmartTrader initialise"},
        {"time": "14:30:05", "type": "BUY", "msg": "CAS1 TENDANCE BUY XAUUSDm"},
    ],
}

MOCK_DATA_DISCONNECTED = {
    "status": "DECONNECTE",
    "error": "Fichier introuvable",
    "balance": 0,
    "equity": 0,
    "openPL": 0,
    "growth": 0,
    "drawdown": 0,
    "trades": 0,
    "winRate": 0,
    "winTrades": 0,
    "lossTrades": 0,
    "martingale": "Normal",
    "losses": 0,
    "initialBalance": 0,
    "peakEquity": 0,
    "currentCAS": "—",
    "prices": {},
    "signal": {"asset": "—", "type": "ATTENTE", "score": 0, "reasons": []},
    "lastAction": "",
    "positions": [],
    "log": [{"time": "14:30:00", "type": "WARN", "msg": "Pas de donnees"}],
}

MOCK_DATA_XSS = {
    "status": "ACTIF",
    "balance": 100,
    "equity": 100,
    "openPL": 0,
    "growth": 0,
    "drawdown": 0,
    "trades": 1,
    "winRate": 0,
    "winTrades": 0,
    "lossTrades": 0,
    "martingale": "Normal",
    "losses": 0,
    "currentCAS": "CAS1_TENDANCE",
    "initialBalance": 100,
    "peakEquity": 100,
    "prices": {},
    "signal": {
        "asset": '<img src=x onerror=alert(1)>',
        "type": "BUY",
        "score": 50,
        "cas": "CAS1",
        "reasons": [
            {"ok": True, "text": '<script>alert("xss")</script>'},
        ],
    },
    "lastAction": '<img src=x onerror=alert("xss")>',
    "positions": [
        {
            "asset": '<script>alert(1)</script>',
            "dir": "BUY",
            "type": '<img onerror=alert(1) src=x>',
            "lot": 0.01,
            "entry": 100,
            "sl": 90,
            "tp": 110,
            "pl": 0,
        }
    ],
    "log": [
        {"time": "00:00:00", "type": "INFO", "msg": '<script>alert("log")</script>'},
    ],
}


class MockDataServer:
    """HTTP server that serves mock JSON data on a given port."""

    def __init__(self, data, port=8765):
        self.data = data
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        data_json = json.dumps(self.data)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner_self):
                body = data_json.encode("utf-8")
                inner_self.send_response(200)
                inner_self.send_header("Content-Type", "application/json")
                inner_self.send_header("Access-Control-Allow-Origin", "*")
                inner_self.send_header("Content-Length", len(body))
                inner_self.end_headers()
                inner_self.wfile.write(body)

            def log_message(inner_self, format, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", self.port), Handler)
        self.server.allow_reuse_address = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()

    def update_data(self, data):
        self.data = data


class TestDashboardRendering(unittest.TestCase):

    PORT = 18701

    @classmethod
    def setUpClass(cls):
        cls.mock_server = MockDataServer(MOCK_DATA_ACTIVE, port=cls.PORT)
        cls.mock_server.start()
        time.sleep(0.3)

        cls.pw = pw.sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(
            headless=True,
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.mock_server.stop()

    def _load_dashboard(self, wait_ms=2500):
        page = self.browser.new_page()
        port = self.PORT
        page.route("**/localhost:8765/**", lambda route: route.fulfill(
            status=301,
            headers={"Location": route.request.url.replace("localhost:8765", f"localhost:{port}")}
        ) if False else route.continue_(url=route.request.url.replace("localhost:8765", f"localhost:{port}")))
        page.goto(f"file://{DASHBOARD_PATH.resolve()}")
        page.wait_for_timeout(wait_ms)
        return page

    def test_balance_renders_correctly(self):
        page = self._load_dashboard()
        try:
            text = page.locator("#balance").text_content()
            self.assertIn("10250", text)
        finally:
            page.close()

    def test_equity_renders_correctly(self):
        page = self._load_dashboard()
        try:
            text = page.locator("#equity").text_content()
            self.assertIn("10300", text)
        finally:
            page.close()

    def test_growth_percentage_shown(self):
        page = self._load_dashboard()
        try:
            text = page.locator("#growth").text_content()
            self.assertIn("2.50", text)
        finally:
            page.close()

    def test_drawdown_shown(self):
        page = self._load_dashboard()
        try:
            text = page.locator("#ddMetric").text_content()
            self.assertIn("0.85", text)
        finally:
            page.close()

    def test_status_pill_shows_active(self):
        page = self._load_dashboard()
        try:
            text = page.locator("#statusText").text_content()
            self.assertEqual(text, "ACTIF")
            pill = page.locator("#statusPill")
            cls = pill.get_attribute("class")
            self.assertIn("sp-active", cls)
        finally:
            page.close()

    def test_positions_table_populated(self):
        page = self._load_dashboard()
        try:
            text = page.locator("#posCount").text_content()
            self.assertIn("1", text)
            rows = page.locator("#posBody tr")
            self.assertGreaterEqual(rows.count(), 1)
            first_row = rows.nth(0).text_content()
            self.assertIn("XAUUSDm", first_row)
            self.assertIn("BUY", first_row)
        finally:
            page.close()

    def test_signal_asset_and_type(self):
        page = self._load_dashboard()
        try:
            asset = page.locator("#sigAsset").text_content()
            self.assertIn("XAUUSDm", asset)
            sig_type = page.locator("#sigType").text_content()
            self.assertEqual(sig_type, "BUY")
        finally:
            page.close()

    def test_signal_score_displayed(self):
        page = self._load_dashboard()
        try:
            score = page.locator("#sigScore").text_content()
            self.assertIn("85", score)
        finally:
            page.close()

    def test_signal_reasons_rendered(self):
        page = self._load_dashboard()
        try:
            reasons = page.locator("#reasonsList .reason")
            self.assertEqual(reasons.count(), 3)
        finally:
            page.close()

    def test_cas_metric_shown(self):
        page = self._load_dashboard()
        try:
            text = page.locator("#casMetric").text_content()
            self.assertIn("CAS1", text)
        finally:
            page.close()

    def test_win_rate_displayed(self):
        page = self._load_dashboard()
        try:
            text = page.locator("#winRate").text_content()
            self.assertIn("60", text)
        finally:
            page.close()

    def test_log_entries_rendered(self):
        page = self._load_dashboard()
        try:
            log = page.locator("#miniLog .log-entry")
            self.assertGreaterEqual(log.count(), 1)
        finally:
            page.close()

    def test_real_time_prices_shown(self):
        page = self._load_dashboard()
        try:
            xau = page.locator("#rXAU").text_content()
            self.assertIn("2345", xau)
        finally:
            page.close()

    def test_tab_switching(self):
        page = self._load_dashboard()
        try:
            stats_tab = page.locator(".tb-tab", has_text="Statistiques")
            stats_tab.click()
            page.wait_for_timeout(300)
            stats_panel = page.locator("#tab-stats")
            self.assertTrue(stats_panel.is_visible())
            dashboard_panel = page.locator("#tab-dashboard")
            self.assertFalse(dashboard_panel.is_visible())
        finally:
            page.close()

    def test_clock_updates(self):
        page = self._load_dashboard()
        try:
            clock = page.locator("#clockDisplay").text_content()
            self.assertNotEqual(clock, "--:--:--")
            self.assertIn(":", clock)
        finally:
            page.close()


class TestDashboardDisconnected(unittest.TestCase):

    PORT = 18702

    @classmethod
    def setUpClass(cls):
        cls.mock_server = MockDataServer(MOCK_DATA_DISCONNECTED, port=cls.PORT)
        cls.mock_server.start()
        time.sleep(0.3)

        cls.pw = pw.sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(
            headless=True,
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.mock_server.stop()

    def _load(self, wait_ms=2500):
        page = self.browser.new_page()
        port = self.PORT
        page.route("**/localhost:8765/**", lambda route: route.continue_(
            url=route.request.url.replace("localhost:8765", f"localhost:{port}")))
        page.goto(f"file://{DASHBOARD_PATH.resolve()}")
        page.wait_for_timeout(wait_ms)
        return page

    def test_balance_shows_zero(self):
        page = self._load()
        try:
            text = page.locator("#balance").text_content()
            self.assertIn("0", text)
        finally:
            page.close()

    def test_no_positions_shown(self):
        page = self._load()
        try:
            text = page.locator("#posBody").text_content()
            self.assertIn("Aucune position", text)
        finally:
            page.close()

    def test_signal_shows_waiting(self):
        page = self._load()
        try:
            sig = page.locator("#sigType").text_content()
            self.assertIn("ATTENTE", sig)
        finally:
            page.close()


class TestDashboardXSS(unittest.TestCase):

    PORT = 18703

    @classmethod
    def setUpClass(cls):
        cls.mock_server = MockDataServer(MOCK_DATA_XSS, port=cls.PORT)
        cls.mock_server.start()
        time.sleep(0.3)

        cls.pw = pw.sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(
            headless=True,
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.mock_server.stop()

    def _load_xss(self, wait_ms=2500):
        page = self.browser.new_page()
        port = self.PORT
        page.route("**/localhost:8765/**", lambda route: route.continue_(
            url=route.request.url.replace("localhost:8765", f"localhost:{port}")))
        page.goto(f"file://{DASHBOARD_PATH.resolve()}")
        page.wait_for_timeout(wait_ms)
        return page

    def test_xss_in_signal_asset_is_escaped(self):
        page = self._load_xss()
        try:
            alerts_fired = page.evaluate("window.__xss_fired || false")
            self.assertFalse(alerts_fired)

            asset_html = page.locator("#sigAsset").inner_html()
            self.assertNotIn("<img", asset_html.lower())
            self.assertNotIn("<script", asset_html.lower())
        finally:
            page.close()

    def test_xss_in_positions_table_is_escaped(self):
        page = self._load_xss()
        try:
            table_html = page.locator("#posBody").inner_html()
            self.assertNotIn("<img", table_html)
            self.assertNotIn("<script", table_html)
            alerts_fired = page.evaluate("window.__xss_fired || false")
            self.assertFalse(alerts_fired)
        finally:
            page.close()

    def test_xss_in_log_is_escaped(self):
        page = self._load_xss()
        try:
            log_html = page.locator("#miniLog").inner_html()
            self.assertNotIn("<script", log_html.lower())
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
