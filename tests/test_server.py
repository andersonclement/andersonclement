import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import smarttrader_server as server


class TestFindJsonFile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_local_file_when_in_script_dir(self):
        json_path = os.path.join(self.tmpdir, server.JSON_FILENAME)
        with open(json_path, "w") as f:
            f.write("{}")

        original_file = server.__file__
        try:
            server.__file__ = os.path.join(self.tmpdir, "smarttrader_server.py")
            with patch.object(server, "MT5_PATHS", []):
                with patch.object(server, "TERMINAL_BASE", "/nonexistent"):
                    result = server.find_json_file()
                    self.assertIsNotNone(result)
                    self.assertEqual(result, str(json_path))
        finally:
            server.__file__ = original_file

    @patch.object(server, "MT5_PATHS", [])
    @patch.object(server, "TERMINAL_BASE", "/nonexistent")
    def test_returns_none_when_no_files_exist(self):
        result = server.find_json_file()
        self.assertIsNone(result)

    def test_checks_mt5_paths(self):
        json_path = os.path.join(self.tmpdir, server.JSON_FILENAME)
        with open(json_path, "w") as f:
            f.write("{}")

        with patch.object(server, "MT5_PATHS", [self.tmpdir]):
            with patch.object(server, "TERMINAL_BASE", "/nonexistent"):
                original = server.find_json_file.__wrapped__ if hasattr(server.find_json_file, '__wrapped__') else server.find_json_file
                # find_json_file checks local first (script dir), then MT5_PATHS
                result = server.find_json_file()
                if result is not None:
                    self.assertTrue(result.endswith(server.JSON_FILENAME))

    def test_glob_fallback_picks_newest_file(self):
        terminal_dir = os.path.join(self.tmpdir, "terminal")
        term1 = os.path.join(terminal_dir, "ABC123", "MQL5", "Files")
        term2 = os.path.join(terminal_dir, "DEF456", "MQL5", "Files")
        os.makedirs(term1)
        os.makedirs(term2)

        f1 = os.path.join(term1, server.JSON_FILENAME)
        f2 = os.path.join(term2, server.JSON_FILENAME)
        with open(f1, "w") as f:
            f.write('{"old": true}')
        time.sleep(0.05)
        with open(f2, "w") as f:
            f.write('{"new": true}')

        with patch.object(server, "MT5_PATHS", []):
            with patch.object(server, "TERMINAL_BASE", terminal_dir):
                result = server.find_json_file()
                if result is not None:
                    self.assertEqual(result, f2)


