from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.errors import InputValidationError
from src.input_loader import clean_url, load_input, save_input_json


def _write_qualification(root: Path, name: str = "资质1", form: str | None = None) -> Path:
    directory = root / "推广审查" / name
    directory.mkdir(parents=True)
    (directory / "表单信息.txt").write_text(
        form
        or "资质编号：编号1\n资质名称：资质名称1\n有效期至：2026-11-12\n举证链接：\n",
        encoding="utf-8",
    )
    (directory / "1.jpg").write_bytes(b"image")
    return directory


def test_clean_url_removes_all_whitespace() -> None:
    assert clean_url("  https://example.com/\n\tpath  ") == "https://example.com/path"


def test_clean_url_repairs_single_slash_after_scheme() -> None:
    assert clean_url("https:/example.com/path") == "https://example.com/path"


def test_load_input_parses_company_and_qualifications(tmp_path: Path) -> None:
    company = tmp_path / "示例公司"
    company.mkdir()
    (company / "url.txt").write_text(" https://example.com\n", encoding="utf-8")
    _write_qualification(company)

    result = load_input(tmp_path)

    assert len(result) == 1
    assert result[0].company_name == "示例公司"
    assert result[0].url == "https://example.com"
    qualification = result[0].qualification_types[0].qualifications[0]
    assert qualification.qualification_no == "编号1"
    assert qualification.expiry.permanent is False
    assert qualification.expiry.date.isoformat() == "2026-11-12"
    assert qualification.evidence_url is None


def test_load_input_parses_permanent_expiry_and_evidence_url(tmp_path: Path) -> None:
    company = tmp_path / "示例公司"
    company.mkdir()
    (company / "url.txt").write_text("https://example.com", encoding="utf-8")
    _write_qualification(
        company,
        form="资质编号：编号1\n资质名称：资质名称1\n有效期至：永久\n举证链接： https://evidence.example/ \n",
    )

    qualification = load_input(tmp_path)[0].qualification_types[0].qualifications[0]

    assert qualification.expiry.permanent is True
    assert qualification.expiry.date is None
    assert qualification.evidence_url == "https://evidence.example/"


def test_load_input_ignores_unsupported_files(tmp_path: Path) -> None:
    company = tmp_path / "示例公司"
    company.mkdir()
    (company / "url.txt").write_text("https://example.com", encoding="utf-8")
    qualification = _write_qualification(company)
    (qualification / "说明.docx").write_bytes(b"ignored")

    result = load_input(tmp_path)

    assert [path.name for path in result[0].qualification_types[0].qualifications[0].files] == ["1.jpg"]


def test_load_input_reports_malformed_form_file(tmp_path: Path) -> None:
    company = tmp_path / "示例公司"
    company.mkdir()
    (company / "url.txt").write_text("https://example.com", encoding="utf-8")
    _write_qualification(company, form="编号1\n资质名称：名称\n有效期至：永久\n举证链接：")

    with pytest.raises(InputValidationError, match="无法识别字段"):
        load_input(tmp_path)
    assert not (company / "input.json").exists()


def test_load_input_rejects_more_than_nine_files(tmp_path: Path) -> None:
    company = tmp_path / "示例公司"
    company.mkdir()
    (company / "url.txt").write_text("https://example.com", encoding="utf-8")
    qualification = _write_qualification(company)
    for index in range(2, 11):
        (qualification / f"{index}.jpg").write_bytes(b"image")

    with pytest.raises(InputValidationError, match="最多 9 个"):
        load_input(tmp_path)


def test_save_input_json_writes_normalized_company_data(tmp_path: Path) -> None:
    company = tmp_path / "示例公司"
    company.mkdir()
    (company / "url.txt").write_text(" https://example.com\n", encoding="utf-8")
    _write_qualification(company)

    companies = load_input(tmp_path)
    saved_paths = save_input_json(companies)

    assert saved_paths == (company / "input.json",)
    payload = json.loads((company / "input.json").read_text(encoding="utf-8"))
    assert payload["companyName"] == "示例公司"
    assert payload["url"] == "https://example.com"
    assert payload["qualificationTypes"][0]["qualifications"][0]["files"] == [
        "推广审查/资质1/1.jpg"
    ]


def test_load_input_allows_duplicate_number_with_different_names(
    tmp_path: Path,
) -> None:
    company = tmp_path / "示例公司"
    company.mkdir()
    (company / "url.txt").write_text("https://example.com", encoding="utf-8")
    _write_qualification(company, name="资质1")
    _write_qualification(
        company,
        name="资质2",
        form="资质编号：编号1\n资质名称：另一个名称\n有效期至：永久\n举证链接：\n",
    )

    result = load_input(tmp_path)

    qualifications = result[0].qualification_types[0].qualifications
    assert [item.qualification_no for item in qualifications] == ["编号1", "编号1"]
    assert [item.qualification_name for item in qualifications] == [
        "资质名称1",
        "另一个名称",
    ]


def test_load_input_rejects_duplicate_number_and_name_in_same_type(
    tmp_path: Path,
) -> None:
    company = tmp_path / "示例公司"
    company.mkdir()
    (company / "url.txt").write_text("https://example.com", encoding="utf-8")
    _write_qualification(company, name="资质1")
    _write_qualification(company, name="资质2")

    with pytest.raises(InputValidationError, match="资质编号 \\+ 资质名称"):
        load_input(tmp_path)
