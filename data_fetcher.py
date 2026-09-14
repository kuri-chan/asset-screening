"""
data_fetcher.py
yfinance を使って東証プライム全銘柄の財務・株価データを取得する。

【取得項目】
- 株価・時価総額・出来高
- バリュエーション: PBR, PER, 配当利回り
- 収益性: ROE, 営業利益率
- 財務健全性: 自己資本比率
- 売上・営業利益(直近4年)
※ ROIC, FCF, PEG, 有利子負債/EBITDA は yfinance だけでは精度に難があるため、
   別途キャッシュフロー・B/Sデータから算出する関数を用意。

【yfinance の制約】
- 日本株データは欠損や遅延あり
- 業績修正履歴は別途取得が必要
- レート制限なし(常識的な範囲で)
"""

import time
import logging
from pathlib import Path
from typing import Optional
import pandas as pd
import yfinance as yf

import config
from yf_session import get_session

logger = logging.getLogger(__name__)
_session = get_session()


def fetch_basic_metrics(ticker: str) -> dict:
    """
    1銘柄の基本指標を取得。失敗時は欠損値辞書を返す。
    """
    result = {
        "ticker": ticker,
        "fetch_success": False,
        "market_cap_oku_yen": None,
        "PBR": None,
        "PER": None,
        "Dividend_Yield": None,
        "ROE": None,
        "Op_Margin": None,
        "Equity_Ratio": None,
        "Revenue_TTM": None,
        "Op_Income_TTM": None,
        "error": None,
    }

    try:
        t = yf.Ticker(ticker, session=_session)
        info = t.info

        if not info or "marketCap" not in info:
            result["error"] = "info_empty_or_no_market_cap"
            return result

        # 時価総額(億円換算)
        market_cap_yen = info.get("marketCap")
        if market_cap_yen:
            result["market_cap_oku_yen"] = market_cap_yen / 1e8

        # バリュエーション
        result["PBR"] = info.get("priceToBook")
        result["PER"] = info.get("trailingPE") or info.get("forwardPE")
        div_yield = info.get("dividendYield")
        if div_yield is not None:
            # yfinanceの仕様変更でデータが%表記または小数表記の両方ありうる
            # 小数(0.03)で来た場合はそのまま、%(3.0)で来た場合は1/100に補正
            result["Dividend_Yield"] = div_yield if div_yield > 1 else div_yield * 100

        # 収益性
        roe = info.get("returnOnEquity")
        if roe is not None:
            result["ROE"] = roe * 100  # 小数→%変換

        op_margin = info.get("operatingMargins")
        if op_margin is not None:
            result["Op_Margin"] = op_margin * 100

        # 財務健全性
        # 自己資本比率は yfinance から直接は取れないので B/Sから算出
        try:
            bs = t.balance_sheet
            if not bs.empty:
                latest = bs.columns[0]
                total_equity = bs.loc["Stockholders Equity", latest] if "Stockholders Equity" in bs.index else None
                total_assets = bs.loc["Total Assets", latest] if "Total Assets" in bs.index else None
                if total_equity and total_assets and total_assets > 0:
                    result["Equity_Ratio"] = (total_equity / total_assets) * 100
        except Exception as e:
            logger.debug(f"{ticker}: B/S取得失敗 {e}")

        # 売上・営業利益
        result["Revenue_TTM"] = info.get("totalRevenue")
        result["Op_Income_TTM"] = info.get("operatingCashflow")

        result["fetch_success"] = True

    except Exception as e:
        result["error"] = str(e)[:200]
        logger.warning(f"{ticker} fetch失敗: {e}")

    return result


