"""
weekly_summary.py
直近5営業日分のスクリーニング結果を集計して、週次TOP5レポートを生成する。

使い方:
  python3 weekly_summary.py

【出力】
- ./output/weekly_summary_YYYY-MM-DD.csv : 週次集計データ
- ./output/weekly_summary_YYYY-MM-DD.md  : Claude Code への分析インプット用
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_recent_csv_files(n: int = 5) -> list[Path]:
    """直近n件のスクリーニング結果CSVを新しい順で返す。"""
    output_dir = Path(config.OUTPUT_DIR)
    files = sorted(output_dir.glob("top_candidates_*.csv"), reverse=True)
    if not files:
        raise FileNotFoundError(f"{output_dir} にスクリーニング結果が見つかりません。")
    return files[:n]


def load_and_tag(csv_path: Path) -> pd.DataFrame:
    """CSVを読み込み、日付カラムを付与する。"""
    date_str = csv_path.stem.replace("top_candidates_", "")
    df = pd.read_csv(csv_path, dtype={"code": str})
    df["date"] = date_str
    df["rank_of_day"] = range(1, len(df) + 1)
    return df


def build_weekly_summary(files: list[Path]) -> pd.DataFrame:
    """複数日のデータを結合して銘柄ごとに集計する。"""
    frames = [load_and_tag(f) for f in files]
    all_data = pd.concat(frames, ignore_index=True)

    # 日付を昇順ソート(トレンド計算用)
    all_data = all_data.sort_values("date")
    dates = sorted(all_data["date"].unique())

    summary_rows = []
    for code, grp in all_data.groupby("code"):
        grp = grp.sort_values("date")
        name = grp["name"].iloc[-1]
        sector = grp.get("sector_33", pd.Series(["–"] * len(grp))).iloc[-1]

        scores = grp["total_score"].tolist()
        dates_appeared = grp["date"].tolist()

        # 最新スコア・最古スコア・トレンド
        latest_score = scores[-1]
        oldest_score = scores[0]
        score_trend = latest_score - oldest_score  # 正 = 上昇

        # 出現回数 / 最高ランク / 平均スコア
        appearance = len(grp)
        best_rank = grp["rank_of_day"].min()
        avg_score = grp["total_score"].mean()
        latest_rank = grp.loc[grp["date"] == grp["date"].max(), "rank_of_day"].values[0]

        # 最新の主要指標
        latest = grp.iloc[-1]

        # 週次総合スコア: 出現回数×平均スコア×(1 + トレンド補正)
        # トレンド補正: +10pp上昇で+10%加点、-10pp下落で-10%減点
        trend_bonus = 1.0 + (score_trend / 100.0)
        weekly_score = (appearance / len(dates)) * avg_score * trend_bonus

        summary_rows.append({
            "code": code,
            "name": name,
            "sector": sector,
            "appearance": appearance,
            "best_rank": best_rank,
            "latest_rank": latest_rank,
            "avg_score": round(avg_score, 1),
            "latest_score": round(latest_score, 1),
            "score_trend": round(score_trend, 1),
            "weekly_score": round(weekly_score, 1),
            "PBR": latest.get("PBR", None),
            "PER": latest.get("PER", None),
            "Dividend_Yield": latest.get("Dividend_Yield", None),
            "ROE": latest.get("ROE", None),
            "market_cap_oku_yen": latest.get("market_cap_oku_yen", None),
            "dates_appeared": ",".join(dates_appeared),
        })

    summary = pd.DataFrame(summary_rows)
    summary = summary.sort_values("weekly_score", ascending=False).reset_index(drop=True)
    return summary, dates


def export_summary(summary: pd.DataFrame, dates: list[str], today: str) -> Path:
    """週次サマリーをCSVとMarkdownで出力する。"""
    output_dir = Path(config.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / f"weekly_summary_{today}.csv"
    summary.to_csv(csv_path, index=False)
    logger.info(f"CSV出力: {csv_path}")

    top5 = summary.head(5)

    md_lines = [
        f"# 週次スクリーニング TOP5 レポート",
        f"",
        f"**集計期間:** {dates[0]} 〜 {dates[-1]}({len(dates)}営業日)",
        f"**生成日時:** {today}",
        f"",
        f"## 総合ランキング TOP5",
        f"",
        f"| 順位 | コード | 銘柄名 | セクター | 出現回数 | 平均スコア | トレンド | 週次スコア |",
        f"|------|--------|--------|---------|---------|-----------|---------|-----------|",
    ]

    for i, row in top5.iterrows():
        trend_str = f"+{row['score_trend']}" if row['score_trend'] >= 0 else str(row['score_trend'])
        trend_emoji = "📈" if row['score_trend'] > 0 else ("📉" if row['score_trend'] < 0 else "➡️")
        md_lines.append(
            f"| {i+1}位 | {row['code']} | {row['name']} | {row['sector']} | "
            f"{row['appearance']}/{len(dates)}日 | {row['avg_score']} | {trend_emoji}{trend_str} | {row['weekly_score']} |"
        )

    md_lines += [
        f"",
        f"## 銘柄別詳細",
        f"",
    ]

    for i, row in top5.iterrows():
        trend_str = f"+{row['score_trend']}" if row['score_trend'] >= 0 else str(row['score_trend'])
        trend_emoji = "📈" if row['score_trend'] > 0 else ("📉" if row['score_trend'] < 0 else "➡️")
        pbr = f"{row['PBR']:.2f}" if pd.notna(row.get('PBR')) else "–"
        per = f"{row['PER']:.1f}" if pd.notna(row.get('PER')) else "–"
        div = f"{row['Dividend_Yield']:.2f}%" if pd.notna(row.get('Dividend_Yield')) else "–"
        roe = f"{row['ROE']:.1f}%" if pd.notna(row.get('ROE')) else "–"
        cap = f"{row['market_cap_oku_yen']:.0f}億円" if pd.notna(row.get('market_cap_oku_yen')) else "–"

        md_lines += [
            f"### {i+1}位: {row['name']}({row['code']}) — {row['sector']}",
            f"",
            f"- **週次スコア:** {row['weekly_score']} / 出現: {row['appearance']}/{len(dates)}日 / 最高順位: {row['best_rank']}位 / 直近順位: {row['latest_rank']}位",
            f"- **スコアトレンド:** {trend_emoji} {trend_str}pp({dates[0]}→{dates[-1]})",
            f"- **主要指標(直近):** PBR {pbr} / PER {per} / 配当利回り {div} / ROE {roe} / 時価総額 {cap}",
            f"- **出現日:** {row['dates_appeared'].replace(',', ' / ')}",
            f"",
        ]

    md_lines += [
        f"## 注意事項",
        f"",
        f"- 週次スコアは「出現頻度 × 平均スコア × トレンド補正」で算出。あくまで深掘り候補の優先順位付けに使うもの。",
        f"- スコア上昇(📈)は株価下落によるバリュエーション割安化を含む。下落理由の確認が必要。",
        f"- 最終判断はKuri自身が行う。",
    ]

    md_path = output_dir / f"weekly_summary_{today}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    logger.info(f"Markdown出力: {md_path}")

    return md_path


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"=== 週次サマリー生成開始 {today} ===")

    files = get_recent_csv_files(n=5)
    logger.info(f"集計対象: {[f.name for f in files]}")

    summary, dates = build_weekly_summary(files)
    md_path = export_summary(summary, dates, today)

    logger.info("=== 完了 ===")
    logger.info(f"TOP5確認: {md_path}")
    logger.info("次の作業: Claude Code に「今週のTOP5を分析してSlackとNotionに投稿して」と依頼")


if __name__ == "__main__":
    main()
