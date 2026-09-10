"""
dashboard.py
蓄積されたスクリーニング・パフォーマンスデータをターミナルに表示する。

使い方:
  python3 dashboard.py              # 全体サマリー
  python3 dashboard.py --date 2026-05-12  # 特定日の詳細
"""

import argparse
from pathlib import Path
import pandas as pd
import config

OUTPUT = Path(config.OUTPUT_DIR)
PERF   = OUTPUT / "performance"


def fmt(val, fmt_str="{:+.1f}%", na="–"):
    try:
        return fmt_str.format(val) if pd.notna(val) else na
    except Exception:
        return na


def show_overall():
    """全検証期間の累積サマリー。"""
    result_files = sorted(PERF.glob("result_*.csv"))
    candidate_files = sorted(OUTPUT.glob("top_candidates_*.csv"))

    print("\n" + "━" * 62)
    print("  📊 資産運用エージェント ダッシュボード")
    print("━" * 62)

    # スクリーニング蓄積状況
    print(f"\n【データ蓄積状況】")
    print(f"  スクリーニング実施日数: {len(candidate_files)}日分")
    if candidate_files:
        dates = [f.stem.replace("top_candidates_", "") for f in candidate_files]
        print(f"  最古: {min(dates)}  最新: {max(dates)}")

    # パフォーマンス検証結果
    print(f"\n【パフォーマンス検証】")
    if not result_files:
        print("  まだ検証データがありません。")
        return

    all_df = pd.concat([pd.read_csv(f, dtype={"code": str}) for f in result_files])

    for label, n in [("TOP5", 5), ("TOP10", 10), ("TOP20", 20)]:
        sub = all_df[all_df["rank"] <= n]
        avg_ret = sub["return_pct"].mean()
        avg_alpha = sub["alpha_pct"].mean() if sub["alpha_pct"].notna().any() else None
        win_rate = (sub["alpha_pct"] > 0).mean() * 100 if sub["alpha_pct"].notna().any() else None
        print(f"  {label:5} 平均リターン {avg_ret:+6.1f}%  "
              f"αvsTOPIX {fmt(avg_alpha, '{:+.1f}%pt', '–'):>9}  "
              f"TOPIX超過率 {fmt(win_rate, '{:.0f}%', '–'):>5}")

    # 個別銘柄ランキング(全期間でアルファが高い順)
    print(f"\n【全期間 アルファ上位10銘柄】")
    top_alpha = (all_df.groupby(["code", "name"])["alpha_pct"]
                 .mean().sort_values(ascending=False).head(10).reset_index())
    for _, r in top_alpha.iterrows():
        print(f"  {r['code']} {r['name'][:18]:<20} α {r['alpha_pct']:+.1f}%pt")

    # 損益シミュレーション(最新検証ベース)
    latest_file = max(result_files)
    latest = pd.read_csv(latest_file, dtype={"code": str})
    entry_date = latest["entry_date"].iloc[0]
    check_date = latest["check_date"].iloc[0]

    print(f"\n【100株シミュレーション ({entry_date}→{check_date})】")
    for label, n in [("TOP5", 5), ("TOP20", 20)]:
        sub = latest[latest["rank"] <= n]
        cost  = (sub["entry_price"]   * 100).sum()
        value = (sub["current_price"] * 100).sum()
        pl    = value - cost
        pct   = pl / cost * 100
        print(f"  {label:5} 元本 ¥{cost:>10,.0f}  評価 ¥{value:>10,.0f}  "
              f"損益 ¥{pl:>+10,.0f} ({pct:+.1f}%)")

    print("\n" + "━" * 62 + "\n")


def show_date(date_str: str):
    """特定日のスクリーニング結果と(あれば)パフォーマンス。"""
    cand_file = OUTPUT / f"top_candidates_{date_str}.csv"
    if not cand_file.exists():
        print(f"スクリーニング結果が見つかりません: {date_str}")
        return

    df = pd.read_csv(cand_file, dtype={"code": str})
    result_files = sorted(PERF.glob(f"result_{date_str}_*.csv"))

    print(f"\n{'━'*62}")
    print(f"  📋 {date_str} スクリーニング結果 (TOP20)")
    print(f"{'━'*62}")

    if result_files:
        res = pd.read_csv(result_files[-1], dtype={"code": str})
        check_date = res["check_date"].iloc[0]
        print(f"  ✅ パフォーマンス確認済み ({check_date}時点)\n")
        merged = df.head(20).merge(
            res[["code", "current_price", "return_pct", "alpha_pct"]],
            on="code", how="left"
        )
        print(f"  {'順位':<4} {'銘柄':<22} {'スコア':>6} {'リターン':>9} {'α':>8}")
        print(f"  {'─'*58}")
        for i, r in merged.iterrows():
            ret_str   = fmt(r.get("return_pct"),  "{:+.1f}%")
            alpha_str = fmt(r.get("alpha_pct"),   "{:+.1f}pt")
            mark = "✅" if (r.get("alpha_pct", 0) or 0) > 0 else "  "
            print(f"  {mark}{i+1:<3} {r['name'][:20]:<22} "
                  f"{r['total_score']:>6.1f} {ret_str:>9} {alpha_str:>8}")
    else:
        print(f"  ⏳ 未検証\n")
        print(f"  {'順位':<4} {'銘柄':<22} {'スコア':>6} {'セクター'}")
        print(f"  {'─'*58}")
        for i, r in df.head(20).iterrows():
            print(f"  {i+1:<4} {r['name'][:20]:<22} "
                  f"{r['total_score']:>6.1f} {r.get('sector_33','–')}")

    print(f"\n{'━'*62}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="特定日の詳細表示 (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.date:
        show_date(args.date)
    else:
        show_overall()


if __name__ == "__main__":
    main()
