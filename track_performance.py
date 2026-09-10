"""
track_performance.py
スクリーニング選出銘柄の実績を追跡・検証する。

機能:
  1. 選出日の株価を記録(entry price)
  2. 現在の株価でリターンを計算
  3. TOPIX(^TOPX)とのアルファを比較
  4. 結果をCSVに蓄積

使い方:
  # 指定日の選出銘柄の現在リターンを確認
  python3 track_performance.py --check 2026-05-12

  # 本日の選出銘柄の入場価格を記録(毎日のスクリーニング後に実行)
  python3 track_performance.py --record

  # 全記録のサマリーを表示
  python3 track_performance.py --summary
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PERF_DIR = Path(config.OUTPUT_DIR) / "performance"
PERF_DIR.mkdir(parents=True, exist_ok=True)

TOPIX_TICKER = "1306.T"   # TOPIX連動ETF(野村)をベンチマークに使用
BENCHMARK_NAME = "TOPIX ETF(1306)"


def get_price_on_date(ticker: str, date_str: str) -> float | None:
    """指定日(または直近営業日)の終値を取得する。"""
    try:
        tk = yf.Ticker(ticker)
        start = (pd.Timestamp(date_str) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        end = (pd.Timestamp(date_str) + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        hist = tk.history(start=start, end=end)
        if hist.empty:
            return None
        # タイムゾーンを除去して比較
        hist.index = hist.index.tz_localize(None) if hist.index.tz is None else hist.index.tz_convert(None)
        cutoff = pd.Timestamp(date_str)
        hist = hist[hist.index.normalize() <= cutoff]
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"{ticker}: 価格取得エラー {e}")
        return None


def get_current_price(ticker: str) -> float | None:
    """現在の株価を取得する。"""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="5d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"{ticker}: 現在価格取得エラー {e}")
        return None


def record_entry(date_str: str = None):
    """本日の選出銘柄の入場価格を記録する。"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    csv_path = Path(config.OUTPUT_DIR) / f"top_candidates_{date_str}.csv"
    if not csv_path.exists():
        logger.error(f"スクリーニング結果が見つかりません: {csv_path}")
        return

    df = pd.read_csv(csv_path, dtype={"code": str})
    top = df.head(config.TOP_N_FOR_QUALITATIVE_REVIEW)

    entry_records = []
    # ベンチマーク(TOPIX)の入場価格も記録
    topix_price = get_price_on_date(TOPIX_TICKER, date_str)

    for _, row in top.iterrows():
        ticker = f"{row['code']}.T"
        price = get_price_on_date(ticker, date_str)
        if price is None:
            logger.warning(f"{row['code']} {row['name']}: 入場価格取得失敗")
            continue
        entry_records.append({
            "entry_date": date_str,
            "code": row["code"],
            "name": row["name"],
            "sector": row.get("sector_33", "–"),
            "rank": _ + 1,
            "total_score": row["total_score"],
            "entry_price": price,
            "topix_entry": topix_price,
        })
        logger.info(f"  {row['code']} {row['name']}: ¥{price:,.0f}")

    out_path = PERF_DIR / f"entry_{date_str}.csv"
    pd.DataFrame(entry_records).to_csv(out_path, index=False)
    logger.info(f"入場価格を記録しました: {out_path}")


