"""CAS 7 strategy engine — Python port of SmartTrader_7CAS.mq5.

Fetches candle/indicator data from MetaApi and runs the full 7-CAS
pipeline: regime detection, signal generation, SL/TP calculation.
The EA's logic is faithfully ported so the platform produces the same
signals as the MQL5 bot.

Indicator data is pulled from MetaApi's REST endpoints; no local MT5
installation is required.
"""

import json
import logging
import math
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

METAAPI_DATA_URL = "https://mt-client-api-v1.agiliumtrade.agiliumtrade.ai"

# ── Parameters matching the MQL5 EA ──────────────────────────────

RSI_PERIOD = 14
STOCHRSI_PER = 14
STOCHRSI_OB = 0.80
STOCHRSI_OS = 0.20
STOCHRSI_BLOCK = 0.95

ADX_TREND = 25.0
ADX_RANGE = 20.0

BOS_LOOKBACK = 15
OB_LOOKBACK = 30
FVG_MIN_SIZE = 0.5
LZ_LOOKBACK = 50
SH_LOOKBACK = 20
SH_WICK_RATIO = 0.7

STOCH14_PERIOD = 14
STOCH14_D_PERIOD = 3
ECART_DK_MIN = 10.0

CAS_PARAMS = {
    "CAS1_TENDANCE":     {"sl_mult": 1.5, "tp_mult": 2.5, "base_score": 60},
    "CAS2_SCALPING":     {"sl_mult": 0.8, "tp_mult": 1.2, "base_score": 55},
    "CAS3_RANGE":        {"sl_mult": 1.0, "tp_mult": 1.5, "base_score": 60},
    "CAS4_CASSURE":      {"sl_mult": 1.5, "tp_mult": 3.0, "base_score": 70},
    "CAS5_SMC":          {"sl_mult": 1.5, "tp_mult": 2.5, "base_score": 80},
    "CAS6_RETOURNEMENT": {"sl_mult": 1.0, "tp_mult": 2.0, "base_score": 65},
    "CAS7_FIBONACCI":    {"sl_mult": 1.5, "tp_mult": 2.5, "base_score": 75},
}

SYMBOLS = ["XAUUSDm", "XAGUSDm", "USOILm"]
SYMBOL_LABELS = {"XAUUSDm": "Or (XAUUSD)", "XAGUSDm": "Argent (XAGUSD)", "USOILm": "Petrole (USOIL)"}

START_HOUR = 8
END_HOUR = 22

NEWS_TIMES = [(8, 30), (12, 0), (14, 0)]
NEWS_BUFFER_MIN = 30


# ── MetaApi data fetching ────────────────────────────────────────

