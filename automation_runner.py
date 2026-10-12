#!/usr/bin/env python3
"""Run the existing NSE EOD report engine for all configured indices.

This runner intentionally leaves app.py and the V3.2 Gradio UI unchanged.
"""
from __future__ import annotations

import json
import os
import sys
import time
import zipfile
import gc
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
os.environ["TZ"] = "Asia/Kolkata"
if hasattr(time, "tzset"):
    time.tzset()

ROOT = Path(__file__).resolve().parent
ARTIFACTS_DIR = ROOT / "artifacts"
EXPORT_DIR = ARTIFACTS_DIR / "exports"
REPORTS_DIR = ARTIFACTS_DIR / "reports"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["EXPORT_DIR"] = str(EXPORT_DIR)

# Import only after setting TZ and EXPORT_DIR. app.py builds the UI but launches
# the server only under its __main__ guard.
import app  # noqa: E402

MISSING_DATA_LIMIT = 0.02
MAX_MARKET_DATA_AGE_DAYS = 5
MAX_TICKER_LAG_DAYS = 4


class DataValidationError(ValueError):
    def __init__(self, message: str, missing_symbols=None, constituent_count=0, latest_market_date=None):
        super().__init__(message)
        self.missing_symbols = list(missing_symbols or [])
        self.constituent_count = constituent_count
        self.latest_market_date = latest_market_date


def log(message: str) -> None:
    stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    with (ARTIFACTS_DIR / "automation.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def get_symbol_column(frame: pd.DataFrame) -> str:
    for candidate in ("Symbol", "SYMBOL", "symbol"):
        if candidate in frame.columns:
            return candidate
    raise ValueError(f"Constituent symbol column not found. Columns: {list(frame.columns)}")


def ticker_frame(market_data: pd.DataFrame, ticker: str):
    if isinstance(market_data.columns, pd.MultiIndex):
        level0 = market_data.columns.get_level_values(0)
        level1 = market_data.columns.get_level_values(1)
        if ticker in level0:
            return market_data.xs(ticker, axis=1, level=0, drop_level=True).copy()
        if ticker in level1:
            return market_data.xs(ticker, axis=1, level=1, drop_level=True).copy()
        return None
    if ticker in market_data.columns:
        return market_data[ticker].copy()
    return None


def normalise_constituents(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str], int]:
    source_col = get_symbol_column(frame)
    normalised = frame.copy()
    normalised["Symbol"] = (
        normalised[source_col].astype(str).str.strip().replace({"nan": "", "None": ""})
    )
    raw_rows = len(normalised)
    normalised = normalised[normalised["Symbol"] != ""].copy()
    symbols = normalised["Symbol"].drop_duplicates().tolist()
    normalised = normalised.drop_duplicates(subset=["Symbol"], keep="first").reset_index(drop=True)
    return normalised, symbols, raw_rows


