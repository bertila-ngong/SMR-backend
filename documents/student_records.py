from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from documents.models import Document
from documents.models import StudentRecord

logger = logging.getLogger(__name__)

STUDENT_RECORD_DOCUMENT_TYPE = "Student Record"
REVIEW_CONFIDENCE_THRESHOLD = 0.75
MISTRAL_TIMEOUT_SECONDS = 120
MISTRAL_EXTRACTION_TIMEOUT_SECONDS = 90

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

REQUIRED_REVIEW_FIELDS = {
    "department": "Department",
    "registration_no": "Registration number",
    "surname": "Surname",
    "other_names": "Other names",
    "date_of_birth": "Date of birth",
    "sex": "Sex",
    "place_of_birth": "Place of birth",
    "nationality": "Nationality",
    "father_name": "Father's name",
    "mother_name": "Mother's name",
}


@dataclass(slots=True)
class StudentRecordExtraction:
    data: dict[str, Any]
    confidence: dict[str, float]
    raw_text: str
    source: str
    error: str = ""


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


def _document_file_path(document: Document) -> Path | None:
    if document.source_path and document.source_path.is_file():
        return document.source_path
    if document.archive_path and document.archive_path.is_file():
        return document.archive_path
    return None


def _mistral_document_payload(document: Document, file_path: Path) -> dict[str, Any]:
    mime_type = document.mime_type or mimetypes.guess_type(file_path.name)[0]
    mime_type = mime_type or "application/octet-stream"
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"

    if mime_type.startswith("image/"):
        return {
            "type": "image_url",
            "image_url": data_url,
        }

    return {
        "type": "document_url",
        "document_url": data_url,
    }


def _extract_text_from_mistral_response(response: dict[str, Any]) -> str:
    parts: list[str] = []

    document_annotation = response.get("document_annotation")
    if isinstance(document_annotation, str) and document_annotation.strip():
        parts.append(document_annotation)

    for page in response.get("pages", []):
        if not isinstance(page, dict):
            continue
        markdown = page.get("markdown")
        if isinstance(markdown, str) and markdown.strip():
            parts.append(markdown)
            continue
        text = page.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)

    return "\n\n".join(parts).strip()


