#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  SmartTrader Bridge Server v1.1
#  Lit smarttrader_data.json depuis MT5 et le sert au dashboard
# ═══════════════════════════════════════════════════════════════
#
#  INSTALLATION : Aucune — Python est deja sur Windows
#  LANCEMENT    : Double-cliquer sur ce fichier, ou :
#                 python smarttrader_server.py
#
#  PREREQUIS    : MetaTrader 5 doit etre ouvert avec l'EA actif
# ═══════════════════════════════════════════════════════════════

import os
import sys
import json
import glob
import time
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────
PORT = 8765
JSON_FILENAME = "smarttrader_data.json"

MT5_PATHS = [
    os.path.expandvars(r"%APPDATA%\MetaQuotes\Terminal\Common\Files"),
    os.path.expandvars(r"%APPDATA%\MetaQuotes\Terminal\Common\files"),
    os.path.expandvars(r"%LOCALAPPDATA%\MetaQuotes\Terminal\Common\Files"),
    r"C:\Program Files\MetaTrader 5\MQL5\Files",
    r"C:\Program Files (x86)\MetaTrader 5\MQL5\Files",
]

TERMINAL_BASE = os.path.expandvars(r"%APPDATA%\MetaQuotes\Terminal")

# ── Thread-safe cache ─────────────────────────────────────────
_cache_lock = threading.Lock()

json_cache = {
    "data": None,
    "path": None,
    "last_mtime": 0,
    "last_check": 0,
}

def find_json_file():
    script_dir = Path(__file__).parent
    local = script_dir / JSON_FILENAME
    if local.exists():
        return str(local)

    for path in MT5_PATHS:
        candidate = Path(path) / JSON_FILENAME
        if candidate.exists():
            return str(candidate)

    if os.path.exists(TERMINAL_BASE):
        pattern = os.path.join(TERMINAL_BASE, "*", "MQL5", "Files", JSON_FILENAME)
        matches = glob.glob(pattern)
        if matches:
            return max(matches, key=os.path.getmtime)

        pattern2 = os.path.join(TERMINAL_BASE, "Common", "Files", JSON_FILENAME)
        if os.path.exists(pattern2):
            return pattern2

    return None

def get_json_data():
    now = time.time()
    with _cache_lock:
        if not json_cache["path"] or now - json_cache["last_check"] > 10:
            json_cache["path"] = find_json_file()
            json_cache["last_check"] = now

        if not json_cache["path"]:
            return None, "Fichier smarttrader_data.json introuvable. Verifiez que l'EA est actif dans MT5."

        try:
            mtime = os.path.getmtime(json_cache["path"])
            if mtime != json_cache["last_mtime"]:
                with open(json_cache["path"], "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        json.loads(content)
                        json_cache["data"] = content
                        json_cache["last_mtime"] = mtime
        except json.JSONDecodeError:
            if json_cache["data"]:
                return json_cache["data"], None
            return None, "Fichier JSON corrompu (ecriture partielle par MT5)"
        except Exception as e:
            return None, f"Erreur lecture: {e}"

        if json_cache["data"]:
            return json_cache["data"], None
        return None, "Fichier vide"

# ── HTTP Handler ───────────────────────────────────────────────
class BridgeHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        if "200" not in str(args):
            super().log_message(format, *args)

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/data":
            data, error = get_json_data()

            if data:
                body = data.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)
            else:
                err_body = json.dumps({
                    "status": "DECONNECTE",
                    "error": error,
                    "balance": 0, "equity": 0, "openPL": 0,
                    "growth": 0, "drawdown": 0, "trades": 0,
                    "winRate": 0, "winTrades": 0, "lossTrades": 0,
                    "martingale": "Normal", "losses": 0,
                    "initialBalance": 0, "peakEquity": 0,
                    "currentCAS": "—",
                    "prices": {},
                    "signal": {"asset": "—", "type": "ATTENTE", "score": 0, "reasons": []},
                    "lastAction": error or "",
                    "positions": [],
                    "log": [{"time": time.strftime("%H:%M:%S"), "type": "WARN", "msg": error or "Pas de donnees"}]
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_cors_headers()
                self.send_header("Content-Length", len(err_body))
                self.end_headers()
                self.wfile.write(err_body)

        elif path == "/status":
            json_path = find_json_file()
            status = {
                "server": "SmartTrader Bridge v1.1",
                "port": PORT,
                "json_found": json_path is not None,
                "json_path": json_path or "introuvable",
                "last_update": time.strftime("%H:%M:%S", time.localtime(json_cache["last_mtime"])) if json_cache["last_mtime"] else "jamais",
            }
            body = json.dumps(status, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

# ── Console UI ─────────────────────────────────────────────────
def print_banner(json_path):
    os.system("cls" if os.name == "nt" else "clear")
    print("+" + "=" * 54 + "+")
    print("|        SmartTrader 7CAS - Bridge Server v1.1        |")
    print("+" + "=" * 54 + "+")
    print(f"|  Port     : http://localhost:{PORT}                   |")
    if json_path:
        short = "..." + json_path[-42:] if len(json_path) > 45 else json_path
        print(f"|  JSON     : Trouve                                  |")
        print(f"|  Chemin   : {short[:51]:<51}|")
    else:
        print("|  JSON     : Introuvable - verifiez l'EA MT5         |")
    print("+" + "=" * 54 + "+")
    print("|  Ouvrez le dashboard dans votre navigateur           |")
    print("|  Appuyez sur Ctrl+C pour arreter                     |")
    print("+" + "=" * 54 + "+")
    print()

def monitor_loop():
    while True:
        time.sleep(5)
        data, error = get_json_data()
        ts = time.strftime("%H:%M:%S")
        if data:
            try:
                d = json.loads(data)
                bal = d.get("balance", 0)
                eq = d.get("equity", 0)
                status = d.get("status", "?")
                cas = d.get("currentCAS", "—")
                pos = len(d.get("positions", []))
                print(f"[{ts}] OK {status} | Bal: ${bal:.2f} | Eq: ${eq:.2f} | CAS: {cas} | Positions: {pos}")
            except json.JSONDecodeError:
                print(f"[{ts}] WARN JSON invalide")
        else:
            print(f"[{ts}] ERR {error}")

# ── Main ───────────────────────────────────────────────────────
if __name__ == "__main__":
    json_path = find_json_file()
    print_banner(json_path)

    if not json_path:
        print("ATTENTION : Fichier JSON introuvable !")
        print("   Assurez-vous que :")
        print("   1. MetaTrader 5 est ouvert")
        print("   2. L'EA SmartTrader_7CAS est actif sur un graphique")
        print("   3. L'option 'Autoriser DLL' est activee dans MT5")
        print()
        print("   Le serveur va continuer a chercher le fichier...")
        print()

    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

    dashboard_path = Path(__file__).parent / "SmartTrader_Dashboard.html"
    if dashboard_path.exists():
        threading.Timer(1.0, lambda: webbrowser.open(str(dashboard_path))).start()
    else:
        print(f"Dashboard HTML non trouve : {dashboard_path}")
        print("   Placez SmartTrader_Dashboard.html dans le meme dossier.")

    server = HTTPServer(("localhost", PORT), BridgeHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\nServeur arrete proprement.")
        sys.exit(0)
