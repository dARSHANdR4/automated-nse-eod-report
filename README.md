# Automated NSE EOD Report Generator — Render deployment package

This package is extracted from the uploaded `autoreportgeneration.ipynb` notebook and prepares the final V3.2 report engine for independent hosting.

## Included
- Six-index dropdown: NIFTY 50, NIFTY NEXT 50, NIFTY MIDCAP 150, NIFTY SMALLCAP 250, NIFTY MIDCAP 50, NIFTY SMALLCAP 50
- Generate / Refresh button
- V3.2 HTML report
- PNG export using Playwright Chromium
- CSV export with company name and market metrics

## Deploy on Render
1. Upload these files to a GitHub repository.
2. In Render, choose **New + → Web Service**, connect the repository.
3. Choose the Docker runtime if prompted.
4. Select the Free instance type if available for your account/region.
5. Deploy. The app reads Render's `PORT` environment variable.
6. Test all six indices, PNG downloads and CSV downloads.

## Notes
- Free hosting may sleep after inactivity and may have resource/time limits.
- Market data is retrieved live from the NSE constituent CSV archive and Yahoo Finance when a report is generated.
- Export files are temporary; download them when generated. They are not permanent storage.
- Smallcap 250 may return fewer market-data rows than the published constituent file if some tickers have no usable Yahoo Finance data.
- Market metrics are best-effort and depend on source availability.
