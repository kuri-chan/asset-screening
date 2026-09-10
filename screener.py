"""
screener.py
スクリーニング3段階ロジックの実装。

[Stage 1] hard_filter: 財務健全性の必須条件で機械除外
[Stage 2] score_universe: 8指標をパーセンタイル順位化、合算スコアでランキング
[Stage 3] export_top_candidates: 上位N銘柄を定性分析用に出力
"""

import logging
from pathlib import Path
import pandas as pd
import numpy as np

import config
from universe_loader import is_financial_sector

logger = logging.getLogger(__name__)


# ============================================================
# Stage 1: ハード除外
# ============================================================
def hard_filter(df: pd.DataFrame) -> pd.DataFrame:
    """
    ハード条件によるフィルタ。除外理由をログに残す。
    金融セクターは一部条件をスキップ。
    """
    initial = len(df)
    rejection_log = {}

    # データ取得失敗
    df = df[df["fetch_success"] == True].copy()
    rejection_log["fetch_failed"] = initial - len(df)

    # 欠損が多すぎるものを除外
    before = len(df)
    df = df[df["missing_metric_count"] <= config.MAX_MISSING_METRICS]
    rejection_log["too_many_missing"] = before - len(df)

    # 時価総額下限
    before = len(df)
    df = df[df["market_cap_oku_yen"].notna() &
            (df["market_cap_oku_yen"] >= config.HARD_FILTER["market_cap_min_oku_yen"])]
    rejection_log["small_market_cap"] = before - len(df)

    # 金融判定列を作成
    df["is_financial"] = df["sector_33_code"].apply(is_financial_sector)

    # 自己資本比率(金融除外)
    before = len(df)
    non_fin = df[~df["is_financial"]]
    fin = df[df["is_financial"]]
    non_fin_filtered = non_fin[
        non_fin["Equity_Ratio"].notna() &
        (non_fin["Equity_Ratio"] >= config.HARD_FILTER["equity_ratio_min"])
    ]
    df = pd.concat([non_fin_filtered, fin], ignore_index=True)
    rejection_log["low_equity_ratio"] = before - len(df)

    # 有利子負債/EBITDA(金融除外)
    before = len(df)
    non_fin = df[~df["is_financial"]]
    fin = df[df["is_financial"]]
    # Debt_to_EBITDA は欠損許容(取れない企業もある)
    non_fin_filtered = non_fin[
        non_fin["Debt_to_EBITDA"].isna() |
        (non_fin["Debt_to_EBITDA"] <= config.HARD_FILTER["debt_ebitda_max"])
    ]
    df = pd.concat([non_fin_filtered, fin], ignore_index=True)
    rejection_log["high_debt"] = before - len(df)

    logger.info(f"Stage 1 除外集計: {rejection_log}")
    logger.info(f"Stage 1 通過: {initial} → {len(df)} 銘柄")

    return df.reset_index(drop=True)


# ============================================================
# Stage 2: スコアリング
# ============================================================
def _rank_score(series: pd.Series, direction: str) -> pd.Series:
    """
    パーセンタイル順位を 0-100 のスコアに変換。
    direction = "low_is_better" or "high_is_better"
    NaN はそのまま NaN を返す(平均算出時にスキップされる)
    """
    if direction == "low_is_better":
        ranks = series.rank(pct=True, ascending=False, na_option="keep")
    elif direction == "high_is_better":
        ranks = series.rank(pct=True, ascending=True, na_option="keep")
    else:
        raise ValueError(f"unknown direction: {direction}")
    return ranks * 100


