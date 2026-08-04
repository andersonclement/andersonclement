"""Dynamic risk management engine.

Calculates lot sizes and enforces risk limits per user account balance.
Adapts automatically: small accounts get micro-lots, large accounts scale up,
and daily loss limits halt trading before catastrophic drawdown.
"""

import logging
import math
from datetime import datetime, timezone

from models import TradingAccount, db

logger = logging.getLogger(__name__)

PIP_VALUES = {
    "EURUSD": 10.0, "GBPUSD": 10.0, "AUDUSD": 10.0, "NZDUSD": 10.0,
    "USDJPY": 6.7, "USDCHF": 10.5, "USDCAD": 7.3,
    "EURGBP": 12.5, "EURJPY": 6.7, "GBPJPY": 6.7,
    "XAUUSD": 10.0, "XAGUSD": 50.0,
}

RISK_TIERS = [
    (100,    0.5, 1, 3.0),
    (500,    1.0, 2, 5.0),
    (2000,   1.5, 3, 5.0),
    (10000,  2.0, 4, 5.0),
    (50000,  2.0, 5, 5.0),
]


def get_risk_tier(balance):
    for threshold, risk_pct, max_pos, max_daily in RISK_TIERS:
        if balance < threshold:
            return risk_pct, max_pos, max_daily
    return 2.0, 5, 5.0


def calculate_lot_size(balance, risk_percent, sl_pips, symbol="EURUSD"):
    if balance <= 0 or sl_pips <= 0:
        return 0.01

    risk_amount = balance * (risk_percent / 100.0)
    pip_value_per_lot = PIP_VALUES.get(symbol.upper(), 10.0)
    raw_lot = risk_amount / (sl_pips * pip_value_per_lot)

    lot = math.floor(raw_lot * 100) / 100
    lot = max(0.01, min(lot, 100.0))

    max_lot_by_balance = balance / 1000.0
    lot = min(lot, max(0.01, math.floor(max_lot_by_balance * 100) / 100))

    return lot


def get_risk_profile(user_id, balance=None):
    account = TradingAccount.query.filter_by(user_id=user_id).first()
    if not account:
        return None

    if balance is None:
        balance = 0

    tier_risk, tier_max_pos, tier_max_daily = get_risk_tier(balance)

    user_risk = account.risk_percent or tier_risk
    user_max_pos = account.max_positions or tier_max_pos
    user_max_daily = account.max_daily_loss_pct or tier_max_daily

    effective_risk = min(user_risk, tier_risk + 1.0)
    effective_max_pos = min(user_max_pos, tier_max_pos + 2)
    effective_max_daily = min(user_max_daily, 10.0)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if account.daily_loss_date != today:
        account.daily_loss_realized = 0.0
        account.daily_loss_date = today
        db.session.commit()

    daily_loss_used = account.daily_loss_realized or 0.0
    daily_loss_pct_used = (daily_loss_used / balance * 100) if balance > 0 else 0
    daily_limit_remaining = effective_max_daily - daily_loss_pct_used
    can_trade = daily_limit_remaining > 0.2

    lot_20 = calculate_lot_size(balance, effective_risk, 20)
    lot_30 = calculate_lot_size(balance, effective_risk, 30)
    lot_50 = calculate_lot_size(balance, effective_risk, 50)

    if balance < 100:
        tier_name = "Micro"
    elif balance < 500:
        tier_name = "Mini"
    elif balance < 2000:
        tier_name = "Standard"
    elif balance < 10000:
        tier_name = "Premium"
    else:
        tier_name = "VIP"

    return {
        "tier": tier_name,
        "balance": balance,
        "risk_percent": effective_risk,
        "max_positions": effective_max_pos,
        "max_daily_loss_pct": effective_max_daily,
        "daily_loss_used": round(daily_loss_pct_used, 2),
        "daily_limit_remaining": round(max(0, daily_limit_remaining), 2),
        "can_trade": can_trade,
        "recommended_lots": {
            "sl_20_pips": lot_20,
            "sl_30_pips": lot_30,
            "sl_50_pips": lot_50,
        },
        "max_risk_amount": round(balance * effective_risk / 100, 2),
    }


def record_trade_loss(user_id, loss_amount):
    if loss_amount <= 0:
        return
    account = TradingAccount.query.filter_by(user_id=user_id).first()
    if not account:
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if account.daily_loss_date != today:
        account.daily_loss_realized = 0.0
        account.daily_loss_date = today

    account.daily_loss_realized = (account.daily_loss_realized or 0) + abs(loss_amount)
    db.session.commit()
    logger.info("User %d daily loss updated: $%.2f", user_id, account.daily_loss_realized)


def update_risk_settings(user_id, risk_percent=None, max_positions=None, max_daily_loss_pct=None):
    account = TradingAccount.query.filter_by(user_id=user_id).first()
    if not account:
        return False

    if risk_percent is not None:
        account.risk_percent = max(0.1, min(float(risk_percent), 5.0))
    if max_positions is not None:
        account.max_positions = max(1, min(int(max_positions), 10))
    if max_daily_loss_pct is not None:
        account.max_daily_loss_pct = max(1.0, min(float(max_daily_loss_pct), 10.0))

    db.session.commit()
    return True