def _mistral_ocr(document: Document) -> tuple[str, str]:
    api_key = getattr(settings, "MISTRAL_API_KEY", "")
    if not api_key:
        return "", "MISTRAL_API_KEY is not configured."

    file_path = _document_file_path(document)
    if not file_path:
        return "", "The original document file could not be found."

    payload = {
        "model": getattr(settings, "MISTRAL_OCR_MODEL", "mistral-ocr-latest"),
        "document": _mistral_document_payload(document, file_path),
        "include_image_base64": False,
        "confidence_scores_granularity": "page",
    }

    response = requests.post(
        getattr(settings, "MISTRAL_OCR_ENDPOINT", "https://api.mistral.ai/v1/ocr"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=MISTRAL_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    text = _extract_text_from_mistral_response(response.json())
    if not text:
        return "", "Mistral OCR returned no readable text."
    return text, ""


def _student_record_json_schema_prompt() -> str:
    return """
Return only a JSON object with exactly these top-level keys:
data, confidence.

data must match this shape:
{
  "department": "CE|EE|CIE or empty string",
  "registration_no": "",
  "surname": "",
  "maiden_name": "",
  "other_names": "",
  "date_of_birth": "DD/MM/YYYY or original readable value",
  "sex": "M|F or empty string",
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
    {"level": "High School", "year": "", "school": "", "qualification": ""}
  ],
  "gce_ol": {"centre": "", "candidate_no": "", "subjects": []},
  "gce_al": {"centre": "", "candidate_no": "", "subjects": []}
}

confidence must be an object mapping field paths to numbers from 0 to 1.
Use empty strings for unreadable or absent values. Do not guess. If handwriting
is ambiguous, keep the best reading but set confidence below 0.75.
""".strip()


def _extract_text_from_chat_response(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _deep_merge_student_record_data(
    base: dict[str, Any],
    extracted: dict[str, Any],
) -> dict[str, Any]:
    data = {**base}
    for key, value in extracted.items():
        if key == "documents_enclosed" and isinstance(value, dict):
            data[key] = {**base["documents_enclosed"], **value}
        elif key in ("gce_ol", "gce_al") and isinstance(value, dict):
            data[key] = {**base[key], **value}
            if not isinstance(data[key].get("subjects"), list):
                data[key]["subjects"] = []
        elif key == "academic_records" and isinstance(value, list):
            rows = []
            for index, default_row in enumerate(base["academic_records"]):
                extracted_row = value[index] if index < len(value) else {}
                rows.append(
                    {
                        **default_row,
                        **(extracted_row if isinstance(extracted_row, dict) else {}),
                    },
                )
            data[key] = rows
        elif key in base:
            data[key] = value if value is not None else ""
    return data


def _mistral_structured_extraction(
    ocr_text: str,
) -> tuple[dict[str, Any], dict[str, float], str]:
    api_key = getattr(settings, "MISTRAL_API_KEY", "")
    if not api_key or not ocr_text.strip():
        return {}, {}, ""

    payload = {
        "model": getattr(settings, "MISTRAL_EXTRACT_MODEL", "mistral-large-latest"),
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract University of Buea Faculty of Engineering "
                    "student record forms from OCR text. Be conservative and "
                    "preserve the user's original wording where possible."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{_student_record_json_schema_prompt()}\n\n"
                    "OCR text:\n"
                    f"{ocr_text[:24000]}"
                ),
            },
        ],
    }

    response = requests.post(
        getattr(
            settings,
            "MISTRAL_CHAT_ENDPOINT",
            "https://api.mistral.ai/v1/chat/completions",
        ),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=MISTRAL_EXTRACTION_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    content = _extract_text_from_chat_response(response.json()).strip()
    if content.startswith("```"):
        content = re.sub(
            r"^```(?:json)?|```$",
            "",
            content,
            flags=re.IGNORECASE,
        ).strip()
    parsed = json.loads(content)
    return (
        parsed.get("data", {}) if isinstance(parsed.get("data"), dict) else {},
        parsed.get("confidence", {}) if isinstance(parsed.get("confidence"), dict) else {},
        "",
    )


def _extract_label_value(text: str, labels: list[str]) -> tuple[str, float]:
    for label in labels:
        match = re.search(
            rf"(?:^|\n)\s*(?:\d+\.\s*)?{label}\s*[:\-]?\s*(.+?)(?=\n\s*(?:\d+\.\s*)?[A-Za-z][A-Za-z\s'()/]+\s*[:\-]|\n\s*\d+\.|\Z)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            value = _clean(match.group(1))
            return value[:160], 0.78 if value else 0.2
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
        match = re.search(
            r"([A-Za-z][A-Za-z /&-]{2,})\s+([A-F][0-9]?|[0-9])$",
            line.strip(),
        )
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


def student_record_needs_review(
    data: dict[str, Any],
    confidence: dict[str, float],
    extraction_error: str = "",
) -> bool:
    if extraction_error:
        return True

    for field in REQUIRED_REVIEW_FIELDS:
        if not _clean(str(data.get(field, ""))):
            return True
        if confidence.get(field, 0) < REVIEW_CONFIDENCE_THRESHOLD:
            return True

    return False


def _extract_student_record_from_text(text: str) -> tuple[dict[str, Any], dict[str, float]]:
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


def extract_student_record(document: Document) -> StudentRecordExtraction:
    source = "mistral"
    error = ""
    try:
        text, error = _mistral_ocr(document)
    except requests.RequestException as exc:
        logger.warning("Mistral OCR failed for document %s: %s", document.pk, exc)
        text = ""
        error = f"Mistral OCR failed: {exc}"

    if not text:
        source = "document_content"
        text = document.content or ""
        if not error:
            error = "Falling back to the existing OCR text."

    data, confidence = _extract_student_record_from_text(text)
    if source == "mistral":
        try:
            structured_data, structured_confidence, structured_error = (
                _mistral_structured_extraction(text)
            )
        except (requests.RequestException, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "Mistral structured extraction failed for document %s: %s",
                document.pk,
                exc,
            )
            structured_data = {}
            structured_confidence = {}
            structured_error = f"Structured extraction failed: {exc}"
        else:
            structured_error = ""

        if structured_data:
            data = _deep_merge_student_record_data(data, structured_data)
            confidence = {
                **confidence,
                **{
                    field: float(score)
                    for field, score in structured_confidence.items()
                    if isinstance(score, int | float)
                },
            }
        if structured_error:
            error = structured_error

    if source != "mistral":
        confidence = {field: min(score, 0.55) for field, score in confidence.items()}

    return StudentRecordExtraction(
        data=data,
        confidence=confidence,
        raw_text=text,
        source=source,
        error=error if source != "mistral" else "",
    )


def get_or_create_student_record(document: Document) -> StudentRecord:
    record, created = StudentRecord.objects.get_or_create(document=document)
    if created or not record.data:
        extraction = extract_student_record(document)
        record.data = extraction.data
        record.confidence = extraction.confidence
        record.raw_text = extraction.raw_text
        record.extraction_source = extraction.source
        record.extraction_error = extraction.error
        record.needs_review = student_record_needs_review(
            extraction.data,
            extraction.confidence,
            extraction.error,
        )
        record.extracted_at = timezone.now()
        record.save(
            update_fields=[
                "data",
                "confidence",
                "raw_text",
                "extraction_source",
                "extraction_error",
                "needs_review",
                "extracted_at",
            ],
        )
    return record
