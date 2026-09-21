"""
run_screening.py
スクリーニングを実行するエントリポイント。

使い方:
  # フル実行(東証プライム全銘柄)
  python run_screening.py

  # デバッグ用に件数制限
  python run_screening.py --limit 50

  # キャッシュ済みデータを使う(再実行時)
  python run_screening.py --use-cache 2026-05-12

【出力】
- ./cache/universe_data_YYYY-MM-DD.csv : 全銘柄の生データ
- ./output/top_candidates_YYYY-MM-DD.csv : 上位候補銘柄
- ./output/top_candidates_YYYY-MM-DD.md  : 定性分析インプット用
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path
import pandas as pd

import config
from universe_loader import load_prime_universe
from data_fetcher import fetch_universe_data, save_snapshot
from screener import hard_filter, score_universe, export_top_candidates
import git_sync


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(description="日本株中期ファンダメンタル・スクリーニング")
    parser.add_argument("--limit", type=int, default=None,
                        help="デバッグ用: 取得銘柄数を制限")
    parser.add_argument("--use-cache", type=str, default=None,
                        help="キャッシュ日付(YYYY-MM-DD) を指定すると再取得をスキップ")
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)

    date_str = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"=== スクリーニング開始 {date_str} ===")

    # 過去の output/ 履歴(前回までのtop_candidates/performance)を取得
    git_sync.pull_latest()

    # ============================================================
    # Step 1: ユニバース読み込み
    # ============================================================
    logger.info("Step 1: 東証プライム銘柄一覧を読み込み")
    universe = load_prime_universe()
    logger.info(f"対象銘柄数: {len(universe)}")

    # ============================================================
    # Step 2: データ取得 or キャッシュ読み込み
    # ============================================================
    if args.use_cache:
        cache_path = Path(config.DATA_CACHE_DIR) / f"universe_data_{args.use_cache}.csv"
        if not cache_path.exists():
            logger.error(f"キャッシュが見つかりません: {cache_path}")
            return
        logger.info(f"Step 2: キャッシュ読み込み {cache_path}")
        raw_df = pd.read_csv(cache_path, dtype={"code": str})
    else:
        logger.info("Step 2: 財務データ取得(時間がかかります)")
        raw_df = fetch_universe_data(universe, limit=args.limit)
        save_snapshot(raw_df, date_str)

    # ============================================================
    # Step 3: Stage 1 ハード除外
    # ============================================================
    logger.info("Step 3: Stage 1 ハード除外フィルタ")
    filtered = hard_filter(raw_df)
    if len(filtered) == 0:
        logger.error("ハード除外で全銘柄が落ちました。閾値を見直してください。")
        return

    # ============================================================
    # Step 4: Stage 2 スコアリング
    # ============================================================
    logger.info("Step 4: Stage 2 スコアリング")
    scored = score_universe(filtered)

    # ============================================================
    # Step 5: 上位候補出力
    # ============================================================
    logger.info("Step 5: 上位候補を出力")
    md_path = export_top_candidates(scored, date_str)

    # 今回の結果をgitに永続化(次回実行時の前週比較に使う)
    git_sync.commit_and_push(f"Screening results {date_str}")

    logger.info(f"=== 完了 ===")
    logger.info(f"次の作業: {md_path} を開き、上位3-5銘柄を Claude に渡して定性分析を依頼")


if __name__ == "__main__":
    main()
