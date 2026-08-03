"""MQL5 strategy logic ported to Python for unit testing.

Tests the pure mathematical and decision logic extracted from
SmartTrader_7CAS.mq5 — regime detection, risk management, trade
filters, price action patterns, and SMC structures.
"""

import math
import unittest
from datetime import datetime


# ═══════════════════════════════════════════════════════════
# Python ports of MQL5 pure-logic functions
# ═══════════════════════════════════════════════════════════

def is_within_trading_hours(hour, start_hour=8, end_hour=22):
    return start_hour <= hour < end_hour


def is_news_time(hour, minute, buffer_min=30):
    current_minutes = hour * 60 + minute
    news_times = [510, 720, 840]  # 8:30, 12:00, 14:00 GMT
    for nt in news_times:
        if abs(current_minutes - nt) <= buffer_min:
            return True
    return False


def check_drawdown(equity, peak_equity, max_drawdown_pct=20.0):
    if peak_equity <= 0:
        return True, 0.0
    dd = ((peak_equity - equity) / peak_equity) * 100
    return dd < max_drawdown_pct, dd


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


def calculate_sl_tp(entry_price, atr, sl_multiplier, tp_multiplier,
                    is_buy, digits):
    if is_buy:
        sl = round(entry_price - atr * sl_multiplier, digits)
        tp = round(entry_price + atr * tp_multiplier, digits)
    else:
        sl = round(entry_price + atr * sl_multiplier, digits)
        tp = round(entry_price - atr * tp_multiplier, digits)
    return sl, tp


def trailing_stop_new_sl(current_price, atr, sl_multiplier, is_buy,
                         current_sl, digits, point):
    trail = atr * sl_multiplier
    if is_buy:
        new_sl = round(current_price - trail, digits)
        if new_sl > current_sl + point * 10:
            return new_sl
    else:
        new_sl = round(current_price + trail, digits)
        if current_sl == 0 or new_sl < current_sl - point * 10:
            return new_sl
    return None


def detect_regime(adx, ema_fast, ema_slow, ema_mid, ema_long,
                  bb_width, has_bos, has_smc, stoch_k,
                  has_fibo, adx_trend=25.0, adx_range=20.0,
                  stoch_block=0.95):
    trend_up = (ema_fast > ema_slow and ema_slow > ema_mid and
                ema_mid > ema_long and adx >= adx_trend)
    trend_dn = (ema_fast < ema_slow and ema_slow < ema_mid and
                ema_mid < ema_long and adx >= adx_trend)
    is_range = adx <= adx_range and bb_width < 1.5
    is_reversal = stoch_k > stoch_block or stoch_k < (1 - stoch_block)

    if trend_up or trend_dn:
        return "CAS1_TENDANCE"
    elif is_range:
        return "CAS3_RANGE"
    elif has_smc:
        return "CAS5_SMC"
    elif has_bos:
        return "CAS4_CASSURE"
    elif is_reversal:
        return "CAS6_RETOURNEMENT"
    elif has_fibo:
        return "CAS7_FIBONACCI"
    else:
        return "CAS2_SCALPING"


def is_bullish_pa(open_p, close_p, high_p, low_p):
    body = abs(close_p - open_p)
    lower_wick = min(open_p, close_p) - low_p
    upper_wick = high_p - max(open_p, close_p)
    return (close_p > open_p and body > upper_wick * 1.5) or \
           (lower_wick > body * 2 and close_p > open_p)


def is_bearish_pa(open_p, close_p, high_p, low_p):
    body = abs(close_p - open_p)
    upper_wick = high_p - max(open_p, close_p)
    lower_wick = min(open_p, close_p) - low_p
    return (close_p < open_p and body > lower_wick * 1.5) or \
           (upper_wick > body * 2 and close_p < open_p)


def is_bullish_bos(closes, highs, lookback=15):
    if len(highs) < lookback + 1:
        return False
    h_max = max(highs[2:lookback + 1])
    return closes[1] > h_max


def is_bearish_bos(closes, lows, lookback=15):
    if len(lows) < lookback + 1:
        return False
    l_min = min(lows[2:lookback + 1])
    return closes[1] < l_min


