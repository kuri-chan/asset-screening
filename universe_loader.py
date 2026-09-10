"""
universe_loader.py
東証プライム上場銘柄一覧を取得する。

JPXは銘柄一覧Excelを公開している:
https://www.jpx.co.jp/markets/statistics-equities/misc/01.html

【使い方】
1. 上記URLから「東証上場銘柄一覧」のExcelをダウンロード
2. ./data/data_j.xls として保存
3. load_prime_universe() を呼ぶ
"""

import pandas as pd
from pathlib import Path


JPX_UNIVERSE_FILE = Path("./data/data_j.xls")


def load_prime_universe() -> pd.DataFrame:
    """
    JPX公開の銘柄一覧ファイルから東証プライム銘柄のみを抽出する。

    Returns:
        pd.DataFrame with columns:
            - code (str): 4桁証券コード
            - name (str): 銘柄名
            - market (str): 市場区分
            - sector_33 (str): 33業種区分
            - sector_17 (str): 17業種区分
            - scale (str): 規模区分
    """
    if not JPX_UNIVERSE_FILE.exists():
        raise FileNotFoundError(
            f"銘柄一覧ファイルが見つかりません: {JPX_UNIVERSE_FILE}\n"
            f"JPX公式サイトからダウンロードしてください:\n"
            f"https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
        )

    df = pd.read_excel(JPX_UNIVERSE_FILE, dtype={"コード": str})

    # 列名を英語化
    df = df.rename(columns={
        "コード": "code",
        "銘柄名": "name",
        "市場・商品区分": "market",
        "33業種コード": "sector_33_code",
        "33業種区分": "sector_33",
        "17業種コード": "sector_17_code",
        "17業種区分": "sector_17",
        "規模コード": "scale_code",
        "規模区分": "scale",
    })

    # プライム市場のみ
    prime_df = df[df["market"].str.contains("プライム", na=False)].copy()

    # ETF・REITは除外(通常株式のみが対象)
    prime_df = prime_df[~prime_df["market"].str.contains("ETF|REIT", na=False, regex=True)]

    # yfinance用のティッカー(例: "7203" -> "7203.T")
    prime_df["ticker"] = prime_df["code"] + ".T"

    return prime_df.reset_index(drop=True)


def is_financial_sector(sector_33_code: str) -> bool:
    """金融セクター判定。スクリーニング条件の業種補正で使用。"""
    if not isinstance(sector_33_code, str):
        return False
    financial_codes = ["7050", "7100", "7150", "7200"]
    return sector_33_code in financial_codes


if __name__ == "__main__":
    # スタンドアロン実行時のテスト
    try:
        df = load_prime_universe()
        print(f"東証プライム銘柄数: {len(df)}")
        print(f"\nセクター別件数(上位10):")
        print(df["sector_33"].value_counts().head(10))
        print(f"\nサンプル銘柄:")
        print(df.head())
    except FileNotFoundError as e:
        print(e)
