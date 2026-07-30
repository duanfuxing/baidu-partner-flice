"""流程 1-6 使用的数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Expiry:
    permanent: bool
    date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "permanent": self.permanent,
            "date": self.date.isoformat() if self.date else None,
        }


@dataclass(frozen=True)
class Qualification:
    index_name: str
    qualification_no: str
    qualification_name: str
    expiry: Expiry
    evidence_url: str | None
    files: tuple[Path, ...]

    def to_dict(self, relative_to: Path | None = None) -> dict[str, Any]:
        def serialize_path(path: Path) -> str:
            if relative_to is not None:
                try:
                    return path.relative_to(relative_to).as_posix()
                except ValueError:
                    pass
            return str(path)

        return {
            "indexName": self.index_name,
            "qualificationNo": self.qualification_no,
            "qualificationName": self.qualification_name,
            "expiry": self.expiry.to_dict(),
            "evidenceUrl": self.evidence_url,
            "files": [serialize_path(path) for path in self.files],
        }


@dataclass(frozen=True)
class QualificationType:
    type_name: str
    qualifications: tuple[Qualification, ...]

    def to_dict(self, relative_to: Path | None = None) -> dict[str, Any]:
        return {
            "typeName": self.type_name,
            "qualifications": [item.to_dict(relative_to=relative_to) for item in self.qualifications],
        }


@dataclass(frozen=True)
class CompanyInput:
    company_name: str
    url: str
    qualification_types: tuple[QualificationType, ...]
    source_path: Path

    def to_dict(self, relative_to: Path | None = None) -> dict[str, Any]:
        return {
            "companyName": self.company_name,
            "url": self.url,
            "qualificationTypes": [item.to_dict(relative_to=relative_to) for item in self.qualification_types],
        }


@dataclass(frozen=True)
class CompanyContext:
    company: CompanyInput
    cust_id: str
    qualification_url: str


@dataclass(frozen=True)
class CompanyRunResult:
    company_name: str
    url: str
    cust_id: str
    qualification_url: str
    final_url: str
    industry_qualification_loaded: bool
    qualification_submission_completed: bool = False
    final_submission_completed: bool = False
    dry_run: bool = False
    submission_result_path: str | None = None


def as_serializable(value: Any) -> Any:
    """将模型或 Path 转成适合 JSON 的值。"""

    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [as_serializable(item) for item in value]
    if isinstance(value, list):
        return [as_serializable(item) for item in value]
    if isinstance(value, dict):
        return {key: as_serializable(item) for key, item in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value
