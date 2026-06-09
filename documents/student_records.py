from __future__ import annotations

import base64
from io import BytesIO
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
from fpdf import FPDF

from documents.models import Document
from documents.models import StudentRecord

logger = logging.getLogger(__name__)

STUDENT_RECORD_DOCUMENT_TYPE = "Student Record"
REVIEW_CONFIDENCE_THRESHOLD = 0.75
MISTRAL_TIMEOUT_SECONDS = 120
MISTRAL_EXTRACTION_TIMEOUT_SECONDS = 90
STRUCTURED_EXTRACTION_PROVIDERS = {"mistral", "groq"}

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


def _mistral_ocr(
    document: Document,
    file_path: Path | None = None,
) -> tuple[str, str]:
    api_key = getattr(settings, "MISTRAL_API_KEY", "")
    if not api_key:
        return "", "MISTRAL_API_KEY is not configured."

    file_path = file_path or _document_file_path(document)
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
  "gce_ol": {
    "centre": "",
    "candidate_no": "",
    "subjects": [{"subject": "Chemistry", "grade": "A1 or code, or empty string"}]
  },
  "gce_al": {
    "centre": "",
    "candidate_no": "",
    "subjects": [{"subject": "Further Maths", "grade": "A1 or code, or empty string"}]
  }
}

confidence must be an object mapping field paths to numbers from 0 to 1.
Use empty strings for unreadable or absent values. Do not guess. If handwriting
is ambiguous, keep the best reading but set confidence below 0.75.
For GCE O/L, Probatoire, GCE A/L, or Baccalaureat results, extract every numbered
subject line even when no grade/code is visible. Put any visible grade or code in
the subject object's "grade" field; otherwise use an empty string.
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
            exam = {**base[key]}
            for exam_key, exam_value in value.items():
                if exam_key == "subjects":
                    if isinstance(exam_value, list) and exam_value:
                        exam["subjects"] = exam_value
                elif exam_value not in (None, ""):
                    exam[exam_key] = exam_value
            if not isinstance(exam.get("subjects"), list):
                exam["subjects"] = []
            data[key] = exam
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


def _structured_extraction_config(provider: str) -> tuple[str, str, str]:
    if provider == "groq":
        return (
            getattr(settings, "GROQ_API_KEY", ""),
            getattr(
                settings,
                "GROQ_CHAT_ENDPOINT",
                "https://api.groq.com/openai/v1/chat/completions",
            ),
            getattr(settings, "GROQ_EXTRACT_MODEL", "llama-3.3-70b-versatile"),
        )

    return (
        getattr(settings, "MISTRAL_API_KEY", ""),
        getattr(
            settings,
            "MISTRAL_CHAT_ENDPOINT",
            "https://api.mistral.ai/v1/chat/completions",
        ),
        getattr(settings, "MISTRAL_EXTRACT_MODEL", "mistral-large-latest"),
    )


def _normalize_structured_extraction_provider(provider: str) -> str:
    provider = (provider or "mistral").strip().lower()
    if provider not in STRUCTURED_EXTRACTION_PROVIDERS:
        return "mistral"
    return provider