def is_bullish_stop_hunt(candles, lookback=20, wick_ratio=0.7):
    for k in range(1, min(lookback + 1, len(candles))):
        o, c, h, l = candles[k]
        if h == l:
            continue
        lower_body = min(o, c)
        if (lower_body - l) / (h - l) > wick_ratio and c > o:
            if len(candles) > 1 and candles[0][1] > c:
                return True
    return False


def calculate_stoch_rsi(rsi_values, period=14):
    if len(rsi_values) < period + 1:
        return 0.5
    window = rsi_values[:period]
    hi = max(window)
    lo = min(window)
    if hi == lo:
        return 0.5
    return (window[0] - lo) / (hi - lo)


def escape_json(s):
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "")
    s = s.replace("\t", "\\t")
    return s


def on_trade_transaction(profit, consecutive_losses, win_trades, loss_trades):
    if profit < 0:
        return consecutive_losses + 1, win_trades, loss_trades + 1
    else:
        return 0, win_trades + 1, loss_trades


def reset_daily_stats(current_day, last_reset_day, total_trades,
                      win_trades, loss_trades):
    if current_day != last_reset_day:
        return 0, 0, 0, current_day
    return total_trades, win_trades, loss_trades, last_reset_day


CAS_SL_TP = {
    "CAS1": (1.5, 2.5),
    "CAS2": (0.8, 1.2),
    "CAS3": (1.0, 1.5),
    "CAS4": (1.5, 3.0),
    "CAS5": (1.5, 2.5),
    "CAS6": (1.0, 2.0),
    "CAS7": (1.5, 2.5),
}


def get_cas_sl_tp(cas_name):
    for key in CAS_SL_TP:
        if key in cas_name:
            return CAS_SL_TP[key]
    return CAS_SL_TP["CAS1"]


FIBO_LEVELS = [0.236, 0.382, 0.500, 0.618, 0.786]


def is_on_bullish_fibo_level(bid, swing_high, swing_low, atr):
    if swing_high <= swing_low:
        return False
    rng = swing_high - swing_low
    for k in range(1, 4):
        level = swing_low + rng * (1 - FIBO_LEVELS[k])
        if abs(bid - level) <= atr * 0.5:
            return True
    return False


def is_on_bearish_fibo_level(bid, swing_high, swing_low, atr):
    if swing_high <= swing_low:
        return False
    rng = swing_high - swing_low
    for k in range(1, 4):
        level = swing_low + rng * FIBO_LEVELS[k]
        if abs(bid - level) <= atr * 0.5:
            return True
    return False


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════

class TestTradingHours(unittest.TestCase):

    def test_within_hours(self):
        for h in [8, 12, 15, 21]:
            self.assertTrue(is_within_trading_hours(h))

    def test_outside_hours(self):
        for h in [0, 3, 7, 22, 23]:
            self.assertFalse(is_within_trading_hours(h))

    def test_boundary_start(self):
        self.assertTrue(is_within_trading_hours(8))
        self.assertFalse(is_within_trading_hours(7))

    def test_boundary_end(self):
        self.assertFalse(is_within_trading_hours(22))
        self.assertTrue(is_within_trading_hours(21))


class TestNewsTime(unittest.TestCase):

    def test_news_at_830(self):
        self.assertTrue(is_news_time(8, 30))
        self.assertTrue(is_news_time(8, 0))
        self.assertTrue(is_news_time(9, 0))

    def test_news_at_1200(self):
        self.assertTrue(is_news_time(12, 0))
        self.assertTrue(is_news_time(11, 30))
        self.assertTrue(is_news_time(12, 30))

    def test_news_at_1400(self):
        self.assertTrue(is_news_time(14, 0))
        self.assertTrue(is_news_time(13, 30))
        self.assertTrue(is_news_time(14, 30))

    def test_no_news(self):
        self.assertFalse(is_news_time(10, 0))
        self.assertFalse(is_news_time(16, 0))
        self.assertFalse(is_news_time(20, 0))

    def test_exact_boundary(self):
        self.assertTrue(is_news_time(8, 0))   # 480 min, |480-510|=30 <= 30
        self.assertFalse(is_news_time(7, 59))  # 479 min, |479-510|=31 > 30


