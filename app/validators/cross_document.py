"""
app/validators/cross_document.py — Cross-document consistency checks CD1–CD7 (§3.13 of spec).

CD1: pan_card_number_match (PAN card vs submission)
CD2: pan_card_name_match (PAN card name vs legal_name)
CD3: gst_cert_gstin_match (GST cert vs submission)
CD4: gst_cert_name_match (GST cert legal name vs legal_name)
CD5a: coi_cin_match (COI vs submission CIN, pvt/pub ltd)
CD5b: coi_name_match (COI company name vs legal_name)
CD6: cheque_ifsc_account_match (cheque IFSC & last4 vs submission)
CD7: gst_cert_address_vs_proof (GST principal state vs address proof state)
"""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz.distance import Levenshtein
from rapidfuzz.fuzz import token_sort_ratio

from app.validators import CheckResult
from app.validators.bank_name import normalise_name


def _clean_str(s: Optional[str]) -> str:
    return str(s or "").strip().upper()


def run_cd1_pan_card_number_match(
    submitted_pan: str,
    raw_text: str,
    extracted_pan: Optional[str],
    confidence: float = 1.0,
    min_confidence: float = 0.80,
) -> CheckResult:
    """CD1: Search raw text first; Levenshtein <= 2 = fixable; hard only when confidently different."""
    sub_pan = _clean_str(submitted_pan)
    raw_clean = _clean_str(raw_text)

    # 1. Search raw text verbatim
    if sub_pan and sub_pan in raw_clean:
        return CheckResult(
            check_name="pan_card_number_match",
            status="pass",
            severity="hard",
            evidence={"matched_via": "raw_text_search", "pan": sub_pan},
            score_contribution=0.0,
            explanation=f"PAN {sub_pan} verified directly in PAN card document text.",
        )

    # 2. Check extracted value
    ext_pan = _clean_str(extracted_pan)
    if not ext_pan:
        return CheckResult(
            check_name="pan_card_number_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_pan": sub_pan, "extracted_pan": None, "reason": "unreadable"},
            score_contribution=0.0,
            explanation="Couldn't read PAN from PAN card. Please upload a clear copy.",
        )

    dist = Levenshtein.distance(sub_pan, ext_pan)
    if dist == 0:
        return CheckResult(
            check_name="pan_card_number_match",
            status="pass",
            severity="hard",
            evidence={"matched_via": "extracted_value", "pan": ext_pan, "confidence": confidence},
            score_contribution=0.0,
            explanation=f"PAN {ext_pan} on PAN card matches submission.",
        )

    # Edit distance <= 2 -> Probable OCR error -> Fixable
    if dist <= 2:
        return CheckResult(
            check_name="pan_card_number_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_pan": sub_pan, "extracted_pan": ext_pan, "edit_distance": dist, "confidence": confidence},
            score_contribution=0.0,
            explanation=f"PAN on card ('{ext_pan}') differs slightly from submission ('{sub_pan}') (edit distance {dist}, probable OCR error). Please verify.",
        )

    # Confidently different -> Hard; low confidence -> Fixable
    if confidence < min_confidence:
        return CheckResult(
            check_name="pan_card_number_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_pan": sub_pan, "extracted_pan": ext_pan, "confidence": confidence, "min_confidence": min_confidence},
            score_contribution=0.0,
            explanation="Document unreadable, please re-upload a clearer copy.",
        )

    return CheckResult(
        check_name="pan_card_number_match",
        status="fail",
        severity="hard",
        evidence={"submitted_pan": sub_pan, "extracted_pan": ext_pan, "edit_distance": dist, "confidence": confidence},
        score_contribution=0.0,
        explanation=f"PAN on PAN card ('{ext_pan}') does not match submitted PAN ('{sub_pan}').",
    )


