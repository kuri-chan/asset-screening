"""
config.py
スクリーニング条件の閾値設定を一元管理。
ここを編集すれば、コード本体に触れずにチューニング可能。
"""

# ============================================================
# 第1段: 財務健全性ハード除外条件
# ============================================================
HARD_FILTER = {
    "equity_ratio_min": 50.0,        # 自己資本比率(%)の下限
    "debt_ebitda_max": 3.0,           # 有利子負債/EBITDA倍率の上限
    "consecutive_loss_max": 1,        # 直近3期で許容する赤字回数の最大
    "market_cap_min_oku_yen": 500,   # 時価総額(億円)の下限
    "exclude_recent_guidance_cut": True,  # 直近12ヶ月の下方修正企業を除外
}

# 金融セクターはハードフィルタの一部を適用しない
FINANCIAL_SECTOR_CODES = [
    "7050",  # 銀行業
    "7100",  # 証券・商品先物取引業
    "7150",  # 保険業
    "7200",  # その他金融業
]


# ============================================================
# 第2段: スコアリング指標と重み
# ============================================================
# 各指標を東証プライム全体内のパーセンタイル順位でスコア化(0-100)
# rank_direction:
#   "low_is_better"  → 値が低いほど高スコア(PBR, PER, PEG等)
#   "high_is_better" → 値が高いほど高スコア(ROE, ROIC, 配当利回り等)

VALUATION_METRICS = {
    "PBR":                  {"rank_direction": "low_is_better", "weight": 1.0},
    "PER":                  {"rank_direction": "low_is_better", "weight": 1.0},
    "PEG":                  {"rank_direction": "low_is_better", "weight": 1.0},
    "Dividend_Yield":       {"rank_direction": "high_is_better", "weight": 1.0},
}

QUALITY_METRICS = {
    "ROE":                  {"rank_direction": "high_is_better", "weight": 1.0},
    "ROIC":                 {"rank_direction": "high_is_better", "weight": 1.0},
    "Op_Margin_Trend_3Y":   {"rank_direction": "high_is_better", "weight": 1.0},
    "FCF_to_Sales_3Y":      {"rank_direction": "high_is_better", "weight": 1.0},
}

# スコア合算方式
# "product": バリュエーション軸スコア × 収益性軸スコア ÷ 100 (推奨。極端な偏りを抑制)
# "average": (バリュエーション軸 + 収益性軸) / 2
SCORE_AGGREGATION = "product"

# 第3段に送る候補数
TOP_N_FOR_QUALITATIVE_REVIEW = 20


# ============================================================
# データソース設定
# ============================================================
# 対象ユニバース: 東証プライム
TARGET_MARKET = "TSE_PRIME"

# データ取得のレート制限(秒)
YFINANCE_SLEEP_SEC = 0.5
EDINET_SLEEP_SEC = 2.0


# ============================================================
# 出力設定
# ============================================================
OUTPUT_DIR = "./output"
DATA_CACHE_DIR = "./cache"


# ============================================================
# EDINET API 設定
# ============================================================
EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
# Subscription-Key は環境変数 EDINET_API_KEY から読み込み


# ============================================================
# データ欠損許容
# ============================================================
# 各銘柄の8指標のうち、欠損が以下の数を超えたらスコアリング対象外
MAX_MISSING_METRICS = 3


# ============================================================
# アラート設定
# ============================================================
# アラート発火条件
ALERT_SCORE_JUMP = 5.0        # 前日比スコアがこの値以上上昇したら通知
ALERT_NEW_ENTRY_RANK = 20     # 圏外からこの順位以内に新規ランクインしたら通知
ALERT_CONSECUTIVE_RISE = 3    # この日数連続でスコアが上昇したら通知