def _api_get(url, token):
    req = urllib.request.Request(url, method="GET")
    req.add_header("auth-token", token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        return {"error": str(e)}, e.code
    except Exception as e:
        return {"error": str(e)}, 0


def fetch_candles(account_id, token, symbol, timeframe="15m", limit=60):
    url = (
        f"{METAAPI_DATA_URL}/users/current/accounts/{account_id}"
        f"/historical-market-data/symbols/{symbol}/timeframes/{timeframe}"
        f"/candles?limit={limit}"
    )
    data, status = _api_get(url, token)
    if status != 200 or not isinstance(data, list):
        return []
    return data


def fetch_price(account_id, token, symbol):
    url = (
        f"{METAAPI_DATA_URL}/users/current/accounts/{account_id}"
        f"/symbols/{symbol}/current-price"
    )
    data, status = _api_get(url, token)
    if status != 200:
        return None
    return data


# ── Indicator calculations ───────────────────────────────────────

def calc_ema(closes, period):
    if len(closes) < period:
        return []
    k = 2.0 / (period + 1)
    ema = [sum(closes[:period]) / period]
    for price in closes[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return []
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains = [max(d, 0) for d in deltas[:period]]
    losses = [max(-d, 0) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    rsi_values = []
    for i in range(period, len(deltas)):
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100.0 - 100.0 / (1.0 + rs))
        d = deltas[i]
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period

    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100.0 - 100.0 / (1.0 + rs))

    return rsi_values


def calc_stochrsi_k(rsi_values, period=14):
    if len(rsi_values) < period:
        return 0.5
    recent = rsi_values[-period:]
    hi = max(recent)
    lo = min(recent)
    if hi == lo:
        return 0.5
    return (recent[-1] - lo) / (hi - lo)


def calc_stoch14(highs, lows, closes, k_period=14, d_period=3):
    """Classic Stochastic Oscillator %K and %D (period 14)."""
    if len(closes) < k_period:
        return 50.0, 50.0
    k_values = []
    for i in range(k_period - 1, len(closes)):
        period_highs = highs[i - k_period + 1:i + 1]
        period_lows = lows[i - k_period + 1:i + 1]
        hh = max(period_highs)
        ll = min(period_lows)
        if hh == ll:
            k_values.append(50.0)
        else:
            k_values.append((closes[i] - ll) / (hh - ll) * 100)
    if len(k_values) < d_period:
        return k_values[-1] if k_values else 50.0, 50.0
    d_value = sum(k_values[-d_period:]) / d_period
    return k_values[-1], d_value


def calc_atr(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return 0
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def calc_adx(highs, lows, closes, period=14):
    if len(highs) < period * 2:
        return 0
    plus_dm = []
    minus_dm = []
    trs = []
    for i in range(1, len(highs)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)

    if len(trs) < period:
        return 0

    atr = sum(trs[:period]) / period
    plus_di = sum(plus_dm[:period]) / period
    minus_di = sum(minus_dm[:period]) / period

    dx_values = []
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        plus_di = (plus_di * (period - 1) + plus_dm[i]) / period
        minus_di = (minus_di * (period - 1) + minus_dm[i]) / period

        if atr == 0:
            continue
        pdi = 100 * plus_di / atr
        mdi = 100 * minus_di / atr
        denom = pdi + mdi
        if denom == 0:
            continue
        dx_values.append(100 * abs(pdi - mdi) / denom)

    if len(dx_values) < period:
        return sum(dx_values) / len(dx_values) if dx_values else 0
    adx = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx = (adx * (period - 1) + dx) / period
    return adx


def calc_bb(closes, period=20, dev=2.0):
    if len(closes) < period:
        return 0, 0, 0
    recent = closes[-period:]
    mid = sum(recent) / period
    variance = sum((c - mid) ** 2 for c in recent) / period
    std = math.sqrt(variance)
    return mid - dev * std, mid, mid + dev * std


def calc_macd(closes, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    if not ema_fast or not ema_slow:
        return 0, 0
    offset = slow - fast
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]
    if len(macd_line) < signal:
        return macd_line[-1] if macd_line else 0, 0
    sig_ema = calc_ema(macd_line, signal)
    return macd_line[-1], sig_ema[-1] if sig_ema else 0


# ── Price Action patterns ────────────────────────────────────────

def is_bullish_pa(opens, closes, highs, lows):
    if len(opens) < 2:
        return False
    o1, c1, h1, l1 = opens[-1], closes[-1], highs[-1], lows[-1]
    o2, c2 = opens[-2], closes[-2]
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    rng = h1 - l1 if h1 != l1 else 0.0001
    if c1 > o1 and c2 < o2 and body1 > body2 * 1.0:
        return True
    lower_wick = min(o1, c1) - l1
    if c1 > o1 and lower_wick / rng > 0.6 and body1 / rng < 0.3:
        return True
    return False


def is_bearish_pa(opens, closes, highs, lows):
    if len(opens) < 2:
        return False
    o1, c1, h1, l1 = opens[-1], closes[-1], highs[-1], lows[-1]
    o2, c2 = opens[-2], closes[-2]
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    rng = h1 - l1 if h1 != l1 else 0.0001
    if c1 < o1 and c2 > o2 and body1 > body2 * 1.0:
        return True
    upper_wick = h1 - max(o1, c1)
    if c1 < o1 and upper_wick / rng > 0.6 and body1 / rng < 0.3:
        return True
    return False


# ── SMC functions ────────────────────────────────────────────────

def is_bullish_bos(highs, closes):
    if len(highs) < BOS_LOOKBACK + 1:
        return False
    h_max = max(highs[-(BOS_LOOKBACK + 1):-1])
    return closes[-1] > h_max


def is_bearish_bos(lows, closes):
    if len(lows) < BOS_LOOKBACK + 1:
        return False
    l_min = min(lows[-(BOS_LOOKBACK + 1):-1])
    return closes[-1] < l_min


def is_bullish_ob(opens, closes, highs, lows):
    if len(opens) < OB_LOOKBACK:
        return False
    c1 = closes[-1]
    for k in range(2, min(OB_LOOKBACK, len(opens))):
        o, c = opens[-k], closes[-k]
        if c < o:
            nc, no = closes[-k + 1], opens[-k + 1]
            if nc > no and (nc - no) > (o - c) * 1.5 and c1 >= c and c1 <= o:
                return True
    return False


def is_bearish_ob(opens, closes, highs, lows):
    if len(opens) < OB_LOOKBACK:
        return False
    c1 = closes[-1]
    for k in range(2, min(OB_LOOKBACK, len(opens))):
        o, c = opens[-k], closes[-k]
        if c > o:
            nc, no = closes[-k + 1], opens[-k + 1]
            if nc < no and (no - nc) > (c - o) * 1.5 and c1 <= c and c1 >= o:
                return True
    return False


def is_bullish_choch(highs, lows, closes):
    n = len(highs)
    if n < BOS_LOOKBACK:
        return False
    ll_count = 0
    prev_low = lows[-BOS_LOOKBACK]
    for k in range(BOS_LOOKBACK - 1, 2, -1):
        cl = lows[-k]
        if cl < prev_low:
            ll_count += 1
        prev_low = cl
    if ll_count < 2:
        return False
    half = BOS_LOOKBACK // 2
    rh = max(highs[-(half + 1):-1]) if half > 1 else 0
    return closes[-1] > rh


def is_bearish_choch(highs, lows, closes):
    n = len(highs)
    if n < BOS_LOOKBACK:
        return False
    hh_count = 0
    prev_high = highs[-BOS_LOOKBACK]
    for k in range(BOS_LOOKBACK - 1, 2, -1):
        ch = highs[-k]
        if ch > prev_high:
            hh_count += 1
        prev_high = ch
    if hh_count < 2:
        return False
    half = BOS_LOOKBACK // 2
    rl = min(lows[-(half + 1):-1]) if half > 1 else float("inf")
    return closes[-1] < rl


def is_bullish_sh(opens, closes, highs, lows):
    for k in range(1, min(SH_LOOKBACK + 1, len(opens))):
        o, c, h, l = opens[-k], closes[-k], highs[-k], lows[-k]
        rng = h - l
        if rng == 0:
            continue
        lower_wick = min(o, c) - l
        if lower_wick / rng > SH_WICK_RATIO and c > o and closes[-1] > c:
            return True
    return False


def is_bearish_sh(opens, closes, highs, lows):
    for k in range(1, min(SH_LOOKBACK + 1, len(opens))):
        o, c, h, l = opens[-k], closes[-k], highs[-k], lows[-k]
        rng = h - l
        if rng == 0:
            continue
        upper_wick = h - max(o, c)
        if upper_wick / rng > SH_WICK_RATIO and c < o and closes[-1] < c:
            return True
    return False


# ── Fibonacci ────────────────────────────────────────────────────

def is_on_fibo_level(highs, lows, closes, atr, direction="bull"):
    if len(highs) < 50 or atr == 0:
        return False
    swing_high = max(highs[-50:])
    swing_low = min(lows[-50:])
    diff = swing_high - swing_low
    if diff == 0:
        return False

    levels = [0.382, 0.5, 0.618]
    price = closes[-1]

    for lvl in levels:
        if direction == "bull":
            fibo_price = swing_high - diff * lvl
        else:
            fibo_price = swing_low + diff * lvl
        if abs(price - fibo_price) < atr * 0.5:
            return True
    return False


# ── Time filters ─────────────────────────────────────────────────

def is_within_trading_hours():
    h = datetime.now(timezone.utc).hour
    return START_HOUR <= h < END_HOUR


def is_news_time():
    now = datetime.now(timezone.utc)
    h, m = now.hour, now.minute
    for nh, nm in NEWS_TIMES:
        diff = abs((h * 60 + m) - (nh * 60 + nm))
        if diff <= NEWS_BUFFER_MIN:
            return True
    return False


# ── Faux Mouvement & Pipeline helpers ───────────────────────────

def detect_faux_mouvement(stochrsi_k, stoch14_k, stoch14_d, direction):
    """FAUX MOUVEMENT: StochRSI in zone but Stoch14 K doesn't confirm."""
    if direction == "BUY":
        return stochrsi_k <= STOCHRSI_OS and stoch14_k <= stoch14_d
    if direction == "SELL":
        return stochrsi_k >= STOCHRSI_OB and stoch14_k >= stoch14_d
    return False


def check_ecart_dk(stoch14_k, stoch14_d):
    """B2 validation: gap |D - K| must be >= ECART_DK_MIN."""
    return abs(stoch14_d - stoch14_k) >= ECART_DK_MIN


def detect_cas_by_adx(adx):
    """CAS number from ADX thresholds (CAS 1-4 pipeline)."""
    if adx > 24:
        return 1
    if adx > 20:
        return 2
    if adx > 10:
        return 3
    return 4


def detect_branch_cas5(closes, direction):
    """Branch A (MA alignee) / B (MA non alignee) for CAS 5."""
    if len(closes) < 50:
        return "B"
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50)
    if not ema9 or not ema21 or not ema50:
        return "B"
    e9, e21, e50 = ema9[-1], ema21[-1], ema50[-1]
    if direction == "BUY" and e9 > e21 > e50:
        return "A"
    if direction == "SELL" and e9 < e21 < e50:
        return "A"
    return "B"


def calc_pyramide_levels(entry_price, atr, direction, num_levels=5):
    """Pyramide P1-P5 entry levels with decreasing lot percentages."""
    step = atr * 0.5
    pcts = [1.0, 0.5, 0.3, 0.2, 0.1]
    levels = []
    for i in range(num_levels):
        offset = step * (i + 1)
        price = entry_price + offset if direction == "BUY" else entry_price - offset
        levels.append({"level": f"P{i + 1}", "price": round(price, 5), "lot_pct": pcts[i]})
    return levels


# ── Regime detection ─────────────────────────────────────────────

def detect_regime(closes, highs, lows, opens, atr, adx, bb_lower, bb_mid, bb_upper):
    if len(closes) < 200:
        return "CAS2_SCALPING"

    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200)

    if ema9 and ema21 and ema50 and ema200:
        e9, e21, e50, e200 = ema9[-1], ema21[-1], ema50[-1], ema200[-1]
        trend_up = e9 > e21 > e50 > e200 and adx >= ADX_TREND
        trend_dn = e9 < e21 < e50 < e200 and adx >= ADX_TREND
        if trend_up or trend_dn:
            return "CAS1_TENDANCE"

    bb_width = ((bb_upper - bb_lower) / bb_mid * 100) if bb_mid > 0 else 999
    if adx <= ADX_RANGE and bb_width < 1.5:
        return "CAS3_RANGE"

    smc_setup = (
        is_bullish_ob(opens, closes, highs, lows)
        or is_bearish_ob(opens, closes, highs, lows)
        or is_bullish_choch(highs, lows, closes)
        or is_bearish_choch(highs, lows, closes)
    )
    if smc_setup:
        return "CAS5_SMC"

    breakout = is_bullish_bos(highs, closes) or is_bearish_bos(lows, closes)
    if breakout:
        return "CAS4_CASSURE"

    rsi_values = calc_rsi(closes, RSI_PERIOD)
    stoch_k = calc_stochrsi_k(rsi_values, STOCHRSI_PER) if rsi_values else 0.5
    if stoch_k > STOCHRSI_BLOCK or stoch_k < (1 - STOCHRSI_BLOCK):
        return "CAS6_RETOURNEMENT"

    if is_on_fibo_level(highs, lows, closes, atr, "bull") or is_on_fibo_level(highs, lows, closes, atr, "bear"):
        return "CAS7_FIBONACCI"

    return "CAS2_SCALPING"


