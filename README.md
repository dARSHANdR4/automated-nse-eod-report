<div align="center">

# 📊 Automated NSE EOD Report Generator

**A clean, multi-index end-of-day snapshot of the Indian equity market.**

Generate a structured market report with market breadth, stock performance, 52-week high/low watch, and downloadable PNG and CSV exports.

[🚀 Open Live Dashboard](https://automated-nse-eod-report.onrender.com) · [📦 View Source Code](https://github.com/dARSHANdR4/automated-nse-eod-report)

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)
![Gradio](https://img.shields.io/badge/UI-Gradio-orange?logo=gradio&logoColor=white)
![Deployment](https://img.shields.io/badge/Deployment-Render-46E3B7?logo=render&logoColor=black)
![Report](https://img.shields.io/badge/Report-EOD-0A7EA4)
![Status](https://img.shields.io/badge/Status-Live-brightgreen)

</div>

---

## ✨ Overview

The **Automated NSE EOD Report Generator** is a Python-based dashboard for reviewing end-of-day market data across selected NSE indices. Choose an index, generate a report, inspect the market snapshot, and download the output for your own review or record-keeping.

**Live app:** https://automated-nse-eod-report.onrender.com

## 📌 Features

- **Multi-index selector** — switch between six configured NSE indices.
- **Market summary** — gainers, losers, flat stocks, and advance/decline counts.
- **Market breadth** — a quick view of advancing versus declining constituents.
- **Volume and intraday range highlights** — surface notable activity in the selected universe.
- **52-week high/low watch** — highlight stocks near relevant 52-week levels when data is available.
- **Ranked stock tables** — review constituent-level prices and daily changes.
- **PNG export** — save a shareable image of the report.
- **CSV export** — download tabular data for further analysis.
- **Browser-based interface** — use the deployed dashboard without setting up Python locally.

## 🧭 Supported indices

| Index | Selection |
|---|---|
| NIFTY 50 | Large-cap benchmark |
| NIFTY NEXT 50 | Next group of large companies |
| NIFTY MIDCAP 150 | Mid-cap universe |
| NIFTY SMALLCAP 250 | Small-cap universe |
| NIFTY MIDCAP 50 | Mid-cap selection |
| NIFTY SMALLCAP 50 | Small-cap selection |

> Index availability in the dropdown does not guarantee that every constituent has usable data on every run. The report depends on the availability and quality of its upstream sources.

## 🖥️ How to use

1. Open the [live dashboard](https://automated-nse-eod-report.onrender.com).
2. Select an index from the dropdown.
3. Click **Generate / Refresh Report** once.
4. Wait for the report and download links to appear.
5. Review the report and download the PNG or CSV if needed.

## 🧰 Technology

- **Python** — report generation and data processing
- **Gradio** — web interface
- **pandas** — tabular data handling
- **yfinance** — market-data retrieval
- **Playwright + Chromium** — PNG report rendering
- **Docker** — deployment packaging
- **Render** — hosted web service
- **GitHub** — source control and deployment trigger

## 🏗️ Project structure

```text
automated-nse-eod-report/
├── app.py
├── Dockerfile
├── requirements.txt
└── README.md
```

## 🔄 Data and report notes

- The app retrieves index constituents and market data from external sources when a report is generated.
- Market data and derived metrics are provided on a **best-effort basis** and can be affected by source availability, rate limits, missing tickers, and delays.
- The report is an end-of-day snapshot; it should not be assumed to be a real-time intraday feed.
- Exported files are temporary download outputs, not a permanent report archive.
- The free hosted service may sleep after inactivity, so the first request after a quiet period can take longer.
- Small-cap indices may produce fewer usable rows if some constituent symbols do not return valid market data.

## 🗺️ Roadmap

- [ ] Validate all six index selections end-to-end.
- [ ] Improve data freshness and source-quality indicators.
- [ ] Add a combined comparison view across the configured indices.
- [ ] Add a persistent daily history archive.
- [ ] Explore scheduled EOD generation and notifications.

## ⚠️ Disclaimer

This project is intended for market observation, reporting, and research. It is **not investment advice** and does not provide guaranteed predictions or returns. Verify important figures with authoritative sources before making financial decisions.

## 🤝 Contributions and feedback

Found an issue or have an improvement idea? Open an issue in this repository with:
- the selected index,
- the approximate time of the run,
- the error message or screenshot, and
- whether the HTML report, PNG export, or CSV export failed.

---

<div align="center">

**Built to make daily NSE market review easier.**

[Open Dashboard](https://automated-nse-eod-report.onrender.com) · [GitHub Repository](https://github.com/dARSHANdR4/automated-nse-eod-report)

</div>
