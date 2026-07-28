import json
import unittest

EXPECTED_SCHEMA = {
    "status": str,
    "balance": (int, float),
    "equity": (int, float),
    "openPL": (int, float),
    "growth": (int, float),
    "drawdown": (int, float),
    "trades": int,
    "winRate": (int, float),
    "winTrades": int,
    "lossTrades": int,
    "martingale": str,
    "losses": int,
    "currentCAS": str,
    "initialBalance": (int, float),
    "peakEquity": (int, float),
    "prices": dict,
    "signal": dict,
    "lastAction": str,
    "positions": list,
    "log": list,
}

SIGNAL_SCHEMA = {
    "asset": str,
    "type": str,
    "score": (int, float),
    "reasons": list,
}

POSITION_SCHEMA = {
    "asset": str,
    "dir": str,
    "type": str,
    "lot": (int, float),
    "entry": (int, float),
    "sl": (int, float),
    "tp": (int, float),
    "pl": (int, float),
}

PRICE_ENTRY_SCHEMA = {
    "price": (int, float),
    "change": (int, float),
    "cas": str,
    "history": list,
}

LOG_ENTRY_SCHEMA = {
    "time": str,
    "type": str,
    "msg": str,
}

SAMPLE_FULL_DATA = {
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
        }
    },
    "signal": {
        "asset": "XAUUSDm",
        "type": "BUY",
        "score": 85,
        "cas": "CAS1_TENDANCE",
        "reasons": [
            {"ok": True, "text": "EMA alignees"},
            {"ok": True, "text": "ADX confirme"},
            {"ok": False, "text": "RSI neutre"},
        ],
    },
    "lastAction": "OUVERT BUY CAS1_TENDANCE XAUUSDm lot=0.05",
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
        {"time": "14:30:05", "type": "BUY", "msg": "CAS1 BUY XAUUSDm"},
    ],
}

