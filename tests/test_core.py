from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.main import (
    AnalystSignal,
    ExecutionPlan,
    RiskApprovedSignal,
    backtest_and_track,
    execution_planner,
)
from app.sentiment import _score_text


class CoreTests(unittest.TestCase):
    def test_sentiment_score_positive_and_negative(self) -> None:
        self.assertGreater(_score_text("Strong growth and record profit"), 0)
        self.assertLess(_score_text("Weak drop and losses"), 0)

    def test_execution_planner_builds_levels(self) -> None:
        signal = AnalystSignal(
            symbol="TEST",
            name="Test Corp",
            price=100.0,
            change_pct=2.0,
            volume=1_000_000,
            avg_volume=500_000,
            market_cap=10_000_000_000,
            rel_volume=2.0,
            intraday_range_pct=4.0,
            momentum_score=30.0,
            thesis="sample",
        )
        approved = [RiskApprovedSignal(signal=signal, risk_score=25.0, risk_notes="ok")]

        plans = execution_planner(approved, top_count=5)
        self.assertEqual(len(plans), 1)
        self.assertIsInstance(plans[0], ExecutionPlan)
        self.assertLess(plans[0].stop_loss, plans[0].entry)
        self.assertGreater(plans[0].take_profit, plans[0].entry)

    def test_backtest_file_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "picks.csv"
            summary = backtest_and_track([], history_path)
            self.assertTrue(history_path.exists())
            content = history_path.read_text(encoding="utf-8")
            self.assertIn("run_date,symbol,entry_price,next_day_close,return_pct,status", content)
            self.assertIn("Backtest summary", summary)

if __name__ == "__main__":
    unittest.main()
