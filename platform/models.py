from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active_account = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    activation_code_id = db.Column(db.Integer, db.ForeignKey("activation_codes.id"))

    trading_account = db.relationship(
        "TradingAccount", backref="user", uselist=False, lazy="joined"
    )
    activation_code = db.relationship("ActivationCode", backref="user", lazy="joined")

    @property
    def is_active(self):
        return self.is_active_account


class ActivationCode(db.Model):
    __tablename__ = "activation_codes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    max_days = db.Column(db.Integer, default=30)
    is_used = db.Column(db.Boolean, default=False, index=True)
    used_by = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    used_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)


class TradingAccount(db.Model):
    __tablename__ = "trading_accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    broker = db.Column(db.String(50), default="Exness")
    account_number_enc = db.Column(db.Text, nullable=False)
    password_enc = db.Column(db.Text, nullable=False)
    server = db.Column(db.String(100), nullable=False)
    platform = db.Column(db.String(10), default="mt5")
    status = db.Column(db.String(20), default="CONFIGURED")
    metaapi_account_id = db.Column(db.String(64), nullable=True)
    bridge_port = db.Column(db.Integer, nullable=True)
    last_seen = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