SAMPLE_DISCONNECTED = {
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


def validate_schema(data, schema, path="root"):
    errors = []
    for key, expected_type in schema.items():
        if key not in data:
            errors.append(f"{path}.{key}: missing")
            continue
        if isinstance(expected_type, tuple):
            if not isinstance(data[key], expected_type):
                errors.append(
                    f"{path}.{key}: expected {expected_type}, got {type(data[key])}"
                )
        else:
            if not isinstance(data[key], expected_type):
                errors.append(
                    f"{path}.{key}: expected {expected_type.__name__}, got {type(data[key]).__name__}"
                )
    return errors


class TestJsonContract(unittest.TestCase):

    def test_full_data_conforms_to_schema(self):
        errors = validate_schema(SAMPLE_FULL_DATA, EXPECTED_SCHEMA)
        self.assertEqual(errors, [], f"Schema violations: {errors}")

    def test_disconnected_data_conforms_to_schema(self):
        errors = validate_schema(SAMPLE_DISCONNECTED, EXPECTED_SCHEMA)
        self.assertEqual(errors, [], f"Schema violations: {errors}")

    def test_signal_schema(self):
        errors = validate_schema(SAMPLE_FULL_DATA["signal"], SIGNAL_SCHEMA, "signal")
        self.assertEqual(errors, [], f"Signal schema violations: {errors}")

    def test_position_schema(self):
        for i, pos in enumerate(SAMPLE_FULL_DATA["positions"]):
            errors = validate_schema(pos, POSITION_SCHEMA, f"positions[{i}]")
            self.assertEqual(errors, [], f"Position schema violations: {errors}")

    def test_price_entry_schema(self):
        for sym, entry in SAMPLE_FULL_DATA["prices"].items():
            errors = validate_schema(entry, PRICE_ENTRY_SCHEMA, f"prices.{sym}")
            self.assertEqual(errors, [], f"Price schema violations: {errors}")

    def test_log_entry_schema(self):
        for i, entry in enumerate(SAMPLE_FULL_DATA["log"]):
            errors = validate_schema(entry, LOG_ENTRY_SCHEMA, f"log[{i}]")
            self.assertEqual(errors, [], f"Log schema violations: {errors}")

    def test_signal_reasons_have_ok_and_text(self):
        for i, reason in enumerate(SAMPLE_FULL_DATA["signal"]["reasons"]):
            self.assertIn("ok", reason, f"reason[{i}] missing 'ok'")
            self.assertIn("text", reason, f"reason[{i}] missing 'text'")
            self.assertIsInstance(reason["ok"], bool)
            self.assertIsInstance(reason["text"], str)

    def test_valid_status_values(self):
        valid_statuses = {"ACTIF", "ARRETE", "PAUSE", "HORS HEURES", "DECONNECTE"}
        self.assertIn(SAMPLE_FULL_DATA["status"], valid_statuses)
        self.assertIn(SAMPLE_DISCONNECTED["status"], valid_statuses)

    def test_valid_signal_types(self):
        valid_types = {"BUY", "SELL", "ATTENTE"}
        self.assertIn(SAMPLE_FULL_DATA["signal"]["type"], valid_types)
        self.assertIn(SAMPLE_DISCONNECTED["signal"]["type"], valid_types)

    def test_valid_cas_names(self):
        valid_cas = {
            "CAS1_TENDANCE", "CAS2_SCALPING", "CAS2_SCALPING_M5",
            "CAS3_RANGE", "CAS4_CASSURE", "CAS5_SMC",
            "CAS6_RETOURNEMENT", "CAS7_FIBONACCI", "—",
        }
        self.assertIn(SAMPLE_FULL_DATA["currentCAS"], valid_cas)

    def test_position_direction_values(self):
        for pos in SAMPLE_FULL_DATA["positions"]:
            self.assertIn(pos["dir"], {"BUY", "SELL"})

    def test_numeric_fields_not_negative_where_inappropriate(self):
        d = SAMPLE_FULL_DATA
        self.assertGreaterEqual(d["balance"], 0)
        self.assertGreaterEqual(d["trades"], 0)
        self.assertGreaterEqual(d["winTrades"], 0)
        self.assertGreaterEqual(d["lossTrades"], 0)
        self.assertGreaterEqual(d["losses"], 0)
        self.assertGreaterEqual(d["drawdown"], 0)
        self.assertGreaterEqual(d["winRate"], 0)
        self.assertLessEqual(d["winRate"], 100)

    def test_price_history_contains_numbers(self):
        for sym, entry in SAMPLE_FULL_DATA["prices"].items():
            for i, val in enumerate(entry["history"]):
                self.assertIsInstance(
                    val, (int, float), f"{sym}.history[{i}] is not numeric"
                )

    def test_sample_data_roundtrips_through_json(self):
        serialized = json.dumps(SAMPLE_FULL_DATA)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized, SAMPLE_FULL_DATA)


class TestEscapeJsonLogic(unittest.TestCase):
    """Tests for the EscapeJSON logic as reimplemented in Python,
    matching the MQL5 EscapeJSON function behavior."""

    @staticmethod
    def escape_json(s):
        s = s.replace("\\", "\\\\")
        s = s.replace('"', '\\"')
        s = s.replace("\n", "\\n")
        s = s.replace("\r", "")
        s = s.replace("\t", "\\t")
        return s

    def test_plain_string(self):
        self.assertEqual(self.escape_json("hello world"), "hello world")

    def test_quotes_escaped(self):
        self.assertEqual(self.escape_json('say "hi"'), 'say \\"hi\\"')

    def test_newlines_escaped(self):
        self.assertEqual(self.escape_json("line1\nline2"), "line1\\nline2")

    def test_carriage_returns_stripped(self):
        self.assertEqual(self.escape_json("line1\r\nline2"), "line1\\nline2")

    def test_tabs_escaped(self):
        self.assertEqual(self.escape_json("col1\tcol2"), "col1\\tcol2")

    def test_backslashes_escaped(self):
        self.assertEqual(self.escape_json("path\\to\\file"), "path\\\\to\\\\file")

    def test_combined(self):
        result = self.escape_json('He said "hello"\nand\tleft\\')
        self.assertEqual(result, 'He said \\"hello\\"\\nand\\tleft\\\\')

    def test_empty_string(self):
        self.assertEqual(self.escape_json(""), "")

    def test_result_is_valid_in_json_string(self):
        raw = 'CAS1 BUY "XAU"\nScore: 85/100'
        escaped = self.escape_json(raw)
        json_str = '{"comment": "' + escaped + '"}'
        parsed = json.loads(json_str)
        self.assertIn("CAS1 BUY", parsed["comment"])