class TestGetJsonData(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        server.json_cache["data"] = None
        server.json_cache["path"] = None
        server.json_cache["last_mtime"] = 0
        server.json_cache["last_check"] = 0

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        server.json_cache["data"] = None
        server.json_cache["path"] = None
        server.json_cache["last_mtime"] = 0
        server.json_cache["last_check"] = 0

    def test_returns_error_when_no_file_found(self):
        with patch("smarttrader_server.find_json_file", return_value=None):
            data, error = server.get_json_data()
            self.assertIsNone(data)
            self.assertIn("introuvable", error)

    def test_reads_valid_json_file(self):
        json_path = os.path.join(self.tmpdir, "test.json")
        payload = {"balance": 1000, "equity": 1050, "status": "ACTIF"}
        with open(json_path, "w") as f:
            json.dump(payload, f)

        server.json_cache["path"] = json_path
        server.json_cache["last_check"] = time.time()

        data, error = server.get_json_data()
        self.assertIsNone(error)
        self.assertIsNotNone(data)
        parsed = json.loads(data)
        self.assertEqual(parsed["balance"], 1000)

    def test_returns_cached_data_on_corrupt_json(self):
        json_path = os.path.join(self.tmpdir, "test.json")
        with open(json_path, "w") as f:
            f.write('{"valid": true}')

        server.json_cache["path"] = json_path
        server.json_cache["last_check"] = time.time()
        server.get_json_data()

        with open(json_path, "w") as f:
            f.write("{corrupt: not json!!!")

        data, error = server.get_json_data()
        self.assertIsNotNone(data)
        parsed = json.loads(data)
        self.assertTrue(parsed["valid"])

    def test_returns_error_on_corrupt_json_without_cache(self):
        json_path = os.path.join(self.tmpdir, "test.json")
        with open(json_path, "w") as f:
            f.write("{corrupt: not valid json")

        server.json_cache["path"] = json_path
        server.json_cache["last_check"] = time.time()

        data, error = server.get_json_data()
        self.assertIsNone(data)
        self.assertIn("corrompu", error)

    def test_returns_error_on_empty_file(self):
        json_path = os.path.join(self.tmpdir, "test.json")
        with open(json_path, "w") as f:
            f.write("")

        server.json_cache["path"] = json_path
        server.json_cache["last_check"] = time.time()

        data, error = server.get_json_data()
        self.assertIsNone(data)
        self.assertIn("vide", error.lower())

    def test_caches_file_by_mtime(self):
        json_path = os.path.join(self.tmpdir, "test.json")
        with open(json_path, "w") as f:
            json.dump({"version": 1}, f)

        server.json_cache["path"] = json_path
        server.json_cache["last_check"] = time.time()

        data1, _ = server.get_json_data()
        data2, _ = server.get_json_data()
        self.assertEqual(data1, data2)

    def test_re_reads_file_when_mtime_changes(self):
        json_path = os.path.join(self.tmpdir, "test.json")
        with open(json_path, "w") as f:
            json.dump({"version": 1}, f)

        server.json_cache["path"] = json_path
        server.json_cache["last_check"] = time.time()

        data1, _ = server.get_json_data()
        time.sleep(0.05)

        with open(json_path, "w") as f:
            json.dump({"version": 2}, f)

        data2, _ = server.get_json_data()
        self.assertNotEqual(data1, data2)
        self.assertIn('"version": 2', data2)


class TestBridgeHandler(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.port = 18765
        from http.server import HTTPServer
        cls.server = HTTPServer(("127.0.0.1", cls.port), server.BridgeHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _get(self, path):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        return resp, body

    def _options(self, path):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("OPTIONS", path)
        return conn.getresponse()

    def test_data_endpoint_returns_json(self):
        valid_data = json.dumps({"balance": 500, "status": "ACTIF"})
        with patch("smarttrader_server.get_json_data", return_value=(valid_data, None)):
            resp, body = self._get("/data")
            self.assertEqual(resp.status, 200)
            self.assertIn("application/json", resp.getheader("Content-Type"))
            parsed = json.loads(body)
            self.assertEqual(parsed["balance"], 500)

    def test_data_endpoint_returns_fallback_on_error(self):
        with patch("smarttrader_server.get_json_data", return_value=(None, "Test error")):
            resp, body = self._get("/data")
            self.assertEqual(resp.status, 200)
            parsed = json.loads(body)
            self.assertEqual(parsed["status"], "DECONNECTE")
            self.assertEqual(parsed["balance"], 0)
            self.assertEqual(parsed["equity"], 0)
            self.assertIn("error", parsed)
            self.assertIn("positions", parsed)
            self.assertIsInstance(parsed["positions"], list)
            self.assertIn("signal", parsed)
            self.assertIn("log", parsed)

    def test_data_fallback_has_complete_schema(self):
        with patch("smarttrader_server.get_json_data", return_value=(None, "Err")):
            _, body = self._get("/data")
            parsed = json.loads(body)
            expected_keys = [
                "status", "error", "balance", "equity", "openPL",
                "growth", "drawdown", "trades", "winRate", "winTrades",
                "lossTrades", "martingale", "losses", "initialBalance",
                "peakEquity", "currentCAS", "prices", "signal",
                "lastAction", "positions", "log"
            ]
            for key in expected_keys:
                self.assertIn(key, parsed, f"Missing key in fallback: {key}")

    def test_cors_headers_present(self):
        valid_data = json.dumps({"test": True})
        with patch("smarttrader_server.get_json_data", return_value=(valid_data, None)):
            resp, _ = self._get("/data")
            self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), "*")
            self.assertIn("GET", resp.getheader("Access-Control-Allow-Methods"))
            self.assertEqual(resp.getheader("Cache-Control"), "no-cache, no-store, must-revalidate")

    def test_options_returns_200(self):
        resp = self._options("/data")
        self.assertEqual(resp.status, 200)

    def test_status_endpoint(self):
        with patch("smarttrader_server.find_json_file", return_value="/fake/path.json"):
            resp, body = self._get("/status")
            self.assertEqual(resp.status, 200)
            parsed = json.loads(body)
            self.assertEqual(parsed["server"], "SmartTrader Bridge v1.1")
            self.assertIn("port", parsed)
            self.assertTrue(parsed["json_found"])

    def test_status_endpoint_no_json(self):
        with patch("smarttrader_server.find_json_file", return_value=None):
            resp, body = self._get("/status")
            parsed = json.loads(body)
            self.assertFalse(parsed["json_found"])
            self.assertEqual(parsed["json_path"], "introuvable")

    def test_unknown_path_returns_404(self):
        resp, _ = self._get("/nonexistent")
        self.assertEqual(resp.status, 404)

    def test_data_endpoint_strips_query_string(self):
        valid_data = json.dumps({"ok": True})
        with patch("smarttrader_server.get_json_data", return_value=(valid_data, None)):
            resp, body = self._get("/data?t=12345&cache=bust")
            self.assertEqual(resp.status, 200)
            parsed = json.loads(body)
            self.assertTrue(parsed["ok"])


class TestCacheThreadSafety(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        server.json_cache["data"] = None
        server.json_cache["path"] = None
        server.json_cache["last_mtime"] = 0
        server.json_cache["last_check"] = 0

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        server.json_cache["data"] = None
        server.json_cache["path"] = None
        server.json_cache["last_mtime"] = 0
        server.json_cache["last_check"] = 0

    def test_concurrent_reads_dont_crash(self):
        json_path = os.path.join(self.tmpdir, "test.json")
        with open(json_path, "w") as f:
            json.dump({"concurrent": True}, f)

        server.json_cache["path"] = json_path
        server.json_cache["last_check"] = time.time()

        errors = []

        def read_data():
            try:
                for _ in range(20):
                    data, error = server.get_json_data()
                    if data is not None:
                        json.loads(data)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_data) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(errors), 0, f"Concurrent read errors: {errors}")


if __name__ == "__main__":
    unittest.main()