# ── Signal generation per CAS ────────────────────────────────────

def generate_signal(closes, opens, highs, lows):
    if len(closes) < 200:
        return _no_signal("Donnees insuffisantes")

    atr = calc_atr(highs, lows, closes)
    adx = calc_adx(highs, lows, closes)
    bb_lower, bb_mid, bb_upper = calc_bb(closes)
    rsi_values = calc_rsi(closes, RSI_PERIOD)
    stoch_k = calc_stochrsi_k(rsi_values, STOCHRSI_PER) if rsi_values else 0.5
    macd_main, macd_sig = calc_macd(closes)
    stoch14_k, stoch14_d = calc_stoch14(highs, lows, closes)

    regime = detect_regime(closes, highs, lows, opens, atr, adx, bb_lower, bb_mid, bb_upper)
    params = CAS_PARAMS[regime]

    is_cas14 = regime in ("CAS1_TENDANCE", "CAS2_SCALPING", "CAS3_RANGE", "CAS4_CASSURE")

    b1_buy = stoch_k <= STOCHRSI_OS
    b1_sell = stoch_k >= STOCHRSI_OB
    b1_active = b1_buy or b1_sell
    b1_direction = "BUY" if b1_buy else "SELL" if b1_sell else "ATTENTE"

    faux_mouvement = False
    if is_cas14 and b1_active:
        faux_mouvement = detect_faux_mouvement(stoch_k, stoch14_k, stoch14_d, b1_direction)

    ecart_dk = abs(stoch14_d - stoch14_k)
    b2_confirmed = False
    if is_cas14 and b1_active and not faux_mouvement:
        b2_confirmed = check_ecart_dk(stoch14_k, stoch14_d)

    cas_adx_num = detect_cas_by_adx(adx) if is_cas14 else 0

    sig = 0
    reasons = []

    if faux_mouvement:
        reasons = [
            {"ok": False, "text": f"FAUX MOUVEMENT — Stoch14 K({stoch14_k:.1f}) {'<=' if b1_direction == 'BUY' else '>='} D({stoch14_d:.1f})"},
            {"ok": True, "text": f"StochRSI en zone ({stoch_k:.3f}) mais Stoch14 ne confirme pas"},
            {"ok": False, "text": "B1 abandonne — scan relance"},
        ]
    elif regime == "CAS1_TENDANCE":
        sig, reasons = _get_cas1(closes, opens, highs, lows, stoch_k, adx, macd_main, macd_sig)
    elif regime == "CAS2_SCALPING":
        sig, reasons = _get_cas2(closes, opens, highs, lows, stoch_k)
    elif regime == "CAS3_RANGE":
        sig, reasons = _get_cas3(closes, highs, lows, stoch_k, bb_lower, bb_upper, atr)
    elif regime == "CAS4_CASSURE":
        sig, reasons = _get_cas4(closes, opens, highs, lows, atr)
    elif regime == "CAS5_SMC":
        sig, reasons = _get_cas5(closes, opens, highs, lows, stoch_k)
    elif regime == "CAS6_RETOURNEMENT":
        sig, reasons = _get_cas6(closes, opens, highs, lows, stoch_k, rsi_values)
    elif regime == "CAS7_FIBONACCI":
        sig, reasons = _get_cas7(closes, opens, highs, lows, stoch_k, atr)

    if is_cas14 and not b2_confirmed and sig != 0:
        reasons.insert(0, {"ok": False, "text": f"Ecart D-K ({ecart_dk:.1f}) < {ECART_DK_MIN} — B2 non confirme"})
        sig = 0

    score = params["base_score"]
    if regime == "CAS1_TENDANCE" and sig != 0:
        score = min(40 + adx, 100)

    direction = "BUY" if sig > 0 else "SELL" if sig < 0 else "ATTENTE"
    sl_pips = atr * params["sl_mult"]
    tp_pips = atr * params["tp_mult"]

    exit_signal = False
    if direction == "BUY" and stoch_k > 0.90:
        exit_signal = True
    elif direction == "SELL" and stoch_k < 0.10:
        exit_signal = True

    branch = ""
    if regime == "CAS5_SMC" and sig != 0:
        branch = detect_branch_cas5(closes, direction)

    pyramide = []
    if sig != 0:
        pyramide = calc_pyramide_levels(closes[-1], atr, direction)

    return {
        "cas": regime,
        "direction": direction,
        "score": round(score),
        "reasons": reasons,
        "sl_pips": round(sl_pips, 2),
        "tp_pips": round(tp_pips, 2),
        "atr": round(atr, 4),
        "adx": round(adx, 1),
        "stoch_k": round(stoch_k, 3),
        "stoch14_k": round(stoch14_k, 1),
        "stoch14_d": round(stoch14_d, 1),
        "ecart_dk": round(ecart_dk, 1),
        "faux_mouvement": faux_mouvement,
        "exit_signal": exit_signal,
        "branch": branch,
        "bb_width": round((bb_upper - bb_lower) / bb_mid * 100, 2) if bb_mid > 0 else 0,
        "macd": round(macd_main, 4),
        "macd_signal": round(macd_sig, 4),
        "pipeline": _get_pipeline_state(regime, sig, stoch_k, adx, stoch14_k, stoch14_d, ecart_dk, faux_mouvement, b1_active, b2_confirmed, branch),
        "pyramide": pyramide,
    }


