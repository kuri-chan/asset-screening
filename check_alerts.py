"""
check_alerts.py
前日比のスコア変化を検知し、条件を満たす銘柄をSlackに自動通知する。

アラート条件:
  1. スコアが前日比 ALERT_SCORE_JUMP 以上上昇
  2. 圏外から ALERT_NEW_ENTRY_RANK 以内に新規ランクイン
  3. ALERT_CONSECUTIVE_RISE 日連続でスコアが上昇中

使い方:
  python3 check_alerts.py          # 最新2日間を比較
  python3 check_alerts.py --dry-run  # Slack通知せずに結果だけ表示
"""

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
import requests

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_recent_csvs(n: int = 5) -> list[tuple[str, pd.DataFrame]]:
    """直近n件のスクリーニング結果を (日付, DataFrame) のリストで返す(新しい順)。"""
    output_dir = Path(config.OUTPUT_DIR)
    files = sorted(output_dir.glob("top_candidates_*.csv"), reverse=True)[:n]
    result = []
    for f in files:
        date_str = f.stem.replace("top_candidates_", "")
        df = pd.read_csv(f, dtype={"code": str})
        df["rank"] = range(1, len(df) + 1)
        result.append((date_str, df))
    return result


def detect_alerts(recent: list[tuple[str, pd.DataFrame]]) -> list[dict]:
    """アラート条件に該当する銘柄を検出する。"""
    if len(recent) < 2:
        logger.warning("比較に必要なデータが不足しています(2日分以上必要)。")
        return []

    today_date, today_df = recent[0]
    yesterday_date, yesterday_df = recent[1]

    alerts = []

    # 前日のスコア・ランクをマッピング
    yesterday_map = yesterday_df.set_index("code")[["total_score", "rank"]].to_dict("index")

    for _, row in today_df.iterrows():
        code = row["code"]
        name = row["name"]
        today_score = row["total_score"]
        today_rank = row["rank"]
        triggered = []

        if code in yesterday_map:
            yesterday_score = yesterday_map[code]["total_score"]
            score_diff = today_score - yesterday_score

            # 条件1: スコア急上昇
            if score_diff >= config.ALERT_SCORE_JUMP:
                triggered.append({
                    "type": "score_jump",
                    "label": f"📈 スコア急上昇 +{score_diff:.1f}pt",
                    "detail": f"{yesterday_date}: {yesterday_score:.1f} → {today_date}: {today_score:.1f}"
                })
        else:
            # 条件2: 新規ランクイン
            if today_rank <= config.ALERT_NEW_ENTRY_RANK:
                triggered.append({
                    "type": "new_entry",
                    "label": f"🆕 新規ランクイン {today_rank}位",
                    "detail": f"前日は圏外 → 本日{today_rank}位(スコア: {today_score:.1f})"
                })

        # 条件3: 連続上昇(3日以上)
        if len(recent) >= config.ALERT_CONSECUTIVE_RISE:
            scores = []
            for date, df in recent[:config.ALERT_CONSECUTIVE_RISE]:
                row_match = df[df["code"] == code]
                if not row_match.empty:
                    scores.append((date, row_match.iloc[0]["total_score"]))
            if len(scores) == config.ALERT_CONSECUTIVE_RISE:
                scores_sorted = sorted(scores, key=lambda x: x[0])
                if all(scores_sorted[i][1] < scores_sorted[i+1][1]
                       for i in range(len(scores_sorted)-1)):
                    trend_str = " → ".join(f"{s:.1f}" for _, s in scores_sorted)
                    triggered.append({
                        "type": "consecutive_rise",
                        "label": f"🔥 {config.ALERT_CONSECUTIVE_RISE}日連続上昇",
                        "detail": trend_str
                    })

        if triggered:
            alerts.append({
                "code": code,
                "name": name,
                "sector": row.get("sector_33", "–"),
                "today_score": today_score,
                "today_rank": today_rank,
                "PBR": row.get("PBR"),
                "PER": row.get("PER"),
                "div_yield": row.get("Dividend_Yield"),
                "ROE": row.get("ROE"),
                "market_cap": row.get("market_cap_oku_yen"),
                "triggers": triggered,
            })

    return alerts


def build_slack_message(alerts: list[dict], today_date: str) -> dict:
    """Slack通知用のメッセージを構築する。"""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"⚡ 銘柄アラート — {today_date}"}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"スクリーニング条件に変化があった銘柄が *{len(alerts)}件* 検出されました。"
            }
        },
        {"type": "divider"}
    ]

    for a in alerts:
        pbr = f"{a['PBR']:.2f}" if pd.notna(a.get("PBR")) else "–"
        per = f"{a['PER']:.1f}" if pd.notna(a.get("PER")) else "–"
        div = f"{a['div_yield']:.2f}%" if pd.notna(a.get("div_yield")) else "–"
        roe = f"{a['ROE']:.1f}%" if pd.notna(a.get("ROE")) else "–"
        cap = f"{a['market_cap']:.0f}億円" if pd.notna(a.get("market_cap")) else "–"

        trigger_lines = "\n".join(
            f"• *{t['label']}*: {t['detail']}" for t in a["triggers"]
        )

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{a['name']}({a['code']})* — {a['sector']} / {a['today_rank']}位 / スコア{a['today_score']:.1f}\n"
                    f"{trigger_lines}\n"
                    f"PBR {pbr} / PER {per} / 配当 {div} / ROE {roe} / 時価総額 {cap}\n"
                    f"<https://finance.yahoo.co.jp/quote/{a['code']}.T|Yahoo!F> | "
                    f"<https://irbank.net/{a['code']}/|IR BANK>"
                )
            }
        })
        blocks.append({"type": "divider"})

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "⚠️ このアラートは深掘り候補の通知です。「買い推奨」ではありません。最終判断はご自身で行ってください。"}]
    })

    return {"blocks": blocks}


def send_slack(message: dict) -> bool:
    """Slack Incoming Webhook にメッセージを送信する。"""
    if not config.SLACK_WEBHOOK_URL:
        logger.error("SLACK_WEBHOOK_URL が設定されていません。")
        return False

    resp = requests.post(
        config.SLACK_WEBHOOK_URL,
        data=json.dumps(message),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    if resp.status_code == 200:
        logger.info("Slack通知を送信しました。")
        return True
    else:
        logger.error(f"Slack送信失敗: {resp.status_code} {resp.text}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Slack通知せずに結果を表示するだけ")
    args = parser.parse_args()

    recent = load_recent_csvs(n=5)
    if not recent:
        logger.error("スクリーニング結果が見つかりません。")
        return

    today_date = recent[0][0]
    logger.info(f"=== アラートチェック {today_date} ===")

    alerts = detect_alerts(recent)

    if not alerts:
        logger.info("アラート条件に該当する銘柄はありませんでした。")
        return

    logger.info(f"{len(alerts)}件のアラートを検出:")
    for a in alerts:
        for t in a["triggers"]:
            logger.info(f"  {a['name']}({a['code']}): {t['label']}")

    if args.dry_run:
        logger.info("--dry-run モード: Slack通知はスキップします。")
        return

    message = build_slack_message(alerts, today_date)
    send_slack(message)


if __name__ == "__main__":
    main()
