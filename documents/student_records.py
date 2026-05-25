from __future__ import annotations

import re
from typing import Any

from django.utils import timezone

from documents.models import Document
from documents.models import StudentRecord

STUDENT_RECORD_DOCUMENT_TYPE = "Student Record"

DEFAULT_STUDENT_RECORD_DATA: dict[str, Any] = {
    "department": "",
    "registration_no": "",
    "surname": "",
    "maiden_name": "",
    "other_names": "",
    "date_of_birth": "",
    "sex": "",
    "place_of_birth": "",
    "division_of_origin": "",
    "region_of_origin": "",
    "nationality": "",
    "marital_status": "",
    "handicap": "",
    "religious_denomination": "",
    "father_name": "",
    "mother_name": "",
    "parent_occupation": "",
    "parent_name_address": "",
    "parent_post_box": "",
    "parent_town": "",
    "parent_country": "",
    "parent_tel": "",
    "student_address": "",
    "student_post_box": "",
    "student_town": "",
    "student_country": "",
    "student_tel": "",
    "documents_enclosed": {},
    "academic_records": [
        {"level": "Primary", "year": "", "school": "", "qualification": ""},
        {"level": "Secondary", "year": "", "school": "", "qualification": ""},
        {"level": "High School", "year": "", "school": "", "qualification": ""},
    ],
    "gce_ol": {"centre": "", "candidate_no": "", "subjects": []},
    "gce_al": {"centre": "", "candidate_no": "", "subjects": []},
}

DOCUMENTS_ENCLOSED = [
    "Birth Certificate",
    "Medical Certificate",
    "Certified Copy G.C.E. O/L",
    "Certified Copy G.C.E. A/L",
    "Certified Copy (Probatoire)",
    "Certified Copy (Baccalaureat)",
    "Receipt of Payment of Registration Fees",
    "Admission Letter",
    "B.Eng",
    "M.Eng",
]

FIELD_LABELS = {
    "registration_no": [r"registration\s*(?:no|number)"],
    "surname": [r"surname"],
    "maiden_name": [r"maiden\s+name"],
    "other_names": [r"other\s+names?"],
    "date_of_birth": [r"date\s+of\s+birth", r"\bdob\b"],
    "sex": [r"\bsex\b"],
    "place_of_birth": [r"place\s+of\s+birth"],
    "division_of_origin": [r"division\s+of\s+origin"],
    "region_of_origin": [r"region\s+of\s+origin"],
    "nationality": [r"nationality"],
    "marital_status": [r"marital\s+status"],
    "handicap": [r"handicap"],
    "religious_denomination": [r"religious\s+denomination"],
    "father_name": [r"father'?s\s+name"],
    "mother_name": [r"mother'?s\s+name"],
    "parent_occupation": [r"parent\s+or\s+guardian'?s\s+occupation"],
}


def blank_student_record_data() -> dict[str, Any]:
    data = DEFAULT_STUDENT_RECORD_DATA.copy()
    data["documents_enclosed"] = {name: False for name in DOCUMENTS_ENCLOSED}
    data["academic_records"] = [
        row.copy() for row in DEFAULT_STUDENT_RECORD_DATA["academic_records"]
    ]
    data["gce_ol"] = {"centre": "", "candidate_no": "", "subjects": []}
    data["gce_al"] = {"centre": "", "candidate_no": "", "subjects": []}
    return data


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" :-\t\r\n")


def _extract_label_value(text: str, labels: list[str]) -> tuple[str, float]:
    for label in labels:
        match = re.search(
            rf"(?:^|\n)\s*(?:\d+\.\s*)?{label}\s*[:\-]?\s*(.+?)(?=\n\s*(?:\d+\.\s*)?[A-Za-z][A-Za-z\s'()/]+\s*[:\-]|\n\s*\d+\.|\Z)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            value = _clean(match.group(1))
            return value[:160], 0.72 if value else 0.2
    return "", 0.0


def _extract_department(text: str) -> tuple[str, float]:
    if re.search(r"\bCIE\b|computer\s+engineering", text, re.IGNORECASE):
        return "CIE", 0.8
    if re.search(r"\bCE\b|civil\s+engineering", text, re.IGNORECASE):
        return "CE", 0.75
    if re.search(r"\bEE\b|electrical\s+engineering", text, re.IGNORECASE):
        return "EE", 0.75
    return "", 0.0


def _extract_subjects(text: str, marker: str, limit: int) -> list[dict[str, str]]:
    marker_match = re.search(marker, text, re.IGNORECASE)
    if not marker_match:
        return []
    chunk = text[marker_match.end() : marker_match.end() + 1000]
    subjects = []
    for line in chunk.splitlines():
        match = re.search(r"([A-Za-z][A-Za-z /&-]{2,})\s+([A-F][0-9]?|[0-9])$", line.strip())
        if match:
            subjects.append(
                {
                    "subject": _clean(match.group(1))[:60],
                    "grade": _clean(match.group(2))[:4],
                },
            )
        if len(subjects) >= limit:
            break
    return subjects


def extract_student_record(document: Document) -> tuple[dict[str, Any], dict[str, float]]:
    text = document.content or ""
    data = blank_student_record_data()
    confidence: dict[str, float] = {}

    department, department_confidence = _extract_department(text)
    data["department"] = department
    confidence["department"] = department_confidence

    for field, labels in FIELD_LABELS.items():
        value, score = _extract_label_value(text, labels)
        data[field] = value
        confidence[field] = score

    for doc_name in DOCUMENTS_ENCLOSED:
        present = bool(re.search(re.escape(doc_name), text, re.IGNORECASE))
        data["documents_enclosed"][doc_name] = present
        confidence[f"documents_enclosed.{doc_name}"] = 0.65 if present else 0.0

    data["gce_ol"]["subjects"] = _extract_subjects(
        text,
        r"GCE\s+O/?L|Ordinary\s+Level|Probatoire",
        10,
    )
    data["gce_al"]["subjects"] = _extract_subjects(
        text,
        r"GCE\s+A/?L|Advanced\s+Level|Baccalaureat",
        5,
    )
    confidence["gce_ol.subjects"] = 0.55 if data["gce_ol"]["subjects"] else 0.0
    confidence["gce_al.subjects"] = 0.55 if data["gce_al"]["subjects"] else 0.0

    return data, confidence


def get_or_create_student_record(document: Document) -> StudentRecord:
    record, created = StudentRecord.objects.get_or_create(document=document)
    if created or not record.data:
        record.data, record.confidence = extract_student_record(document)
        record.needs_review = True
        record.extracted_at = timezone.now()
        record.save(update_fields=["data", "confidence", "needs_review", "extracted_at"])
    return record