def _no_signal(msg):
    return {
        "cas": "—",
        "direction": "ATTENTE",
        "score": 0,
        "reasons": [{"ok": False, "text": msg}],
        "sl_pips": 0,
        "tp_pips": 0,
        "atr": 0,
        "adx": 0,
        "stoch_k": 0.5,
        "stoch14_k": 50.0,
        "stoch14_d": 50.0,
        "ecart_dk": 0,
        "faux_mouvement": False,
        "exit_signal": False,
        "branch": "",
        "bb_width": 0,
        "macd": 0,
        "macd_signal": 0,
        "pipeline": {},
        "pyramide": [],
    }


def _get_pipeline_state(regime, sig, stoch_k, adx, stoch14_k=50, stoch14_d=50, ecart_dk=0, faux_mouvement=False, b1_active=False, b2_confirmed=False, branch=""):
    is_cas14 = regime in ("CAS1_TENDANCE", "CAS2_SCALPING", "CAS3_RANGE", "CAS4_CASSURE")
    cas_num = int(regime.split("_")[0][-1]) if regime[3:4].isdigit() else 0

    if is_cas14:
        return {
            "type": "CAS_1_4",
            "b1": {
                "active": b1_active and not faux_mouvement,
                "faux": faux_mouvement,
                "label": "B1",
                "detail": f"StochRSI {stoch_k:.3f}",
                "stoch14_k": round(stoch14_k, 1),
                "stoch14_d": round(stoch14_d, 1),
            },
            "b2": {
                "active": b2_confirmed,
                "label": "B2",
                "detail": f"Ecart D-K: {ecart_dk:.1f}",
                "ecart_ok": ecart_dk >= ECART_DK_MIN,
            },
            "cas": {
                "active": sig != 0,
                "label": f"CAS{cas_num}",
                "detail": f"ADX {adx:.1f}",
            },
            "b3": {
                "active": sig != 0,
                "label": "B3",
                "detail": "Confirme" if sig != 0 else "Attente",
            },
            "pyramide": {
                "active": sig != 0,
                "label": "P+",
                "detail": "Pyramide" if sig != 0 else "—",
            },
            "exit": {
                "active": stoch_k < 0.10 or stoch_k > 0.90,
                "label": "OUT",
                "detail": "K<0.10 fermer" if stoch_k < 0.10 else "K>0.90 fermer" if stoch_k > 0.90 else "Actif",
            },
        }

    return {
        "type": "CAS_5",
        "b1": {
            "active": True,
            "label": "B1",
            "detail": regime.replace("_", " "),
        },
        "b2": {
            "active": sig != 0,
            "label": "B2",
            "detail": f"StochRSI {stoch_k:.3f}",
        },
        "branch": {
            "active": sig != 0 and bool(branch),
            "label": f"BR-{branch}" if branch else "BR",
            "detail": "MA alignee" if branch == "A" else "MA non alignee" if branch == "B" else "—",
        },
        "confirm": {
            "active": sig != 0,
            "label": "1s",
            "detail": "Confirme" if sig != 0 else "Attente",
        },
        "entry": {
            "active": sig != 0,
            "label": "P1",
            "detail": "BUY" if sig > 0 else "SELL" if sig < 0 else "—",
        },
        "exit": {
            "active": False,
            "label": "OUT",
            "detail": "Conditions sortie",
        },
    }


