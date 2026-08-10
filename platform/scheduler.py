"""Background scheduler for autonomous auto-trade cycles.

Runs independently of user browser sessions. Every TRADE_INTERVAL_MIN
minutes, scans all accounts with auto_trade_enabled=True, skips news
hours, and executes the trade cycle.
"""

import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_scheduler_started = False
_lock = threading.Lock()


def start_scheduler(app):
    global _scheduler_started
    with _lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    from strategy_engine import TRADE_INTERVAL_MIN

    interval = TRADE_INTERVAL_MIN * 60

    def _run_cycle():
        while True:
            time.sleep(interval)
            try:
                _execute_cycle(app)
            except Exception:
                logger.exception("Scheduler cycle error")

    t = threading.Thread(target=_run_cycle, daemon=True, name="autotrade-scheduler")
    t.start()
    logger.info("Auto-trade scheduler started (every %d min)", TRADE_INTERVAL_MIN)


def _execute_cycle(app):
    with app.app_context():
        from models import TradingAccount, User, db
        from trading_manager import TradingManager

        accounts = (
            TradingAccount.query
            .filter_by(auto_trade_enabled=True, status="RUNNING")
            .all()
        )

        if not accounts:
            return

        now = datetime.now(timezone.utc)
        logger.info("Scheduler: scanning %d active accounts", len(accounts))

        for account in accounts:
            try:
                user = db.session.get(User, account.user_id)
                if not user or not user.is_active_account:
                    continue

                code = user.activation_code
                if code and code.expires_at:
                    exp = code.expires_at.replace(tzinfo=timezone.utc)
                    if now >= exp:
                        continue

                TradingManager.get_trading_data(account.user_id)
            except Exception:
                logger.exception("Scheduler: error on user_id=%d", account.user_id)
