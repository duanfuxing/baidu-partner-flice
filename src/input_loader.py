"""input 目录解析和校验。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .errors import InputPersistenceError, InputValidationError
from .models import CompanyInput, Expiry, Qualification, QualificationType

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".pdf"})
MAX_FILE_COUNT = 9
MAX_FILE_SIZE = 10 * 1024 * 1024
FORM_FIELDS = ("资质编号", "资质名称", "有效期至", "举证链接")
FIELD_PATTERN = re.compile(r"^\s*(资质编号|资质名称|有效期至|举证链接)\s*[：:]\s*(.*?)\s*$")


def clean_url(value: str) -> str:
    """移除 URL 空白，并修正常见的协议单斜杠。"""

    cleaned = "".join(value.split())
    return re.sub(r"^(https?):/(?!/)", r"\1://", cleaned, flags=re.IGNORECASE)


def _natural_sort_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name)]


def _parse_form_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise InputValidationError(f"{path}: 必须使用 UTF-8 编码") from exc

    values: dict[str, str] = {}
    errors: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        match = FIELD_PATTERN.match(line)
        if not match:
            errors.append(f"{path}:{line_number}: 无法识别字段，格式应为“字段名：值”")
            continue
        field, value = match.groups()
        if field in values:
            errors.append(f"{path}:{line_number}: 字段“{field}”重复")
            continue
        values[field] = value.strip()

    for field in FORM_FIELDS:
        if field not in values:
            errors.append(f"{path}: 缺少字段“{field}”")

    if errors:
        raise InputValidationError(errors)
    return values


def _parse_expiry(value: str, path: Path) -> Expiry:
    if value == "永久":
        return Expiry(permanent=True)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise InputValidationError(f"{path}: 有效期必须是 YYYY-MM-DD 或“永久”，实际为“{value}”") from exc
    return Expiry(permanent=False, date=parsed)


def _collect_files(directory: Path) -> tuple[Path, ...]:
    files = sorted(
        (
            item
            for item in directory.iterdir()
            if item.is_file() and item.suffix.casefold() in SUPPORTED_EXTENSIONS
        ),
        key=_natural_sort_key,
    )
    errors: list[str] = []
    if not files:
        errors.append(f"{directory}: 没有找到 jpg/jpeg/png/pdf 资质文件")
    if len(files) > MAX_FILE_COUNT:
        errors.append(f"{directory}: 资质文件最多 {MAX_FILE_COUNT} 个，实际 {len(files)} 个")
    for file_path in files:
        try:
            size = file_path.stat().st_size
        except OSError as exc:
            errors.append(f"{file_path}: 无法读取文件大小：{exc}")
            continue
        if size > MAX_FILE_SIZE:
            errors.append(f"{file_path}: 文件不能超过 10MB，实际 {size / 1024 / 1024:.2f}MB")
    if errors:
        raise InputValidationError(errors)
    return tuple(files)


def _parse_qualification(directory: Path) -> Qualification:
    form_path = directory / "表单信息.txt"
    if not form_path.is_file():
        raise InputValidationError(f"{directory}: 缺少表单信息.txt")
    values = _parse_form_file(form_path)
    qualification_no = values["资质编号"]
    qualification_name = values["资质名称"]
    if not qualification_no:
        raise InputValidationError(f"{form_path}: 资质编号不能为空")
    if not qualification_name:
        raise InputValidationError(f"{form_path}: 资质名称不能为空")
    evidence_url = clean_url(values["举证链接"]) or None
    return Qualification(
        index_name=directory.name,
        qualification_no=qualification_no,
        qualification_name=qualification_name,
        expiry=_parse_expiry(values["有效期至"], form_path),
        evidence_url=evidence_url,
        files=_collect_files(directory),
    )


def _parse_company(directory: Path) -> CompanyInput:
    errors: list[str] = []
    url_path = directory / "url.txt"
    url = ""
    if not url_path.is_file():
        errors.append(f"{directory}: 缺少 url.txt")
    else:
        try:
            url = clean_url(url_path.read_text(encoding="utf-8-sig"))
        except UnicodeDecodeError:
            errors.append(f"{url_path}: 必须使用 UTF-8 编码")
        if not url:
            errors.append(f"{url_path}: URL 清理后不能为空")

    type_directories = sorted(
        (item for item in directory.iterdir() if item.is_dir() and not item.name.startswith(".")),
        key=lambda item: item.name.casefold(),
    )
    if not type_directories:
        errors.append(f"{directory}: 至少需要一个资质类型目录")

    qualification_types: list[QualificationType] = []
    for type_directory in type_directories:
        qualification_directories = sorted(
            (item for item in type_directory.iterdir() if item.is_dir() and not item.name.startswith(".")),
            key=_natural_sort_key,
        )
        if not qualification_directories:
            errors.append(f"{type_directory}: 至少需要一个资质目录")
            continue
        qualifications: list[Qualification] = []
        for qualification_directory in qualification_directories:
            try:
                qualifications.append(_parse_qualification(qualification_directory))
            except InputValidationError as exc:
                errors.extend(exc.errors)
        if qualifications:
            seen_keys: set[tuple[str, str]] = set()
            duplicate_keys: set[tuple[str, str]] = set()
            for qualification in qualifications:
                key = (
                    qualification.qualification_no,
                    qualification.qualification_name,
                )
                if key in seen_keys:
                    duplicate_keys.add(key)
                seen_keys.add(key)
            if duplicate_keys:
                errors.append(
                    f"{type_directory}: 同一资质类型内“资质编号 + 资质名称”不能同时重复："
                    + "、".join(
                        f"{number} / {name}"
                        for number, name in sorted(duplicate_keys)
                    )
                )
            qualification_types.append(
                QualificationType(type_name=type_directory.name, qualifications=tuple(qualifications))
            )

    if errors:
        raise InputValidationError(errors)
    return CompanyInput(
        company_name=directory.name,
        url=url,
        qualification_types=tuple(qualification_types),
        source_path=directory,
    )


def load_input(input_root: Path | str) -> tuple[CompanyInput, ...]:
    """解析整个 input 目录；所有公司校验通过后才返回结果。"""

    root = Path(input_root).expanduser().resolve()
    if not root.is_dir():
        raise InputValidationError(f"input 目录不存在：{root}")
    company_directories = sorted(
        (item for item in root.iterdir() if item.is_dir() and not item.name.startswith(".")),
        key=lambda item: item.name.casefold(),
    )
    if not company_directories:
        raise InputValidationError(f"input 目录没有公司目录：{root}")

    companies: list[CompanyInput] = []
    errors: list[str] = []
    for company_directory in company_directories:
        try:
            companies.append(_parse_company(company_directory))
        except InputValidationError as exc:
            errors.extend(exc.errors)
    if errors:
        raise InputValidationError(errors)
    return tuple(companies)


def save_input_json(companies: tuple[CompanyInput, ...]) -> tuple[Path, ...]:
    """将校验通过的公司数据保存到各自目录下的 input.json。"""

    errors: list[str] = []
    saved_paths: list[Path] = []
    for company in companies:
        target = company.source_path / "input.json"
        temporary = company.source_path / ".input.json.tmp"
        try:
            payload = company.to_dict(relative_to=company.source_path)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(target)
            saved_paths.append(target)
        except OSError as exc:
            errors.append(f"{target}: {exc}")
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
    if errors:
        raise InputPersistenceError(errors)
    return tuple(saved_paths)