# ── CAS signal functions ────────────────────────────────────────

def _get_cas1(closes, opens, highs, lows, stoch_k, adx, macd_m, macd_s):
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200)
    if not all([ema9, ema21, ema50, ema200]):
        return 0, []

    e9, e21, e50, e200 = ema9[-1], ema21[-1], ema50[-1], ema200[-1]
    trend_up = e9 > e21 > e50 > e200
    trend_dn = e9 < e21 < e50 < e200
    pullback_buy = stoch_k <= STOCHRSI_OS
    pullback_sell = stoch_k >= STOCHRSI_OB
    macd_bull = macd_m > macd_s
    macd_bear = macd_m < macd_s
    pa_bull = is_bullish_pa(opens, closes, highs, lows)
    pa_bear = is_bearish_pa(opens, closes, highs, lows)

    if trend_up and pullback_buy and macd_bull and pa_bull:
        return 1, [
            {"ok": True, "text": f"CAS1 : Tendance haussiere (EMA alignees)"},
            {"ok": True, "text": f"ADX {adx:.1f} > 25 confirme tendance"},
            {"ok": True, "text": f"StochRSI survendu ({stoch_k:.2f}) — timing BUY"},
            {"ok": True, "text": "MACD haussier"},
            {"ok": True, "text": "Price Action haussiere"},
        ]
    if trend_dn and pullback_sell and macd_bear and pa_bear:
        return -1, [
            {"ok": True, "text": f"CAS1 : Tendance baissiere (EMA alignees)"},
            {"ok": True, "text": f"ADX {adx:.1f} > 25 confirme tendance"},
            {"ok": True, "text": f"StochRSI surachete ({stoch_k:.2f}) — timing SELL"},
            {"ok": True, "text": "MACD baissier"},
            {"ok": True, "text": "Price Action baissiere"},
        ]

    reasons = [
        {"ok": trend_up or trend_dn, "text": "EMA alignees" if (trend_up or trend_dn) else "EMA non alignees"},
        {"ok": pullback_buy or pullback_sell, "text": f"StochRSI {stoch_k:.2f}"},
        {"ok": adx >= ADX_TREND, "text": f"ADX {adx:.1f}"},
    ]
    return 0, reasons