def run_cd2_pan_card_name_match(
    submitted_legal_name: str,
    extracted_name: Optional[str],
    confidence: float = 1.0,
    min_confidence: float = 0.80,
    failed_in_previous_run: bool = False,
    threshold: float = 85.0,
) -> CheckResult:
    """CD2: Name on PAN card vs legal_name using normalised token-set ratio >= threshold."""
    if not extracted_name or not extracted_name.strip():
        return CheckResult(
            check_name="pan_card_name_match",
            status="fail",
            severity="fixable",
            evidence={"extracted_name": None, "reason": "unreadable"},
            score_contribution=0.0,
            explanation="Couldn't read name from PAN card. Please upload a clear copy.",
        )

    norm_sub = normalise_name(submitted_legal_name)
    norm_ext = normalise_name(extracted_name)
    score = float(token_sort_ratio(norm_ext, norm_sub))

    if score >= 90.0:
        return CheckResult(
            check_name="pan_card_name_match",
            status="pass",
            severity="fixable",
            evidence={"score": score, "threshold": 90.0, "extracted": extracted_name},
            score_contribution=0.0,
            explanation=f"Name on PAN card matches submitted legal name (score {score:.1f} >= 90.0).",
        )

    if score >= 75.0:
        return CheckResult(
            check_name="pan_card_name_match",
            status="fail",
            severity="fixable",
            evidence={"score": score, "threshold": 90.0, "extracted": extracted_name, "zone": "warn"},
            score_contribution=0.0,
            explanation=f"Name on PAN card ('{extracted_name}') is a partial match (score {score:.1f} in [75, 90)). Please upload a matching document.",
        )

    # Below 75 = fail
    if failed_in_previous_run:
        if confidence < min_confidence:
            return CheckResult(
                check_name="pan_card_name_match",
                status="fail",
                severity="fixable",
                evidence={"score": score, "confidence": confidence},
                score_contribution=0.0,
                explanation="Document unreadable, please re-upload a clearer copy.",
            )
        return CheckResult(
            check_name="pan_card_name_match",
            status="fail",
            severity="hard",
            evidence={"score": score, "threshold": 75.0, "extracted": extracted_name, "repeat_failure": True},
            score_contribution=0.0,
            explanation=f"Name on PAN card ('{extracted_name}') does not match legal name (score {score:.1f} < 75.0, repeat failure).",
        )

    return CheckResult(
        check_name="pan_card_name_match",
        status="fail",
        severity="fixable",
        evidence={"score": score, "threshold": 75.0, "extracted": extracted_name, "repeat_failure": False},
        score_contribution=0.0,
        explanation=f"Name on PAN card ('{extracted_name}') does not match submitted legal name (score {score:.1f} < 75.0). Please upload a matching document.",
    )


def run_cd3_gst_cert_gstin_match(
    submitted_gstin: str,
    raw_text: str,
    extracted_gstin: Optional[str],
    confidence: float = 1.0,
    min_confidence: float = 0.80,
) -> CheckResult:
    """CD3: GST cert GSTIN vs submission. Raw text search first; Levenshtein <= 2 = fixable; hard only when confidently different."""
    sub_gst = _clean_str(submitted_gstin)
    raw_clean = _clean_str(raw_text)

    if sub_gst and sub_gst in raw_clean:
        return CheckResult(
            check_name="gst_cert_gstin_match",
            status="pass",
            severity="hard",
            evidence={"matched_via": "raw_text_search", "gstin": sub_gst},
            score_contribution=0.0,
            explanation=f"GSTIN {sub_gst} verified directly in GST certificate text.",
        )

    ext_gst = _clean_str(extracted_gstin)
    if not ext_gst:
        return CheckResult(
            check_name="gst_cert_gstin_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_gstin": sub_gst, "extracted_gstin": None, "reason": "unreadable"},
            score_contribution=0.0,
            explanation="Couldn't read GSTIN from GST certificate. Please upload a clear copy.",
        )

    dist = Levenshtein.distance(sub_gst, ext_gst)
    if dist == 0:
        return CheckResult(
            check_name="gst_cert_gstin_match",
            status="pass",
            severity="hard",
            evidence={"matched_via": "extracted_value", "gstin": ext_gst},
            score_contribution=0.0,
            explanation=f"GSTIN on certificate matches submission ({ext_gst}).",
        )

    if dist <= 2:
        return CheckResult(
            check_name="gst_cert_gstin_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_gstin": sub_gst, "extracted_gstin": ext_gst, "edit_distance": dist},
            score_contribution=0.0,
            explanation=f"GSTIN on certificate ('{ext_gst}') differs slightly from submission ('{sub_gst}') (edit distance {dist}, probable OCR error). Please verify.",
        )

    if confidence < min_confidence:
        return CheckResult(
            check_name="gst_cert_gstin_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_gstin": sub_gst, "extracted_gstin": ext_gst, "confidence": confidence},
            score_contribution=0.0,
            explanation="Document unreadable, please re-upload a clearer copy.",
        )

    return CheckResult(
        check_name="gst_cert_gstin_match",
        status="fail",
        severity="hard",
        evidence={"submitted_gstin": sub_gst, "extracted_gstin": ext_gst, "edit_distance": dist, "confidence": confidence},
        score_contribution=0.0,
        explanation=f"GSTIN on GST certificate ('{ext_gst}') does not match submitted GSTIN ('{sub_gst}').",
    )


