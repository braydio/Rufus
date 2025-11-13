# rsa/watchlist_manager.py
import os
import json
from datetime import datetime
from utils.logging_setup import logger


class RufusWatchlistManager:
    def __init__(
        self, storage_path="watchlist_store.json", audit_log_path="watchlist_audit.json"
    ):
        self.watchlist = {}
        self.storage_path = storage_path
        self.audit_log_path = audit_log_path
        self.audit_log = []
        self.load()

    def add(self, ticker, split_date_str):
        try:
            split_date = datetime.strptime(split_date_str, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Invalid split date format for {ticker}: {split_date_str}")
            return False

        ticker = ticker.upper()
        entry = self.watchlist.setdefault(
            ticker,
            {
                "split_date": str(split_date),
                "purchases": {},
                "closeouts": {},
                "tags": [],
                "notes": "",
            },
        )
        entry["split_date"] = str(split_date)
        self.log_action("add_or_update", ticker, {"split_date": split_date_str})
        self.save()
        return True

    def mark_purchase(self, ticker, broker_account, quantity=1):
        ticker = ticker.upper()
        self.watchlist.setdefault(
            ticker,
            {
                "split_date": "9999-01-01",
                "purchases": {},
                "closeouts": {},
                "tags": [],
                "notes": "",
            },
        )
        self.watchlist[ticker]["purchases"][broker_account] = (
            self.watchlist[ticker]["purchases"].get(broker_account, 0) + quantity
        )
        self.log_action(
            "purchase", ticker, {"account": broker_account, "quantity": quantity}
        )
        self.save()

    def mark_closeout(self, ticker, broker_account, quantity=1):
        ticker = ticker.upper()
        if ticker not in self.watchlist:
            return
        self.watchlist[ticker]["closeouts"][broker_account] = (
            self.watchlist[ticker]["closeouts"].get(broker_account, 0) + quantity
        )
        self.log_action(
            "closeout", ticker, {"account": broker_account, "quantity": quantity}
        )
        self.save()

    def get_status(self, ticker):
        ticker = ticker.upper()
        if ticker not in self.watchlist:
            return f"No tracking info for `{ticker}`."

        data = self.watchlist[ticker]
        try:
            split_date = datetime.strptime(data["split_date"], "%Y-%m-%d").date()
        except ValueError:
            return f"Invalid split date stored for `{ticker}`."

        today = datetime.today().date()
        split_passed = today >= split_date

        purchases = data["purchases"]
        closeouts = data["closeouts"]
        open_positions = {
            acct: qty for acct, qty in purchases.items() if qty > closeouts.get(acct, 0)
        }

        summary = f"📊 **{ticker}** split date: {split_date}"
        summary += (
            " (✅ passed)\n"
            if split_passed
            else f" (⏳ {(split_date - today).days} day(s) left)\n"
        )
        summary += f"💳 Purchases: {purchases or 'None'}\n"
        summary += f"📤 Closeouts: {closeouts or 'None'}\n"
        summary += (
            f"⚠️ Still open: {open_positions}"
            if open_positions
            else "✅ All positions closed."
        )
        return summary

    def get_all_statuses(self):
        return [self.get_status(ticker) for ticker in self.watchlist]

    def log_and_get_summary(self):
        logger.info("\n===== 🕒 Daily Watchlist Summary =====")
        summaries = self.get_all_statuses()
        for summary in summaries:
            print(summary)
            logger.info(summary)
        return summaries

    def save(self):
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self.watchlist, f, indent=2)
            with open(self.audit_log_path, "w", encoding="utf-8") as f:
                json.dump(self.audit_log, f, indent=2)
            logger.info("💾 Watchlist and audit log saved.")
        except Exception as e:
            logger.error(f"❌ Failed to save watchlist: {e}")

    def load(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    self.watchlist = json.load(f)
                logger.info("📂 Loaded watchlist from disk.")
            except Exception as e:
                logger.error(f"❌ Failed to load watchlist: {e}")
        if os.path.exists(self.audit_log_path):
            try:
                with open(self.audit_log_path, "r", encoding="utf-8") as f:
                    self.audit_log = json.load(f)
            except Exception as e:
                logger.warning(f"⚠️ Failed to load audit log: {e}")

    def log_action(self, action, ticker, metadata=None):
        self.audit_log.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "ticker": ticker,
                "action": action,
                "metadata": metadata or {},
            }
        )