class TestLotSizingLogic(unittest.TestCase):
    """Tests for the lot sizing formula used in ExecuteTrade(),
    reimplemented in Python for verification."""

    @staticmethod
    def calculate_lot(balance, risk_pct, entry_price, sl_price,
                      tick_value, tick_size, vol_min, vol_max, vol_step,
                      consecutive_losses=0, martingale_multi=1.3,
                      max_martingale=3):
        risk = balance * (risk_pct / 100.0)
        if 0 < consecutive_losses <= max_martingale:
            risk *= martingale_multi ** consecutive_losses
        pip_value = tick_value / tick_size if tick_size > 0 else tick_value
        sl_distance = abs(entry_price - sl_price)
        if sl_distance == 0 or pip_value == 0:
            return vol_min
        lot = risk / (sl_distance * pip_value)
        lot = max(vol_min, min(vol_max, round(lot / vol_step) * vol_step))
        return lot

    def test_basic_lot_calculation(self):
        lot = self.calculate_lot(
            balance=10000, risk_pct=2.5, entry_price=2340,
            sl_price=2320, tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01
        )
        self.assertGreater(lot, 0)
        self.assertGreaterEqual(lot, 0.01)
        self.assertLessEqual(lot, 100)

    def test_lot_respects_minimum(self):
        lot = self.calculate_lot(
            balance=100, risk_pct=0.1, entry_price=2340,
            sl_price=2300, tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01
        )
        self.assertGreaterEqual(lot, 0.01)

    def test_lot_respects_maximum(self):
        lot = self.calculate_lot(
            balance=10_000_000, risk_pct=100, entry_price=2340,
            sl_price=2339.99, tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=5.0, vol_step=0.01
        )
        self.assertLessEqual(lot, 5.0)

    def test_lot_rounds_to_step(self):
        lot = self.calculate_lot(
            balance=10000, risk_pct=2.5, entry_price=2340,
            sl_price=2320, tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.05
        )
        remainder = round(lot % 0.05, 10)
        self.assertAlmostEqual(remainder, 0.0, places=5)

    def test_martingale_increases_lot(self):
        lot_normal = self.calculate_lot(
            balance=10000, risk_pct=2.5, entry_price=2340,
            sl_price=2320, tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01,
            consecutive_losses=0
        )
        lot_marti1 = self.calculate_lot(
            balance=10000, risk_pct=2.5, entry_price=2340,
            sl_price=2320, tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01,
            consecutive_losses=1
        )
        self.assertGreater(lot_marti1, lot_normal)

    def test_martingale_reverts_above_max(self):
        lot_normal = self.calculate_lot(
            balance=10000, risk_pct=2.5, entry_price=2340,
            sl_price=2320, tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01,
            consecutive_losses=0
        )
        lot_over_max = self.calculate_lot(
            balance=10000, risk_pct=2.5, entry_price=2340,
            sl_price=2320, tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01,
            consecutive_losses=4
        )
        self.assertEqual(lot_normal, lot_over_max)

    def test_zero_sl_distance_returns_minimum(self):
        lot = self.calculate_lot(
            balance=10000, risk_pct=2.5, entry_price=2340,
            sl_price=2340, tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01
        )
        self.assertEqual(lot, 0.01)


if __name__ == "__main__":
    unittest.main()