def run_cd4_gst_cert_name_match(
    submitted_legal_name: str,
    extracted_legal_name: Optional[str],
    extracted_trade_name: Optional[str] = None,
    confidence: float = 1.0,
    min_confidence: float = 0.80,
    failed_in_previous_run: bool = False,
    threshold: float = 85.0,
) -> CheckResult:
    """CD4: Legal/trade name on GST certificate vs legal_name using normalised token-set ratio >= threshold."""
    if not extracted_legal_name and not extracted_trade_name:
        return CheckResult(
            check_name="gst_cert_name_match",
            status="fail",
            severity="fixable",
            evidence={"extracted_name": None, "reason": "unreadable"},
            score_contribution=0.0,
            explanation="Couldn't read legal name from GST certificate. Please upload a clear copy.",
        )

    norm_sub = normalise_name(submitted_legal_name)
    s_legal = float(token_sort_ratio(normalise_name(extracted_legal_name or ""), norm_sub))
    s_trade = float(token_sort_ratio(normalise_name(extracted_trade_name or ""), norm_sub)) if extracted_trade_name else 0.0
    score = max(s_legal, s_trade)

    if score >= 90.0:
        return CheckResult(
            check_name="gst_cert_name_match",
            status="pass",
            severity="fixable",
            evidence={"score": score, "threshold": 90.0, "legal_on_cert": extracted_legal_name, "trade_on_cert": extracted_trade_name},
            score_contribution=0.0,
            explanation=f"Name on GST certificate matches submitted legal name (score {score:.1f} >= 90.0).",
        )

    if score >= 75.0:
        return CheckResult(
            check_name="gst_cert_name_match",
            status="fail",
            severity="fixable",
            evidence={"score": score, "threshold": 90.0, "legal_on_cert": extracted_legal_name, "zone": "warn"},
            score_contribution=0.0,
            explanation=f"Name on GST certificate ('{extracted_legal_name}') is a partial match (score {score:.1f} in [75, 90)). Please upload a matching certificate.",
        )

    if failed_in_previous_run:
        if confidence < min_confidence:
            return CheckResult(
                check_name="gst_cert_name_match",
                status="fail",
                severity="fixable",
                evidence={"score": score, "confidence": confidence},
                score_contribution=0.0,
                explanation="Document unreadable, please re-upload a clearer copy.",
            )
        return CheckResult(
            check_name="gst_cert_name_match",
            status="fail",
            severity="hard",
            evidence={"score": score, "threshold": 75.0, "repeat_failure": True},
            score_contribution=0.0,
            explanation=f"Name on GST certificate does not match submitted legal name (score {score:.1f} < 75.0, repeat failure).",
        )

    return CheckResult(
        check_name="gst_cert_name_match",
        status="fail",
        severity="fixable",
        evidence={"score": score, "threshold": 75.0, "repeat_failure": False},
        score_contribution=0.0,
        explanation=f"Name on GST certificate ('{extracted_legal_name}') does not match submitted legal name (score {score:.1f} < 75.0). Please upload a matching certificate.",
    )


