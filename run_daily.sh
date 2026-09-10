#!/bin/bash
# 毎営業日のスクリーニング自動実行スクリプト
# cron から呼び出される

cd "$(dirname "$0")"

LOG_DIR="./logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/screening_$(date +%Y-%m-%d).log"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') スクリーニング開始 ===" >> "$LOG_FILE"

python3 run_screening.py >> "$LOG_FILE" 2>&1

EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') スクリーニング完了 ===" >> "$LOG_FILE"
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') アラートチェック開始 ===" >> "$LOG_FILE"
    python3 check_alerts.py >> "$LOG_FILE" 2>&1
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') アラートチェック完了 ===" >> "$LOG_FILE"
else
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') エラー (exit code: $EXIT_CODE) ===" >> "$LOG_FILE"
fi