class TestCheckDrawdown(unittest.TestCase):

    def test_no_drawdown(self):
        ok, dd = check_drawdown(10000, 10000)
        self.assertTrue(ok)
        self.assertAlmostEqual(dd, 0.0)

    def test_small_drawdown(self):
        ok, dd = check_drawdown(9500, 10000)
        self.assertTrue(ok)
        self.assertAlmostEqual(dd, 5.0)

    def test_at_max_drawdown(self):
        ok, dd = check_drawdown(8000, 10000)
        self.assertFalse(ok)
        self.assertAlmostEqual(dd, 20.0)

    def test_beyond_max_drawdown(self):
        ok, dd = check_drawdown(7000, 10000)
        self.assertFalse(ok)

    def test_zero_peak_equity(self):
        ok, dd = check_drawdown(5000, 0)
        self.assertTrue(ok)

    def test_equity_above_peak(self):
        ok, dd = check_drawdown(11000, 10000)
        self.assertTrue(ok)
        self.assertTrue(dd < 0)

    def test_custom_max_drawdown(self):
        ok, _ = check_drawdown(9500, 10000, max_drawdown_pct=4.0)
        self.assertFalse(ok)


class TestCalculateLot(unittest.TestCase):

    def test_gold_lot_sizing(self):
        lot = calculate_lot(
            balance=10000, risk_pct=2.5,
            entry_price=2340, sl_price=2320,
            tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01
        )
        expected_risk = 250  # 10000 * 2.5%
        pip_value = 100  # 1/0.01
        sl_dist = 20
        expected_lot = round(expected_risk / (sl_dist * pip_value) / 0.01) * 0.01
        self.assertAlmostEqual(lot, expected_lot, places=2)

    def test_silver_lot_sizing(self):
        lot = calculate_lot(
            balance=10000, risk_pct=2.5,
            entry_price=29.50, sl_price=29.00,
            tick_value=5, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01
        )
        self.assertGreater(lot, 0)

    def test_very_tight_stop(self):
        lot = calculate_lot(
            balance=10000, risk_pct=2.5,
            entry_price=2340, sl_price=2339.50,
            tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=1.0, vol_step=0.01
        )
        self.assertLessEqual(lot, 1.0)

    def test_martingale_level_1(self):
        lot_base = calculate_lot(
            balance=10000, risk_pct=2.5,
            entry_price=2340, sl_price=2320,
            tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01,
            consecutive_losses=0
        )
        lot_m1 = calculate_lot(
            balance=10000, risk_pct=2.5,
            entry_price=2340, sl_price=2320,
            tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01,
            consecutive_losses=1
        )
        self.assertAlmostEqual(lot_m1 / lot_base, 1.3, places=1)

    def test_martingale_level_3(self):
        lot_base = calculate_lot(
            balance=10000, risk_pct=2.5,
            entry_price=2340, sl_price=2320,
            tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01,
            consecutive_losses=0
        )
        lot_m3 = calculate_lot(
            balance=10000, risk_pct=2.5,
            entry_price=2340, sl_price=2320,
            tick_value=1, tick_size=0.01,
            vol_min=0.01, vol_max=100, vol_step=0.01,
            consecutive_losses=3
        )
        self.assertGreater(lot_m3, lot_base * 2)

    def test_zero_tick_size_uses_tick_value(self):
        lot = calculate_lot(
            balance=10000, risk_pct=2.5,
            entry_price=100, sl_price=90,
            tick_value=10, tick_size=0,
            vol_min=0.01, vol_max=100, vol_step=0.01
        )
        self.assertGreater(lot, 0)


class TestSLTP(unittest.TestCase):

    def test_buy_sl_below_entry(self):
        sl, tp = calculate_sl_tp(2340, 20, 1.5, 2.5, True, 2)
        self.assertLess(sl, 2340)
        self.assertGreater(tp, 2340)

    def test_sell_sl_above_entry(self):
        sl, tp = calculate_sl_tp(2340, 20, 1.5, 2.5, False, 2)
        self.assertGreater(sl, 2340)
        self.assertLess(tp, 2340)

    def test_tp_further_than_sl(self):
        sl, tp = calculate_sl_tp(2340, 20, 1.5, 2.5, True, 2)
        sl_dist = abs(2340 - sl)
        tp_dist = abs(tp - 2340)
        self.assertGreater(tp_dist, sl_dist)

    def test_each_cas_has_positive_rr(self):
        for cas, (sl_m, tp_m) in CAS_SL_TP.items():
            self.assertGreater(tp_m / sl_m, 1.0,
                               f"{cas} has risk-reward <= 1.0")