def check_performance(entry_date: str):
    """指定日の選出銘柄の現在リターンをTOPIXと比較する。"""
    entry_path = PERF_DIR / f"entry_{entry_date}.csv"

    # entryファイルがなければ入場価格をまず取得
    if not entry_path.exists():
        logger.info(f"入場価格ファイルが未作成。{entry_date}分を取得します...")
        record_entry(entry_date)

    if not entry_path.exists():
        logger.error(f"入場価格データが取得できませんでした。")
        return

    entry_df = pd.read_csv(entry_path, dtype={"code": str})
    today = datetime.now().strftime("%Y-%m-%d")
    topix_now = get_current_price(TOPIX_TICKER)

    results = []
    for _, row in entry_df.iterrows():
        ticker = f"{row['code']}.T"
        current_price = get_current_price(ticker)
        if current_price is None:
            continue

        entry_price = row["entry_price"]
        stock_return = (current_price - entry_price) / entry_price * 100

        topix_entry = row.get("topix_entry")
        topix_return = None
        alpha = None
        if topix_entry and topix_now:
            topix_return = (topix_now - topix_entry) / topix_entry * 100
            alpha = stock_return - topix_return

        results.append({
            "code": row["code"],
            "name": row["name"],
            "sector": row.get("sector", "–"),
            "rank": row["rank"],
            "score": row["total_score"],
            "entry_date": entry_date,
            "entry_price": entry_price,
            "current_price": current_price,
            "return_pct": stock_return,
            "topix_return_pct": topix_return,
            "alpha_pct": alpha,
            "check_date": today,
        })

    if not results:
        logger.error("リターン計算できる銘柄がありませんでした。")
        return

    result_df = pd.DataFrame(results)

    # 結果表示
    print(f"\n{'='*60}")
    print(f"  パフォーマンス検証: {entry_date} 選出 → {today} 現在")
    print(f"{'='*60}")

    for _, r in result_df.iterrows():
        ret_str = f"{r['return_pct']:+.1f}%"
        alpha_str = f"α {r['alpha_pct']:+.1f}%pt" if r['alpha_pct'] is not None else ""
        topix_str = f"(TOPIX: {r['topix_return_pct']:+.1f}%)" if r['topix_return_pct'] is not None else ""
        sign = "✅" if (r['alpha_pct'] or 0) > 0 else "❌"
        print(f"{sign} [{r['rank']}位] {r['name']}({r['code']})")
        print(f"     ¥{r['entry_price']:,.0f} → ¥{r['current_price']:,.0f}  {ret_str}  {alpha_str} {topix_str}")

    avg_return = result_df["return_pct"].mean()
    avg_alpha = result_df["alpha_pct"].mean() if result_df["alpha_pct"].notna().any() else None
    winners = (result_df["alpha_pct"] > 0).sum() if result_df["alpha_pct"].notna().any() else None

    print(f"\n{'─'*60}")
    print(f"  平均リターン:     {avg_return:+.1f}%")
    if avg_alpha is not None:
        print(f"  平均アルファ:     {avg_alpha:+.1f}%pt vs TOPIX")
        print(f"  TOPIX超過銘柄数: {winners}/{len(results)}社")
    print(f"{'='*60}\n")

    # CSVに保存
    out_path = PERF_DIR / f"result_{entry_date}_checked_{today}.csv"
    result_df.to_csv(out_path, index=False)
    logger.info(f"結果を保存: {out_path}")

    return result_df


def summary():
    """全パフォーマンス記録のサマリーを表示する。"""
    result_files = sorted(PERF_DIR.glob("result_*.csv"))
    if not result_files:
        print("まだ検証データがありません。")
        return

    all_results = pd.concat([pd.read_csv(f) for f in result_files])
    print(f"\n{'='*60}")
    print(f"  累積パフォーマンスサマリー ({len(result_files)}回分)")
    print(f"{'='*60}")
    print(f"  総検証銘柄数:     {len(all_results)}件")
    print(f"  平均リターン:     {all_results['return_pct'].mean():+.1f}%")
    if all_results["alpha_pct"].notna().any():
        print(f"  平均アルファ:     {all_results['alpha_pct'].mean():+.1f}%pt vs TOPIX")
        win_rate = (all_results["alpha_pct"] > 0).mean() * 100
        print(f"  TOPIX超過率:     {win_rate:.0f}%")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=str, help="指定日の選出銘柄のリターンを確認 (YYYY-MM-DD)")
    parser.add_argument("--record", action="store_true", help="本日の選出銘柄の入場価格を記録")
    parser.add_argument("--summary", action="store_true", help="全記録のサマリーを表示")
    args = parser.parse_args()

    if args.check:
        check_performance(args.check)
    elif args.record:
        record_entry()
    elif args.summary:
        summary()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