def evaluate_data(index_name: str, constituents: pd.DataFrame, symbols: list[str],
                  market_data: pd.DataFrame) -> tuple[pd.DataFrame, list[str], str]:
    if not symbols:
        raise ValueError("Constituent list contains no valid symbols.")
    if market_data is None or market_data.empty:
        raise ValueError("Yahoo Finance returned no market data.")

    index_dates = pd.to_datetime(market_data.index, errors="coerce")
    valid_index_dates = index_dates[~index_dates.isna()]
    if len(valid_index_dates) == 0:
        raise ValueError("Market data has no valid trading dates.")
    latest_market_date = valid_index_dates.max().date()
    today_ist = datetime.now(IST).date()
    age_days = (today_ist - latest_market_date).days
    if age_days > MAX_MARKET_DATA_AGE_DAYS:
        raise ValueError(
            f"Market data is stale: latest available date {latest_market_date}, "
            f"{age_days} calendar days old (maximum {MAX_MARKET_DATA_AGE_DAYS})."
        )

    raw_metrics = app.calculate_metrics(constituents, market_data)
    metric_symbols = set()
    if raw_metrics is not None and not raw_metrics.empty and "Symbol" in raw_metrics.columns:
        metric_symbols = set(raw_metrics["Symbol"].astype(str).str.strip())

    missing = set(symbols) - metric_symbols
    latest_data_date = latest_market_date
    for symbol in symbols:
        frame = ticker_frame(market_data, f"{symbol}.NS")
        if frame is None or "Close" not in frame.columns:
            missing.add(symbol)
            continue
        closes = pd.to_numeric(frame["Close"], errors="coerce").dropna()
        if len(closes) < 2:
            missing.add(symbol)
            continue
        ticker_dates = pd.to_datetime(closes.index, errors="coerce")
        ticker_dates = ticker_dates[~ticker_dates.isna()]
        if len(ticker_dates) == 0:
            missing.add(symbol)
            continue
        ticker_latest = ticker_dates.max().date()
        if (latest_data_date - ticker_latest).days > MAX_TICKER_LAG_DAYS:
            missing.add(symbol)

    # Keep all stocks which passed calculation and freshness checks. A stock
    # with missing/stale data is not silently represented using an old value.
    missing_symbols = sorted(missing)
    accepted_symbols = set(symbols) - set(missing_symbols)
    metrics = raw_metrics.copy() if raw_metrics is not None else pd.DataFrame()
    if not metrics.empty:
        metrics["Symbol"] = metrics["Symbol"].astype(str).str.strip()
        metrics = metrics[metrics["Symbol"].isin(accepted_symbols)].copy()

    missing_count = len(set(missing_symbols))
    missing_pct = missing_count / len(symbols)
    max_allowed = int(len(symbols) * MISSING_DATA_LIMIT)
    log(
        f"{index_name}: constituents_raw_rows={len(constituents)}, "
        f"unique_symbols={len(symbols)}, valid_metrics={len(metrics)}, "
        f"missing_or_stale={missing_count}/{len(symbols)} ({missing_pct:.2%}), "
        f"allowed_count={max_allowed}, latest_market_date={latest_market_date}"
    )
    if missing_symbols:
        log(f"{index_name}: missing/stale symbols: {', '.join(missing_symbols)}")

    if missing_count > max_allowed or missing_pct > MISSING_DATA_LIMIT:
        raise DataValidationError(
            f"Rejected: {missing_count}/{len(symbols)} constituents missing or stale "
            f"({missing_pct:.2%}); limit is 2.00%.",
            missing_symbols=missing_symbols,
            constituent_count=len(symbols),
            latest_market_date=latest_market_date,
        )
    if metrics.empty:
        raise DataValidationError(
            "No valid stock metrics remain after validation.",
            missing_symbols=missing_symbols,
            constituent_count=len(symbols),
            latest_market_date=latest_market_date,
        )
    status = "PARTIAL" if missing_count else "SUCCESS"
    return metrics, missing_symbols, status


def run_one_index(index_name: str) -> dict:
    result = {
        "index": index_name,
        "status": "FAILED",
        "constituents": 0,
        "valid_stocks": 0,
        "missing_count": 0,
        "missing_symbols": [],
        "latest_market_date": None,
        "html": None,
        "csv": None,
        "png": None,
        "error": None,
    }
    log(f"Starting {index_name}")
    try:
        constituents_raw = app.fetch_index_constituents(index_name)
        constituents, symbols, raw_rows = normalise_constituents(constituents_raw)
        if not symbols:
            raise ValueError("NSE constituent file contains no symbols.")

        # One market-data download per index. The existing report functions are
        # temporarily wired to this cached data so HTML/CSV/PNG use the same
        # snapshot and no second Yahoo download is triggered.
        market_data = app.fetch_market_data(symbols)
        metrics, missing_symbols, status = evaluate_data(
            index_name, constituents, symbols, market_data
        )

        original_fetch_constituents = app.fetch_index_constituents
        original_fetch_market_data = app.fetch_market_data
        original_calculate_metrics = app.calculate_metrics
        try:
            app.fetch_index_constituents = lambda requested_index: constituents.copy()
            app.fetch_market_data = lambda requested_symbols: market_data
            app.calculate_metrics = lambda _constituents, _market_data: metrics.copy()
            html_report, report_metrics = app.generate_report(index_name, return_data=True)
            csv_path = app.export_csv(index_name, metrics=report_metrics)
            png_path = app.export_png(index_name, html_report=html_report)
        finally:
            app.fetch_index_constituents = original_fetch_constituents
            app.fetch_market_data = original_fetch_market_data
            app.calculate_metrics = original_calculate_metrics

        date_stamp = datetime.now(IST).strftime("%Y-%m-%d")
        safe_name = index_name.replace(" ", "_").replace("/", "_")
        html_path = REPORTS_DIR / f"{safe_name}_EOD_{date_stamp}.html"
        html_path.write_text(html_report, encoding="utf-8")

        result.update({
            "status": status,
            "constituents": len(symbols),
            "raw_constituent_rows": raw_rows,
            "valid_stocks": len(report_metrics),
            "missing_count": len(missing_symbols),
            "missing_symbols": missing_symbols,
            "latest_market_date": str(pd.to_datetime(market_data.index).max().date()),
            "html": str(html_path.relative_to(ROOT)),
            "csv": str(Path(csv_path).relative_to(ROOT)),
            "png": str(Path(png_path).relative_to(ROOT)),
        })
        log(f"Completed {index_name}: {status}; valid stocks={len(report_metrics)}")
        del report_metrics, metrics, market_data, constituents, constituents_raw
        gc.collect()
    except Exception as exc:
        if isinstance(exc, DataValidationError):
            result["constituents"] = exc.constituent_count
            result["missing_count"] = len(exc.missing_symbols)
            result["missing_symbols"] = exc.missing_symbols
            result["latest_market_date"] = str(exc.latest_market_date or "")
        result["error"] = f"{type(exc).__name__}: {exc}"
        log(f"FAILED {index_name}: {result['error']}")
    return result


