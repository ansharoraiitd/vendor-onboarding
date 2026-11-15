"""
Deterministic mapping from check_name to vendor-facing category.
No LLM involvement. Used by rejected/human_review email templates.
Multiple checks mapping to the same category are deduplicated to one line.
"""
from __future__ import annotations

CHECK_CATEGORIES: dict[str, str] = {
    # PAN
    "pan_format": "Identity number issue",
    "pan_entity_type_match": "Identity number issue",
    "pan_status": "Identity number issue",
    # GSTIN
    "gstin_format": "Tax registration issue",
    "gstin_checksum": "Tax registration issue",
    "gstin_embedded_pan_match": "Tax registration issue",
    "gstin_state_code_match": "Registration address mismatch",
    "gst_state_vs_address_state": "Tax registration state warning",
    # CIN / LLPIN
    "cin_format": "Company registration issue",
    "cin_entity_type_match": "Company registration issue",
    "cin_state_match": "Registration address mismatch",
    "cin_year_match": "Company registration issue",
    "cin_registered_name_match": "Company registration issue",
    "cin_active_status": "Company registration issue",
    "llpin_format": "Company registration issue",
    # Bank / IFSC
    "ifsc_format": "Bank account verification failed",
    "ifsc_lookup": "Bank account verification failed",
    "bank_name_fuzzy_match": "Bank account verification failed",
    # Udyam (informational — not a rejection reason in practice)
    "udyam_format": "MSME registration issue",
    "udyam_category": "MSME registration issue",
    "udyam_activity_type": "MSME registration issue",
    "payment_term_cap": "MSME registration issue",
    # TDS
    "tds_higher_rate_flag": "Identity number issue",
    # External status
    "gstin_status_check": "Registration status issue",
    "mca_company_status": "Registration status issue",
    "cvc_gem_debarment": "Eligibility restriction",
    "internal_blocklist": "Eligibility restriction",
    # PDF metadata (soft — rarely a rejection cause)
    "pdf_editing_tool": "Document integrity concern",
    "pdf_moddate_gap": "Document integrity concern",
    "pdf_impossible_creation_date": "Document integrity concern",
    # Required docs
    "required_docs_present": "Missing required document",
    # Duplicates
    "duplicate_pan_gstin": "Duplicate registration detected",
    "duplicate_bank_account": "Bank account verification failed",
    "duplicate_name_fuzzy": "Duplicate registration detected",
    # Cross-document
    "pan_card_number_match": "Document–record mismatch",
    "pan_card_name_match": "Document–record mismatch",
    "gst_cert_gstin_match": "Document–record mismatch",
    "gst_cert_name_match": "Document–record mismatch",
    "coi_cin_match": "Document–record mismatch",
    "coi_name_match": "Document–record mismatch",
    "cheque_ifsc_account_match": "Document–record mismatch",
    "gst_cert_address_vs_proof": "Document–record mismatch",
}

# Human-readable labels shown in pending notifications (fixable checks)
FIXABLE_LABELS: dict[str, str] = {
    "pan_status": "Valid PAN not found — please provide a valid PAN",
    "gstin_state_code_match": "GSTIN state code does not match your address — please verify",
    "ifsc_lookup": "IFSC code could not be verified — please re-check and resubmit",
    "bank_name_fuzzy_match": "Bank account holder name does not match your legal name",
    "udyam_format": "Udyam registration number format is invalid",
    "udyam_category": "Could not read Udyam category — please re-upload a clearer certificate",
    "udyam_activity_type": "Could not read Udyam activity type — please re-upload a clearer certificate",
    "required_docs_present": "Required document is missing",
    "pan_card_number_match": "PAN on your PAN card does not match the PAN provided",
    "pan_card_name_match": "Name on your PAN card does not match your legal name",
    "gst_cert_gstin_match": "GSTIN on your GST certificate does not match the GSTIN provided",
    "gst_cert_name_match": "Legal name on your GST certificate does not match",
    "coi_cin_match": "CIN on your Certificate of Incorporation does not match",
    "coi_name_match": "Company name on your Certificate of Incorporation does not match",
    "cheque_ifsc_account_match": "Bank details on your cancelled cheque do not match",
    "tds_higher_rate_flag": "No valid PAN on file — higher TDS rate will apply until corrected",
    "cin_year_match": "Incorporation year on Certificate of Incorporation does not match",
    "cin_registered_name_match": "Company name does not match MCA records",
}


def get_category(check_name: str) -> str:
    """Return the vendor-facing category for a check_name, or a generic fallback."""
    return CHECK_CATEGORIES.get(check_name, "Verification issue")


def get_fixable_label(check_name: str, doc_type: str = "") -> str:
    """Return a human-readable description of a fixable check."""
    if check_name == "required_docs_present" and doc_type:
        doc_labels = {
            "pan_card": "PAN card",
            "gst_certificate": "GST registration certificate",
            "cancelled_cheque": "Cancelled cheque or bank letter",
            "bank_letter": "Bank letter or cancelled cheque",
            "coi": "Certificate of Incorporation",
            "llpin_cert": "LLPIN certificate",
            "udyam_cert": "Udyam registration certificate",
            "address_proof": "Address proof document",
        }
        return f"Missing required document: {doc_labels.get(doc_type, doc_type)}"
    return FIXABLE_LABELS.get(check_name, f"Issue with {check_name.replace('_', ' ')}")


def unique_categories(check_names: list[str]) -> list[str]:
    """Return deduplicated ordered list of categories for a set of check_names."""
    seen: set[str] = set()
    result = []
    for name in check_names:
        cat = get_category(name)
        if cat not in seen:
            seen.add(cat)
            result.append(cat)
    return result