def _get_cas2(closes, opens, highs, lows, stoch_k):
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    if not ema9 or not ema21 or len(ema9) < 2 or len(ema21) < 2:
        return 0, []

    cross_up = ema9[-2] <= ema21[-2] and ema9[-1] > ema21[-1]
    cross_dn = ema9[-2] >= ema21[-2] and ema9[-1] < ema21[-1]
    pa_bull = is_bullish_pa(opens, closes, highs, lows)
    pa_bear = is_bearish_pa(opens, closes, highs, lows)

    if cross_up and stoch_k <= STOCHRSI_OS and pa_bull:
        return 1, [
            {"ok": True, "text": "CAS2 : Scalping BUY"},
            {"ok": True, "text": "EMA croisement haussier"},
            {"ok": True, "text": f"StochRSI survendu ({stoch_k:.2f})"},
            {"ok": True, "text": "Price Action haussiere"},
        ]
    if cross_dn and stoch_k >= STOCHRSI_OB and pa_bear:
        return -1, [
            {"ok": True, "text": "CAS2 : Scalping SELL"},
            {"ok": True, "text": "EMA croisement baissier"},
            {"ok": True, "text": f"StochRSI surachete ({stoch_k:.2f})"},
            {"ok": True, "text": "Price Action baissiere"},
        ]
    return 0, [{"ok": False, "text": "Scan scalping — attente croisement EMA"}]


