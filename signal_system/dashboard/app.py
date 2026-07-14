# signal_system/dashboard/app.py
"""
Flask dashboard — §10.
Signal queue, approve/reject actions, system health banner.

Run standalone:
    python -m signal_system.dashboard.app

Or mounted alongside the scheduler via a thread (see scheduler.py).
"""

import json
import logging
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request, abort
from flask_cors import CORS
from sqlalchemy import text

from ..db import get_db
from ..health import get_source_statuses

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    CORS(app)

    # ----------------------------------------------------------------
    # Health banner — §10.3
    # ----------------------------------------------------------------

    @app.route("/api/health")
    def api_health():
        sources = get_source_statuses()
        return jsonify(sources)

    # ----------------------------------------------------------------
    # Lightweight keep-alive endpoint — no DB dependency.
    # Used by external cron pinger (cron-job.org) to prevent Railway
    # free-tier container sleep during market hours.
    # ----------------------------------------------------------------
    @app.route("/ping")
    def ping():
        return jsonify({"status": "awake"}), 200

    # ----------------------------------------------------------------
    # Signal queue — §10.1
    # Returns pending signals (approved IS NULL, status = 'pending')
    # ordered by score desc, then time desc
    # ----------------------------------------------------------------

    @app.route("/api/signals")
    def api_signals():
        with get_db() as db:
            rows = db.execute(
                text("""
                    SELECT
                        signal_id,
                        created_at,
                        ticker,
                        sector,
                        trigger_type,
                        score,
                        factors_json,
                        sources_healthy_json,
                        data_quality,
                        status,
                        approved,
                        reject_reason
                    FROM signals
                    WHERE status = 'pending'
                      AND approved IS NULL
                    ORDER BY score DESC, created_at DESC
                    LIMIT 50
                """)
            ).fetchall()

        signals = []
        for r in rows:
            s = dict(r._mapping)
            # Parse jsonb fields — SQLAlchemy returns them as strings from some drivers
            for field in ("factors_json", "sources_healthy_json"):
                if isinstance(s[field], str):
                    s[field] = json.loads(s[field])
            # Serialise datetime
            s["created_at"] = s["created_at"].isoformat() if s["created_at"] else None
            signals.append(s)

        return jsonify(signals)

    # ----------------------------------------------------------------
    # Recent decisions — last 50 approved/rejected for reference
    # ----------------------------------------------------------------

    @app.route("/api/signals/decided")
    def api_signals_decided():
        with get_db() as db:
            rows = db.execute(
                text("""
                    SELECT
                        signal_id, created_at, ticker, sector,
                        trigger_type, score, data_quality,
                        approved, reject_reason, approval_timestamp,
                        outcome_label
                    FROM signals
                    WHERE approved IS NOT NULL
                    ORDER BY approval_timestamp DESC
                    LIMIT 50
                """)
            ).fetchall()

        results = []
        for r in rows:
            s = dict(r._mapping)
            for field in ("created_at", "approval_timestamp"):
                if s[field]:
                    s[field] = s[field].isoformat()
            results.append(s)

        return jsonify(results)

    # ----------------------------------------------------------------
    # Approve — §10.2
    # Sets approved = true, records entry price, creates paper trade
    # ----------------------------------------------------------------

    @app.route("/api/signals/<signal_id>/approve", methods=["POST"])
    def approve_signal(signal_id):
        now = datetime.now(timezone.utc)

        with get_db() as db:
            # Fetch signal
            row = db.execute(
                text("SELECT * FROM signals WHERE signal_id = :id"),
                {"id": signal_id},
            ).fetchone()

            if not row:
                abort(404, "Signal not found")
            if row.approved is not None:
                abort(400, "Signal already decided")

            # Get current price for entry
            from sqlalchemy import text as t
            price_row = db.execute(
                t("""
                    SELECT price FROM market_data
                    WHERE ticker = :ticker
                    ORDER BY ingested_at DESC
                    LIMIT 1
                """),
                {"ticker": row.ticker},
            ).fetchone()

            entry_price = float(price_row.price) if price_row else None

            # Update signal
            db.execute(
                text("""
                    UPDATE signals SET
                        approved           = true,
                        approval_timestamp = :now,
                        entry_price        = :price
                    WHERE signal_id = :id
                """),
                {"now": now, "price": entry_price, "id": signal_id},
            )

            # Create paper trade — §13
            position_size = float(os.getenv("POSITION_SIZE_USD", 1000))
            result = db.execute(
                text("""
                    INSERT INTO paper_trades
                        (signal_id, ticker, entry_price, position_size_usd, entry_time, status)
                    VALUES
                        (:signal_id, :ticker, :entry_price, :size, :entry_time, 'open')
                    RETURNING trade_id
                """),
                {
                    "signal_id":   signal_id,
                    "ticker":      row.ticker,
                    "entry_price": entry_price,
                    "size":        position_size,
                    "entry_time":  now,
                },
            )
            trade_id = result.fetchone().trade_id

            # Back-link signal → paper trade
            db.execute(
                text("UPDATE signals SET paper_trade_id = :tid WHERE signal_id = :sid"),
                {"tid": str(trade_id), "sid": signal_id},
            )

        logger.info("signal=%s approved entry_price=%s trade=%s", signal_id, entry_price, trade_id)
        return jsonify({"status": "approved", "trade_id": str(trade_id), "entry_price": entry_price})

    # ----------------------------------------------------------------
    # Reject — §10.2
    # Requires reject_reason from dropdown
    # ----------------------------------------------------------------

    VALID_REJECT_REASONS = {
        "already_moved",
        "earnings_risk",
        "low_conviction",
        "sector_noise",
        "other",
    }

    @app.route("/api/signals/<signal_id>/reject", methods=["POST"])
    def reject_signal(signal_id):
        body   = request.get_json(silent=True) or {}
        reason = body.get("reason", "").strip()

        if reason not in VALID_REJECT_REASONS:
            abort(400, f"reason must be one of: {sorted(VALID_REJECT_REASONS)}")

        now = datetime.now(timezone.utc)

        with get_db() as db:
            row = db.execute(
                text("SELECT approved FROM signals WHERE signal_id = :id"),
                {"id": signal_id},
            ).fetchone()

            if not row:
                abort(404, "Signal not found")
            if row.approved is not None:
                abort(400, "Signal already decided")

            db.execute(
                text("""
                    UPDATE signals SET
                        approved           = false,
                        reject_reason      = :reason,
                        approval_timestamp = :now
                    WHERE signal_id = :id
                """),
                {"reason": reason, "now": now, "id": signal_id},
            )

        logger.info("signal=%s rejected reason=%s", signal_id, reason)
        return jsonify({"status": "rejected", "reason": reason})

    # ----------------------------------------------------------------
    # Calibration summary — §16
    # ----------------------------------------------------------------

    @app.route("/api/calibration")
    def api_calibration():
        with get_db() as db:
            hit_rate = db.execute(text("SELECT * FROM v_hit_rate")).fetchone()
            by_score = db.execute(text("SELECT * FROM v_score_vs_outcome")).fetchall()
            by_quality = db.execute(text("SELECT * FROM v_partial_vs_full")).fetchall()
            by_reason  = db.execute(text("SELECT * FROM v_reject_reasons")).fetchall()

        return jsonify({
            "hit_rate":   dict(hit_rate._mapping) if hit_rate else {},
            "by_score":   [dict(r._mapping) for r in by_score],
            "by_quality": [dict(r._mapping) for r in by_quality],
            "by_reason":  [dict(r._mapping) for r in by_reason],
        })

    # ----------------------------------------------------------------
    # Main UI — served from template
    # ----------------------------------------------------------------

    @app.route("/")
    def index():
        return render_template("index.html")

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)
