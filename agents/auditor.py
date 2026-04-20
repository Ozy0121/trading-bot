"""
Agent 6 — The Auditor.

Reviews performance and improves the system. Logs every trade,
computes running stats, and runs a daily AI review via Anthropic API (Opus).

Input: {} (uses internal journal)
Output: {"report": AuditReport}
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from agents.base import BaseAgent, AuditReport
from agents.event_bus import EventBus
from logger_setup import get_logger

log = get_logger()

_DEFAULT_JOURNAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "trade_journal.json"
)
_AUDITOR_MODEL = os.getenv("AUDITOR_MODEL", "claude-opus-4-6")


class Auditor(BaseAgent):
    """Agent that records trades, computes performance stats, and runs daily reviews."""

    name = "auditor"

    def __init__(self, event_bus: EventBus, journal_path: str | None = None) -> None:
        super().__init__(event_bus)
        self._journal_path = journal_path or _DEFAULT_JOURNAL_PATH
        self._journal: list[dict] = []
        self._daily_summary: str = ""

    def _execute(self, input_data: dict) -> dict:
        """Compute stats from journal and emit performance metrics."""
        report = self._compute_stats()
        self.event_bus.emit("agent.output", {
            "agent": self.name,
            "output": {
                "total_trades": report.total_trades,
                "win_rate": report.win_rate,
                "daily_pnl": report.daily_pnl,
            },
        })
        return {"report": report}

    def _summarize_output(self) -> str:
        r = self.last_output.get("report")
        if not r:
            return f"{len(self._journal)} trades in journal"
        return f"{r.total_trades} trades, {r.win_rate:.0f}% win rate, P&L ${r.daily_pnl:.2f}"

    def record_trade(self, trade: dict) -> None:
        """Record a completed trade to the journal."""
        trade["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._journal.append(trade)
        log.info("[auditor] Recorded trade: %s %s P&L=$%.2f",
                 trade.get("symbol", "?"), "WIN" if trade.get("win") else "LOSS",
                 trade.get("pnl", 0))

    def _compute_stats(self) -> AuditReport:
        """Compute performance statistics from journal."""
        if not self._journal:
            return AuditReport()

        total = len(self._journal)
        wins = [t for t in self._journal if t.get("win")]
        losses = [t for t in self._journal if not t.get("win")]

        win_rate = len(wins) / total if total > 0 else 0.0
        avg_win = (sum(t.get("pnl", 0) for t in wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(t.get("pnl", 0) for t in losses) / len(losses)) if losses else 0.0

        # Profit factor: gross wins / gross losses
        gross_wins = sum(abs(t.get("pnl", 0)) for t in wins)
        gross_losses = sum(abs(t.get("pnl", 0)) for t in losses)
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 0.0

        # Daily P&L: sum of today's P&Ls
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        trades_today = [t for t in self._journal
                        if t.get("timestamp", "").startswith(today)]
        daily_pnl = sum(t.get("pnl", 0) for t in trades_today)

        return AuditReport(
            total_trades=total,
            win_rate=round(win_rate, 2),
            profit_factor=round(profit_factor, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            daily_pnl=round(daily_pnl, 2),
            trades_today=trades_today,
        )

    def save_journal(self) -> None:
        """Persist journal to disk as JSON."""
        os.makedirs(os.path.dirname(self._journal_path), exist_ok=True)
        with open(self._journal_path, "w") as f:
            json.dump(self._journal, f, indent=2)
        log.info("[auditor] Journal saved: %d trades", len(self._journal))

    def load_journal(self) -> None:
        """Load journal from disk if it exists."""
        if os.path.exists(self._journal_path):
            with open(self._journal_path, "r") as f:
                self._journal = json.load(f)
            log.info("[auditor] Journal loaded: %d trades", len(self._journal))

    def daily_review(self) -> str:
        """Generate a daily performance review using Claude Opus."""
        report = self._compute_stats()
        if report.total_trades == 0:
            return "No trades to review."

        try:
            import anthropic

            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if not api_key or api_key.startswith("YOUR_"):
                return self._format_text_summary(report)

            client = anthropic.Anthropic(api_key=api_key)
            prompt = (
                f"You are a trading performance analyst. Review today's trading:\n"
                f"Total trades: {report.total_trades}\n"
                f"Win rate: {report.win_rate:.0%}\n"
                f"Profit factor: {report.profit_factor:.2f}\n"
                f"Avg win: ${report.avg_win:.2f}, Avg loss: ${report.avg_loss:.2f}\n"
                f"Daily P&L: ${report.daily_pnl:.2f}\n\n"
                f"Trades: {json.dumps(report.trades_today, default=str)}\n\n"
                f"Provide: 1) What went well 2) What to improve 3) Pattern observations"
            )
            response = client.messages.create(
                model=_AUDITOR_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            self._daily_summary = response.content[0].text
            return self._daily_summary

        except Exception as exc:
            log.warning("[auditor] AI review failed: %s", exc)
            return self._format_text_summary(report)

    def _format_text_summary(self, report: AuditReport) -> str:
        """Format a simple text summary when AI is unavailable."""
        return (
            f"Daily Summary: {report.total_trades} trades, "
            f"{report.win_rate:.0%} win rate, P&L: ${report.daily_pnl:.2f}"
        )
