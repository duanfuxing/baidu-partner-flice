"""流程 6 的脱敏执行结果。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class QualificationActionResult:
    type_name: str
    qualification_no: str
    qualification_name: str
    action: str
    success: bool
    file_count: int = 0
    uploaded_file_ids: tuple[str, ...] = ()
    input_file_hashes: tuple[str, ...] = ()
    error: str | None = None


@dataclass
class SubmissionResult:
    company_name: str
    url: str
    started_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    completed_at: str | None = None
    deleted_businesses: list[str] = field(default_factory=list)
    added_businesses: list[str] = field(default_factory=list)
    deleted_qualifications: list[dict[str, str]] = field(default_factory=list)
    qualifications: list[QualificationActionResult] = field(default_factory=list)
    final_submission_success: bool = False
    error: str | None = None

    def finish(self) -> None:
        self.completed_at = datetime.now().astimezone().isoformat(timespec="seconds")

    @property
    def qualifications_success(self) -> bool:
        return self.error is None and all(item.success for item in self.qualifications)

    @property
    def success(self) -> bool:
        return self.qualifications_success and self.final_submission_success

    def save(self, company_directory: Path) -> Path:
        target = company_directory / "qualification-submit-result.json"
        temporary = company_directory / ".qualification-submit-result.json.tmp"
        payload = asdict(self)
        payload["success"] = self.success
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        return target

    @staticmethod
    def load_file_history(
        company_directory: Path,
    ) -> dict[tuple[str, str, str], tuple[tuple[str, ...], tuple[str, ...]]]:
        path = company_directory / "qualification-submit-result.json"
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        history: dict[
            tuple[str, str, str],
            tuple[tuple[str, ...], tuple[str, ...]],
        ] = {}
        for item in payload.get("qualifications") or []:
            if not item.get("success"):
                continue
            type_name = item.get("type_name")
            qualification_no = item.get("qualification_no")
            qualification_name = item.get("qualification_name")
            file_ids = item.get("uploaded_file_ids") or []
            file_hashes = item.get("input_file_hashes") or []
            if (
                type_name
                and qualification_no
                and qualification_name
                and file_ids
                and file_hashes
            ):
                history[
                    (
                        str(type_name),
                        str(qualification_no),
                        str(qualification_name),
                    )
                ] = (
                    tuple(str(value) for value in file_ids),
                    tuple(str(value) for value in file_hashes),
                )
        return history
