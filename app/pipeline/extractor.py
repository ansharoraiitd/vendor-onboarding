"""
app/pipeline/extractor.py — Real LLM and digital PDF extractor with Gemini API integration,
anti-hallucination snippet verification against digital text layers, deterministic regex
cross-checking, persistent SHA-256 disk cache, document type classification, and strict fail-closed behavior.

NO ECHO FALLBACK: If a file is missing or unreadable, this module returns an extraction error
with low/empty confidences. It NEVER synthesizes extracted fields from user submission inputs.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

import httpx
import pypdf

logger = logging.getLogger(__name__)

# Directory for persistent SHA-256 disk cache (configurable via env var)
_CACHE_PATH_ENV = os.getenv("EXTRACTION_CACHE_DIR")
if _CACHE_PATH_ENV:
    DISK_CACHE_DIR = Path(_CACHE_PATH_ENV)
else:
    _data_dir = os.getenv("DATA_DIR", "data")
    DISK_CACHE_DIR = Path(_data_dir) / "extraction_cache" if _data_dir != "data" else Path("data/extraction_cache")
DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)

PROMPT_SCHEMA_VERSION = "v1.0"

# Circuit breaker state for Gemini API
_CIRCUIT_BREAKER_TRIPPED: bool = False
_CIRCUIT_BREAKER_REASON: str = ""


def get_extractor_mode() -> str:
    """Return 'offline' or 'auto'."""
    return os.getenv("EXTRACTOR_MODE", "auto").strip().lower()


def is_ai_extraction_enabled() -> bool:
    """Return True if Gemini extraction is active and not disabled by mode or circuit breaker."""
    if get_extractor_mode() == "offline":
        return False
    if _CIRCUIT_BREAKER_TRIPPED:
        return False
    return bool(os.getenv("GEMINI_API_KEY"))


def trip_circuit_breaker(code: int, reason: str = "") -> None:
    """Trip the circuit breaker, disabling Gemini calls for the remainder of the process."""
    global _CIRCUIT_BREAKER_TRIPPED, _CIRCUIT_BREAKER_REASON
    if not _CIRCUIT_BREAKER_TRIPPED:
        _CIRCUIT_BREAKER_TRIPPED = True
        _CIRCUIT_BREAKER_REASON = f"HTTP {code} ({reason or 'Auth/Billing error'})"
        logger.error(
            "Gemini circuit breaker tripped: HTTP %s (%s). Disabling AI calls for the remainder of the process.",
            code,
            reason or "Auth/Billing error",
        )


def reset_circuit_breaker() -> None:
    """Reset circuit breaker (for tests)."""
    global _CIRCUIT_BREAKER_TRIPPED, _CIRCUIT_BREAKER_REASON
    _CIRCUIT_BREAKER_TRIPPED = False
    _CIRCUIT_BREAKER_REASON = ""


def is_circuit_breaker_tripped() -> Tuple[bool, str]:
    """Returns (tripped: bool, reason: str)."""
    return _CIRCUIT_BREAKER_TRIPPED, _CIRCUIT_BREAKER_REASON


def _clean_for_comparison(s: str) -> str:
    """Normalize whitespace, case, and punctuation for robust anti-hallucination snippet comparison."""
    if not s:
        return ""
    import string
    # Remove punctuation, lowercase, collapse whitespace
    s_clean = s.lower().translate(str.maketrans("", "", string.punctuation))
    return " ".join(s_clean.split())


def compute_cache_key(file_sha: str, doc_type: str, version: str = PROMPT_SCHEMA_VERSION) -> str:
    """Cache key = sha256 + doc_type + prompt/schema version."""
    raw = f"{file_sha}:{doc_type}:{version}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass
class ExtractionResult:
    """Fields extracted from a single document."""
    doc_type: str
    doc_type_detected: str = "unknown_document"
    fields: dict[str, Any] = field(default_factory=dict)
    # Per-field confidences: field_name -> float (0.0 to 1.0)
    confidences: dict[str, float] = field(default_factory=dict)
    # Verbatim snippets from document: field_name -> snippet string
    snippets: dict[str, str] = field(default_factory=dict)
    # Raw text extracted from digital layer
    raw_text: str = ""
    error: Optional[str] = None
    cached: bool = False
    timed_out: bool = False
    extractor_type: str = "gemini_extractor"  # "gemini_extractor" | "text_layer_regex" | "disk_cache" | "stub_test"

    def confidence(self, field_name: str, default: float = 0.95) -> float:
        return self.confidences.get(field_name, default)


class LLMProvider(Protocol):
    """Protocol for pluggable extraction providers."""
    def extract(
        self,
        doc_path: str,
        doc_type: str,
        submission_fields: dict[str, Any],
        timeout_seconds: float = 5.0,
    ) -> ExtractionResult:
        ...


def parse_pdf_date_str(pdf_date: Optional[str]) -> Optional[str]:
    """Convert PDF date format (D:YYYYMMDDHHMMSS...) to ISO-8601 string."""
    if not pdf_date:
        return None
    s = str(pdf_date).strip()
    if s.startswith("D:"):
        s = s[2:]
    if len(s) >= 8 and s[:8].isdigit():
        yyyy, mm, dd = s[:4], s[4:6], s[6:8]
        hh = s[8:10] if len(s) >= 10 and s[8:10].isdigit() else "00"
        mi = s[10:12] if len(s) >= 12 and s[10:12].isdigit() else "00"
        ss = s[12:14] if len(s) >= 14 and s[12:14].isdigit() else "00"
        return f"{yyyy}-{mm}-{dd}T{hh}:{mi}:{ss}Z"
    return None


def classify_document_type(text: str, filename: str = "") -> str:
    """
    Classify document type based on text content and keywords.
    Returns: 'pan_card' | 'gst_certificate' | 'cancelled_cheque' | 'coi' |
             'llpin_cert' | 'address_proof' | 'udyam_cert' | 'unknown_document'
    """
    t = text.lower()

    # 1. Cancelled Cheque / Bank Letter
    if ("pay to" in t or "beneficiary" in t or "cancelled" in t or "cheque" in t or "ifs code" in t or "account number" in t) and ("bank" in t or "branch" in t or "cheque" in t):
        if not ("goods and services" in t or "income tax department" in t or "incorporation" in t):
            return "cancelled_cheque"

    # 2. PAN Card
    if "income tax department" in t or "permanent account number" in t or "father's name" in t or "govt. of india" in t and "pan" in t:
        if "gstin" not in t:
            return "pan_card"

    # 3. GST Certificate
    if "goods and services tax" in t or "form gst reg" in t or "gstin" in t or "date of liability" in t:
        return "gst_certificate"

    # 4. Certificate of Incorporation (COI)
    if "certificate of incorporation" in t or "corporate affairs" in t or ("consequent upon conversion" in t and "cin" in t):
        return "coi"

    # 5. LLPIN Registration Certificate
    if "limited liability partnership" in t or "llpin" in t or "llp registration" in t:
        return "llpin_cert"

    # 6. Udyam MSME Registration Certificate
    if "udyam" in t or "ministry of micro" in t or "msme" in t or "enterprise type" in t:
        return "udyam_cert"

    # 7. Proof of Address / Utility Bill
    if "electricity" in t or "consumer no" in t or "proof of address" in t or "power distribution" in t or "utility bill" in t:
        return "address_proof"

    return "unknown_document"


# ---------------------------------------------------------------------------
# StubLLMProvider — STRICTLY FOR ISOLATED UNIT TESTS ONLY
# ---------------------------------------------------------------------------
class StubLLMProvider:
    """
    STUB PROVIDER (UNIT TESTS ONLY).
    Used explicitly in unit tests that specifically pass provider=StubLLMProvider().
    Never used in application runtime.
    """

    def extract(
        self,
        doc_path: str,
        doc_type: str,
        submission_fields: dict[str, Any],
        timeout_seconds: float = 5.0,
    ) -> ExtractionResult:
        pan = submission_fields.get("pan", "AABCU9603R")
        gstin = submission_fields.get("gstin", "27AABCU9603R1ZP")
        cin = submission_fields.get("cin", "U65110MH2000GOI018559")
        legal_name = submission_fields.get("legal_name", "Acme Manufacturing Pvt Ltd")
        ifsc = submission_fields.get("ifsc", "SBIN0000300")
        account_last4 = submission_fields.get("bank_account_number_last4", "1234")
        state_code = submission_fields.get("address_state_code", "27")
        address_line = submission_fields.get("address_line", "123 Industrial Estate, Mumbai")

        if doc_type == "pan_card":
            raw = f"INCOME TAX DEPARTMENT\nPAN: {pan}\nName: {legal_name}\nDate: 2022-01-01"
            return ExtractionResult(
                doc_type=doc_type,
                doc_type_detected="pan_card",
                fields={"pan_number": pan, "name_on_pan": legal_name, "_claimed_issue_date": "2022-01-01"},
                confidences={"pan_number": 0.98, "name_on_pan": 0.95, "_claimed_issue_date": 0.92},
                snippets={"pan_number": f"PAN: {pan}", "name_on_pan": f"Name: {legal_name}"},
                raw_text=raw,
                extractor_type="stub_test",
            )

        if doc_type == "gst_certificate":
            raw = (
                f"GOODS AND SERVICES TAX REGISTRATION CERTIFICATE\n"
                f"GSTIN: {gstin}\nLegal Name: {legal_name}\n"
                f"Trade Name: {legal_name}\nState Code: {state_code}\n"
                f"Principal Place: {address_line}\nDate of Liability: 2022-04-01"
            )
            return ExtractionResult(
                doc_type=doc_type,
                doc_type_detected="gst_certificate",
                fields={
                    "gstin_on_cert": gstin,
                    "legal_name_on_cert": legal_name,
                    "trade_name_on_cert": legal_name,
                    "principal_place_state_code": state_code,
                    "address_on_cert": address_line,
                    "_claimed_issue_date": "2022-04-01",
                },
                confidences={
                    "gstin_on_cert": 0.98,
                    "legal_name_on_cert": 0.96,
                    "trade_name_on_cert": 0.95,
                    "principal_place_state_code": 0.95,
                    "address_on_cert": 0.90,
                    "_claimed_issue_date": 0.92,
                },
                snippets={"gstin_on_cert": f"GSTIN: {gstin}", "legal_name_on_cert": f"Legal Name: {legal_name}"},
                raw_text=raw,
                extractor_type="stub_test",
            )

        if doc_type in ("cancelled_cheque", "bank_letter"):
            raw = (
                f"CANCELLED CHEQUE\n"
                f"Pay to: {legal_name}\nIFSC: {ifsc}\n"
                f"Account Number: XXXX XXXX {account_last4}"
            )
            return ExtractionResult(
                doc_type=doc_type,
                doc_type_detected="cancelled_cheque",
                fields={
                    "account_holder_name": legal_name,
                    "ifsc_on_cheque": ifsc,
                    "account_last4_on_cheque": account_last4,
                },
                confidences={
                    "account_holder_name": 0.96,
                    "ifsc_on_cheque": 0.98,
                    "account_last4_on_cheque": 0.92,
                },
                snippets={"account_holder_name": f"Pay to: {legal_name}", "ifsc_on_cheque": f"IFSC: {ifsc}"},
                raw_text=raw,
                extractor_type="stub_test",
            )

        if doc_type == "coi":
            raw = (
                f"CERTIFICATE OF INCORPORATION\n"
                f"CIN: {cin}\nCompany Name: {legal_name}\n"
                f"Date of Incorporation: 2010-06-15"
            )
            return ExtractionResult(
                doc_type=doc_type,
                doc_type_detected="coi",
                fields={
                    "cin_on_coi": cin,
                    "company_name_on_coi": legal_name,
                    "incorporation_date": "2010-06-15",
                    "_claimed_issue_date": "2010-06-15",
                },
                confidences={
                    "cin_on_coi": 0.97,
                    "company_name_on_coi": 0.95,
                    "incorporation_date": 0.90,
                    "_claimed_issue_date": 0.90,
                },
                snippets={"cin_on_coi": f"CIN: {cin}", "company_name_on_coi": f"Company Name: {legal_name}"},
                raw_text=raw,
                extractor_type="stub_test",
            )

        if doc_type == "udyam_cert":
            return ExtractionResult(
                doc_type=doc_type,
                doc_type_detected="udyam_cert",
                fields={
                    "udyam_number": submission_fields.get("udyam_number", "UDYAM-MH-00-0012345"),
                    "udyam_category": submission_fields.get("udyam_category", "small"),
                    "udyam_activity_type": submission_fields.get("udyam_activity_type", "manufacturing"),
                },
                confidences={"udyam_number": 0.98, "udyam_category": 0.95, "udyam_activity_type": 0.93},
                snippets={"udyam_number": "UDYAM-MH-00-0012345"},
                raw_text="UDYAM CERTIFICATE",
                extractor_type="stub_test",
            )

        return ExtractionResult(
            doc_type=doc_type,
            doc_type_detected="unknown_document",
            fields={},
            confidences={},
            snippets={},
            raw_text="",
            extractor_type="stub_test",
        )


# ---------------------------------------------------------------------------
# Deterministic Text Layer & Regex Extraction
# ---------------------------------------------------------------------------
def _extract_from_text_layer(
    text: str,
    doc_type: str,
) -> Tuple[str, Dict[str, Any], Dict[str, float], Dict[str, str], Optional[str]]:
    """
    Parse digital text layer deterministically with regex.
    Handles varied layout patterns like "Beneficiary Name", "Pay to", "A/c Holder".
    Returns: (detected_type, fields, confidences, snippets, claimed_date)
    """
    fields: dict[str, Any] = {}
    confs: dict[str, float] = {}
    snippets: dict[str, str] = {}
    claimed_date: Optional[str] = None

    detected_type = classify_document_type(text)

    # Generic date finder
    date_m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b|\b(\d{2}/\d{2}/\d{4})\b", text)
    if date_m:
        raw_d = date_m.group(1) or date_m.group(2)
        if "/" in raw_d:
            parts = raw_d.split("/")
            claimed_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            claimed_date = raw_d

    if doc_type == "pan_card" or detected_type == "pan_card":
        pan_m = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text)
        if pan_m:
            fields["pan_number"] = pan_m.group(1)
            confs["pan_number"] = 0.99
            snippets["pan_number"] = pan_m.group(0)

        name_m = re.search(
            r"(?:Name\s+on\s+Card|Name\s+as\s+per\s+PAN|Name\s+of\s+Cardholder|Cardholder\s+Name|Name)\s*:\s*([^\n\r]+)",
            text,
            re.IGNORECASE,
        )
        if not name_m:
            name_m = re.search(r"(?:Cardholder\s+Name|Name)\s+([^\n\r]+)", text, re.IGNORECASE)
        if name_m:
            n = name_m.group(1).strip()
            fields["name_on_pan"] = n
            confs["name_on_pan"] = 0.96
            snippets["name_on_pan"] = name_m.group(0).strip()

    if doc_type == "gst_certificate" or detected_type == "gst_certificate":
        gstin_m = re.search(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[A-Z0-9])\b", text)
        if gstin_m:
            fields["gstin_on_cert"] = gstin_m.group(1)
            confs["gstin_on_cert"] = 0.99
            snippets["gstin_on_cert"] = gstin_m.group(0)

        legal_m = re.search(r"Legal Name(?: of Business)?[:\s]+([^\n\r]+)", text, re.IGNORECASE)
        if legal_m:
            l = legal_m.group(1).strip()
            fields["legal_name_on_cert"] = l
            confs["legal_name_on_cert"] = 0.97
            snippets["legal_name_on_cert"] = legal_m.group(0).strip()

        trade_m = re.search(r"Trade Name(?:, if any)?[:\s]+([^\n\r]+)", text, re.IGNORECASE)
        if trade_m:
            t = trade_m.group(1).strip()
            fields["trade_name_on_cert"] = t
            confs["trade_name_on_cert"] = 0.95
            snippets["trade_name_on_cert"] = trade_m.group(0).strip()

        state_m = re.search(
            r"(?:Principal\s+Place\s+of\s+Business\s+State|State\s+Code|State)\s*:\s*(\d{2})\b",
            text,
            re.IGNORECASE,
        )
        if not state_m:
            state_m = re.search(r"(?:State\s+Code|State)[:\s]+(\d{2})\b", text, re.IGNORECASE)
        if state_m:
            sc = state_m.group(1).strip()
            fields["principal_place_state_code"] = sc
            confs["principal_place_state_code"] = 0.98
            snippets["principal_place_state_code"] = state_m.group(0).strip()

        addr_m = re.search(r"Principal Place of Business[:\s]+([^\n\r]+)", text, re.IGNORECASE)
        if addr_m:
            fields["address_on_cert"] = addr_m.group(1).strip()
            confs["address_on_cert"] = 0.92
            snippets["address_on_cert"] = addr_m.group(0).strip()

    if doc_type in ("cancelled_cheque", "bank_letter") or detected_type == "cancelled_cheque":
        # Supports varied layout naming: "Pay to", "Beneficiary Name", "A/c Holder Name", "Account Holder"
        holder_m = re.search(
            r"(?:Pay\s+to|Beneficiary(?:\s+Name)?|Account\s+Holder(?:\s+Name)?|A/c\s+Holder(?:\s+Name)?|In\s+the\s+name\s+of)[:\s]+([^\n\r]+)",
            text,
            re.IGNORECASE,
        )
        if holder_m:
            h = holder_m.group(1).strip()
            fields["account_holder_name"] = h
            confs["account_holder_name"] = 0.96
            snippets["account_holder_name"] = holder_m.group(0).strip()

        ifsc_m = re.search(r"\b([A-Z]{4}0[A-Z0-9]{6})\b", text)
        if ifsc_m:
            fields["ifsc_on_cheque"] = ifsc_m.group(1)
            confs["ifsc_on_cheque"] = 0.99
            snippets["ifsc_on_cheque"] = ifsc_m.group(0)

        acct_m = re.search(r"(?:Account(?:\s+Number|\s+No)?|A/c(?:\s+No|\s+Number)?)[:\s]+(?:[X\*\s]+)?(\d{4,18})\b", text, re.IGNORECASE)
        if acct_m:
            full_or_last = acct_m.group(1)
            fields["account_last4_on_cheque"] = full_or_last[-4:]
            confs["account_last4_on_cheque"] = 0.95
            snippets["account_last4_on_cheque"] = acct_m.group(0).strip()

    if doc_type == "coi" or detected_type == "coi":
        cin_m = re.search(r"\b([UL]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})\b", text)
        if cin_m:
            fields["cin_on_coi"] = cin_m.group(1)
            confs["cin_on_coi"] = 0.99
            snippets["cin_on_coi"] = cin_m.group(0)

        comp_m = re.search(r"(?:certify that|Company Name)[:\s]+([^\n\r]+)", text, re.IGNORECASE)
        if comp_m:
            fields["company_name_on_coi"] = comp_m.group(1).strip()
            confs["company_name_on_coi"] = 0.95
            snippets["company_name_on_coi"] = comp_m.group(0).strip()

        date_incorp_m = re.search(r"Date of Incorporation[:\s]+(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
        if date_incorp_m:
            fields["incorporation_date"] = date_incorp_m.group(1).strip()
            confs["incorporation_date"] = 0.95
            snippets["incorporation_date"] = date_incorp_m.group(0).strip()

    if doc_type == "llpin_cert" or detected_type == "llpin_cert":
        llpin_m = re.search(r"\b([A-Z]{3}-\d{4}|\d{7})\b", text)
        if llpin_m:
            fields["llpin_on_cert"] = llpin_m.group(1)
            confs["llpin_on_cert"] = 0.98
            snippets["llpin_on_cert"] = llpin_m.group(0)

        name_llp_m = re.search(r"LLP Name[:\s]+([^\n\r]+)", text, re.IGNORECASE)
        if name_llp_m:
            fields["llp_name_on_cert"] = name_llp_m.group(1).strip()
            confs["llp_name_on_cert"] = 0.95
            snippets["llp_name_on_cert"] = name_llp_m.group(0).strip()

    if doc_type == "udyam_cert" or detected_type == "udyam_cert":
        udyam_m = re.search(r"\b(UDYAM-[A-Z]{2}-\d{2}-\d{7})\b", text)
        if udyam_m:
            fields["udyam_number"] = udyam_m.group(1)
            confs["udyam_number"] = 0.99
            snippets["udyam_number"] = udyam_m.group(0)

        cat_m = re.search(r"\b(micro|small|medium)\b", text, re.IGNORECASE)
        if cat_m:
            fields["udyam_category"] = cat_m.group(1).lower()
            confs["udyam_category"] = 0.96
            snippets["udyam_category"] = cat_m.group(0)

        act_m = re.search(r"\b(manufacturing|services|trading)\b", text, re.IGNORECASE)
        if act_m:
            fields["udyam_activity_type"] = act_m.group(1).lower()
            confs["udyam_activity_type"] = 0.95
            snippets["udyam_activity_type"] = act_m.group(0)

    if doc_type == "address_proof" or detected_type == "address_proof":
        state_m = re.search(r"State Code[:\s]+(\d{2})", text, re.IGNORECASE)
        if state_m:
            fields["address_state_code"] = state_m.group(1).strip()
            confs["address_state_code"] = 0.96
            snippets["address_state_code"] = state_m.group(0)

    return detected_type, fields, confs, snippets, claimed_date


# ---------------------------------------------------------------------------
# Real Gemini API Extractor with Swappability & Disk Cache
# ---------------------------------------------------------------------------
class GeminiExtractor:
    """
    Production-grade LLM Extractor using Google Gemini API.
    1. Checks SHA-256 persistent disk cache first (instant offline/demo execution).
    2. Reads PDF digital text layer & metadata via pypdf.
    3. If GEMINI_API_KEY is available:
       - Sends document to Gemini Vision API with per-doc-type structured JSON schema.
       - Solves layout variations (e.g. 'Beneficiary Name', 'A/c Holder').
       - Performs anti-hallucination verification: ensures snippets exist in digital text layer.
       - Cross-checks with deterministic regex parser; disagreement -> low confidence.
       - Caches verified output to data/extraction_cache/{sha256}.json.
    4. If GEMINI_API_KEY is not available:
       - Parses digital text layer with deterministic parser.
       - If image-only (scanned with NO text layer and NO cache):
         FAILS CLOSED: returns extraction error and low confidence. NEVER synthesizes stub data.
    """

    def __init__(self, api_key: Optional[str] = None):
        if not api_key and not os.environ.get("GEMINI_API_KEY"):
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def extract(
        self,
        doc_path: str,
        doc_type: str,
        submission_fields: dict[str, Any],
        timeout_seconds: float = 8.0,
    ) -> ExtractionResult:
        if not doc_path or not os.path.exists(doc_path):
            return ExtractionResult(
                doc_type=doc_type,
                doc_type_detected="missing_file",
                fields={},
                confidences={},
                raw_text="",
                error=f"Document file missing from disk: {doc_path}",
                extractor_type="missing_file_error",
            )

        file_sha = compute_file_sha256(doc_path)
        cache_key = compute_cache_key(file_sha, doc_type)
        cache_file = DISK_CACHE_DIR / f"{cache_key}.json"
        legacy_cache_file = DISK_CACHE_DIR / f"{file_sha}.json"

        # 1. Check persistent disk cache first (supports versioned key and legacy sha256)
        target_cache = cache_file if cache_file.exists() else (legacy_cache_file if legacy_cache_file.exists() else None)
        if target_cache and target_cache.exists():
            try:
                with open(target_cache, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return ExtractionResult(
                    doc_type=doc_type,
                    doc_type_detected=data.get("doc_type_detected", doc_type),
                    fields=data.get("fields", {}),
                    confidences=data.get("confidences", {}),
                    snippets=data.get("snippets", {}),
                    raw_text=data.get("raw_text", ""),
                    cached=True,
                    extractor_type="disk_cache",
                )
            except Exception:
                pass  # Corrupt cache; fall through

        # 2. Read PDF text layer and metadata via pypdf (if PDF)
        raw_text = ""
        producer = ""
        creation_date = ""
        mod_date = ""

        is_raster_image = doc_path.lower().endswith((".png", ".jpg", ".jpeg"))
        if not is_raster_image:
            try:
                reader = pypdf.PdfReader(doc_path)
                meta = reader.metadata or {}
                producer = str(meta.get("/Producer") or meta.get("Producer") or "")
                creation_date = parse_pdf_date_str(meta.get("/CreationDate") or meta.get("CreationDate")) or ""
                mod_date = parse_pdf_date_str(meta.get("/ModDate") or meta.get("ModDate")) or ""
                for page in reader.pages:
                    raw_text += (page.extract_text() or "") + "\n"
            except Exception as exc:
                return ExtractionResult(
                    doc_type=doc_type,
                    doc_type_detected="corrupt_pdf",
                    error=f"PDF parsing error: {exc}",
                    confidences={"all": 0.20},
                    extractor_type="corrupt_pdf_error",
                )

        text_clean = raw_text.strip()
        metadata_fields = {}
        if producer:
            metadata_fields["_pdf_producer"] = producer
        if creation_date:
            metadata_fields["_pdf_creation_date"] = creation_date
        if mod_date:
            metadata_fields["_pdf_mod_date"] = mod_date

        # 3. Call Gemini API if enabled, API key is available, and circuit breaker has not tripped
        should_call_gemini = (
            get_extractor_mode() != "offline"
            and not _CIRCUIT_BREAKER_TRIPPED
            and bool(self.api_key)
        )

        if should_call_gemini:
            gemini_res = self._call_gemini_api(doc_path, doc_type, timeout_seconds)
            if gemini_res.error:
                logger.warning("Gemini API call failed: %s", gemini_res.error)
                # If digital text layer exists, extract via text_layer_regex while recording API failure.
                # Per spec: NEVER write a regex-fallback result to cache when Gemini failed.
                if len(text_clean) > 20:
                    detected_type, parsed_fields, parsed_confs, parsed_snips, claimed_d = _extract_from_text_layer(
                        text_clean, doc_type
                    )
                    parsed_fields.update(metadata_fields)
                    if claimed_d:
                        parsed_fields["_claimed_issue_date"] = claimed_d
                    return ExtractionResult(
                        doc_type=doc_type,
                        doc_type_detected=detected_type,
                        fields=parsed_fields,
                        confidences=parsed_confs,
                        snippets=parsed_snips,
                        raw_text=text_clean,
                        error=gemini_res.error,
                        extractor_type="text_layer_regex",
                    )

                # Surface API failure directly when no readable text layer
                gemini_res.fields.update(metadata_fields)
                return gemini_res

            # Anti-hallucination check against digital text layer with whitespace/case/punctuation normalization
            if len(text_clean) > 20:
                normalized_text_layer = _clean_for_comparison(text_clean)
                for fld, snip in gemini_res.snippets.items():
                    if snip:
                        norm_snip = _clean_for_comparison(snip)
                        if norm_snip and norm_snip not in normalized_text_layer:
                            # Snippet not found in digital text layer -> penalize confidence
                            gemini_res.confidences[fld] = min(gemini_res.confidences.get(fld, 1.0), 0.35)

                # Regex cross-check
                _, rx_fields, _, _, _ = _extract_from_text_layer(text_clean, doc_type)
                for rk, rv in rx_fields.items():
                    gv = gemini_res.fields.get(rk)
                    if gv and str(gv).strip().upper() != str(rv).strip().upper():
                        # Disagreement between regex and LLM -> penalize confidence
                        gemini_res.confidences[rk] = min(gemini_res.confidences.get(rk, 1.0), 0.35)

            gemini_res.fields.update(metadata_fields)
            gemini_res.raw_text = text_clean or gemini_res.raw_text

            # Save genuine Gemini extraction to persistent disk cache
            self._save_to_disk_cache(cache_file, gemini_res)
            return gemini_res

        # 4. Deterministic Text Layer Extraction (Offline mode or AI disabled)
        if len(text_clean) > 20:
            detected_type, parsed_fields, parsed_confs, parsed_snips, claimed_d = _extract_from_text_layer(
                text_clean, doc_type
            )
            parsed_fields.update(metadata_fields)
            if claimed_d:
                parsed_fields["_claimed_issue_date"] = claimed_d

            res = ExtractionResult(
                doc_type=doc_type,
                doc_type_detected=detected_type,
                fields=parsed_fields,
                confidences=parsed_confs,
                snippets=parsed_snips,
                raw_text=text_clean,
                extractor_type="text_layer_regex",
            )
            self._save_to_disk_cache(cache_file, res)
            return res

        # 5. Image-only Scan (No text layer) -> FAIL CLOSED
        return ExtractionResult(
            doc_type=doc_type,
            doc_type_detected="scanned_image_unreadable",
            fields=metadata_fields,
            confidences={"pan_number": 0.20, "gstin_on_cert": 0.20, "account_holder_name": 0.20},
            raw_text="[SCANNED IMAGE - UNREADABLE WITHOUT VISION MODEL]",
            error="Document scan unreadable; no digital text layer found and vision model unavailable (offline mode).",
            extractor_type="scan_unreadable_fail_closed",
        )

    def _call_gemini_api(self, doc_path: str, doc_type: str, timeout_seconds: float) -> ExtractionResult:
        """Send document to Gemini Flash generateContent endpoint via x-goog-api-key."""
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        headers = {
            "x-goog-api-key": str(self.api_key),
            "Content-Type": "application/json",
        }

        ext = os.path.splitext(doc_path)[1].lower()
        if ext in (".png",):
            mime_type = "image/png"
        elif ext in (".jpg", ".jpeg"):
            mime_type = "image/jpeg"
        else:
            mime_type = "application/pdf"

        try:
            with open(doc_path, "rb") as f:
                b64_content = base64.b64encode(f.read()).decode("utf-8")
        except Exception as exc:
            return ExtractionResult(
                doc_type=doc_type,
                doc_type_detected="file_read_error",
                error=f"Cannot read document file: {exc}",
                confidences={"all": 0.10},
                extractor_type="gemini_api",
            )

        prompt = (
            f"You are a strict Indian financial document compliance extractor. "
            f"Extract all information from this document for expected document type: {doc_type}. "
            f"Identify if the document matches the expected slot or if it is a different document type. "
            f"Respond ONLY with a valid JSON object matching this schema:\n"
            f'{{\n'
            f'  "doc_type_detected": "pan_card" | "gst_certificate" | "cancelled_cheque" | "coi" | "llpin_cert" | "address_proof" | "udyam_cert" | "unknown_document",\n'
            f'  "fields": {{"field_name": "value"}},\n'
            f'  "confidences": {{"field_name": float_between_0_and_1}},\n'
            f'  "snippets": {{"field_name": "exact verbatim string from document"}}\n'
            f'}}\n'
            f"Key fields by doc type:\n"
            f"- pan_card: pan_number, name_on_pan, _claimed_issue_date\n"
            f"- gst_certificate: gstin_on_cert, legal_name_on_cert, trade_name_on_cert, principal_place_state_code, address_on_cert, _claimed_issue_date\n"
            f"- cancelled_cheque: account_holder_name (from 'Beneficiary', 'Pay to', 'A/c Holder'), ifsc_on_cheque, account_last4_on_cheque\n"
            f"- coi: cin_on_coi, company_name_on_coi, incorporation_date\n"
            f"- llpin_cert: llpin_on_cert, llp_name_on_cert\n"
            f"- address_proof: address_state_code\n"
            f"- udyam_cert: udyam_number, udyam_category, udyam_activity_type\n"
        )

        response_schema = {
            "type": "OBJECT",
            "properties": {
                "doc_type_detected": {"type": "STRING"},
                "fields": {"type": "OBJECT"},
                "confidences": {"type": "OBJECT"},
                "snippets": {"type": "OBJECT"},
            },
            "required": ["doc_type_detected", "fields", "confidences", "snippets"],
        }

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {"mimeType": mime_type, "data": b64_content}},
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
                "temperature": 0.0,
            },
        }

        max_tries = 4
        backoff = 1.0  # 1s, 2s, 4s, 8s

        for attempt in range(max_tries):
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    # Circuit breaker on 401, 402, 403: disable Gemini immediately for the process, do not retry
                    if resp.status_code in (401, 402, 403):
                        trip_circuit_breaker(resp.status_code, resp.reason_phrase or "Client Auth/Billing Error")
                        return ExtractionResult(
                            doc_type=doc_type,
                            doc_type_detected="circuit_breaker",
                            error=f"Gemini API circuit breaker tripped (HTTP {resp.status_code})",
                            confidences={"all": 0.10},
                            extractor_type="gemini_api",
                        )

                    # Retry on 429 (rate-limit) or 503 (service unavailable) with exponential backoff (max 4 tries)
                    if resp.status_code in (429, 503) and attempt < max_tries - 1:
                        time.sleep(backoff)
                        backoff *= 2
                        continue

                    if resp.status_code != 200:
                        clean_err = resp.text[:200]
                        if self.api_key:
                            clean_err = clean_err.replace(self.api_key, "[REDACTED]")
                        return ExtractionResult(
                            doc_type=doc_type,
                            doc_type_detected="api_error",
                            error=f"Gemini API failure (HTTP {resp.status_code}): {clean_err}",
                            confidences={"all": 0.10},
                            extractor_type="gemini_api",
                        )

                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        return ExtractionResult(
                            doc_type=doc_type,
                            doc_type_detected="api_empty",
                            error="Gemini API returned no candidates",
                            confidences={"all": 0.10},
                            extractor_type="gemini_api",
                        )

                    raw_json = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    parsed = json.loads(raw_json)

                    return ExtractionResult(
                        doc_type=doc_type,
                        doc_type_detected=parsed.get("doc_type_detected", "unknown_document"),
                        fields=parsed.get("fields", {}),
                        confidences=parsed.get("confidences", {}),
                        snippets=parsed.get("snippets", {}),
                        raw_text="",
                        extractor_type="gemini_api",
                    )
            except Exception as exc:
                err_str = str(exc)
                if self.api_key:
                    err_str = err_str.replace(self.api_key, "[REDACTED]")
                if attempt < max_tries - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return ExtractionResult(
                    doc_type=doc_type,
                    doc_type_detected="api_exception",
                    error=f"Gemini API request exception: {err_str}",
                    confidences={"all": 0.10},
                    extractor_type="gemini_api",
                )

    def _save_to_disk_cache(self, cache_file: Path, res: ExtractionResult) -> None:
        """Write extraction output to persistent disk cache."""
        try:
            payload = {
                "doc_type": res.doc_type,
                "doc_type_detected": res.doc_type_detected,
                "fields": res.fields,
                "confidences": res.confidences,
                "snippets": res.snippets,
                "raw_text": res.raw_text,
                "extractor_type": res.extractor_type,
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Global Provider State
# ---------------------------------------------------------------------------
_EXTRACTION_CACHE: Dict[str, ExtractionResult] = {}
_DEFAULT_PROVIDER: LLMProvider = GeminiExtractor()


def set_llm_provider(provider: LLMProvider) -> None:
    """Swap the active LLM provider."""
    global _DEFAULT_PROVIDER
    _DEFAULT_PROVIDER = provider


def get_llm_provider() -> LLMProvider:
    """Return currently active LLM provider."""
    return _DEFAULT_PROVIDER


def clear_extraction_cache() -> None:
    """Clear memory extraction cache."""
    _EXTRACTION_CACHE.clear()


def compute_file_sha256(file_path: str) -> str:
    """Compute sha256 of file if it exists, else hash the path string."""
    if file_path and os.path.exists(file_path):
        hasher = hashlib.sha256()
        with open(file_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    return hashlib.sha256((file_path or "").encode("utf-8")).hexdigest()


def extract(
    doc_path: str,
    doc_type: str,
    submission_fields: Optional[dict[str, Any]] = None,
    provider: Optional[LLMProvider] = None,
    timeout_seconds: float = 8.0,
    simulate_timeout: bool = False,
) -> ExtractionResult:
    """
    Extract fields with sha256 disk + memory cache check, timeout guard,
    document type classification, and strict fail-closed handling.
    """
    if submission_fields is None:
        submission_fields = {}

    active_provider = provider or _DEFAULT_PROVIDER
    file_sha = compute_file_sha256(doc_path)
    cache_key = f"{file_sha}:{doc_type}"

    # Check memory cache
    if cache_key in _EXTRACTION_CACHE:
        cached_res = _EXTRACTION_CACHE[cache_key]
        return ExtractionResult(
            doc_type=cached_res.doc_type,
            doc_type_detected=cached_res.doc_type_detected,
            fields=dict(cached_res.fields),
            confidences=dict(cached_res.confidences),
            snippets=dict(cached_res.snippets),
            raw_text=cached_res.raw_text,
            error=cached_res.error,
            cached=True,
            timed_out=cached_res.timed_out,
            extractor_type=cached_res.extractor_type,
        )

    if simulate_timeout:
        fallback = ExtractionResult(
            doc_type=doc_type,
            doc_type_detected="timeout",
            fields={},
            confidences={k: 0.10 for k in ["pan_number", "gstin_on_cert", "account_holder_name", "cin_on_coi"]},
            snippets={},
            raw_text="",
            error="Extraction timed out; fell back to low-confidence default",
            timed_out=True,
            extractor_type="timeout_fallback",
        )
        _EXTRACTION_CACHE[cache_key] = fallback
        return fallback

    start = time.monotonic()
    try:
        res = active_provider.extract(
            doc_path=doc_path,
            doc_type=doc_type,
            submission_fields=submission_fields,
            timeout_seconds=timeout_seconds,
        )
        if (time.monotonic() - start) > timeout_seconds:
            fallback = ExtractionResult(
                doc_type=doc_type,
                doc_type_detected=res.doc_type_detected,
                fields=res.fields,
                confidences={k: 0.20 for k in res.confidences},
                snippets=res.snippets,
                raw_text=res.raw_text,
                error="Extraction exceeded timeout deadline; downgraded confidence",
                timed_out=True,
                extractor_type="timeout_fallback",
            )
            _EXTRACTION_CACHE[cache_key] = fallback
            return fallback

        _EXTRACTION_CACHE[cache_key] = res
        return res
    except Exception as exc:  # noqa: BLE001
        fallback = ExtractionResult(
            doc_type=doc_type,
            doc_type_detected="error",
            fields={},
            confidences={k: 0.25 for k in ["pan_number", "gstin_on_cert", "account_holder_name"]},
            snippets={},
            raw_text="",
            error=f"Extraction failure: {exc}",
            extractor_type="error_fallback",
        )
        _EXTRACTION_CACHE[cache_key] = fallback
        return fallback
