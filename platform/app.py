import logging
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

from flask import (
    Flask, render_template, redirect, url_for, request, flash, jsonify, abort,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user,
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

sys.path.insert(0, os.path.dirname(__file__))

from models import db, User, ActivationCode, TradingAccount
from crypto_utils import encrypt, decrypt
from trading_manager import TradingManager


def create_app():
    app = Flask(__name__)
    app.config.from_pyfile("config.py")

    os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)

    db.init_app(app)
    CSRFProtect(app)
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[app.config.get("RATELIMIT_DEFAULT", "200 per hour")],
        storage_uri=app.config.get("RATELIMIT_STORAGE_URI", "memory://"),
    )

    login_manager = LoginManager(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Veuillez vous connecter."
    login_manager.session_protection = "strong"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("smarttrader")

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    def _check_license(user):
        code = user.activation_code
        if not code or not code.expires_at:
            return True
        return datetime.now(timezone.utc) < code.expires_at.replace(tzinfo=timezone.utc)

    with app.app_context():
        db.create_all()
        admin_user = app.config.get("ADMIN_USERNAME", "admin")
        admin_pass = app.config.get("ADMIN_PASSWORD", "")
        if admin_pass and not User.query.filter_by(is_admin=True).first():
            admin = User(
                username=admin_user,
                password_hash=generate_password_hash(admin_pass),
                is_admin=True,
            )
            db.session.add(admin)
            db.session.commit()
            logger.info("Admin user '%s' created", admin_user)

    # ---------- Auth ----------

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    @limiter.limit("10 per minute")
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                if not user.is_active_account:
                    flash("Compte desactive. Contactez l'administrateur.", "error")
                    return render_template("login.html")
                login_user(user, remember=False)
                logger.info("User '%s' logged in", username)
                nxt = request.args.get("next")
                if nxt and nxt.startswith("/"):
                    return redirect(nxt)
                return redirect(url_for("dashboard"))
            logger.warning("Failed login attempt for '%s'", username)
            flash("Identifiants incorrects.", "error")
        return render_template("login.html")

    @app.route("/register", methods=["GET", "POST"])
    @limiter.limit("5 per minute")
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            code_str = request.form.get("activation_code", "").strip().upper()
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")

            if not code_str or not username or not password:
                flash("Tous les champs sont requis.", "error")
                return render_template("register.html")

            if len(username) < 3 or len(username) > 30:
                flash("Le nom d'utilisateur doit contenir entre 3 et 30 caracteres.", "error")
                return render_template("register.html")

            if not username.isalnum():
                flash("Le nom d'utilisateur ne doit contenir que des lettres et chiffres.", "error")
                return render_template("register.html")

            if password != confirm:
                flash("Les mots de passe ne correspondent pas.", "error")
                return render_template("register.html")

            if len(password) < 8:
                flash("Le mot de passe doit contenir au moins 8 caracteres.", "error")
                return render_template("register.html")

            if User.query.filter_by(username=username).first():
                flash("Ce nom d'utilisateur est deja pris.", "error")
                return render_template("register.html")

            code = ActivationCode.query.filter_by(code=code_str, is_used=False).first()
            if not code:
                flash("Code d'activation invalide ou deja utilise.", "error")
                return render_template("register.html")

            now = datetime.now(timezone.utc)
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                activation_code_id=code.id,
            )
            code.is_used = True
            code.used_by = username
            code.used_at = now
            code.expires_at = now + timedelta(days=code.max_days)

            db.session.add(user)
            db.session.commit()

            login_user(user, remember=False)
            logger.info("New user '%s' registered with code %s", username, code_str)
            flash("Compte cree ! Configurez vos identifiants trading.", "success")
            return redirect(url_for("setup_trading"))

        return render_template("register.html")

    @app.route("/logout")
    @login_required
    def logout():
        logger.info("User '%s' logged out", current_user.username)
        logout_user()
        return redirect(url_for("login"))

    # ---------- Dashboard ----------

    @app.route("/dashboard")
    @login_required
    def dashboard():
        if not _check_license(current_user):
            flash("Votre licence a expire. Contactez l'administrateur.", "error")
            return render_template("expired.html")

        account = TradingAccount.query.filter_by(user_id=current_user.id).first()
        status = TradingManager.get_status(current_user.id)
        code = current_user.activation_code
        expires = code.expires_at if code else None
        return render_template(
            "dashboard.html",
            account=account,
            status=status,
            expires=expires,
        )

    @app.route("/api/trading-data")
    @login_required
    @limiter.limit("60 per minute")
    def api_trading_data():
        data = TradingManager.get_trading_data(current_user.id)
        resp = jsonify(data)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    # ---------- Trading Setup ----------

    @app.route("/setup", methods=["GET", "POST"])
    @login_required
    def setup_trading():
        existing = TradingAccount.query.filter_by(user_id=current_user.id).first()

        if request.method == "POST":
            account_number = request.form.get("account_number", "").strip()
            password = request.form.get("trading_password", "")
            server = request.form.get("server", "").strip()

            if not account_number or not password or not server:
                flash("Tous les champs sont requis.", "error")
                return render_template("setup.html", account=existing)

            if not account_number.isdigit():
                flash("Le numero de compte doit etre numerique.", "error")
                return render_template("setup.html", account=existing)

            VALID_SERVERS = {
                "Exness-MT5Real", "Exness-MT5Real2", "Exness-MT5Real3",
                "Exness-MT5Real4", "Exness-MT5Real6", "Exness-MT5Real7",
                "Exness-MT5Real8", "Exness-MT5Real9",
                "Exness-MT5Trial", "Exness-MT5Trial2",
            }
            if server not in VALID_SERVERS:
                flash("Serveur invalide.", "error")
                return render_template("setup.html", account=existing)

            enc_number = encrypt(account_number)
            enc_password = encrypt(password)

            if existing:
                existing.account_number_enc = enc_number
                existing.password_enc = enc_password
                existing.server = server
                existing.status = "CONFIGURED"
                existing.metaapi_account_id = None
            else:
                acct = TradingAccount(
                    user_id=current_user.id,
                    account_number_enc=enc_number,
                    password_enc=enc_password,
                    server=server,
                )
                db.session.add(acct)

            db.session.commit()
            logger.info("User '%s' configured trading account on %s", current_user.username, server)
            flash("Identifiants trading enregistres (chiffres AES-256).", "success")
            return redirect(url_for("dashboard"))

        display_account = None
        if existing:
            try:
                num = decrypt(existing.account_number_enc)
                display_account = {"number_masked": num[:3] + "****" + num[-2:], "server": existing.server}
            except Exception:
                display_account = {"number_masked": "****", "server": existing.server}

        return render_template("setup.html", account=existing, display_account=display_account)

    # ---------- Trading Controls ----------

    @app.route("/api/start-trading", methods=["POST"])
    @login_required
    def start_trading():
        if not _check_license(current_user):
            return jsonify({"ok": False, "error": "Licence expiree"}), 403
        result = TradingManager.start_instance(current_user.id)
        return jsonify(result)

    @app.route("/api/stop-trading", methods=["POST"])
    @login_required
    def stop_trading():
        result = TradingManager.stop_instance(current_user.id)
        return jsonify(result)

    # ---------- Admin ----------

    @app.route("/admin")
    @login_required
    def admin_panel():
        if not current_user.is_admin:
            abort(403)
        users = User.query.all()
        codes = ActivationCode.query.order_by(ActivationCode.created_at.desc()).all()
        return render_template("admin.html", users=users, codes=codes)

    @app.route("/admin/generate-codes", methods=["POST"])
    @login_required
    def generate_codes():
        if not current_user.is_admin:
            abort(403)
        count = min(max(int(request.form.get("count", 1)), 1), 50)
        days = min(max(int(request.form.get("days", 30)), 1), 365)

        generated = []
        for _ in range(count):
            code_str = secrets.token_hex(4).upper()
            code = ActivationCode(code=code_str, max_days=days)
            db.session.add(code)
            generated.append(code_str)
        db.session.commit()

        logger.info("Admin generated %d activation codes (%d days)", count, days)
        flash(f"{count} code(s) generes : {', '.join(generated)}", "success")
        return redirect(url_for("admin_panel"))

    @app.route("/admin/toggle-user/<int:user_id>", methods=["POST"])
    @login_required
    def toggle_user(user_id):
        if not current_user.is_admin:
            abort(403)
        user = db.session.get(User, user_id)
        if user and not user.is_admin:
            user.is_active_account = not user.is_active_account
            if not user.is_active_account:
                TradingManager.stop_instance(user.id)
            db.session.commit()
            state = "active" if user.is_active_account else "desactive"
            logger.info("Admin toggled user '%s' -> %s", user.username, state)
            flash(f"Utilisateur {user.username} {state}.", "success")
        return redirect(url_for("admin_panel"))

    @app.route("/admin/extend-license/<int:user_id>", methods=["POST"])
    @login_required
    def extend_license(user_id):
        if not current_user.is_admin:
            abort(403)
        days = min(max(int(request.form.get("days", 30)), 1), 365)
        user = db.session.get(User, user_id)
        if user and user.activation_code:
            now = datetime.now(timezone.utc)
            current_exp = user.activation_code.expires_at
            if current_exp:
                base = current_exp.replace(tzinfo=timezone.utc)
                if base < now:
                    base = now
            else:
                base = now
            user.activation_code.expires_at = base + timedelta(days=days)
            db.session.commit()
            flash(f"Licence de {user.username} prolongee de {days} jours.", "success")
        return redirect(url_for("admin_panel"))

    # ---------- Error handlers ----------

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="Acces interdit"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Page introuvable"), 404

    @app.errorhandler(429)
    def rate_limited(e):
        return render_template("error.html", code=429, message="Trop de requetes. Reessayez dans quelques minutes."), 429

    @app.errorhandler(500)
    def server_error(e):
        logger.exception("Internal server error")
        return render_template("error.html", code=500, message="Erreur interne du serveur"), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_ENV") != "production")
