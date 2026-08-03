import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

from flask import (
    Flask, render_template, redirect, url_for, request, flash, jsonify, abort,
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

sys.path.insert(0, os.path.dirname(__file__))

from models import db, User, ActivationCode, TradingAccount
from crypto_utils import encrypt, decrypt
from trading_manager import TradingManager

app = Flask(__name__)
app.config.from_pyfile("config.py")

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Veuillez vous connecter."


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


with app.app_context():
    db.create_all()
    if not User.query.filter_by(is_admin=True).first():
        admin = User(
            username="admin",
            password_hash=generate_password_hash("admin7cas"),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()


# ---------- Auth ----------

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            if not user.is_active_account:
                flash("Compte désactivé. Contactez l'administrateur.", "error")
                return render_template("login.html")
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Identifiants incorrects.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
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

        if password != confirm:
            flash("Les mots de passe ne correspondent pas.", "error")
            return render_template("register.html")

        if len(password) < 6:
            flash("Le mot de passe doit contenir au moins 6 caractères.", "error")
            return render_template("register.html")

        if User.query.filter_by(username=username).first():
            flash("Ce nom d'utilisateur est déjà pris.", "error")
            return render_template("register.html")

        code = ActivationCode.query.filter_by(code=code_str, is_used=False).first()
        if not code:
            flash("Code d'activation invalide ou déjà utilisé.", "error")
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

        login_user(user)
        flash("Compte créé avec succès ! Configurez vos identifiants trading.", "success")
        return redirect(url_for("setup_trading"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ---------- Dashboard ----------

@app.route("/dashboard")
@login_required
def dashboard():
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

        enc_number = encrypt(account_number)
        enc_password = encrypt(password)

        if existing:
            existing.account_number_enc = enc_number
            existing.password_enc = enc_password
            existing.server = server
            existing.status = "CONFIGURED"
        else:
            account = TradingAccount(
                user_id=current_user.id,
                account_number_enc=enc_number,
                password_enc=enc_password,
                server=server,
            )
            db.session.add(account)

        db.session.commit()
        flash("Identifiants trading enregistrés (chiffrés).", "success")
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
    count = int(request.form.get("count", 1))
    days = int(request.form.get("days", 30))
    count = max(1, min(count, 50))

    generated = []
    for _ in range(count):
        code_str = secrets.token_hex(4).upper()
        code = ActivationCode(code=code_str, max_days=days)
        db.session.add(code)
        generated.append(code_str)
    db.session.commit()

    flash(f"{count} code(s) générés : {', '.join(generated)}", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/toggle-user/<int:user_id>", methods=["POST"])
@login_required
def toggle_user(user_id):
    if not current_user.is_admin:
        abort(403)
    user = db.session.get(User, user_id)
    if user and not user.is_admin:
        user.is_active_account = not user.is_active_account
        db.session.commit()
        state = "activé" if user.is_active_account else "désactivé"
        flash(f"Utilisateur {user.username} {state}.", "success")
    return redirect(url_for("admin_panel"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
