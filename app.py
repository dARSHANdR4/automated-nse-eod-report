import os
import asyncio
from pathlib import Path
from datetime import datetime
from html import escape

import gradio as gr
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from io import BytesIO
from playwright.sync_api import sync_playwright

EXPORT_DIR = Path(os.environ.get("EXPORT_DIR", "/tmp/nse_eod_exports"))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
NSE_BASE_URL = "https://www.nseindia.com"


INDEX_CONFIG = {

    "NIFTY 50": {
        "nse_file": "ind_nifty50list.csv",
        "display_name": "NIFTY 50"
    },

    "NIFTY NEXT 50": {
        "nse_file": "ind_niftynext50list.csv",
        "display_name": "NIFTY NEXT 50"
    },

    "NIFTY MIDCAP 150": {
        "nse_file": "ind_niftymidcap150list.csv",
        "display_name": "NIFTY MIDCAP 150"
    },

    "NIFTY SMALLCAP 250": {
        "nse_file": "ind_niftysmallcap250list.csv",
        "display_name": "NIFTY SMALLCAP 250"
    },

    "NIFTY MIDCAP 50": {
        "nse_file": "ind_niftymidcap50list.csv",
        "display_name": "NIFTY MIDCAP 50"
    },

    "NIFTY SMALLCAP 50": {
        "nse_file": "ind_niftysmallcap50list.csv",
        "display_name": "NIFTY SMALLCAP 50"
    }
}