class TestCasSLTP(unittest.TestCase):

    def test_cas1_returns_correct_values(self):
        self.assertEqual(get_cas_sl_tp("CAS1_TENDANCE"), (1.5, 2.5))

    def test_cas2_returns_correct_values(self):
        self.assertEqual(get_cas_sl_tp("CAS2_SCALPING"), (0.8, 1.2))

    def test_cas4_returns_correct_values(self):
        self.assertEqual(get_cas_sl_tp("CAS4_CASSURE"), (1.5, 3.0))

    def test_unknown_defaults_to_cas1(self):
        self.assertEqual(get_cas_sl_tp("UNKNOWN"), (1.5, 2.5))


class TestTrailingStop(unittest.TestCase):

    def test_buy_trailing_moves_sl_up(self):
        new_sl = trailing_stop_new_sl(
            current_price=2360, atr=20, sl_multiplier=1.5,
            is_buy=True, current_sl=2310, digits=2, point=0.01
        )
        self.assertIsNotNone(new_sl)
        self.assertGreater(new_sl, 2310)

    def test_buy_trailing_no_move_when_close(self):
        new_sl = trailing_stop_new_sl(
            current_price=2340, atr=20, sl_multiplier=1.5,
            is_buy=True, current_sl=2310, digits=2, point=0.01
        )
        self.assertIsNone(new_sl)

    def test_sell_trailing_moves_sl_down(self):
        new_sl = trailing_stop_new_sl(
            current_price=2300, atr=20, sl_multiplier=1.5,
            is_buy=False, current_sl=2370, digits=2, point=0.01
        )
        self.assertIsNotNone(new_sl)
        self.assertLess(new_sl, 2370)

    def test_sell_trailing_initial_sl_zero(self):
        new_sl = trailing_stop_new_sl(
            current_price=2300, atr=20, sl_multiplier=1.5,
            is_buy=False, current_sl=0, digits=2, point=0.01
        )
        self.assertIsNotNone(new_sl)


class TestDetectRegime(unittest.TestCase):

    def test_strong_uptrend(self):
        result = detect_regime(
            adx=30, ema_fast=110, ema_slow=105,
            ema_mid=100, ema_long=95,
            bb_width=2.0, has_bos=False, has_smc=False,
            stoch_k=0.5, has_fibo=False
        )
        self.assertEqual(result, "CAS1_TENDANCE")

    def test_strong_downtrend(self):
        result = detect_regime(
            adx=30, ema_fast=90, ema_slow=95,
            ema_mid=100, ema_long=105,
            bb_width=2.0, has_bos=False, has_smc=False,
            stoch_k=0.5, has_fibo=False
        )
        self.assertEqual(result, "CAS1_TENDANCE")

    def test_range_market(self):
        result = detect_regime(
            adx=15, ema_fast=100.1, ema_slow=100.2,
            ema_mid=100, ema_long=99.9,
            bb_width=1.0, has_bos=False, has_smc=False,
            stoch_k=0.5, has_fibo=False
        )
        self.assertEqual(result, "CAS3_RANGE")

    def test_smc_setup(self):
        result = detect_regime(
            adx=22, ema_fast=100, ema_slow=101,
            ema_mid=99, ema_long=102,
            bb_width=2.0, has_bos=False, has_smc=True,
            stoch_k=0.5, has_fibo=False
        )
        self.assertEqual(result, "CAS5_SMC")

    def test_breakout(self):
        result = detect_regime(
            adx=22, ema_fast=100, ema_slow=101,
            ema_mid=99, ema_long=102,
            bb_width=2.0, has_bos=True, has_smc=False,
            stoch_k=0.5, has_fibo=False
        )
        self.assertEqual(result, "CAS4_CASSURE")

    def test_reversal(self):
        result = detect_regime(
            adx=22, ema_fast=100, ema_slow=101,
            ema_mid=99, ema_long=102,
            bb_width=2.0, has_bos=False, has_smc=False,
            stoch_k=0.97, has_fibo=False
        )
        self.assertEqual(result, "CAS6_RETOURNEMENT")

    def test_fibonacci(self):
        result = detect_regime(
            adx=22, ema_fast=100, ema_slow=101,
            ema_mid=99, ema_long=102,
            bb_width=2.0, has_bos=False, has_smc=False,
            stoch_k=0.5, has_fibo=True
        )
        self.assertEqual(result, "CAS7_FIBONACCI")

    def test_scalping_fallback(self):
        result = detect_regime(
            adx=22, ema_fast=100, ema_slow=101,
            ema_mid=99, ema_long=102,
            bb_width=2.0, has_bos=False, has_smc=False,
            stoch_k=0.5, has_fibo=False
        )
        self.assertEqual(result, "CAS2_SCALPING")

    def test_trend_takes_priority_over_all(self):
        result = detect_regime(
            adx=30, ema_fast=110, ema_slow=105,
            ema_mid=100, ema_long=95,
            bb_width=0.5, has_bos=True, has_smc=True,
            stoch_k=0.98, has_fibo=True
        )
        self.assertEqual(result, "CAS1_TENDANCE")

    def test_smc_takes_priority_over_breakout(self):
        result = detect_regime(
            adx=22, ema_fast=100, ema_slow=101,
            ema_mid=99, ema_long=102,
            bb_width=2.0, has_bos=True, has_smc=True,
            stoch_k=0.5, has_fibo=False
        )
        self.assertEqual(result, "CAS5_SMC")