def fetch_cashflow_metrics(ticker: str) -> dict:
    """
    キャッシュフロー関連指標を取得。
    - FCF / 売上比 (3年平均)
    - 有利子負債 / EBITDA
    """
    result = {
        "ticker": ticker,
        "FCF_to_Sales_3Y": None,
        "Debt_to_EBITDA": None,
    }

    try:
        t = yf.Ticker(ticker, session=_session)
        cashflow = t.cashflow
        bs = t.balance_sheet
        fin = t.financials

        if not cashflow.empty and not fin.empty:
            # FCF = 営業CF - 設備投資
            fcf_list = []
            sales_list = []
            for col in cashflow.columns[:3]:  # 直近3年
                op_cf = cashflow.loc["Operating Cash Flow", col] if "Operating Cash Flow" in cashflow.index else None
                capex = cashflow.loc["Capital Expenditure", col] if "Capital Expenditure" in cashflow.index else None
                if op_cf is not None and capex is not None:
                    fcf = op_cf + capex  # capexは負値で来る
                    fcf_list.append(fcf)
                if col in fin.columns:
                    sales = fin.loc["Total Revenue", col] if "Total Revenue" in fin.index else None
                    if sales:
                        sales_list.append(sales)

            if fcf_list and sales_list and len(fcf_list) == len(sales_list):
                ratios = [f / s for f, s in zip(fcf_list, sales_list) if s > 0]
                if ratios:
                    result["FCF_to_Sales_3Y"] = sum(ratios) / len(ratios) * 100

        # 有利子負債 / EBITDA
        if not bs.empty and not fin.empty:
            latest = bs.columns[0]
            total_debt = bs.loc["Total Debt", latest] if "Total Debt" in bs.index else None
            ebitda_row = "EBITDA"
            ebitda = fin.loc[ebitda_row, fin.columns[0]] if ebitda_row in fin.index else None
            if total_debt and ebitda and ebitda > 0:
                result["Debt_to_EBITDA"] = total_debt / ebitda

    except Exception as e:
        logger.debug(f"{ticker} cashflow取得失敗: {e}")

    return result


def calc_op_margin_trend(ticker: str) -> Optional[float]:
    """
    営業利益率の3年改善トレンドを算出。
    直近期の営業利益率 - 3期前の営業利益率 (パーセントポイント)
    """
    try:
        t = yf.Ticker(ticker, session=_session)
        fin = t.financials
        if fin.empty or len(fin.columns) < 3:
            return None

        margins = []
        for col in fin.columns[:3]:
            revenue = fin.loc["Total Revenue", col] if "Total Revenue" in fin.index else None
            op_income = fin.loc["Operating Income", col] if "Operating Income" in fin.index else None
            if revenue and op_income and revenue > 0:
                margins.append(op_income / revenue * 100)

        if len(margins) >= 2:
            return margins[0] - margins[-1]  # 直近 - 過去
        return None
    except Exception:
        return None


def fetch_universe_data(universe_df: pd.DataFrame, limit: Optional[int] = None) -> pd.DataFrame:
    """
    ユニバース全銘柄に対してデータ取得を実行。
    limit を指定するとデバッグ用に件数制限。

    結果はDataFrameで返す。各銘柄の欠損状況も含む。
    """
    tickers = universe_df["ticker"].tolist()
    if limit:
        tickers = tickers[:limit]

    logger.info(f"データ取得開始: {len(tickers)}銘柄")

    rows = []
    for i, ticker in enumerate(tickers):
        if i % 50 == 0:
            logger.info(f"  進捗: {i}/{len(tickers)}")

        basic = fetch_basic_metrics(ticker)
        cashflow = fetch_cashflow_metrics(ticker)
        op_trend = calc_op_margin_trend(ticker)

        row = {**basic, **cashflow}
        row["Op_Margin_Trend_3Y"] = op_trend
        rows.append(row)

        time.sleep(config.YFINANCE_SLEEP_SEC)

    result_df = pd.DataFrame(rows)

    # 銘柄マスタとマージ
    universe_subset = universe_df[["code", "name", "ticker", "sector_33", "sector_33_code"]]
    result_df = result_df.merge(universe_subset, on="ticker", how="left")

    # 欠損数カウント
    metric_cols = ["PBR", "PER", "Dividend_Yield", "ROE", "ROIC",
                   "Op_Margin_Trend_3Y", "FCF_to_Sales_3Y", "PEG"]
    available_metric_cols = [c for c in metric_cols if c in result_df.columns]
    result_df["missing_metric_count"] = result_df[available_metric_cols].isnull().sum(axis=1)

    logger.info(f"取得完了: 成功 {result_df['fetch_success'].sum()}/{len(result_df)}")

    return result_df


def save_snapshot(df: pd.DataFrame, date_str: str):
    """日付付きCSVで保存。"""
    out_dir = Path(config.DATA_CACHE_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"universe_data_{date_str}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info(f"保存完了: {path}")
    return path