def _structured_extraction(
    provider: str,
    ocr_text: str,
) -> tuple[dict[str, Any], dict[str, float], str]:
    provider = _normalize_structured_extraction_provider(provider)
    api_key, endpoint, model = _structured_extraction_config(provider)
    if not api_key or not ocr_text.strip():
        return {}, {}, f"{provider.title()} structured extraction is not configured."

    payload = {
        "model": model,
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
        endpoint,
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


def _configured_structured_extraction_providers() -> list[str]:
    primary = _normalize_structured_extraction_provider(
        getattr(settings, "STUDENT_RECORD_EXTRACT_PROVIDER", "mistral"),
    )
    fallback = _normalize_structured_extraction_provider(
        getattr(settings, "STUDENT_RECORD_EXTRACT_FALLBACK_PROVIDER", "mistral"),
    )
    providers = [primary]
    if fallback != primary:
        providers.append(fallback)
    return providers


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


def _exam_chunk(text: str, marker: str, stop_marker: str | None = None) -> str:
    marker_match = re.search(marker, text, re.IGNORECASE)
    if not marker_match:
        return ""
    chunk = text[marker_match.end() : marker_match.end() + 1500]
    if stop_marker:
        stop_match = re.search(stop_marker, chunk, re.IGNORECASE)
        if stop_match:
            chunk = chunk[: stop_match.start()]
    return chunk


def _extract_exam_meta(chunk: str, label: str) -> tuple[str, float]:
    match = re.search(
        rf"{label}\s*(?:no\.?|number)?\s*[:.\-]?\s*([A-Za-z0-9 /.-]{{2,40}})",
        chunk,
        flags=re.IGNORECASE,
    )
    if not match:
        return "", 0.0
    value = _clean(match.group(1))
    value = re.split(r"\s{2,}|\||\n", value, maxsplit=1)[0]
    return value[:40], 0.62 if value else 0.0


def _looks_like_subject(value: str) -> bool:
    if not value:
        return False
    if len(value) < 3 or len(value) > 80:
        return False
    if re.search(
        r"centre|candidate|subject|results?|gce|probatoire|baccalaureat|written",
        value,
        re.IGNORECASE,
    ):
        return False
    return bool(re.search(r"[A-Za-z]", value))


def _subject_from_line(line: str) -> dict[str, str] | None:
    line = _clean(line)
    if not line:
        return None
    line = line.strip("|")
    line = re.sub(r"^\|?\s*\d{1,2}\s*[.)|\-:]?\s*", "", line)
    line = re.sub(r"\s*\|\s*", " ", line).strip()
    if not line:
        return None

    match = re.match(
        r"(?P<subject>[A-Za-z][A-Za-z0-9 /&'().-]{2,}?)"
        r"(?:\s{2,}|\s+-\s+|\s+)"
        r"(?P<grade>[A-F][0-9]?|[0-9]{1,3}|[A-Z]{2,}[0-9A-Z.-]{0,8})$",
        line,
    )
    if match:
        subject = _clean(match.group("subject"))
        grade = _clean(match.group("grade")).upper()
        if _looks_like_subject(subject):
            return {"subject": subject[:60], "grade": grade[:12]}

    if _looks_like_subject(line):
        return {"subject": line[:60], "grade": ""}
    return None


def _extract_subjects_from_chunk(chunk: str, limit: int) -> list[dict[str, str]]:
    subjects = []
    for line in chunk.splitlines():
        if not re.match(r"^\s*\|?\s*\d{1,2}\s*[.)|\-:]?", line):
            continue
        subject = _subject_from_line(line)
        if subject:
            subjects.append(subject)
        if len(subjects) >= limit:
            break
    return subjects


def _extract_exam(
    text: str,
    marker: str,
    stop_marker: str | None,
    limit: int,
) -> tuple[dict[str, Any], dict[str, float]]:
    chunk = _exam_chunk(text, marker, stop_marker)
    exam = {"centre": "", "candidate_no": "", "subjects": []}
    confidence: dict[str, float] = {}
    if not chunk:
        return exam, confidence

    centre, centre_confidence = _extract_exam_meta(chunk, "centre")
    candidate_no, candidate_confidence = _extract_exam_meta(chunk, "candidate")
    subjects = _extract_subjects_from_chunk(chunk, limit)

    exam["centre"] = centre
    exam["candidate_no"] = candidate_no
    exam["subjects"] = subjects
    confidence["centre"] = centre_confidence
    confidence["candidate_no"] = candidate_confidence
    confidence["subjects"] = 0.62 if subjects else 0.0
    return exam, confidence


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


def _pdf_text(value: Any) -> str:
    text = str(value or "")
    return text.encode("latin-1", "replace").decode("latin-1")


def _pdf_field(pdf: FPDF, label: str, value: Any, width: int = 92) -> None:
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(34, 6, _pdf_text(label), border=1)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(width, 6, _pdf_text(value), border=1)


def export_student_record_pdf(record: StudentRecord) -> bytes:
    data = {**blank_student_record_data(), **(record.data or {})}
    data["documents_enclosed"] = {
        **blank_student_record_data()["documents_enclosed"],
        **(data.get("documents_enclosed") or {}),
    }

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_margins(10, 10, 10)

    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 7, "University of Buea", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(
        0,
        6,
        "Faculty of Engineering and Technology",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 7, "Student's Record", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(
        0,
        5,
        "(STRICTLY CONFIDENTIAL)",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 7, "I. Personal Information", border=1, fill=False, new_x="LMARGIN", new_y="NEXT")
    rows = [
        ("Department", data.get("department")),
        ("Registration No", data.get("registration_no")),
        ("Surname", data.get("surname")),
        ("Maiden Name", data.get("maiden_name")),
        ("Other Names", data.get("other_names")),
        ("Date of Birth", data.get("date_of_birth")),
        ("Sex", data.get("sex")),
        ("Place of Birth", data.get("place_of_birth")),
        ("Division of Origin", data.get("division_of_origin")),
        ("Region of Origin", data.get("region_of_origin")),
        ("Nationality", data.get("nationality")),
        ("Marital Status", data.get("marital_status")),
        ("Handicap", data.get("handicap")),
        ("Religion", data.get("religious_denomination")),
        ("Father's Name", data.get("father_name")),
        ("Mother's Name", data.get("mother_name")),
        ("Parent Occupation", data.get("parent_occupation")),
    ]
    for index in range(0, len(rows), 2):
        _pdf_field(pdf, rows[index][0], rows[index][1])
        if index + 1 < len(rows):
            _pdf_field(pdf, rows[index + 1][0], rows[index + 1][1], width=30)
        pdf.ln()

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 7, "Documents Enclosed", border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    for index, (name, checked) in enumerate(data["documents_enclosed"].items()):
        mark = "Yes" if checked else "No"
        pdf.cell(95, 6, _pdf_text(f"{name}: {mark}"), border=1)
        if index % 2 == 1:
            pdf.ln()
    if len(data["documents_enclosed"]) % 2 == 1:
        pdf.ln()

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 7, "Addresses", border=1, new_x="LMARGIN", new_y="NEXT")
    for label, value in [
        ("Parent/Guardian Name and Address", data.get("parent_name_address")),
        ("Parent Post Box", data.get("parent_post_box")),
        ("Parent Town", data.get("parent_town")),
        ("Parent Country", data.get("parent_country")),
        ("Parent Tel", data.get("parent_tel")),
        ("Student Mailing Address", data.get("student_address")),
        ("Student Post Box", data.get("student_post_box")),
        ("Student Town", data.get("student_town")),
        ("Student Country", data.get("student_country")),
        ("Student Tel", data.get("student_tel")),
    ]:
        _pdf_field(pdf, label, value, width=155)
        pdf.ln()

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 7, "II. Academic Records", border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(35, 6, "Level", border=1)
    pdf.cell(35, 6, "Year", border=1)
    pdf.cell(75, 6, "School", border=1)
    pdf.cell(45, 6, "Qualification", border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    for row in data.get("academic_records", []):
        pdf.cell(35, 6, _pdf_text(row.get("level")), border=1)
        pdf.cell(35, 6, _pdf_text(row.get("year")), border=1)
        pdf.cell(75, 6, _pdf_text(row.get("school")), border=1)
        pdf.cell(45, 6, _pdf_text(row.get("qualification")), border=1, new_x="LMARGIN", new_y="NEXT")

    for title, exam in [
        ("GCE O/L or Probatoire", data.get("gce_ol", {})),
        ("GCE A/L or Baccalaureat", data.get("gce_al", {})),
    ]:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 7, title, border=1, new_x="LMARGIN", new_y="NEXT")
        _pdf_field(pdf, "Centre", exam.get("centre"), width=60)
        _pdf_field(pdf, "Candidate No", exam.get("candidate_no"), width=28)
        pdf.ln()
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(145, 6, "Subject", border=1)
        pdf.cell(45, 6, "Grade / Code", border=1, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        for subject in exam.get("subjects", []):
            pdf.cell(145, 6, _pdf_text(subject.get("subject")), border=1)
            pdf.cell(45, 6, _pdf_text(subject.get("grade")), border=1, new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output(dest="S"))


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

    gce_ol, gce_ol_confidence = _extract_exam(
        text,
        r"GCE\s+O/?L|Ordinary\s+Level|Probatoire",
        r"GCE\s+A/?L|Advanced\s+Level|Baccalaureat|II\.\s+Academic",
        10,
    )
    gce_al, gce_al_confidence = _extract_exam(
        text,
        r"GCE\s+A/?L|Advanced\s+Level|Baccalaureat",
        None,
        5,
    )
    data["gce_ol"] = gce_ol
    data["gce_al"] = gce_al
    confidence["gce_ol.centre"] = gce_ol_confidence.get("centre", 0.0)
    confidence["gce_ol.candidate_no"] = gce_ol_confidence.get("candidate_no", 0.0)
    confidence["gce_ol.subjects"] = gce_ol_confidence.get("subjects", 0.0)
    confidence["gce_al.centre"] = gce_al_confidence.get("centre", 0.0)
    confidence["gce_al.candidate_no"] = gce_al_confidence.get("candidate_no", 0.0)
    confidence["gce_al.subjects"] = gce_al_confidence.get("subjects", 0.0)

    return data, confidence


def extract_student_record(
    document: Document,
    file_path: Path | None = None,
) -> StudentRecordExtraction:
    source = "mistral"
    error = ""
    try:
        text, error = _mistral_ocr(document, file_path=file_path)
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
        structured_data: dict[str, Any] = {}
        structured_confidence: dict[str, float] = {}
        structured_error = ""
        structured_provider = ""

        for provider in _configured_structured_extraction_providers():
            try:
                structured_data, structured_confidence, structured_error = (
                    _structured_extraction(provider, text)
                )
            except (
                requests.RequestException,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as exc:
                logger.warning(
                    "%s structured extraction failed for document %s: %s",
                    provider.title(),
                    document.pk,
                    exc,
                )
                structured_data = {}
                structured_confidence = {}
                structured_error = f"{provider.title()} structured extraction failed: {exc}"
            if structured_data:
                structured_provider = provider
                break

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
            if structured_provider == "groq":
                source = "mistral_ocr_groq_extract"
        if structured_error:
            error = structured_error

    if source == "document_content":
        confidence = {field: min(score, 0.55) for field, score in confidence.items()}

    return StudentRecordExtraction(
        data=data,
        confidence=confidence,
        raw_text=text,
        source=source,
        error=error,
    )


def get_or_create_student_record(
    document: Document,
    file_path: Path | None = None,
) -> StudentRecord:
    student = document.owner if hasattr(document.owner, "student_profile") else None
    record, created = StudentRecord.objects.get_or_create(
        document=document,
        defaults={"student": student},
    )
    if record.student_id is None and student is not None:
        record.student = student
        record.save(update_fields=["student"])

    should_extract = created or not record.data
    if file_path is not None and (
        record.extraction_source == "document_content" or record.extraction_error
    ):
        should_extract = True

    if should_extract:
        extraction = extract_student_record(document, file_path=file_path)
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