def main() -> int:
    start = datetime.now(IST)
    selected = sys.argv[1].strip() if len(sys.argv) > 1 else "All indices"
    if selected == "All indices":
        selected_indices = list(app.INDEX_CONFIG)
    elif selected in app.INDEX_CONFIG:
        selected_indices = [selected]
    else:
        raise ValueError(f"Unknown index selection: {selected}")

    log(
        f"NSE EOD automation started for {len(selected_indices)} index(es). "
        "Missing-data policy: maximum 2% inclusive."
    )
    results = []
    for index_name in selected_indices:
        results.append(run_one_index(index_name))
        gc.collect()

    summary = {
        "run_started_ist": start.isoformat(),
        "run_finished_ist": datetime.now(IST).isoformat(),
        "missing_data_limit_percent": 2,
        "results": results,
    }
    summary_path = ARTIFACTS_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    summary_rows = []
    for item in results:
        summary_rows.append({
            "Index": item["index"],
            "Status": item["status"],
            "Constituents": item.get("constituents", 0),
            "Valid Stocks": item.get("valid_stocks", 0),
            "Missing/Stale Count": item.get("missing_count", 0),
            "Missing/Stale Symbols": ", ".join(item.get("missing_symbols", [])),
            "Latest Market Date": item.get("latest_market_date") or "",
            "Error": item.get("error") or "",
        })
    pd.DataFrame(summary_rows).to_csv(ARTIFACTS_DIR / "summary.csv", index=False)

    date_stamp = datetime.now(IST).strftime("%Y-%m-%d")
    zip_path = ARTIFACTS_DIR / f"NSE_EOD_Reports_{date_stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for folder in (EXPORT_DIR, REPORTS_DIR):
            if folder.exists():
                for file_path in sorted(folder.glob("*")):
                    if file_path.is_file():
                        archive.write(file_path, file_path.relative_to(ARTIFACTS_DIR))
        for file_path in (
            ARTIFACTS_DIR / "summary.json",
            ARTIFACTS_DIR / "summary.csv",
            ARTIFACTS_DIR / "automation.log",
        ):
            if file_path.exists():
                archive.write(file_path, file_path.relative_to(ARTIFACTS_DIR))

    succeeded = sum(item["status"] in ("SUCCESS", "PARTIAL") for item in results)
    partial = sum(item["status"] == "PARTIAL" for item in results)
    failed = sum(item["status"] == "FAILED" for item in results)
    log(f"Run summary: successful={succeeded}, partial={partial}, failed={failed}")
    log(f"ZIP package created: {zip_path}")
    print("\n## NSE EOD Automation Summary")
    print(f"- Run date (IST): {date_stamp}")
    print(f"- Successful/partial indices: {succeeded}/{len(results)}")
    print(f"- Partial reports: {partial}")
    print(f"- Failed/rejected indices: {failed}")
    print(f"- ZIP: {zip_path}")
    for item in results:
        print(
            f"- {item['index']}: {item['status']} — "
            f"{item.get('valid_stocks', 0)}/{item.get('constituents', 0)} stocks; "
            f"missing/stale={item.get('missing_count', 0)}"
            + (f"; reason={item['error']}" if item.get("error") else "")
        )

    # Preserve artifact upload even when some/all index reports fail.
    return 1 if succeeded == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
