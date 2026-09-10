"""
generate_analysis_prompt.py
スクリーニング上位候補銘柄を Claude に分析依頼するためのプロンプトを自動生成する。

使い方:
  # 上位3社について、Claude に渡すプロンプト一式を出力
  python generate_analysis_prompt.py --date 2026-05-12 --top 3

  # 出力先は ./output/analysis_prompts/

【プロンプトの特徴】
- 03_output_template.md のフォーマット準拠
- ブル/ベア両論、判断のための問い、を必ず含めるよう明示指示
- 「買い」「売り」断定の禁止を再強調
- EDINET URLや一次ソースリンクを生成
"""

import argparse
import logging
from pathlib import Path
import pandas as pd

import config
from edinet_client import EdinetClient

logger = logging.getLogger(__name__)


PROMPT_TEMPLATE = """# 個別銘柄 定性分析依頼

## 対象銘柄
- 証券コード: {code}
- 銘柄名: {name}
- セクター: {sector}
- 時価総額: {market_cap}億円

## スクリーニング結果(参考)

この銘柄は、私(Kuri)の以下のスクリーニング条件で上位{rank}位に選出された:

### 第1段通過条件(満たしている)
- 自己資本比率 50%以上
- 有利子負債/EBITDA 3倍以内(または金融セクター)
- 連続赤字なし・直近12ヶ月の下方修正なし
- 時価総額 500億円以上

### 第2段スコアリング結果
- バリュエーション軸スコア: {score_val}/100
- 収益性軸スコア: {score_qual}/100
- 総合スコア: {score_total}/100

### 主要指標(yfinance取得時点、要再確認)
| 指標 | 値 |
|------|---|
| PBR | {pbr} |
| PER | {per} |
| PEG(簡易) | {peg} |
| 配当利回り | {div_yield}% |
| ROE | {roe}% |
| ROIC(簡易) | {roic}% |
| 営業利益率改善(3年) | {opm_trend}pp |
| FCF/売上(3年平均) | {fcf}% |
| 自己資本比率 | {equity_ratio}% |
| 有利子負債/EBITDA | {debt_ebitda}倍 |

## 一次ソースへのリンク(分析の際に必ず参照すること)

- EDINET 書類一覧: https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx?keyword={code}
- 適時開示(TDnet): https://www.release.tdnet.info/inbs/I_main_00.html
- 会社情報: https://www2.jpx.co.jp/tseHpFront/JJK010010Action.do?Show=Show
- Yahoo!ファイナンス: https://finance.yahoo.co.jp/quote/{code}.T
- IR BANK: https://irbank.net/{code}/

## 分析依頼

上記銘柄について、以下の指示に厳密に従って分析レポートを作成してください。

### 必須遵守事項
1. **「買い」「売り」の断定は禁止**。ブル/ベア両論併記が絶対条件。
2. **数値は必ず一次ソース(EDINET / 適時開示 / 会社IR)から最新版を取得**。上記のスクリーニング指標は参考値であり、最新値で再確認すること。
3. **事実と解釈を明確に分離**。事実セクションには出典URLを併記、解釈には「私見」と明記。
4. **株価予測の禁止**。「年内に〇〇円目指す」「割安なので上昇する」等は書かない。
5. **判断のための問いを必ず5項目記入**。省略しない。

### 出力フォーマット

以下のテンプレートに従って構造化レポートを作成すること。

```
## 【検討候補銘柄レポート】対象: {name}({code})

### 1. なぜ候補に挙がったか(事実ベース)
| カテゴリ | 内容 | 出典 |
|---------|------|------|
| バリュエーション | (最新の数値) | (一次ソースURL) |
| 収益性 | (最新の数値) | (一次ソースURL) |
| 直近決算 | (直近Qの動向) | (適時開示URL) |
| 財務 | (最新B/S指標) | (有報URL) |
| 市場評価 | (時価総額・流動性) | (取引所データURL) |

### 2. 強気に見える材料(ブルケース) ※3点
1. **[論点タイトル]**
   - 事実:
   - 解釈(私見):
   - 出典:
(以下、3点まで)

### 3. 弱気に見る材料(ベアケース) ※3点
1. **[論点タイトル]**
   - 事実:
   - 解釈(私見):
   - 出典:
(以下、3点まで)

### 4. Kuriが確認すべき論点
- (一次ソース要確認の項目)
- (競合動向で見るべき点)
- (マクロ要因との接続)
- (既存ポートフォリオとの重複リスク)

### 5. 判断のための問い(必須5項目)
1. 投資テーゼを1文で: この銘柄を持つことで、自分は何にベットしているのか?
2. 外れる条件: どの数値・どの事象が起きたら「このテーゼは間違っていた」と判定するか?
3. 保有期間: 想定保有期間は? その間に確認するKPIは?
4. ポジションサイズ: ポートフォリオ全体の何%が妥当か? その理由は?
5. 代替案との比較: 同じテーマで他により良い選択肢はないか?

### 6. 情報の鮮度メモ
- 株価データ取得日時:
- 直近決算反映:
- 適時開示反映:

### 7. このレポートの限界
- 機械的スクリーニングベース、未開示情報・経営の質的評価は反映されていない
- ベアケースに見落としがある可能性
- 株価は予測不能要因で動くため、本レポートは「買い」推奨ではない
- 最終判断はKuri自身が行う
```

### 補足
- 私は中期ファンダメンタル投資が中心で、想定保有期間は1〜3年。
- NISA成長投資枠での購入を想定。
- 既存保有銘柄との相関リスクの観点も意識してほしい(具体銘柄は別途共有可能)。

それでは分析を開始してください。
"""