def score_universe(df: pd.DataFrame) -> pd.DataFrame:
    """
    8指標をスコア化し、軸別平均→総合スコアを算出。
    """
    df = df.copy()

    # PEG 算出: PER ÷ 利益成長率(過去3年CAGR)が理想だが、
    # yfinance では成長率取得が不安定なので、簡易版として PER × (1 - ROE/100) を使うことも可
    # 今回は PEG = PER / ROE という近似(利益成長は ROE に表れる前提)
    # 厳密な PEG は EDINET 深掘り段階で再計算
    if "PEG" not in df.columns:
        df["PEG"] = df["PER"] / df["ROE"].replace(0, np.nan)

    # ROIC も簡易計算: ROIC ≈ ROE × (1 - 負債比率調整)
    # 厳密には NOPAT / 投下資本だが、yfinance単独では計算困難
    # ここでは ROE で代用し、深掘り段階で精緻化
    if "ROIC" not in df.columns:
        df["ROIC"] = df["ROE"]

    # バリュエーション軸スコア
    val_scores = []
    for metric, conf in config.VALUATION_METRICS.items():
        if metric not in df.columns:
            logger.warning(f"指標 {metric} が見つからずスキップ")
            continue
        col_name = f"score_{metric}"
        df[col_name] = _rank_score(df[metric], conf["rank_direction"])
        val_scores.append(col_name)

    df["score_valuation"] = df[val_scores].mean(axis=1)

    # 収益性軸スコア
    qual_scores = []
    for metric, conf in config.QUALITY_METRICS.items():
        if metric not in df.columns:
            logger.warning(f"指標 {metric} が見つからずスキップ")
            continue
        col_name = f"score_{metric}"
        df[col_name] = _rank_score(df[metric], conf["rank_direction"])
        qual_scores.append(col_name)

    df["score_quality"] = df[qual_scores].mean(axis=1)

    # 総合スコア
    if config.SCORE_AGGREGATION == "product":
        df["total_score"] = (df["score_valuation"] * df["score_quality"]) / 100
    elif config.SCORE_AGGREGATION == "average":
        df["total_score"] = (df["score_valuation"] + df["score_quality"]) / 2
    else:
        raise ValueError(f"unknown aggregation: {config.SCORE_AGGREGATION}")

    return df.sort_values("total_score", ascending=False).reset_index(drop=True)


# ============================================================
# Stage 3: 上位候補の出力
# ============================================================
def export_top_candidates(scored_df: pd.DataFrame, date_str: str) -> Path:
    """
    上位N社を CSV と Markdown サマリで出力。
    Markdown は Claude に渡して定性分析させる用。
    """
    top = scored_df.head(config.TOP_N_FOR_QUALITATIVE_REVIEW).copy()

    out_dir = Path(config.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # CSV出力
    csv_path = out_dir / f"top_candidates_{date_str}.csv"
    cols_to_export = [
        "code", "name", "sector_33", "ticker",
        "market_cap_oku_yen",
        "PBR", "PER", "PEG", "Dividend_Yield",
        "ROE", "ROIC", "Op_Margin_Trend_3Y", "FCF_to_Sales_3Y",
        "Equity_Ratio", "Debt_to_EBITDA",
        "score_valuation", "score_quality", "total_score",
    ]
    available_cols = [c for c in cols_to_export if c in top.columns]
    top[available_cols].to_csv(csv_path, index=False, encoding="utf-8-sig")
    logger.info(f"CSV出力: {csv_path}")

    # Markdown出力(定性分析のインプット用)
    md_path = out_dir / f"top_candidates_{date_str}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# スクリーニング結果 {date_str}\n\n")
        f.write(f"## サマリ\n\n")
        f.write(f"- 第3段定性分析候補: 上位{len(top)}社\n")
        f.write(f"- スコア合算方式: {config.SCORE_AGGREGATION}\n\n")
        f.write(f"## 候補銘柄一覧\n\n")
        f.write("| 順位 | コード | 銘柄名 | セクター | 時価総額(億) | PBR | PER | ROE(%) | 配当(%) | 総合スコア |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for i, row in top.iterrows():
            f.write(
                f"| {i+1} "
                f"| {row.get('code', '-')} "
                f"| {row.get('name', '-')} "
                f"| {row.get('sector_33', '-')} "
                f"| {_fmt(row.get('market_cap_oku_yen'), '{:.0f}')} "
                f"| {_fmt(row.get('PBR'), '{:.2f}')} "
                f"| {_fmt(row.get('PER'), '{:.1f}')} "
                f"| {_fmt(row.get('ROE'), '{:.1f}')} "
                f"| {_fmt(row.get('Dividend_Yield'), '{:.2f}')} "
                f"| {_fmt(row.get('total_score'), '{:.1f}')} |\n"
            )
        f.write("\n## 次のステップ\n\n")
        f.write("上位3-5銘柄について、以下を Claude に依頼して定性分析レポートを作成してください:\n\n")
        f.write("1. EDINET API で直近の有価証券報告書を取得\n")
        f.write("2. 各社IRサイトから中期経営計画・統合報告書を確認\n")
        f.write("3. `03_output_template.md` のフォーマットに沿って、ブル/ベア両論レポートを生成\n\n")
        f.write("**重要: このリストは「買い銘柄」ではなく「定性深掘り候補」です。**\n")
        f.write("最終的な投資判断は、深掘り後の Kuri さん自身の評価に基づきます。\n")

    logger.info(f"Markdown出力: {md_path}")
    return md_path


def _fmt(val, fmt_str: str) -> str:
    """欠損値を '-' で表示するヘルパ。"""
    if val is None or pd.isna(val):
        return "-"
    try:
        return fmt_str.format(val)
    except (ValueError, TypeError):
        return str(val)