def run_cd5a_coi_cin_match(
    submitted_cin: str,
    raw_text: str,
    extracted_cin: Optional[str],
    confidence: float = 1.0,
    min_confidence: float = 0.80,
) -> CheckResult:
    """CD5a: CIN on COI vs submission. Raw text search first; Levenshtein <= 2 = fixable; hard only when confidently different."""
    sub_cin = _clean_str(submitted_cin)
    raw_clean = _clean_str(raw_text)

    if sub_cin and sub_cin in raw_clean:
        return CheckResult(
            check_name="coi_cin_match",
            status="pass",
            severity="hard",
            evidence={"matched_via": "raw_text_search", "cin": sub_cin},
            score_contribution=0.0,
            explanation=f"CIN {sub_cin} verified directly in COI document text.",
        )

    ext_cin = _clean_str(extracted_cin)
    if not ext_cin:
        return CheckResult(
            check_name="coi_cin_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_cin": sub_cin, "extracted_cin": None, "reason": "unreadable"},
            score_contribution=0.0,
            explanation="Couldn't read CIN from Certificate of Incorporation. Please upload a clear copy.",
        )

    dist = Levenshtein.distance(sub_cin, ext_cin)
    if dist == 0:
        return CheckResult(
            check_name="coi_cin_match",
            status="pass",
            severity="hard",
            evidence={"matched_via": "extracted_value", "cin": ext_cin},
            score_contribution=0.0,
            explanation=f"CIN on Certificate of Incorporation matches submission ({ext_cin}).",
        )

    if dist <= 2:
        return CheckResult(
            check_name="coi_cin_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_cin": sub_cin, "extracted_cin": ext_cin, "edit_distance": dist},
            score_contribution=0.0,
            explanation=f"CIN on COI ('{ext_cin}') differs slightly from submission ('{sub_cin}') (edit distance {dist}, probable OCR error). Please verify.",
        )

    if confidence < min_confidence:
        return CheckResult(
            check_name="coi_cin_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_cin": sub_cin, "extracted_cin": ext_cin, "confidence": confidence},
            score_contribution=0.0,
            explanation="Document unreadable, please re-upload a clearer copy.",
        )

    return CheckResult(
        check_name="coi_cin_match",
        status="fail",
        severity="hard",
        evidence={"submitted_cin": sub_cin, "extracted_cin": ext_cin, "edit_distance": dist, "confidence": confidence},
        score_contribution=0.0,
        explanation=f"CIN on COI ('{ext_cin}') does not match submitted CIN ('{sub_cin}').",
    )


def run_cd5b_coi_name_match(
    submitted_legal_name: str,
    extracted_company_name: Optional[str],
    confidence: float = 1.0,
    min_confidence: float = 0.80,
    failed_in_previous_run: bool = False,
    threshold: float = 85.0,
) -> CheckResult:
    """CD5b: Company name on COI vs legal_name using normalised token-set ratio >= threshold."""
    if not extracted_company_name or not extracted_company_name.strip():
        return CheckResult(
            check_name="coi_name_match",
            status="fail",
            severity="fixable",
            evidence={"extracted_name": None, "reason": "unreadable"},
            score_contribution=0.0,
            explanation="Couldn't read company name from Certificate of Incorporation. Please upload a clear copy.",
        )

    norm_sub = normalise_name(submitted_legal_name)
    norm_ext = normalise_name(extracted_company_name)
    score = float(token_sort_ratio(norm_ext, norm_sub))

    if score >= 90.0:
        return CheckResult(
            check_name="coi_name_match",
            status="pass",
            severity="fixable",
            evidence={"score": score, "threshold": 90.0, "company_on_coi": extracted_company_name},
            score_contribution=0.0,
            explanation=f"Company name on COI matches submitted legal name (score {score:.1f} >= 90.0).",
        )

    if score >= 75.0:
        return CheckResult(
            check_name="coi_name_match",
            status="fail",
            severity="fixable",
            evidence={"score": score, "threshold": 90.0, "company_on_coi": extracted_company_name, "zone": "warn"},
            score_contribution=0.0,
            explanation=f"Company name on COI ('{extracted_company_name}') is a partial match (score {score:.1f} in [75, 90)). Please upload a matching document.",
        )

    if failed_in_previous_run:
        if confidence < min_confidence:
            return CheckResult(
                check_name="coi_name_match",
                status="fail",
                severity="fixable",
                evidence={"score": score, "confidence": confidence},
                score_contribution=0.0,
                explanation="Document unreadable, please re-upload a clearer copy.",
            )
        return CheckResult(
            check_name="coi_name_match",
            status="fail",
            severity="hard",
            evidence={"score": score, "threshold": 75.0, "repeat_failure": True},
            score_contribution=0.0,
            explanation=f"Company name on COI does not match submitted legal name (score {score:.1f} < 75.0, repeat failure).",
        )

    return CheckResult(
        check_name="coi_name_match",
        status="fail",
        severity="fixable",
        evidence={"score": score, "threshold": 75.0, "repeat_failure": False},
        score_contribution=0.0,
        explanation=f"Company name on COI ('{extracted_company_name}') does not match submitted legal name (score {score:.1f} < 75.0). Please upload matching document.",
    )


