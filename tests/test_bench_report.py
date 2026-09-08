"""render_report() is the other pure function in the lag benchmark -- no DB,
no Docker, so it's tested the same way percentile() is: directly, in CI, even
though the script that calls it needs a live consumer to run at all.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.bench_outbox_lag import Result, render_report  # noqa: E402


def make_result(**overrides) -> Result:
    defaults = dict(
        count=10_000,
        p50_lag_s=12.3,
        p99_lag_s=98.7,
        max_lag_s=101.2,
        replay_s=115.4,
        poll_interval_ms=2000,
        batch_size=200,
    )
    return Result(**{**defaults, **overrides})


def test_report_states_every_number_the_table_promises():
    report = render_report(make_result())
    assert "10,000" in report
    assert "12.30s" in report  # p50
    assert "98.70s" in report  # p99
    assert "101.20s" in report  # max
    assert "115.40s" in report  # replay


def test_report_states_the_config_the_numbers_depend_on():
    """Numbers with no config attached are not reproducible: p50/p99 on this
    pipeline are a direct function of poll_interval_ms and batch_size."""
    report = render_report(make_result(poll_interval_ms=500, batch_size=50))
    assert "500" in report
    assert "50" in report


def test_report_computes_throughput_from_the_config():
    # batch_size / (poll_interval_ms / 1000) = events/s at that config.
    report = render_report(make_result(poll_interval_ms=2000, batch_size=200))
    assert "100" in report  # 200 / 2.0 = 100 events/s


def test_report_includes_a_reproduce_command_with_the_actual_count():
    report = render_report(make_result(count=42))
    assert "--count 42" in report
    assert "--force" in report


def test_report_is_a_markdown_table():
    report = render_report(make_result())
    assert "| Metric | Value |" in report
    assert "|---|---|" in report
