"""
edinet_client.py
EDINET API V2 を使って、指定銘柄の最新有価証券報告書を取得する。

【EDINET API V2 の特性】
- 日付ベースで全提出書類リストを取得 → 銘柄コードでフィルタする方式
- 認証は Subscription-Key (環境変数 EDINET_API_KEY から)
- ファイルは ZIP で、XBRL本体と PDF が含まれる
- 銘柄コード(secCode)は5桁(末尾0付加)で返ってくる場合あり

【使い方】
  client = EdinetClient(api_key=os.getenv("EDINET_API_KEY"))
  doc_id = client.find_latest_annual_report("7203")  # トヨタ
  pdf_path = client.download_pdf(doc_id)
"""

import os
import time
import logging
import zipfile
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)


# 様式コード(EDINET API仕様書 別紙1より)
DOC_TYPE_ANNUAL_REPORT = "120"      # 有価証券報告書
DOC_TYPE_QUARTERLY = "140"          # 四半期報告書
DOC_TYPE_SEMI_ANNUAL = "160"        # 半期報告書


class EdinetClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("EDINET_API_KEY")
        if not self.api_key:
            raise ValueError(
                "EDINET_API_KEY が設定されていません。"
                "https://disclosure2dl.edinet-fsa.go.jp/ でAPI Keyを取得してください。"
            )
        self.base = config.EDINET_API_BASE
        self.sleep = config.EDINET_SLEEP_SEC

    def list_documents(self, date: datetime) -> list[dict]:
        """指定日に提出された全書類のメタデータを取得。"""
        url = f"{self.base}/documents.json"
        params = {
            "date": date.strftime("%Y-%m-%d"),
            "type": 2,  # 取得書類: 書類一覧及びメタデータ
            "Subscription-Key": self.api_key,
        }
        try:
            res = requests.get(url, params=params, timeout=30)
            res.raise_for_status()
            data = res.json()
            time.sleep(self.sleep)
            return data.get("results", [])
        except requests.HTTPError as e:
            logger.error(f"EDINET API エラー ({date}): {e}")
            return []
        except Exception as e:
            logger.error(f"EDINET API 取得失敗 ({date}): {e}")
            return []

    def find_latest_annual_report(self, sec_code: str, lookback_days: int = 400) -> Optional[dict]:
        """
        指定銘柄(4桁証券コード)の最新有価証券報告書のメタデータを返す。
        過去 lookback_days 日を遡って検索。
        """
        # EDINETは5桁コード(例: "72030")で記録されるので両方試す
        target_codes = {sec_code, sec_code + "0"}

        end = datetime.now()
        start = end - timedelta(days=lookback_days)

        # 日付逆順で検索(最新を見つけたら終了)
        cur = end
        while cur >= start:
            docs = self.list_documents(cur)
            for doc in docs:
                doc_sec = doc.get("secCode")
                doc_type = doc.get("docTypeCode")
                if doc_sec in target_codes and doc_type == DOC_TYPE_ANNUAL_REPORT:
                    logger.info(f"有報発見: {sec_code} / {doc.get('docID')} / {doc.get('submitDateTime')}")
                    return doc
            cur -= timedelta(days=1)
            # 検索効率化: 週末は飛ばす
            if cur.weekday() == 5:  # 土曜
                cur -= timedelta(days=1)

        logger.warning(f"有報が見つかりません: {sec_code}")
        return None

    def download_pdf(self, doc_id: str, output_dir: Optional[Path] = None) -> Optional[Path]:
        """指定書類のPDFをダウンロード。"""
        out_dir = output_dir or Path(config.DATA_CACHE_DIR) / "edinet_pdfs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{doc_id}.pdf"

        if out_path.exists():
            logger.info(f"既にダウンロード済み: {out_path}")
            return out_path

        url = f"{self.base}/documents/{doc_id}"
        params = {
            "type": 2,  # 2 = PDF
            "Subscription-Key": self.api_key,
        }
        try:
            res = requests.get(url, params=params, timeout=60)
            res.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(res.content)
            logger.info(f"PDF保存: {out_path}")
            time.sleep(self.sleep)
            return out_path
        except Exception as e:
            logger.error(f"PDF取得失敗 {doc_id}: {e}")
            return None

    def download_xbrl(self, doc_id: str, output_dir: Optional[Path] = None) -> Optional[Path]:
        """XBRLのZIPを取得して解凍済みディレクトリパスを返す。"""
        out_dir = output_dir or Path(config.DATA_CACHE_DIR) / "edinet_xbrl"
        out_dir.mkdir(parents=True, exist_ok=True)
        extract_dir = out_dir / doc_id

        if extract_dir.exists():
            logger.info(f"既に解凍済み: {extract_dir}")
            return extract_dir

        url = f"{self.base}/documents/{doc_id}"
        params = {
            "type": 1,  # 1 = XBRL等の本文書類
            "Subscription-Key": self.api_key,
        }
        try:
            res = requests.get(url, params=params, timeout=60)
            res.raise_for_status()
            with zipfile.ZipFile(BytesIO(res.content)) as zf:
                zf.extractall(extract_dir)
            logger.info(f"XBRL解凍: {extract_dir}")
            time.sleep(self.sleep)
            return extract_dir
        except Exception as e:
            logger.error(f"XBRL取得失敗 {doc_id}: {e}")
            return None
