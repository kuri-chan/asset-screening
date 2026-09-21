# Week 1 スクリーニング機能 セットアップガイド

## 構成ファイル

```
scripts/
├── config.py                       # 設定(閾値・パス)
├── universe_loader.py              # 東証プライム銘柄一覧読込
├── data_fetcher.py                 # yfinanceで財務データ取得
├── screener.py                     # 3段階フィルタロジック
├── run_screening.py                # メイン実行スクリプト
├── edinet_client.py                # EDINET API クライアント(深掘り用)
└── generate_analysis_prompt.py     # Claude用分析プロンプト生成
```

## 必要パッケージ

```bash
pip install yfinance pandas openpyxl xlrd requests
```

## 事前準備

### 1. JPX銘柄一覧のダウンロード

東証プライム銘柄を抽出するために、JPX公式の銘柄一覧Excelを使う。

1. https://www.jpx.co.jp/markets/statistics-equities/misc/01.html を開く
2. 「東証上場銘柄一覧」のExcelをダウンロード
3. `./data/data_j.xls` として保存

### 2. EDINET API Key の取得(深掘り段階で必要)

1. https://disclosure2.edinet-fsa.go.jp/ にアクセス
2. アカウント作成 → APIキー発行
3. 環境変数に設定:
   ```bash
   export EDINET_API_KEY="your_key_here"
   ```

## 実行手順

### Step 1: テスト実行(少数銘柄で動作確認)

```bash
cd scripts
python run_screening.py --limit 30
```

30社のみで動かして、エラーが出ないこと、結果のCSV/Markdownが生成されることを確認。

### Step 2: フル実行(東証プライム全銘柄)

```bash
python run_screening.py
```

所要時間: 全銘柄(約1,600社)× 0.5秒待機 = 約15〜20分。
yfinanceの応答遅延次第で30分前後かかる可能性。

### Step 3: 結果の確認

`./output/top_candidates_YYYY-MM-DD.md` を開いて、上位20社のリストを確認。

### Step 4: 上位候補の分析プロンプト生成

```bash
python generate_analysis_prompt.py --date 2026-05-12 --top 3
```

`./output/analysis_prompts/2026-05-12/` 配下に、各銘柄向けのプロンプトファイルが生成される。

### Step 5: Claude による定性分析

1. Claude.ai で資産運用エージェント Project を開く
2. 生成されたプロンプトファイルの内容をコピペして実行
3. Claude が EDINET / 適時開示 / 各種一次ソースを参照しながらブル/ベア両論レポートを生成
4. 出力された分析レポートを Notion 等に保存

## キャッシュの活用

データ取得は時間がかかるので、一度取った日のデータを再利用できる:

```bash
# 5/12 に取得したデータでスクリーニング条件だけ変えて再実行
python run_screening.py --use-cache 2026-05-12
```

config.py の閾値をいじって、スクリーニング条件のチューニングが可能。

## 注意事項

### データ精度の限界
- **yfinanceの日本株データは欠損あり**。完璧ではない。
- **PEG・ROICは簡易計算**(yfinance単独では厳密値が取れない)。深掘り段階で再計算する前提。
- **業績修正履歴**は yfinance では取れないため、本実装ではハード除外対象から除外している。改善するなら適時開示スクレイピングが必要。

### スクリーニング結果の読み方
- 上位20社は「**買い銘柄**」ではない。「**さらに深掘りすべき候補**」。
- 機械的フィルタの限界を理解する(例: 業界特性、無形資産価値、経営陣の質などは反映されない)。
- 同じ業種ばかり上位に来た場合は、業種補正が効いていない兆候。config.py で業種別ランキングを有効にすることを検討。

### チューニング指針
- 候補が0件 → ハード条件を緩める(`HARD_FILTER` の閾値)
- 候補が出すぎる → 第3段に送る件数を絞る(`TOP_N_FOR_QUALITATIVE_REVIEW`)
- 同じ銘柄ばかり上位に → スコア合算方式を `product` から `average` に変更してみる
- 特定指標が支配的すぎる → `VALUATION_METRICS` / `QUALITY_METRICS` の `weight` を調整

## トラブルシューティング

### yfinance でデータが取れない銘柄が多い
- yfinanceの仕様変更で一時的にデータ取得不能なケースあり
- `yfinance` を最新版にアップデート: `pip install -U yfinance`
- それでもダメなら J-Quants API(無料プラン12週間遅延あり)を補助的に使う

### EDINET API でレート制限エラー
- `config.EDINET_SLEEP_SEC` を 3.0 以上に上げる
- 1回の実行で取得する書類数を絞る(深掘り対象を3-5社に限定)

### スクリーニング結果が業種偏重
- 銀行・不動産が多すぎる → `02_screening_criteria.md` 記載の業種補正を実装する
- 全銘柄を一律パーセンタイル化せず、業種内ランキングを使う方式に変更

## 次のステップ

Week 1 のスクリーニング機能が動いたら、Week 2 のマクロレポート機能に進む。
詳細は `07_mvp_roadmap.md` 参照。

## 結果の永続化(前週比較・Notion保存)

### output/ はgit管理下(2026-09-21〜)

週次エージェントは毎回新しいコンテナで動くため、`output/`(スクリーニング結果・
`output/performance/` のエントリー価格/検証結果)を **git commit + push で永続化**
している(`git_sync.py`)。`run_screening.py` と `track_performance.py` は実行開始時に
`git pull --ff-only origin main` で過去の履歴を取得し、実行後に変更を自動でcommit・
pushする。これにより `weekly_summary.py` / `check_alerts.py` / `track_performance.py --check`
が前週以前のデータと比較できるようになっている。`cache/` と `data/` は引き続きgitignore対象
(サイズが大きく、JPX/yfinanceから再取得可能なため)。

### Notionへの保存(制約あり)

このリポジトリを操作するNotion MCP接続には、現時点で `search` / `fetch` /
`create_pages` / `create_database` / `update_page` が(接続先の権限確認では
「利用可能」と出るにもかかわらず)実際にはツールとして公開されていない。
そのため、当初想定していた「TOP10週次トラッキング」データベース(行＝銘柄、
順位・スコア等をプロパティで保持)の自動作成・書き込みはできない。

**代替として、既存の「AIエージェント運用ハブ」ページ配下に `TOP10週次トラッキング`
という Folder を作成し(folder_id: `93bb0f24-9bb7-4b36-9b0c-7f4611085a81`)、
週次レポート(.md)・TOP20 CSV・エントリー価格CSV を毎週ファイル添付として
保存する運用にしている。** 手順(利用可能なNotionツールのみで完結):

1. `notion-create-attachment`(`content` にファイル本文をインラインで渡す。
   `notion-create-file-upload` で得た `upload_url` への直接POSTは、この環境の
   egressプロキシが `api.notion.com` への直接接続を拒否するため使えない)
2. 返ってきた `file_upload_id` を集めて `notion-update-folder`
   (`command: "add_files"`, 対象 `folder_id` 上記)で追加

これは構造化データベースではなくファイルの集積なので、Notion上でのフィルタ/
ソート/プロパティ集計はできない。`search` / `fetch` / `create_pages` /
`create_database` がこの環境のツールとして実際に使えるようになった場合は、
当初仕様どおりのデータベース化に切り替えるべき。