class TestPriceAction(unittest.TestCase):

    def test_bullish_engulfing(self):
        self.assertTrue(is_bullish_pa(100, 110, 112, 99))

    def test_bullish_hammer(self):
        self.assertTrue(is_bullish_pa(108, 110, 111, 100))

    def test_bearish_engulfing(self):
        self.assertTrue(is_bearish_pa(110, 100, 111, 99))

    def test_bearish_shooting_star(self):
        self.assertTrue(is_bearish_pa(102, 100, 110, 99))

    def test_doji_with_long_lower_wick_is_bullish(self):
        # body=0.01, lower_wick=5.0 -> lower_wick > body*2 and close>open
        self.assertTrue(is_bullish_pa(100, 100.01, 105, 95))

    def test_doji_with_long_upper_wick_is_bearish(self):
        # body=0.01, upper_wick=5.01 -> upper_wick > body*2 and close<open
        self.assertTrue(is_bearish_pa(100, 99.99, 105, 95))


class TestBOS(unittest.TestCase):

    def test_bullish_bos_detected(self):
        highs = [0, 110, 105, 100, 102, 98, 99, 101, 97, 96, 95,
                 94, 93, 92, 91, 90]
        closes = [0, 111]
        self.assertTrue(is_bullish_bos(closes, highs))

    def test_no_bullish_bos(self):
        highs = [0, 110, 105, 100, 102, 98, 99, 101, 97, 96, 95,
                 94, 93, 92, 91, 90]
        closes = [0, 104]
        self.assertFalse(is_bullish_bos(closes, highs))

    def test_bearish_bos_detected(self):
        lows = [0, 85, 90, 95, 93, 97, 96, 94, 98, 99, 100,
                101, 102, 103, 104, 105]
        closes = [0, 84]
        self.assertTrue(is_bearish_bos(closes, lows))

    def test_no_bearish_bos(self):
        lows = [0, 85, 90, 95, 93, 97, 96, 94, 98, 99, 100,
                101, 102, 103, 104, 105]
        closes = [0, 91]
        self.assertFalse(is_bearish_bos(closes, lows))


class TestStopHunt(unittest.TestCase):

    def test_bullish_stop_hunt(self):
        # (open, close, high, low)
        candles = [
            (105, 106, 107, 104),  # current candle closes above
            (103, 104, 105, 95),   # long lower wick, bullish close
        ]
        self.assertTrue(is_bullish_stop_hunt(candles, lookback=5))

    def test_no_stop_hunt_without_wick(self):
        candles = [
            (105, 106, 107, 104),
            (103, 104, 105, 103),  # no significant lower wick
        ]
        self.assertFalse(is_bullish_stop_hunt(candles, lookback=5))