def fetch_index_constituents(index_name):
    """
    Fetch the latest constituent list for any configured NSE index.
    """

    if index_name not in INDEX_CONFIG:
        raise ValueError(f"Index not configured: {index_name}")

    nse_file = INDEX_CONFIG[index_name]["nse_file"]
    url = NSE_BASE_URL + nse_file

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,*/*"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    constituents = pd.read_csv(
        BytesIO(response.content)
    )

    return constituents

def fetch_market_data(symbols):

    print("Downloading EOD data...")
    print(f"Stocks requested: {len(symbols)}")

    yahoo_symbols = [
        f"{str(symbol).strip()}.NS"
        for symbol in symbols
    ]

    data = yf.download(
        yahoo_symbols,
        period="1y",
        interval="1d",
        auto_adjust=False,
        group_by="ticker",
        threads=True,
        progress=False
    )

    print("Download completed.")

    return data

def calculate_metrics(constituents, market_data):

    results = []

    # Get unique symbols from constituent list
    symbols = (
        constituents["Symbol"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
    )

    def get_ticker_data(ticker):

        # Case 1: yfinance MultiIndex columns
        if isinstance(market_data.columns, pd.MultiIndex):

            level0 = market_data.columns.get_level_values(0)
            level1 = market_data.columns.get_level_values(1)

            # Structure: (Ticker, Price)
            if ticker in level0:
                df = market_data.xs(
                    ticker,
                    axis=1,
                    level=0,
                    drop_level=True
                ).copy()

            # Structure: (Price, Ticker)
            elif ticker in level1:
                df = market_data.xs(
                    ticker,
                    axis=1,
                    level=1,
                    drop_level=True
                ).copy()

            else:
                return None

        # Case 2: normal single-level columns
        else:
            if ticker not in market_data.columns:
                return None

            df = market_data[ticker].copy()

        return df

    for symbol in symbols:

        ticker = symbol + ".NS"

        try:

            df = get_ticker_data(ticker)

            if df is None:
                print(f"Skipped {symbol}: ticker data not found")
                continue

            # Make sure required columns exist
            required = ["High", "Low", "Close", "Volume"]

            if not all(col in df.columns for col in required):
                print(f"Skipped {symbol}: missing required columns")
                continue

            # Remove rows without Close
            df = df.dropna(subset=["Close"])

            if len(df) < 2:
                print(f"Skipped {symbol}: insufficient data")
                continue

            # Latest and previous trading day
            today = df.iloc[-1]
            previous = df.iloc[-2]

            close = float(today["Close"])
            previous_close = float(previous["Close"])

            if previous_close == 0:
                continue

            # Daily Change %
            change_pct = (
                (close / previous_close) - 1
            ) * 100

            # Volume Change %
            today_volume = float(today["Volume"])
            previous_volume = float(previous["Volume"])

            if previous_volume > 0:
                volume_change_pct = (
                    (today_volume / previous_volume) - 1
                ) * 100
            else:
                volume_change_pct = np.nan

            # Intraday High / Low
            day_high = float(today["High"])
            day_low = float(today["Low"])

            if day_low > 0:
                intraday_range_pct = (
                    (day_high / day_low) - 1
                ) * 100
            else:
                intraday_range_pct = np.nan

            # 52 Week High / Low
            last_252 = df.tail(252)

            week52_high = float(last_252["High"].max())
            week52_low = float(last_252["Low"].min())

            # Distance from 52W High
            if week52_high > 0:
                distance_from_52w_high = (
                    (week52_high - close) / week52_high
                ) * 100
            else:
                distance_from_52w_high = np.nan

            # Distance from 52W Low
            if week52_low > 0:
                distance_from_52w_low = (
                    (close - week52_low) / week52_low
                ) * 100
            else:
                distance_from_52w_low = np.nan

            results.append({
                "Symbol": symbol,
                "Close": close,
                "Change %": change_pct,
                "Volume Change %": volume_change_pct,
                "Intraday Range %": intraday_range_pct,
                "52W Low": week52_low,
                "52W High": week52_high,
                "Distance from 52W Low %": distance_from_52w_low,
                "Distance from 52W High %": distance_from_52w_high
            })

        except Exception as e:
            print(f"Skipped {symbol}: {e}")

    return pd.DataFrame(results)

def generate_report(index_name):

    # --------------------------------------------------------
    # 1. FETCH CONSTITUENTS
    # --------------------------------------------------------

    constituents = fetch_index_constituents(index_name)

    # Find symbol column safely
    symbol_col = None

    for col in ["Symbol", "SYMBOL", "symbol"]:
        if col in constituents.columns:
            symbol_col = col
            break

    if symbol_col is None:
        raise ValueError("Symbol column not found in constituent data.")

    symbols = (
        constituents[symbol_col]
        .astype(str)
        .str.strip()
        .replace("nan", "")
    )

    symbols = symbols[symbols != ""].drop_duplicates().tolist()

    # --------------------------------------------------------
    # 2. DOWNLOAD MARKET DATA
    # --------------------------------------------------------

    market_data = fetch_market_data(symbols)

    # --------------------------------------------------------
    # 3. CALCULATE METRICS
    # --------------------------------------------------------

    metrics_df = calculate_metrics(
        constituents,
        market_data
    )

    if metrics_df is None or metrics_df.empty:
        raise ValueError("No metrics data available.")

    # --------------------------------------------------------
    # 4. STANDARDIZE NUMERIC COLUMNS
    # --------------------------------------------------------

    numeric_columns = [
        "Close",
        "Change %",
        "Volume Change %",
        "Intraday Range %",
        "52W Low",
        "52W High",
        "Distance from 52W Low %",
        "Distance from 52W High %"
    ]

    for col in numeric_columns:
        if col in metrics_df.columns:
            metrics_df[col] = pd.to_numeric(
                metrics_df[col],
                errors="coerce"
            )

    # --------------------------------------------------------
    # 5. COMPANY NAME MAPPING
    # --------------------------------------------------------

    company_col = None

    for col in [
        "Company Name",
        "Company",
        "CompanyName",
        "COMPANY",
        "companyName"
    ]:
        if col in constituents.columns:
            company_col = col
            break

    if company_col is not None:

        company_map = dict(
            zip(
                constituents[symbol_col].astype(str).str.strip(),
                constituents[company_col].astype(str).str.strip()
            )
        )

        metrics_df["Company Name"] = (
            metrics_df["Symbol"]
            .astype(str)
            .str.strip()
            .map(company_map)
            .fillna(metrics_df["Symbol"])
        )

    else:

        metrics_df["Company Name"] = (
            metrics_df["Symbol"]
            .astype(str)
        )

    # --------------------------------------------------------
    # 6. MARKET SUMMARY
    # --------------------------------------------------------

    tolerance = 0.05

    gainers_df = metrics_df[
        metrics_df["Change %"] > tolerance
    ]

    losers_df = metrics_df[
        metrics_df["Change %"] < -tolerance
    ]

    flat_df = metrics_df[
        metrics_df["Change %"].abs() <= tolerance
    ]

    gainers = len(gainers_df)
    losers = len(losers_df)
    flat = len(flat_df)

    total = len(metrics_df)

    # --------------------------------------------------------
    # 7. ADV / DEC
    # --------------------------------------------------------

    adv_dec_text = f"{gainers} / {losers}"

    if total > 0:
        breadth_pct = (
            (gainers - losers) / total
        ) * 100
    else:
        breadth_pct = 0

    # --------------------------------------------------------
    # 8. TOP VOLUME CHANGE
    # --------------------------------------------------------

    volume_valid = metrics_df[
        metrics_df["Volume Change %"].notna()
    ]

    if not volume_valid.empty:

        top_volume_row = volume_valid.loc[
            volume_valid["Volume Change %"].idxmax()
        ]

        top_volume_symbol = str(
            top_volume_row["Symbol"]
        )

        top_volume_value = float(
            top_volume_row["Volume Change %"]
        )

    else:

        top_volume_symbol = "N/A"
        top_volume_value = 0

    # --------------------------------------------------------
    # 9. TOP INTRADAY RANGE
    # --------------------------------------------------------

    intraday_valid = metrics_df[
        metrics_df["Intraday Range %"].notna()
    ]

    if not intraday_valid.empty:

        top_intraday_row = intraday_valid.loc[
            intraday_valid["Intraday Range %"].idxmax()
        ]

        top_intraday_symbol = str(
            top_intraday_row["Symbol"]
        )

        top_intraday_value = float(
            top_intraday_row["Intraday Range %"]
        )

    else:

        top_intraday_symbol = "N/A"
        top_intraday_value = 0

    # --------------------------------------------------------
    # 10. 52 WEEK HIGH WATCH
    #     TOP 5 WITHIN 5%
    # --------------------------------------------------------

    high_watch = metrics_df[
        metrics_df["Distance from 52W High %"] <= 5
    ].copy()

    high_watch = high_watch.sort_values(
        "Distance from 52W High %"
    ).head(5)

    # --------------------------------------------------------
    # 11. 52 WEEK LOW WATCH
    #     ALL WITHIN 1%
    # --------------------------------------------------------

    low_watch = metrics_df[
        metrics_df["Distance from 52W Low %"] <= 1
    ].copy()

    low_watch = low_watch.sort_values(
        "Distance from 52W Low %"
    )

    # --------------------------------------------------------
    # 12. SORT MAIN TABLE
    # --------------------------------------------------------

    display_df = metrics_df.sort_values(
        "Change %",
        ascending=False
    ).reset_index(drop=True)

    display_df["Rank"] = range(
        1,
        len(display_df) + 1
    )

    # --------------------------------------------------------
    # 13. MARKET DATE
    # --------------------------------------------------------

    report_date = datetime.now().strftime(
        "%d-%b-%Y"
    )

    # --------------------------------------------------------
    # 14. HELPER FUNCTIONS
    # --------------------------------------------------------

    def format_price(value):

        if pd.isna(value):
            return "—"

        return f"₹{float(value):,.2f}"

    def format_pct(value):

        if pd.isna(value):
            return "—"

        value = float(value)

        if value > 0:
            return f"+{value:.2f}%"

        return f"{value:.2f}%"

    def change_class(value):

        if pd.isna(value):
            return "flat"

        value = float(value)

        if value > tolerance:
            return "positive"

        if value < -tolerance:
            return "negative"

        return "flat"

    # --------------------------------------------------------
    # 15. TABLE ROW GENERATOR
    # --------------------------------------------------------

    def build_table_rows(df):

        rows = []

        for _, row in df.iterrows():

            rank = int(row["Rank"])

            company = escape(
                str(row["Company Name"])
            )

            symbol = escape(
                str(row["Symbol"])
            )

            close = format_price(
                row["Close"]
            )

            change = format_pct(
                row["Change %"]
            )

            low52 = format_price(
                row["52W Low"]
            )

            high52 = format_price(
                row["52W High"]
            )

            cls = change_class(
                row["Change %"]
            )

            # ------------------------------------------------
            # IMPORTANT:
            # COLORS ARE INLINE + !IMPORTANT
            # This prevents old CSS from making text black.
            # ------------------------------------------------

            rows.append(
                f"""
                <tr>

                    <td style="
                        color:#D7DCE3 !important;
                        font-size:13px;
                        width:42px;
                        font-weight:500;
                    ">
                        {rank:02d}
                    </td>

                    <td style="
                        color:#F2F4F7 !important;
                        font-size:14px;
                        font-weight:600;
                        line-height:1.15;
                        min-width:220px;
                    ">
                        {company}

                        <div style="
                            color:#9FAABA !important;
                            font-size:11px;
                            font-weight:400;
                            margin-top:3px;
                        ">
                            {symbol}
                        </div>
                    </td>

                    <td style="
                        color:#E6EAF0 !important;
                        font-size:13px;
                        text-align:right;
                        white-space:nowrap;
                    ">
                        {close}
                    </td>

                    <td style="
                        color:
                        {'#00D084' if cls == 'positive'
                         else '#FF4D67' if cls == 'negative'
                         else '#B8C0CC'}
                        !important;

                        font-size:13px;
                        font-weight:700;
                        text-align:right;
                        white-space:nowrap;
                    ">
                        {change}
                    </td>

                    <td style="
                        color:#E6EAF0 !important;
                        font-size:13px;
                        text-align:right;
                        white-space:nowrap;
                    ">
                        {low52}
                    </td>

                    <td style="
                        color:#E6EAF0 !important;
                        font-size:13px;
                        text-align:right;
                        white-space:nowrap;
                    ">
                        {high52}
                    </td>

                </tr>
                """
            )

        return "".join(rows)

    # --------------------------------------------------------
    # 16. SPLIT TABLE INTO TWO COLUMNS
    # --------------------------------------------------------

    midpoint = (len(display_df) + 1) // 2

    left_df = display_df.iloc[
        :midpoint
    ].copy()

    right_df = display_df.iloc[
        midpoint:
    ].copy()

    left_rows = build_table_rows(
        left_df
    )

    right_rows = build_table_rows(
        right_df
    )

    # --------------------------------------------------------
    # 17. HIGH WATCH HTML
    # --------------------------------------------------------

    high_watch_html = ""

    if high_watch.empty:

        high_watch_html = """
        <div style="
            color:#8F9BAB !important;
            font-size:13px;
            padding-top:10px;
        ">
            None within 5%
        </div>
        """

    else:

        for _, row in high_watch.iterrows():

            symbol = escape(
                str(row["Symbol"])
            )

            distance = float(
                row["Distance from 52W High %"]
            )

            high_watch_html += f"""
            <div style="
                display:flex;
                justify-content:space-between;
                align-items:center;
                padding:8px 0;
                border-bottom:1px solid #272C33;
            ">

                <span style="
                    color:#F2F4F7 !important;
                    font-weight:600;
                    font-size:13px;
                ">
                    {symbol}
                </span>

                <span style="
                    color:#AEB7C4 !important;
                    font-size:12px;
                ">
                    {distance:.2f}% below high
                </span>

            </div>
            """

    # --------------------------------------------------------
    # 18. LOW WATCH HTML
    # --------------------------------------------------------

    low_watch_html = ""

    if low_watch.empty:

        low_watch_html = """
        <div style="
            color:#8F9BAB !important;
            font-size:13px;
            padding-top:10px;
        ">
            None within 1%
        </div>
        """

    else:

        for _, row in low_watch.iterrows():

            symbol = escape(
                str(row["Symbol"])
            )

            distance = float(
                row["Distance from 52W Low %"]
            )

            low_watch_html += f"""
            <div style="
                display:flex;
                justify-content:space-between;
                align-items:center;
                padding:7px 0;
                border-bottom:1px solid #272C33;
            ">

                <span style="
                    color:#F2F4F7 !important;
                    font-weight:600;
                    font-size:13px;
                ">
                    {symbol}
                </span>

                <span style="
                    color:#AEB7C4 !important;
                    font-size:12px;
                ">
                    {distance:.2f}% above low
                </span>

            </div>
            """

    # --------------------------------------------------------
    # 19. BREADTH BAR
    # --------------------------------------------------------

    if total > 0:

        advancing_width = (
            gainers / total
        ) * 100

        declining_width = (
            losers / total
        ) * 100

    else:

        advancing_width = 0
        declining_width = 0

    # --------------------------------------------------------
    # 20. FINAL HTML
    # --------------------------------------------------------

    html = f"""
    <html>

    <head>

    <meta charset="UTF-8">

    <style>

        * {{
            box-sizing:border-box;
        }}

        body {{
            margin:0;
            padding:0;
            background:#0B0F12;
            font-family:
                Arial,
                Helvetica,
                sans-serif;
            color:#E6EAF0;
        }}

        .report {{
            width:100%;
            background:#0F1317;
            padding:30px;
            border-radius:16px;
        }}

        .header {{
            display:flex;
            justify-content:space-between;
            align-items:flex-start;
            padding-bottom:22px;
            border-bottom:1px solid #292E35;
        }}

        .title {{
            color:#F2F4F7 !important;
            font-size:26px;
            font-weight:700;
            letter-spacing:.3px;
        }}

        .subtitle {{
            color:#8F9BAB !important;
            font-size:13px;
            margin-top:7px;
        }}

        .badge {{
            color:#AEB7C4 !important;
            background:#1B2128;
            border:1px solid #29313A;
            border-radius:7px;
            padding:8px 13px;
            font-size:11px;
            letter-spacing:1px;
        }}

        .section {{
            margin-top:22px;
        }}

        .cards {{
            display:grid;
            grid-template-columns:
                repeat(4, 1fr);
            gap:12px;
        }}

        .card {{
            background:#181D22;
            border:1px solid #292F36;
            border-radius:11px;
            padding:17px;
            min-height:88px;
        }}

        .label {{
            color:#8F9BAB !important;
            font-size:10px;
            letter-spacing:1px;
            text-transform:uppercase;
        }}

        .value {{
            color:#F2F4F7 !important;
            font-size:23px;
            font-weight:700;
            margin-top:9px;
        }}

        .green {{
            color:#00D084 !important;
        }}

        .red {{
            color:#FF4D67 !important;
        }}

        .blue {{
            color:#B7C8DD !important;
        }}

        .summary-grid {{
            display:grid;
            grid-template-columns:
                repeat(3, 1fr);
            gap:12px;
        }}

        .summary-box {{
            background:#181D22;
            border:1px solid #292F36;
            border-radius:11px;
            padding:17px;
            min-height:70px;
        }}

        .summary-value {{
            color:#F2F4F7 !important;
            font-size:17px;
            font-weight:700;
            margin-top:8px;
        }}

        .watch-grid {{
            display:grid;
            grid-template-columns:
                1fr 1fr;
            gap:12px;
        }}

        .watch-box {{
            background:#181D22;
            border:1px solid #292F36;
            border-radius:11px;
            padding:16px;
        }}

        .watch-title {{
            color:#8F9BAB !important;
            font-size:10px;
            letter-spacing:1px;
            text-transform:uppercase;
            margin-bottom:6px;
        }}

        .breadth-box {{
            background:#181D22;
            border:1px solid #292F36;
            border-radius:11px;
            padding:16px;
        }}

        .breadth-text {{
            color:#DCE2E9 !important;
            font-size:13px;
            margin-top:8px;
        }}

        .breadth-bar {{
            height:7px;
            width:100%;
            background:#2A3037;
            border-radius:10px;
            overflow:hidden;
            margin-top:9px;
        }}

        .breadth-fill {{
            height:100%;
            background:#657384;
            border-radius:10px;
        }}

        .tables {{
            display:grid;
            grid-template-columns:
                1fr 1fr;
            gap:18px;
            margin-top:22px;
        }}

        .table-wrap {{
            width:100%;
        }}

        table {{
            width:100%;
            border-collapse:collapse;
            table-layout:auto;
        }}

        th {{
            color:#8F9BAB !important;
            font-size:10px;
            letter-spacing:.8px;
            font-weight:500;
            text-align:left;
            padding:0 8px 11px 8px;
            border-bottom:1px solid #30363D;
        }}

        td {{
            color:#E6EAF0 !important;
            padding:9px 8px;
            border-bottom:1px solid #252A30;
            background:#0F1317;
        }}

        tr:nth-child(even) td {{
            background:#171C21;
        }}

        .footer {{
            margin-top:22px;
            padding-top:15px;
            border-top:1px solid #292F36;
        }}

        .footer-text {{
            color:#718092 !important;
            font-size:10px;
            line-height:1.6;
        }}

    </style>

    </head>

    <body>

    <div class="report">

        <!-- HEADER -->

        <div class="header">

            <div>

                <div class="title">
                    {escape(index_name)}
                    / EOD MARKET SUMMARY
                </div>

                <div class="subtitle">
                    {report_date} · Market Close
                </div>

            </div>

            <div class="badge">
                AUTOMATED
            </div>

        </div>


        <!-- SNAPSHOT -->

        <div class="section">

            <div class="cards">

                <div class="card">

                    <div class="label">
                        Gainers
                    </div>

                    <div class="value green">
                        {gainers}
                    </div>

                </div>


                <div class="card">

                    <div class="label">
                        Losers
                    </div>

                    <div class="value red">
                        {losers}
                    </div>

                </div>


                <div class="card">

                    <div class="label">
                        Flat
                    </div>

                    <div class="value">
                        {flat}
                    </div>

                </div>


                <div class="card">

                    <div class="label">
                        ADV / DEC
                    </div>

                    <div class="value">
                        {adv_dec_text}
                    </div>

                </div>

            </div>

        </div>


        <!-- MARKET ALERTS -->

        <div class="section">

            <div class="summary-grid">

                <div class="summary-box">

                    <div class="label">
                        Top Volume Change
                    </div>

                    <div class="summary-value">
                        {escape(top_volume_symbol)}
                        <span class="green">
                            {format_pct(top_volume_value)}
                        </span>
                    </div>

                </div>


                <div class="summary-box">

                    <div class="label">
                        Top Intraday Range
                    </div>

                    <div class="summary-value">
                        {escape(top_intraday_symbol)}
                        <span class="blue">
                            {top_intraday_value:.2f}%
                        </span>
                    </div>

                </div>


                <div class="summary-box">

                    <div class="label">
                        Market Breadth
                    </div>

                    <div class="summary-value">
                        {breadth_pct:.1f}%
                    </div>

                </div>

            </div>

        </div>


        <!-- 52 WEEK WATCH -->

        <div class="section">

            <div class="watch-grid">

                <div class="watch-box">

                    <div class="watch-title">
                        52W HIGH WATCH · TOP 5 · WITHIN 5%
                    </div>

                    {high_watch_html}

                </div>


                <div class="watch-box">

                    <div class="watch-title">
                        52W LOW WATCH · ALL · WITHIN 1%
                    </div>

                    {low_watch_html}

                </div>

            </div>

        </div>


        <!-- BREADTH -->

        <div class="section">

            <div class="breadth-box">

                <div class="label">
                    Market Breadth · ADV / DEC
                </div>

                <div class="breadth-text">
                    {gainers} Advancing / {losers} Declining
                </div>

                <div class="breadth-bar">

                    <div
                        class="breadth-fill"
                        style="
                            width:{declining_width:.2f}%;
                        "
                    ></div>

                </div>

            </div>

        </div>


        <!-- MAIN TABLE -->

        <div class="tables">

            <div class="table-wrap">

                <table>

                    <thead>

                        <tr>

                            <th>#</th>
                            <th>COMPANY</th>
                            <th style="text-align:right;">
                                CLOSE
                            </th>
                            <th style="text-align:right;">
                                CHANGE
                            </th>
                            <th style="text-align:right;">
                                52W LOW
                            </th>
                            <th style="text-align:right;">
                                52W HIGH
                            </th>

                        </tr>

                    </thead>

                    <tbody>

                        {left_rows}

                    </tbody>

                </table>

            </div>


            <div class="table-wrap">

                <table>

                    <thead>

                        <tr>

                            <th>#</th>
                            <th>COMPANY</th>
                            <th style="text-align:right;">
                                CLOSE
                            </th>
                            <th style="text-align:right;">
                                CHANGE
                            </th>
                            <th style="text-align:right;">
                                52W LOW
                            </th>
                            <th style="text-align:right;">
                                52W HIGH
                            </th>

                        </tr>

                    </thead>

                    <tbody>

                        {right_rows}

                    </tbody>

                </table>

            </div>

        </div>


        <!-- FOOTER -->

        <div class="footer">

            <div class="footer-text">
                Source: NSE constituents + Yahoo Finance EOD data
            </div>

            <div class="footer-text">
                Provided for reference on a best-effort basis.
            </div>

        </div>

    </div>

    </body>

    </html>
    """

    # --------------------------------------------------------
    # 21. FINAL SAFETY PATCH
    # --------------------------------------------------------
    # This is intentionally redundant.
    # It makes sure generated table cells cannot inherit
    # black text from any outer CSS.

    html = html.replace(
        "<body>",
        """
        <body style="
            background:#0B0F12 !important;
            color:#E6EAF0 !important;
        ">
        """
    )

    return html

def prepare_export_data(index_name):
    """
    Prepare complete CSV export data.

    Output columns:
    Symbol
    Close
    Change %
    Volume Change %
    Intraday Range %
    52W Low
    52W High
    Distance from 52W Low %
    Distance from 52W High %
    Company
    """

    print(f"Preparing CSV data → {index_name}")

    # --------------------------------------------------------
    # 1. Fetch constituents
    # --------------------------------------------------------
    constituents = fetch_index_constituents(index_name)

    print(f"Constituents found: {len(constituents)}")

    # --------------------------------------------------------
    # 2. Fetch EOD market data
    # --------------------------------------------------------
    symbols = (
        constituents["Symbol"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )

    market_data = fetch_market_data(symbols)

    # --------------------------------------------------------
    # 3. Calculate metrics
    # --------------------------------------------------------
    metrics = calculate_metrics(
        constituents,
        market_data
    )

    if metrics.empty:
        raise ValueError(
            f"No metrics generated for {index_name}"
        )

    # --------------------------------------------------------
    # 4. Build Symbol → Company mapping
    # --------------------------------------------------------
    name_map = dict(
        zip(
            constituents["Symbol"]
                .astype(str)
                .str.strip(),

            constituents["Company Name"]
                .astype(str)
                .str.strip()
        )
    )

    # --------------------------------------------------------
    # 5. Add Company column
    # --------------------------------------------------------
    metrics["Company"] = (
        metrics["Symbol"]
        .astype(str)
        .str.strip()
        .map(name_map)
    )

    # --------------------------------------------------------
    # 6. Safety check
    # --------------------------------------------------------
    missing_company = metrics["Company"].isna().sum()

    if missing_company > 0:

        print(
            f"⚠️ Company mapping missing for "
            f"{missing_company} rows"
        )

        metrics["Company"] = (
            metrics["Company"]
            .fillna(metrics["Symbol"])
        )

    # --------------------------------------------------------
    # 7. Same ordering as report
    # --------------------------------------------------------
    metrics = (
        metrics
        .sort_values(
            "Change %",
            ascending=False
        )
        .reset_index(drop=True)
    )

    # --------------------------------------------------------
    # 8. FINAL column order
    # --------------------------------------------------------
    final_columns = [
        "Symbol",
        "Close",
        "Change %",
        "Volume Change %",
        "Intraday Range %",
        "52W Low",
        "52W High",
        "Distance from 52W Low %",
        "Distance from 52W High %",
        "Company"
    ]

    # Keep only columns that should exist
    metrics = metrics[final_columns]

    print(
        f"Export rows: {len(metrics)}"
    )

    print(
        f"Export columns: {metrics.columns.tolist()}"
    )

    return metrics

def export_csv(index_name):

    metrics = prepare_export_data(index_name)

    date_str = datetime.now().strftime("%Y-%m-%d")

    safe_name = index_name.replace(" ", "_")

    path = os.path.join(
        EXPORT_DIR,
        f"{safe_name}_EOD_{date_str}.csv"
    )

    metrics.to_csv(
        path,
        index=False
    )

    print(
        f"✅ CSV CREATED → {path}"
    )

    print(
        f"Rows    : {len(metrics)}"
    )

    print(
        f"Columns : {len(metrics.columns)}"
    )

    return path

def export_png(index_name):
    """Render the final report HTML to a high-resolution PNG with Chromium."""
    if index_name not in INDEX_CONFIG:
        raise ValueError(f"Index not configured: {index_name}")

    html_report = generate_report(index_name)
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_name = index_name.replace(" ", "_").replace("/", "_")
    output_file = EXPORT_DIR / f"{safe_name}_EOD_{date_str}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2
        )
        page.set_content(html_report, wait_until="networkidle", timeout=90000)
        page.screenshot(path=str(output_file), full_page=True)
        browser.close()

    if not output_file.exists() or output_file.stat().st_size == 0:
        raise RuntimeError("PNG export failed: output file was not created.")
    return str(output_file)


def ui_generate_report(index_name):
    if not index_name:
        return "<div style='padding:20px;color:#ffcc66;'>Please select an index.</div>", None, None, "Waiting for index selection."
    try:
        html_report = generate_report(index_name)
        png_path = export_png(index_name)
        csv_path = export_csv(index_name)
        status = (
            f"✅ Report generated successfully<br>"
            f"<b>Index:</b> {escape(index_name)}<br>"
            f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d')}<br>"
            f"<b>PNG:</b> Ready<br><b>CSV:</b> Ready"
        )
        return html_report, png_path, csv_path, status
    except Exception as exc:
        safe_error = escape(str(exc))
        error_html = (
            "<div style='background:#2b1515;border:1px solid #8b3a3a;"
            "padding:20px;border-radius:10px;color:#ff8080;font-family:Arial'>"
            f"<h3>Report Generation Error</h3><pre style='white-space:pre-wrap'>{safe_error}</pre></div>"
        )
        return error_html, None, None, f"❌ Error: {safe_error}"


UI_INDEXES = list(INDEX_CONFIG.keys())

with gr.Blocks(title="Automated NSE EOD Report Generator", theme=gr.themes.Base()) as app:
    gr.Markdown(
        "# 📊 Automated NSE EOD Report Generator\n"
        "### Stage 1 — Multi-Index Market Report Engine\n"
        "Generate an end-of-day report for any configured NSE index."
    )
    with gr.Row():
        index_dropdown = gr.Dropdown(
            choices=UI_INDEXES,
            value="NIFTY 50",
            label="Select Index",
            interactive=True
        )
        generate_button = gr.Button("🚀 Generate / Refresh Report", variant="primary")

    status_box = gr.HTML(
        "<div style='padding:12px;background:#151515;border-radius:8px;color:#aaa'>"
        "Select an index and click <b>Generate / Refresh Report</b>.</div>"
    )
    gr.Markdown("## 📈 EOD Market Report")
    report_html = gr.HTML(
        "<div style='padding:40px;text-align:center;background:#111;border-radius:12px;color:#888'>"
        "Report will appear here.</div>"
    )
    gr.Markdown("## 📥 Downloads")
    with gr.Row():
        png_download = gr.File(label="🖼️ PNG Report", interactive=False)
        csv_download = gr.File(label="📊 CSV Data", interactive=False)

    generate_button.click(
        fn=ui_generate_report,
        inputs=[index_dropdown],
        outputs=[report_html, png_download, csv_download, status_box]
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.launch(server_name="0.0.0.0", server_port=port, share=False)
