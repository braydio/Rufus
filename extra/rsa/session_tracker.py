import json
import os
from datetime import datetime, timedelta


class RSASessionManager:
    def __init__(self, session_store_path="rsa_sessions.json"):
        self.sessions = {}
        self.session_store_path = session_store_path
        self.load()

    def start_session(self, user_id, expected_brokers):
        self.sessions[user_id] = {
            "started_at": datetime.utcnow().isoformat(),
            "expected_brokers": set(b.lower() for b in expected_brokers),
            "completed_brokers": set(),
            "confirmed_all": False,
            "errors": [],
            "messages": [],  # 🆕 stores incoming text for lifecycle analysis
        }
        self.save()

    def mark_broker_complete(self, user_id, broker_name):
        session = self.sessions.get(user_id)
        if session:
            session["completed_brokers"].add(broker_name.lower())
            self.save()

    def mark_error(self, user_id, broker_name, message):
        session = self.sessions.get(user_id)
        if session:
            session["errors"].append((broker_name, message))
            self.save()

    def mark_all_done(self, user_id):
        session = self.sessions.get(user_id)
        if session:
            session["confirmed_all"] = True
            self.save()

    def append_message(self, user_id, message):
        session = self.sessions.get(user_id)
        if session:
            session.setdefault("messages", []).append(
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "content": message,
                }
            )
            self.save()

    def get_message_chunks(self, user_id, chunk_size=1500):
        session = self.sessions.get(user_id)
        if not session or not session.get("messages"):
            return []

        all_text = "\n".join(m["content"] for m in session["messages"])
        return [
            all_text[i : i + chunk_size] for i in range(0, len(all_text), chunk_size)
        ]

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

    def cleanup_expired_sessions(self, ttl_minutes=60):
        now = datetime.utcnow()
        self.sessions = {
            uid: data
            for uid, data in self.sessions.items()
            if datetime.fromisoformat(data["started_at"])
            >= now - timedelta(minutes=ttl_minutes)
        }
        self.save()

    def save(self):
        try:
            with open(self.session_store_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        uid: {
                            **data,
                            "expected_brokers": list(data["expected_brokers"]),
                            "completed_brokers": list(data["completed_brokers"]),
                        }
                        for uid, data in self.sessions.items()
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            print(f"Error saving RSA sessions: {e}")

    def load(self):
        if not os.path.exists(self.session_store_path):
            return
        try:
            with open(self.session_store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for uid, session in data.items():
                    session["expected_brokers"] = set(session["expected_brokers"])
                    session["completed_brokers"] = set(session["completed_brokers"])
                    self.sessions[int(uid)] = session
        except Exception as e:
            print(f"Error loading RSA sessions: {e}")