class TestStochRSI(unittest.TestCase):

    def test_oversold(self):
        values = [30] + [50, 60, 70, 65, 55, 45, 40, 35, 38, 42, 48, 52, 58, 62]
        k = calculate_stoch_rsi(values)
        self.assertLess(k, 0.3)

    def test_overbought(self):
        values = [70] + [50, 40, 30, 35, 45, 55, 60, 65, 62, 58, 52, 48, 42, 38]
        k = calculate_stoch_rsi(values)
        self.assertGreater(k, 0.7)

    def test_equal_values_returns_half(self):
        values = [50] * 15
        k = calculate_stoch_rsi(values)
        self.assertEqual(k, 0.5)

    def test_insufficient_data(self):
        k = calculate_stoch_rsi([50, 55, 60])
        self.assertEqual(k, 0.5)


class TestFibonacci(unittest.TestCase):

    def test_bullish_fibo_at_382(self):
        swing_high = 2400
        swing_low = 2300
        rng = 100
        level_382 = swing_low + rng * (1 - 0.382)
        self.assertTrue(is_on_bullish_fibo_level(level_382, swing_high, swing_low, 5))

    def test_bullish_fibo_at_618(self):
        swing_high = 2400
        swing_low = 2300
        rng = 100
        level_618 = swing_low + rng * (1 - 0.618)
        self.assertTrue(is_on_bullish_fibo_level(level_618, swing_high, swing_low, 5))

    def test_no_fibo_far_from_level(self):
        # ATR=2, tolerance=1.0. Level at 2361.8 is 11.8 away from 2350, but
        # level at 2350 (50% retracement) is within 0.5*2=1.0 tolerance
        # Use a price clearly outside all fibo zones
        self.assertFalse(is_on_bullish_fibo_level(2320, 2400, 2300, 2))

    def test_bearish_fibo_at_382(self):
        swing_high = 2400
        swing_low = 2300
        level = swing_low + 100 * 0.382
        self.assertTrue(is_on_bearish_fibo_level(level, swing_high, swing_low, 5))

    def test_equal_swing_returns_false(self):
        self.assertFalse(is_on_bullish_fibo_level(100, 100, 100, 5))
        self.assertFalse(is_on_bearish_fibo_level(100, 100, 100, 5))


class TestTradeTransaction(unittest.TestCase):

    def test_loss_increments_consecutive(self):
        cl, wt, lt = on_trade_transaction(-50, 0, 5, 3)
        self.assertEqual(cl, 1)
        self.assertEqual(lt, 4)
        self.assertEqual(wt, 5)

    def test_win_resets_consecutive(self):
        cl, wt, lt = on_trade_transaction(100, 3, 5, 3)
        self.assertEqual(cl, 0)
        self.assertEqual(wt, 6)
        self.assertEqual(lt, 3)

    def test_multiple_losses(self):
        cl, wt, lt = 0, 0, 0
        for _ in range(5):
            cl, wt, lt = on_trade_transaction(-10, cl, wt, lt)
        self.assertEqual(cl, 5)
        self.assertEqual(lt, 5)

    def test_win_after_losses_resets(self):
        cl, wt, lt = 3, 2, 3
        cl, wt, lt = on_trade_transaction(50, cl, wt, lt)
        self.assertEqual(cl, 0)


class TestResetDailyStats(unittest.TestCase):

    def test_same_day_no_reset(self):
        t, w, l, d = reset_daily_stats(5, 5, 10, 6, 4)
        self.assertEqual(t, 10)
        self.assertEqual(w, 6)
        self.assertEqual(l, 4)

    def test_new_day_resets(self):
        t, w, l, d = reset_daily_stats(6, 5, 10, 6, 4)
        self.assertEqual(t, 0)
        self.assertEqual(w, 0)
        self.assertEqual(l, 0)
        self.assertEqual(d, 6)


class TestEscapeJson(unittest.TestCase):

    def test_special_chars(self):
        self.assertEqual(escape_json('a"b'), 'a\\"b')
        self.assertEqual(escape_json("a\nb"), "a\\nb")
        self.assertEqual(escape_json("a\\b"), "a\\\\b")

    def test_injection_attempt(self):
        raw = '","evil":true,"x":"'
        escaped = escape_json(raw)
        import json
        result = json.loads('{"val":"' + escaped + '"}')
        self.assertEqual(result["val"], raw)
        self.assertNotIn("evil", result)


if __name__ == "__main__":
    unittest.main()