def _get_cas3(closes, highs, lows, stoch_k, bb_lower, bb_upper, atr):
    bid = closes[-1]
    buy_range = abs(bid - bb_lower) <= atr * 0.8 and stoch_k <= STOCHRSI_OS
    sell_range = abs(bid - bb_upper) <= atr * 0.8 and stoch_k >= STOCHRSI_OB

    if buy_range:
        return 1, [
            {"ok": True, "text": "CAS3 : Range — prix sur BB bas"},
            {"ok": True, "text": "ADX < 20 marche consolide"},
            {"ok": True, "text": f"StochRSI survendu ({stoch_k:.2f})"},
            {"ok": True, "text": "Achat bas du range"},
        ]
    if sell_range:
        return -1, [
            {"ok": True, "text": "CAS3 : Range — prix sur BB haut"},
            {"ok": True, "text": "ADX < 20 marche consolide"},
            {"ok": True, "text": f"StochRSI surachete ({stoch_k:.2f})"},
            {"ok": True, "text": "Vente haut du range"},
        ]
    return 0, [{"ok": False, "text": "Range detecte — attente extremite BB"}]


def _get_cas4(closes, opens, highs, lows, atr):
    if len(closes) < 2 or atr == 0:
        return 0, []
    body = abs(closes[-1] - opens[-1])
    big_candle = body > atr * 1.5
    bos_bull = is_bullish_bos(highs, closes)
    bos_bear = is_bearish_bos(lows, closes)

    if bos_bull and big_candle and closes[-1] > opens[-1]:
        return 1, [
            {"ok": True, "text": "CAS4 : Cassure directe haussiere"},
            {"ok": True, "text": "Break of Structure (BOS) confirme"},
            {"ok": True, "text": f"Grande bougie ({body / atr:.1f}x ATR)"},
            {"ok": True, "text": "Entree sur momentum de cassure"},
        ]
    if bos_bear and big_candle and closes[-1] < opens[-1]:
        return -1, [
            {"ok": True, "text": "CAS4 : Cassure directe baissiere"},
            {"ok": True, "text": "Break of Structure (BOS) confirme"},
            {"ok": True, "text": f"Grande bougie ({body / atr:.1f}x ATR)"},
            {"ok": True, "text": "Entree sur momentum de cassure"},
        ]
    return 0, [{"ok": False, "text": "Cassure detectee — attente confirmation"}]


def _get_cas5(closes, opens, highs, lows, stoch_k):
    ob_b = is_bullish_ob(opens, closes, highs, lows)
    ob_s = is_bearish_ob(opens, closes, highs, lows)
    choch_b = is_bullish_choch(highs, lows, closes)
    choch_s = is_bearish_choch(highs, lows, closes)
    sh_b = is_bullish_sh(opens, closes, highs, lows)
    sh_s = is_bearish_sh(opens, closes, highs, lows)
    pa_bull = is_bullish_pa(opens, closes, highs, lows)
    pa_bear = is_bearish_pa(opens, closes, highs, lows)

    smc_bull = (2 if ob_b else 0) + (3 if choch_b else 0) + (3 if sh_b else 0)
    smc_bear = (2 if ob_s else 0) + (3 if choch_s else 0) + (3 if sh_s else 0)

    if smc_bull >= 3 and stoch_k <= STOCHRSI_OS and pa_bull:
        return 1, [
            {"ok": True, "text": "CAS5 : SMC — cassure indirecte haussiere"},
            {"ok": ob_b, "text": "Order Block haussier"},
            {"ok": choch_b, "text": "CHoCH haussier"},
            {"ok": sh_b, "text": "Stop Hunt haussier"},
            {"ok": True, "text": f"StochRSI survendu ({stoch_k:.2f})"},
        ]
    if smc_bear >= 3 and stoch_k >= STOCHRSI_OB and pa_bear:
        return -1, [
            {"ok": True, "text": "CAS5 : SMC — cassure indirecte baissiere"},
            {"ok": ob_s, "text": "Order Block baissier"},
            {"ok": choch_s, "text": "CHoCH baissier"},
            {"ok": sh_s, "text": "Stop Hunt baissier"},
            {"ok": True, "text": f"StochRSI surachete ({stoch_k:.2f})"},
        ]
    return 0, [{"ok": False, "text": "SMC scan — score insuffisant"}]


