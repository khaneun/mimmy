"""자연어 지시 → git feature branch → (선택적) PR / auto-merge / restart.

안전 원칙:
1. 무조건 새 브랜치에서 작업 (main 직접 수정 금지)
2. 기본값은 PR까지만. auto-merge는 설정 플래그가 true여야 함
3. 각 단계는 audit_log 테이블에 기록 (추후 store.py 연동)
4. 적용 실패/테스트 실패 시 브랜치는 남겨두고 사람이 보게 둔다
"""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mimmy.config import get_settings
from mimmy.logging import get_logger
from mimmy.self_edit.editor import propose_edits

log = get_logger(__name__)


@dataclass
class ProposeResult:
    requested_by: str
    instruction: str
    branch: str
    applied: bool
    tests_ok: bool
    pushed: bool
    merged: bool
    restarted: bool
    pr_url: str | None
    message: str

    def summary_for_user(self) -> str:
        lines = [
            f"지시: {self.instruction[:120]}",
            f"브랜치: {self.branch}",
            f"적용: {'O' if self.applied else 'X'}",
            f"스모크테스트: {'O' if self.tests_ok else 'X'}",
            f"push: {'O' if self.pushed else 'X'}",
        ]
        if self.pr_url:
            lines.append(f"PR: {self.pr_url}")
        if self.merged:
            lines.append("main 머지됨")
        if self.restarted:
            lines.append("서비스 재기동됨")
        lines.append(self.message)
        return "\n".join(lines)


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


async def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, stdout.decode()


async def propose_change(instruction: str, requested_by: str) -> ProposeResult:
    settings = get_settings()
    repo = Path.cwd()
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    branch = f"mimmy/self-edit/{stamp}"

    log.info("self_edit_start", requested_by=requested_by, branch=branch)

    # 1) 현재 상태 확인 + 새 브랜치
    try:
        _git("checkout", "-B", branch, cwd=repo)
    except subprocess.CalledProcessError as e:
        return ProposeResult(
            requested_by, instruction, branch,
            applied=False, tests_ok=False, pushed=False, merged=False, restarted=False,
            pr_url=None, message=f"브랜치 생성 실패: {e.stderr}",
        )

    # 2) LLM으로 변경안 제안
    plan = await propose_edits(instruction, repo)
    if not plan.edits:
        return ProposeResult(
            requested_by, instruction, branch,
            applied=False, tests_ok=False, pushed=False, merged=False, restarted=False,
            pr_url=None,
            message=f"변경안 없음 ({plan.rationale})",
        )

    # 3) 파일 적용
    for edit in plan.edits:
        edit.path.parent.mkdir(parents=True, exist_ok=True)
        edit.path.write_text(edit.new_content, encoding="utf-8")

    # 4) 스모크 테스트
    rc_compile, _ = await _run(["python", "-m", "compileall", "-q", "src"], cwd=repo)
    rc_tests, tests_out = await _run(["pytest", "-q", "--maxfail=1"], cwd=repo)
    tests_ok = rc_compile == 0 and rc_tests == 0

    # 5) 커밋
    _git("add", "-A", cwd=repo)
    _git(
        "commit",
        "-m",
        f"self-edit: {instruction[:72]}\n\nrequested-by: {requested_by}",
        cwd=repo,
    )

    # 6) push
    pushed = False
    pr_url: str | None = None
    try:
        _git("push", "-u", settings.git_remote, branch, cwd=repo)
        pushed = True
    except subprocess.CalledProcessError as e:
        log.warning("push_failed", err=e.stderr)

    # 7) PR 생성 (gh CLI)
    if pushed:
        rc_pr, pr_out = await _run(
            [
                "gh", "pr", "create",
                "--base", settings.git_base_branch,
                "--head", branch,
                "--title", f"[Mimmy self-edit] {instruction[:60]}",
                "--body", f"자연어 지시: {instruction}\n\n요청자: {requested_by}\n테스트: {'통과' if tests_ok else '실패'}",
            ],
            cwd=repo,
        )
        if rc_pr == 0:
            pr_url = pr_out.strip().splitlines()[-1]

    # 8) 자동 머지 + 재기동 (플래그 ON + 테스트 통과 시에만)
    merged = False
    restarted = False
    if settings.self_edit_auto_merge and tests_ok and pr_url:
        rc_m, _ = await _run(["gh", "pr", "merge", "--squash", "--auto", pr_url], cwd=repo)
        merged = rc_m == 0
        if merged:
            rc_r, _ = await _run(
                ["sudo", "systemctl", "restart", "mimmy", "mimmy-dashboard"],
                cwd=repo,
            )
            restarted = rc_r == 0

    msg = "OK" if tests_ok else f"테스트 실패:\n{tests_out[-500:]}"
    return ProposeResult(
        requested_by, instruction, branch,
        applied=True, tests_ok=tests_ok, pushed=pushed, merged=merged, restarted=restarted,
        pr_url=pr_url, message=msg,
    )
