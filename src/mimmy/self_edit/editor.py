"""자연어 지시 → 파일 변경 제안.

실제 구현은 Anthropic Claude를 file-edit tool use 모드로 부른다:
- 시스템 프롬프트에 저장소 구조와 규칙을 명시
- tool: read_file, write_file, search
- 결과로 변경된 파일 목록 + 각 파일의 새 전문

여기선 인터페이스만 두고, 호출부에선 NotImplementedError로 폴백한다.
다음 반복에서 Claude 파일 편집 루프를 실제 코드로 붙인다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mimmy.logging import get_logger

log = get_logger(__name__)


@dataclass
class FileEdit:
    path: Path
    new_content: str


@dataclass
class EditPlan:
    rationale: str
    edits: list[FileEdit] = field(default_factory=list)


async def propose_edits(instruction: str, repo_root: Path) -> EditPlan:
    """TODO: Claude file-editing agent 붙이기.

    현재는 빈 플랜을 반환한다 — 파이프라인이 '지시를 받았지만 코드는 바뀌지 않음'을
    명시적으로 보고할 수 있게.
    """
    log.info("propose_edits_stub", instruction=instruction[:80])
    return EditPlan(
        rationale="editor stub — 실제 변경은 Claude 파일편집 루프 구현 후에 활성화됩니다.",
        edits=[],
    )