def _get_cas6(closes, opens, highs, lows, stoch_k, rsi_values):
    sh_b = is_bullish_sh(opens, closes, highs, lows)
    sh_s = is_bearish_sh(opens, closes, highs, lows)
    pa_bull = is_bullish_pa(opens, closes, highs, lows)
    pa_bear = is_bearish_pa(opens, closes, highs, lows)
    rsi = rsi_values[-1] if rsi_values else 50

    if stoch_k < 0.10 and sh_b and rsi < 35 and pa_bull:
        return 1, [
            {"ok": True, "text": "CAS6 : Retournement haussier"},
            {"ok": True, "text": f"StochRSI bloque bas ({stoch_k:.2f})"},
            {"ok": True, "text": "Stop Hunt — piege retourne"},
            {"ok": True, "text": f"RSI survendu ({rsi:.1f})"},
            {"ok": True, "text": "Price Action retournement"},
        ]
    if stoch_k > 0.90 and sh_s and rsi > 65 and pa_bear:
        return -1, [
            {"ok": True, "text": "CAS6 : Retournement baissier"},
            {"ok": True, "text": f"StochRSI bloque haut ({stoch_k:.2f})"},
            {"ok": True, "text": "Stop Hunt — piege retourne"},
            {"ok": True, "text": f"RSI surachete ({rsi:.1f})"},
            {"ok": True, "text": "Price Action retournement"},
        ]
    return 0, [{"ok": False, "text": "Retournement scan — conditions non reunies"}]


def _get_cas7(closes, opens, highs, lows, stoch_k, atr):
    fibo_b = is_on_fibo_level(highs, lows, closes, atr, "bull")
    fibo_s = is_on_fibo_level(highs, lows, closes, atr, "bear")
    ob_b = is_bullish_ob(opens, closes, highs, lows)
    ob_s = is_bearish_ob(opens, closes, highs, lows)
    pa_bull = is_bullish_pa(opens, closes, highs, lows)
    pa_bear = is_bearish_pa(opens, closes, highs, lows)

    if fibo_b and ob_b and stoch_k <= STOCHRSI_OS and pa_bull:
        return 1, [
            {"ok": True, "text": "CAS7 : Fibonacci confluence haussiere"},
            {"ok": True, "text": "Prix sur niveau Fibo cle"},
            {"ok": True, "text": "Order Block sur zone Fibo"},
            {"ok": True, "text": f"StochRSI survendu ({stoch_k:.2f})"},
        ]
    if fibo_s and ob_s and stoch_k >= STOCHRSI_OB and pa_bear:
        return -1, [
            {"ok": True, "text": "CAS7 : Fibonacci confluence baissiere"},
            {"ok": True, "text": "Prix sur niveau Fibo cle"},
            {"ok": True, "text": "Order Block sur zone Fibo"},
            {"ok": True, "text": f"StochRSI surachete ({stoch_k:.2f})"},
        ]
    return 0, [{"ok": False, "text": "Fibonacci scan — confluence insuffisante"}]


# ── Main analysis entry point ────────────────────────────────────

def analyze_symbol(account_id, token, symbol):
    candles = fetch_candles(account_id, token, symbol, "15m", 250)
    if not candles or len(candles) < 50:
        return _no_signal(f"Pas assez de bougies pour {symbol}")

    closes = [c["close"] for c in candles]
    opens = [c["open"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    signal = generate_signal(closes, opens, highs, lows)
    signal["asset"] = SYMBOL_LABELS.get(symbol, symbol)
    signal["symbol"] = symbol
    return signal


def analyze_all(account_id, token, symbols=None):
    if symbols is None:
        symbols = SYMBOLS

    if not is_within_trading_hours():
        return {
            "best": _no_signal("Hors heures de trading (8h-22h GMT)"),
            "all_signals": [],
            "trading_hours": False,
            "news_time": False,
        }

    if is_news_time():
        return {
            "best": _no_signal("Pause news — buffer de 30 minutes"),
            "all_signals": [],
            "trading_hours": True,
            "news_time": True,
        }

    all_signals = []
    best = None

    for sym in symbols:
        sig = analyze_symbol(account_id, token, sym)
        all_signals.append(sig)
        if sig["direction"] != "ATTENTE":
            if best is None or sig["score"] > best["score"]:
                best = sig

    return {
        "best": best if best else _no_signal("Scan en cours — aucun signal"),
        "all_signals": all_signals,
        "trading_hours": True,
        "news_time": False,
    }
