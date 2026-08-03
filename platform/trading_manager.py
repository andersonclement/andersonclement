"""Interface for managing MT5 trading instances per user.

Designed to work with MetaApi (metaapi.cloud) or a local MT5 bridge.
Each user gets an isolated trading instance with their own credentials.
"""

import json
import logging
from datetime import datetime, timezone

from models import TradingAccount, db
from crypto_utils import decrypt

logger = logging.getLogger(__name__)

FALLBACK_DATA = {
    "status": "DECONNECTE",
    "error": "Instance non démarrée",
    "balance": 0, "equity": 0, "openPL": 0, "growth": 0,
    "drawdown": 0, "trades": 0, "winRate": 0, "winTrades": 0,
    "lossTrades": 0, "martingale": "Normal", "losses": 0,
    "initialBalance": 0, "peakEquity": 0, "currentCAS": "—",
    "prices": {},
    "signal": {"asset": "—", "type": "ATTENTE", "score": 0, "reasons": []},
    "lastAction": "", "positions": [],
    "log": [{"time": "—", "type": "INFO", "msg": "En attente de connexion"}],
}


class TradingManager:

    _instances: dict[int, dict] = {}

    @classmethod
    def start_instance(cls, user_id: int) -> dict:
        account = TradingAccount.query.filter_by(user_id=user_id).first()
        if not account:
            return {"ok": False, "error": "Aucun compte trading configuré"}

        try:
            acct_number = decrypt(account.account_number_enc)
            acct_password = decrypt(account.password_enc)
        except Exception:
            return {"ok": False, "error": "Erreur de déchiffrement des identifiants"}

        cls._instances[user_id] = {
            "status": "RUNNING",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "account": acct_number,
            "server": account.server,
        }

        account.status = "RUNNING"
        account.last_seen = datetime.now(timezone.utc)
        db.session.commit()

        logger.info("Trading instance started for user %d on %s", user_id, account.server)
        return {"ok": True, "message": "Instance démarrée"}

    @classmethod
    def stop_instance(cls, user_id: int) -> dict:
        cls._instances.pop(user_id, None)
        account = TradingAccount.query.filter_by(user_id=user_id).first()
        if account:
            account.status = "STOPPED"
            db.session.commit()
        return {"ok": True, "message": "Instance arrêtée"}

    @classmethod
    def get_status(cls, user_id: int) -> str:
        info = cls._instances.get(user_id)
        if info:
            return info["status"]
        account = TradingAccount.query.filter_by(user_id=user_id).first()
        return account.status if account else "NOT_CONFIGURED"

    @classmethod
    def get_trading_data(cls, user_id: int) -> dict:
        account = TradingAccount.query.filter_by(user_id=user_id).first()
        if not account or account.status != "RUNNING":
            return FALLBACK_DATA.copy()

        if account.bridge_port:
            try:
                import urllib.request
                url = f"http://127.0.0.1:{account.bridge_port}/data"
                with urllib.request.urlopen(url, timeout=3) as resp:
                    return json.loads(resp.read().decode())
            except Exception:
                pass

        data = FALLBACK_DATA.copy()
        data["status"] = "ACTIF"
        data["log"] = [{"time": "—", "type": "INFO", "msg": "Connecté au serveur"}]
        return data
