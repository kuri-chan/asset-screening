"""
git_sync.py
実行コンテナがセッションごとに再作成される前提で、output/ 配下の
スクリーニング結果・パフォーマンス追跡データをgit経由で永続化する。

- pull_latest(): 実行開始時に呼び、過去の履歴(前回以前のoutput/)を取得する
- commit_and_push(): 実行後に呼び、今回生成したoutput/の差分をコミット・push する

どちらも失敗時は例外を投げず警告ログのみに留める(ネットワーク不通等でも
スクリーニング本体の処理は継続できるようにするため)。
"""

import logging
import subprocess

logger = logging.getLogger(__name__)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def pull_latest() -> None:
    """originのmainブランチから最新のoutput/履歴を取り込む(fast-forwardのみ)。"""
    result = _run(["git", "pull", "--ff-only", "origin", "main"])
    if result.returncode != 0:
        logger.warning(f"git pull に失敗しました(履歴なしで続行します): {result.stderr.strip()}")
    else:
        logger.info("git pull 完了: 過去の output/ 履歴を取得しました")


def commit_and_push(message: str, paths: tuple[str, ...] = ("output",)) -> None:
    """output/ の変更をコミットしてpushする。差分が無ければ何もしない。"""
    add_result = _run(["git", "add", *paths])
    if add_result.returncode != 0:
        logger.warning(f"git add に失敗しました: {add_result.stderr.strip()}")
        return

    diff_check = _run(["git", "diff", "--cached", "--quiet"])
    if diff_check.returncode == 0:
        logger.info("コミット対象の変更はありません")
        return

    commit_result = _run(["git", "commit", "-m", message])
    if commit_result.returncode != 0:
        logger.warning(f"git commit に失敗しました: {commit_result.stderr.strip()}")
        return

    push_result = _run(["git", "push", "origin", "HEAD:main"])
    if push_result.returncode != 0:
        logger.warning(
            f"git push に失敗しました(ローカルにはコミット済み): {push_result.stderr.strip()}"
        )
    else:
        logger.info("output/ の変更をコミット・pushしました")
