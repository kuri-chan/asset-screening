"""
yf_session.py
yfinance用のHTTPセッションを提供する。

yfinanceのデフォルトはcurl_cffiでブラウザのTLSフィンガープリントを
偽装するが、TLSを再終端するプロキシ環境下では接続がリセットされる。
通常のrequestsセッションにブラウザUser-Agentを付与すれば同じ用途で動く。
"""

import requests

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})
    return session
