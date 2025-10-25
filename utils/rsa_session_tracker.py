# utils/rsa_session_tracker.py

from datetime import datetime


class RSASessionManager:
    def __init__(self):
        self.sessions = {}  # {user_id: session_data}

    def start_session(self, user_id, expected_brokers):
        self.sessions[user_id] = {
            "started_at": datetime.utcnow(),
            "expected_brokers": set(b.lower() for b in expected_brokers),
            "completed_brokers": set(),
            "confirmed_all": False,
            "errors": [],
        }

    def mark_broker_complete(self, user_id, broker_name):
        session = self.sessions.get(user_id)
        if session:
            session["completed_brokers"].add(broker_name.lower())

    def mark_error(self, user_id, broker_name, message):
        session = self.sessions.get(user_id)
        if session:
            session["errors"].append((broker_name, message))

    def mark_all_done(self, user_id):
        session = self.sessions.get(user_id)
        if session:
            session["confirmed_all"] = True

    def get_status(self, user_id):
        session = self.sessions.get(user_id)
        if not session:
            return "No active RSA session for this user."

        missing = session["expected_brokers"] - session["completed_brokers"]
        status = f"Brokers complete: {sorted(session['completed_brokers'])}\n"
        if missing:
            status += f"⚠️ Missing: {sorted(missing)}\n"
        if session["errors"]:
            status += "❌ Errors:\n" + "\n".join(
                f"  - {b}: {msg}" for b, msg in session["errors"]
            )
        if session["confirmed_all"]:
            status += "\n✅ All brokers marked complete."
        return status