def run_cd6_cheque_ifsc_account_match(
    submitted_ifsc: str,
    submitted_last4: str,
    raw_text: str,
    extracted_ifsc: Optional[str],
    extracted_last4: Optional[str],
    ifsc_conf: float = 1.0,
    last4_conf: float = 1.0,
    min_confidence: float = 0.80,
) -> CheckResult:
    """CD6: Cheque IFSC & account last4 vs submission. Raw text search first; Levenshtein <= 2 = fixable; hard only when confidently different."""
    sub_ifsc = _clean_str(submitted_ifsc)
    sub_l4 = _clean_str(submitted_last4)
    raw_clean = _clean_str(raw_text)

    # Raw embedded text check for IFSC and account number
    if sub_ifsc and sub_l4 and (sub_ifsc in raw_clean) and (sub_l4 in raw_clean):
        return CheckResult(
            check_name="cheque_ifsc_account_match",
            status="pass",
            severity="hard",
            evidence={"matched_via": "raw_text_search", "ifsc": sub_ifsc, "account_last4": sub_l4},
            score_contribution=0.0,
            explanation="Cheque IFSC and account number verified directly in document text.",
        )

    ext_ifsc = _clean_str(extracted_ifsc)
    ext_l4 = _clean_str(extracted_last4)

    if not ext_ifsc or not ext_l4:
        return CheckResult(
            check_name="cheque_ifsc_account_match",
            status="fail",
            severity="fixable",
            evidence={"extracted_ifsc": ext_ifsc or None, "extracted_last4": ext_l4 or None, "reason": "unreadable"},
            score_contribution=0.0,
            explanation="Couldn't read IFSC or account number from cancelled cheque. Please upload a clear copy.",
        )

    dist_ifsc = Levenshtein.distance(sub_ifsc, ext_ifsc) if sub_ifsc else 0
    dist_l4 = Levenshtein.distance(sub_l4, ext_l4) if sub_l4 else 0
    max_dist = max(dist_ifsc, dist_l4)

    if max_dist == 0:
        return CheckResult(
            check_name="cheque_ifsc_account_match",
            status="pass",
            severity="hard",
            evidence={"ifsc": ext_ifsc, "account_last4": ext_l4},
            score_contribution=0.0,
            explanation=f"Cheque IFSC ({ext_ifsc}) and account number match submission.",
        )

    if max_dist <= 2:
        return CheckResult(
            check_name="cheque_ifsc_account_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_ifsc": sub_ifsc, "extracted_ifsc": ext_ifsc, "submitted_last4": sub_l4, "extracted_last4": ext_l4, "max_distance": max_dist},
            score_contribution=0.0,
            explanation=f"Cheque details differ slightly from submission (edit distance {max_dist}, probable OCR error). Please verify.",
        )

    min_c = min(ifsc_conf, last4_conf)
    if min_c < min_confidence:
        return CheckResult(
            check_name="cheque_ifsc_account_match",
            status="fail",
            severity="fixable",
            evidence={"submitted_ifsc": sub_ifsc, "extracted_ifsc": ext_ifsc, "confidence": min_c},
            score_contribution=0.0,
            explanation="Document unreadable, please re-upload a clearer copy.",
        )

    return CheckResult(
        check_name="cheque_ifsc_account_match",
        status="fail",
        severity="hard",
        evidence={"submitted_ifsc": sub_ifsc, "extracted_ifsc": ext_ifsc, "submitted_last4": sub_l4, "extracted_last4": ext_l4},
        score_contribution=0.0,
        explanation="IFSC or account number on cheque does not match submission.",
    )


def run_cd7_gst_cert_address_vs_proof(
    gst_state_code: Optional[str],
    proof_state_code: Optional[str],
    confidence: float = 1.0,
    min_confidence: float = 0.80,
) -> Optional[CheckResult]:
    """CD7: GST certificate principal state vs address proof state. Soft signal (+8 risk score; low confidence -> Skip)."""
    if not gst_state_code or not proof_state_code:
        return None

    if confidence < min_confidence:
        # SPEC §3.13: low-confidence -> Skip
        return None

    s_gst = _clean_str(gst_state_code)
    s_proof = _clean_str(proof_state_code)

    if s_gst == s_proof:
        return CheckResult(
            check_name="gst_cert_address_vs_proof",
            status="pass",
            severity="soft",
            evidence={"gst_state": s_gst, "proof_state": s_proof},
            score_contribution=0.0,
            explanation=f"Principal place state on GST certificate ({s_gst}) matches address proof.",
        )

    return CheckResult(
        check_name="gst_cert_address_vs_proof",
        status="warn",
        severity="soft",
        evidence={"gst_state": s_gst, "proof_state": s_proof},
        score_contribution=8.0,
        explanation=f"Principal place state on GST certificate ({s_gst}) does not match address proof state ({s_proof}) (+8 risk score).",
    )
