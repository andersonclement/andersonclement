"""Manages MT5 trading instances per user via MetaApi cloud.

MetaApi (metaapi.cloud) connects to MetaTrader accounts in the cloud,
no local MT5 installation needed. Each user's credentials are decrypted
on-the-fly to provision a cloud account, then streamed for live data.

Set METAAPI_TOKEN in environment to enable cloud trading.
Without it, the manager runs in local-bridge mode (smarttrader_server.py).
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from models import TradingAccount, TradeHistory, db
from crypto_utils import decrypt
from risk_manager import get_risk_profile
from strategy_engine import analyze_all, SYMBOL_LABELS, CAS_PRIORITY

logger = logging.getLogger(__name__)

METAAPI_URL = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
METAAPI_DATA_URL = "https://mt-client-api-v1.agiliumtrade.agiliumtrade.ai"

FALLBACK_DATA = {
    "status": "DECONNECTE",
    "error": "Instance non demarree",
    "balance": 0, "equity": 0, "openPL": 0, "growth": 0,
    "drawdown": 0, "trades": 0, "winRate": 0, "winTrades": 0,
    "lossTrades": 0, "martingale": "Normal", "losses": 0,
    "initialBalance": 0, "peakEquity": 0, "currentCAS": "—",
    "prices": {},
    "signal": {"asset": "—", "type": "ATTENTE", "score": 0, "reasons": []},
    "lastAction": "", "positions": [],
    "log": [{"time": "—", "type": "INFO", "msg": "En attente de connexion"}],
}


def _metaapi_token():
    return os.environ.get("METAAPI_TOKEN", "")


def _api_call(method, url, token, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("auth-token", token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        logger.error("MetaApi %s %s -> %d: %s", method, url, e.code, body_text[:200])
        return {"error": body_text}, e.code
    except Exception as e:
        logger.error("MetaApi request failed: %s", e)
        return {"error": str(e)}, 0


class TradingManager:

    @classmethod
    def start_instance(cls, user_id: int) -> dict:
        account = TradingAccount.query.filter_by(user_id=user_id).first()
        if not account:
            return {"ok": False, "error": "Aucun compte trading configure"}

        try:
            acct_number = decrypt(account.account_number_enc)
            acct_password = decrypt(account.password_enc)
        except Exception:
            return {"ok": False, "error": "Erreur de dechiffrement des identifiants"}

        token = _metaapi_token()
        if token:
            result = cls._start_metaapi(account, acct_number, acct_password, token)
        else:
            result = cls._start_local(account, acct_number)

        if result["ok"]:
            account.status = "RUNNING"
            account.last_seen = datetime.now(timezone.utc)
            db.session.commit()

        return result

    @classmethod
    def _start_metaapi(cls, account, acct_number, acct_password, token):
        if account.metaapi_account_id:
            deploy_url = f"{METAAPI_URL}/users/current/accounts/{account.metaapi_account_id}/deploy"
            resp, status = _api_call("POST", deploy_url, token)
            if status in (200, 204, 409):
                logger.info("MetaApi account %s deployed", account.metaapi_account_id)
                return {"ok": True, "message": "Instance MetaApi demarree"}
            logger.warning("Deploy failed (%d), re-provisioning", status)

        provision_body = {
            "name": f"SmartTrader-{account.user_id}",
            "type": "cloud",
            "login": acct_number,
            "password": acct_password,
            "server": account.server,
            "platform": account.platform or "mt5",
        }
        resp, status = _api_call(
            "POST", f"{METAAPI_URL}/users/current/accounts", token, provision_body
        )
        if status not in (200, 201):
            return {"ok": False, "error": f"MetaApi provisioning echoue: {resp.get('error', status)}"}

        account.metaapi_account_id = resp.get("id")
        db.session.commit()

        deploy_url = f"{METAAPI_URL}/users/current/accounts/{account.metaapi_account_id}/deploy"
        _api_call("POST", deploy_url, token)

        logger.info("MetaApi provisioned account %s for user %d", account.metaapi_account_id, account.user_id)
        return {"ok": True, "message": "Instance MetaApi provisionnee et demarree"}

    @classmethod
    def _start_local(cls, account, acct_number):
        logger.info("Local mode: trading started for account %s on %s", acct_number[:4] + "****", account.server)
        return {"ok": True, "message": "Instance demarree (mode local)"}

    @classmethod
    def stop_instance(cls, user_id: int) -> dict:
        account = TradingAccount.query.filter_by(user_id=user_id).first()
        if not account:
            return {"ok": True, "message": "Aucun compte"}

        token = _metaapi_token()
        if token and account.metaapi_account_id:
            undeploy_url = f"{METAAPI_URL}/users/current/accounts/{account.metaapi_account_id}/undeploy"
            _api_call("POST", undeploy_url, token)

        account.status = "STOPPED"
        db.session.commit()
        return {"ok": True, "message": "Instance arretee"}

    @classmethod
    def get_status(cls, user_id: int) -> str:
        account = TradingAccount.query.filter_by(user_id=user_id).first()
        if not account:
            return "NOT_CONFIGURED"

        token = _metaapi_token()
        if token and account.metaapi_account_id and account.status == "RUNNING":
            url = f"{METAAPI_URL}/users/current/accounts/{account.metaapi_account_id}"
            resp, status = _api_call("GET", url, token)
            if status == 200:
                state = resp.get("state", "")
                if state == "DEPLOYED":
                    return "RUNNING"
                if state == "DEPLOYING":
                    return "STARTING"
                return "STOPPED"

        return account.status

    @classmethod
    def get_trading_data(cls, user_id: int) -> dict:
        account = TradingAccount.query.filter_by(user_id=user_id).first()
        if not account or account.status not in ("RUNNING", "STARTING"):
            return FALLBACK_DATA.copy()

        token = _metaapi_token()
        if token and account.metaapi_account_id:
            return cls._get_metaapi_data(account, token)

        if account.bridge_port:
            try:
                url = f"http://127.0.0.1:{account.bridge_port}/data"
                with urllib.request.urlopen(url, timeout=3) as resp:
                    return json.loads(resp.read().decode())
            except Exception:
                pass

        data = FALLBACK_DATA.copy()
        data["status"] = "ACTIF"
        data["log"] = [{"time": "—", "type": "INFO", "msg": "Connecte au serveur"}]
        return data

    @classmethod
    def _execute_order(cls, account, token, symbol, direction, lot, sl_price, tp_price):
        acct_id = account.metaapi_account_id
        trade_url = f"{METAAPI_DATA_URL}/users/current/accounts/{acct_id}/trade"
        action = "ORDER_TYPE_BUY" if direction == "BUY" else "ORDER_TYPE_SELL"
        body = {
            "actionType": action,
            "symbol": symbol,
            "volume": round(lot, 2),
        }
        if sl_price > 0:
            body["stopLoss"] = round(sl_price, 5)
        if tp_price > 0:
            body["takeProfit"] = round(tp_price, 5)

        resp, status = _api_call("POST", trade_url, token, body)
        if status in (200, 201):
            logger.info("Order executed: %s %s %.2f lots on %s", direction, symbol, lot, account.server)
            return True, resp
        logger.error("Order failed (%d): %s", status, resp.get("error", ""))
        return False, resp

    @classmethod
    def _close_position(cls, account, token, position_id):
        acct_id = account.metaapi_account_id
        trade_url = f"{METAAPI_DATA_URL}/users/current/accounts/{acct_id}/trade"
        body = {
            "actionType": "POSITION_CLOSE_ID",
            "positionId": position_id,
        }
        resp, status = _api_call("POST", trade_url, token, body)
        if status in (200, 201):
            logger.info("Position %s closed", position_id)
            return True
        logger.error("Close position failed (%d): %s", status, resp.get("error", ""))
        return False

    @classmethod
    def _get_metaapi_data(cls, account, token):
        acct_id = account.metaapi_account_id
        info_url = f"{METAAPI_DATA_URL}/users/current/accounts/{acct_id}/account-information"
        resp, status = _api_call("GET", info_url, token)

        if status != 200:
            data = FALLBACK_DATA.copy()
            data["status"] = "CONNEXION"
            data["log"] = [{"time": "—", "type": "WARN", "msg": "Connexion MetaApi en cours..."}]
            return data

        pos_url = f"{METAAPI_DATA_URL}/users/current/accounts/{acct_id}/positions"
        pos_resp, _ = _api_call("GET", pos_url, token)

        balance = resp.get("balance", 0)
        equity = resp.get("equity", 0)
        initial = balance
        positions = []
        open_pl = 0

        if isinstance(pos_resp, list):
            for p in pos_resp:
                pl = p.get("unrealizedProfit", p.get("profit", 0))
                open_pl += pl
                positions.append({
                    "asset": p.get("symbol", "?"),
                    "dir": p.get("type", "BUY").replace("POSITION_TYPE_", ""),
                    "type": p.get("comment", ""),
                    "lot": p.get("volume", 0),
                    "entry": p.get("openPrice", 0),
                    "sl": p.get("stopLoss", 0),
                    "tp": p.get("takeProfit", 0),
                    "pl": pl,
                })

        growth = ((equity - initial) / initial * 100) if initial > 0 else 0

        risk = get_risk_profile(account.user_id, balance)

        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log_entries = [
            {"time": now_str, "type": "INFO", "msg": f"Balance: {balance:.2f} | Equity: {equity:.2f}"},
        ]

        analysis = None
        signal_data = {"asset": "—", "type": "ATTENTE", "score": 0, "reasons": []}
        current_cas = "—"
        pipeline = {}

        try:
            analysis = analyze_all(acct_id, token)
            best = analysis.get("best", {})
            if best.get("direction", "ATTENTE") != "ATTENTE":
                signal_data = {
                    "asset": best.get("asset", "—"),
                    "type": best.get("direction", "ATTENTE"),
                    "score": best.get("score", 0),
                    "reasons": best.get("reasons", []),
                }
                current_cas = best.get("cas", "—")
                log_entries.append({"time": now_str, "type": best["direction"], "msg": f"{best['cas']} {best['direction']} {best.get('asset', '')} score={best['score']}"})
            else:
                signal_data["reasons"] = best.get("reasons", [])
                current_cas = best.get("cas", "—")

            pipeline = best.get("pipeline", {})

            if not analysis.get("trading_hours", True):
                log_entries.append({"time": now_str, "type": "INFO", "msg": "Hors heures de trading (8h-22h GMT)"})
            elif analysis.get("news_time", False):
                log_entries.append({"time": now_str, "type": "WARN", "msg": "Pause news — buffer 30 min"})

            for sig in analysis.get("all_signals", []):
                if sig.get("direction") != "ATTENTE":
                    log_entries.append({"time": now_str, "type": "INFO", "msg": f"{sig.get('symbol', '?')}: {sig['cas']} {sig['direction']} score={sig['score']}"})
        except Exception as e:
            logger.warning("Strategy analysis failed: %s", e)
            log_entries.append({"time": now_str, "type": "WARN", "msg": "Analyse strategie en cours..."})

        if risk:
            log_entries.append({"time": now_str, "type": "INFO", "msg": f"Risque: {risk['risk_percent']}% | Lot: {risk['recommended_lots']['sl_30_pips']} | Tier: {risk['tier']}"})
            if not risk["can_trade"]:
                log_entries.append({"time": now_str, "type": "WARN", "msg": f"Limite perte journaliere atteinte ({risk['max_daily_loss_pct']}%)"})

        indicators = {}
        cas_evaluations = {}
        if analysis and analysis.get("best"):
            b = analysis["best"]
            indicators = {
                "stochRSI_K": b.get("stoch_k", 0),
                "stoch14_K": b.get("stoch14_k", 50),
                "stoch14_D": b.get("stoch14_d", 50),
                "ecart_dk": b.get("ecart_dk", 0),
                "adx": b.get("adx", 0),
                "atr": b.get("atr", 0),
                "bb_width": b.get("bb_width", 0),
                "macd": b.get("macd", 0),
                "macd_signal": b.get("macd_signal", 0),
            }
            cas_evaluations = b.get("cas_evaluations", {})

        if account.auto_trade_enabled and analysis and risk and risk.get("can_trade"):
            cls._auto_trade_cycle(account, token, analysis, risk, balance, positions, log_entries, now_str)

        return {
            "status": "ACTIF",
            "balance": balance,
            "equity": equity,
            "openPL": open_pl,
            "growth": round(growth, 2),
            "drawdown": 0,
            "trades": 0,
            "winRate": 0,
            "winTrades": 0,
            "lossTrades": 0,
            "martingale": "Normal",
            "losses": 0,
            "initialBalance": initial,
            "peakEquity": equity,
            "currentCAS": current_cas,
            "prices": {},
            "signal": signal_data,
            "lastAction": "",
            "positions": positions,
            "risk": risk,
            "indicators": indicators,
            "pipeline": pipeline,
            "cas_evaluations": cas_evaluations,
            "auto_trade": account.auto_trade_enabled,
            "faux_mouvement": analysis.get("best", {}).get("faux_mouvement", False) if analysis else False,
            "exit_signal": analysis.get("best", {}).get("exit_signal", False) if analysis else False,
            "branch": analysis.get("best", {}).get("branch", "") if analysis else "",
            "pyramide": analysis.get("best", {}).get("pyramide", []) if analysis else [],
            "log": log_entries,
        }

    @classmethod
    def _auto_trade_cycle(cls, account, token, analysis, risk, balance, positions, log_entries, now_str):
        best = analysis.get("best", {})
        direction = best.get("direction", "ATTENTE")
        exit_signal = best.get("exit_signal", False)
        acct_id = account.metaapi_account_id

        if exit_signal and positions:
            pos_url = f"{METAAPI_DATA_URL}/users/current/accounts/{acct_id}/positions"
            pos_resp, _ = _api_call("GET", pos_url, token)
            if isinstance(pos_resp, list):
                for p in pos_resp:
                    pid = p.get("id")
                    if pid:
                        closed = cls._close_position(account, token, pid)
                        if closed:
                            profit = p.get("unrealizedProfit", p.get("profit", 0))
                            trade = TradeHistory(
                                user_id=account.user_id,
                                symbol=p.get("symbol", "?"),
                                direction=p.get("type", "BUY").replace("POSITION_TYPE_", ""),
                                cas=best.get("cas", ""),
                                lot_size=p.get("volume", 0),
                                entry_price=p.get("openPrice", 0),
                                exit_price=p.get("currentPrice", 0),
                                sl=p.get("stopLoss", 0),
                                tp=p.get("takeProfit", 0),
                                profit=profit,
                                status="CLOSED",
                                closed_at=datetime.now(timezone.utc),
                            )
                            db.session.add(trade)
                            log_entries.append({"time": now_str, "type": "INFO", "msg": f"Auto-close: {p.get('symbol', '?')} P&L={profit:.2f}"})
                db.session.commit()
            return

        if direction not in ("BUY", "SELL"):
            return

        max_pos = risk.get("max_positions", 3)
        if len(positions) >= max_pos:
            log_entries.append({"time": now_str, "type": "WARN", "msg": f"Max positions ({max_pos}) atteint"})
            return

        symbol = best.get("symbol", "")
        if not symbol:
            return

        already_open = any(p.get("asset") == symbol for p in positions)
        if already_open:
            return

        lots = risk.get("recommended_lots", {})
        lot = lots.get("sl_30_pips", 0.01)
        sl_pips = best.get("sl_pips", 0)
        tp_pips = best.get("tp_pips", 0)
        entry = best.get("pyramide", [{}])[0].get("price", 0) if best.get("pyramide") else 0

        if entry <= 0:
            return

        if direction == "BUY":
            sl_price = entry - sl_pips
            tp_price = entry + tp_pips
        else:
            sl_price = entry + sl_pips
            tp_price = entry - tp_pips

        ok, resp = cls._execute_order(account, token, symbol, direction, lot, sl_price, tp_price)
        if ok:
            trade = TradeHistory(
                user_id=account.user_id,
                symbol=symbol,
                direction=direction,
                cas=best.get("cas", ""),
                lot_size=lot,
                entry_price=entry,
                sl=sl_pips,
                tp=tp_pips,
                status="OPEN",
            )
            db.session.add(trade)
            db.session.commit()
            log_entries.append({"time": now_str, "type": direction, "msg": f"Auto-trade: {direction} {symbol} {lot} lots — {best.get('cas', '')}"})
        else:
            log_entries.append({"time": now_str, "type": "WARN", "msg": f"Auto-trade echoue: {resp.get('error', 'erreur inconnue')[:60]}"})
