#!/bin/bash
# Daily AI Analysis Pipeline — runs at 23:00 BRT via cron
#
# Cron entry (add with: crontab -e):
#   0 2 * * * /c/Dev/polymarket-v1/cron_daily_analysis.sh >> /c/Dev/polymarket-v1/logs/cron.log 2>&1
#   (2:00 UTC = 23:00 BRT)
#
# Or on Windows Task Scheduler:
#   Program: bash
#   Arguments: /c/Dev/polymarket-v1/cron_daily_analysis.sh
#   Trigger: Daily at 23:00

cd /c/Dev/polymarket-v1 || exit 1

echo "=== $(date) === Starting daily analysis ==="

# Export data and run analysis via OpenClaw + send to Telegram
python daily_report.py --days 1 --analyze --telegram

echo "=== $(date) === Done ==="
