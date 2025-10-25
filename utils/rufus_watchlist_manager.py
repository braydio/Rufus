# rufus_watchlist_manager.py
import os
import json
from datetime import datetime
from utils.logging_setup import logger


class RufusWatchlistManager:
    def __init__(self, storage_path="watchlist_store.json"):
        self.watchlist = {}
        self.storage_path = storage_path
        self.load()

    def add(self, ticker, split_date_str):
        try:
            split_date = datetime.strptime(split_date_str, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Invalid split date format for {ticker}: {split_date_str}")
            return False

        ticker = ticker.upper()
        if ticker not in self.watchlist:
            self.watchlist[ticker] = {
                "split_date": str(split_date),
                "purchases": [],
                "closeouts": [],
            }
            logger.info(
                f"📋 Added new ticker to watchlist: {ticker} split on {split_date}"
            )
        else:
            logger.info(
                f"✏️ Ticker already tracked: {ticker}, updating split date to {split_date}"
            )
            self.watchlist[ticker]["split_date"] = str(split_date)

        self.save()
        return True

    def mark_purchase(self, ticker, broker_account):
        ticker = ticker.upper()
        if ticker in self.watchlist:
            if broker_account not in self.watchlist[ticker]["purchases"]:
                self.watchlist[ticker]["purchases"].append(broker_account)
                logger.info(f"✅ Purchase recorded for {ticker} by {broker_account}")
                self.save()

    def mark_closeout(self, ticker, broker_account):
        ticker = ticker.upper()
        if ticker in self.watchlist:
            if broker_account not in self.watchlist[ticker]["closeouts"]:
                self.watchlist[ticker]["closeouts"].append(broker_account)
                logger.info(f"📤 Closeout recorded for {ticker} by {broker_account}")
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

        purchases = sorted(set(data["purchases"]))
        closeouts = sorted(set(data["closeouts"]))
        open_positions = [acct for acct in purchases if acct not in closeouts]

        summary = f"\U0001f4ca **{ticker}** split date: {split_date}"
        summary += (
            " (\u2705 passed)\n"
            if split_passed
            else f" (\u23f3 {(split_date - today).days} day(s) left)\n"
        )
        summary += f"\U0001f4b3 Brokers purchased: {', '.join(purchases) or 'None'}\n"
        summary += f"\U0001f4e4 Closeouts: {', '.join(closeouts) or 'None'}\n"
        summary += (
            f"\u26a0\ufe0f Still open: {', '.join(open_positions)}"
            if open_positions
            else "\u2705 All positions closed."
        )

        return summary

    def get_all_statuses(self):
        return [self.get_status(ticker) for ticker in self.watchlist]

    def save(self):
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self.watchlist, f, indent=2)
                logger.info("💾 Watchlist saved to disk.")
        except Exception as e:
            logger.error(f"❌ Failed to save watchlist: {e}")

    def load(self):
        if not os.path.exists(self.storage_path):
            logger.info("📁 No watchlist store found. Starting fresh.")
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                self.watchlist = json.load(f)
                logger.info("📂 Loaded watchlist from disk.")
        except Exception as e:
            logger.error(f"❌ Failed to load watchlist: {e}")