def generate_prompts(date_str: str, top_n: int):
    """指定日のスクリーニング結果から、上位 top_n 社のプロンプトを生成。"""
    csv_path = Path(config.OUTPUT_DIR) / f"top_candidates_{date_str}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"スクリーニング結果が見つかりません: {csv_path}")

    df = pd.read_csv(csv_path, dtype={"code": str})
    top = df.head(top_n)

    out_dir = Path(config.OUTPUT_DIR) / "analysis_prompts" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, row in top.iterrows():
        prompt = PROMPT_TEMPLATE.format(
            code=row["code"],
            name=row["name"],
            sector=row.get("sector_33", "-"),
            market_cap=_fmt(row.get("market_cap_oku_yen"), "{:.0f}"),
            rank=i+1,
            score_val=_fmt(row.get("score_valuation"), "{:.1f}"),
            score_qual=_fmt(row.get("score_quality"), "{:.1f}"),
            score_total=_fmt(row.get("total_score"), "{:.1f}"),
            pbr=_fmt(row.get("PBR"), "{:.2f}"),
            per=_fmt(row.get("PER"), "{:.1f}"),
            peg=_fmt(row.get("PEG"), "{:.2f}"),
            div_yield=_fmt(row.get("Dividend_Yield"), "{:.2f}"),
            roe=_fmt(row.get("ROE"), "{:.1f}"),
            roic=_fmt(row.get("ROIC"), "{:.1f}"),
            opm_trend=_fmt(row.get("Op_Margin_Trend_3Y"), "{:+.1f}"),
            fcf=_fmt(row.get("FCF_to_Sales_3Y"), "{:.1f}"),
            equity_ratio=_fmt(row.get("Equity_Ratio"), "{:.1f}"),
            debt_ebitda=_fmt(row.get("Debt_to_EBITDA"), "{:.2f}"),
        )

        out_path = out_dir / f"prompt_{row['code']}_{row['name']}.md"
        # ファイル名に使えない文字を除去
        safe_name = "".join(c for c in row['name'] if c.isalnum() or c in "._- ").strip()
        out_path = out_dir / f"prompt_{row['code']}_{safe_name}.md"

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        logger.info(f"プロンプト出力: {out_path}")

    print(f"\n=== 完了 ===")
    print(f"出力先: {out_dir}")
    print(f"使い方: 各 .md ファイルの内容を Claude.ai (Project化済みエージェント) にコピペして実行")


def _fmt(val, fmt_str: str) -> str:
    if val is None or pd.isna(val):
        return "-"
    try:
        return fmt_str.format(val)
    except (ValueError, TypeError):
        return str(val)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="スクリーニング実行日 YYYY-MM-DD")
    parser.add_argument("--top", type=int, default=3, help="上位何社のプロンプトを生成するか")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    generate_prompts(args.date, args.top)


if __name__ == "__main__":
    main()
