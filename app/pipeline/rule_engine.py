"""
Rule engine — calls all validators in order and applies the confidence gate.

run_all_checks(submission, extracted_fields_by_doc, config,
               prior_failures, adapter) -> List[CheckResult]

The confidence gate (§3.10):
  Hard check + low-confidence field  → downgrade severity to "fixable"
  Soft check + low-confidence field  → skip entirely (return nothing)
  Fixable check                      → always run (already a "please fix")
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional, Set

from rapidfuzz import fuzz

from app.adapters import AdapterResult
from app.adapters.mock import MockAdapter
from app.config import Config
from app.validators import CheckResult
from app.validators.bank_name import run_bank_name_fuzzy_match
from app.validators.cin import (
    run_cin_entity_type_match,
    run_cin_format,
    run_cin_state_match,
    run_cin_year_match,
)
from app.validators.cross_document import (
    run_cd1_pan_card_number_match,
    run_cd2_pan_card_name_match,
    run_cd3_gst_cert_gstin_match,
    run_cd4_gst_cert_name_match,
    run_cd5a_coi_cin_match,
    run_cd5b_coi_name_match,
    run_cd6_cheque_ifsc_account_match,
    run_cd7_gst_cert_address_vs_proof,
)
from app.validators.gstin import (
    run_gstin_checksum,
    run_gstin_embedded_pan_match,
    run_gstin_format,
    run_gstin_state_code_match,
)
from app.validators.ifsc import run_ifsc_format
from app.validators.llpin import run_llpin_format
from app.validators.pan import run_pan_entity_type_match, run_pan_format
from app.validators.pdf_meta import (
    run_pdf_editing_tool,
    run_pdf_impossible_creation_date,
    run_pdf_moddate_gap,
)
from app.validators.udyam import (
    run_payment_term_cap,
    run_udyam_activity_type,
    run_udyam_category,
    run_udyam_format,
)

# GST 2-digit state code to 2-letter ROC/postal state code
GST_NUM_TO_ALPHA = {
    "01": "JK", "02": "HP", "03": "PB", "04": "CH", "05": "UK",
    "06": "HR", "07": "DL", "08": "RJ", "09": "UP", "10": "BR",
    "11": "SK", "12": "AR", "13": "NL", "14": "MN", "15": "MZ",
    "16": "TR", "17": "ML", "18": "AS", "19": "WB", "20": "JH",
    "21": "OR", "22": "CT", "23": "MP", "24": "GJ", "26": "DD",
    "27": "MH", "29": "KA", "30": "GA", "31": "LD", "32": "KL",
    "33": "TN", "34": "PY", "35": "AN", "36": "TG", "37": "AP",
    "38": "LA",
}


# ---------------------------------------------------------------------------
# Confidence gate helpers
# ---------------------------------------------------------------------------

def _apply_confidence_gate(
    result: CheckResult,
    confidence: float,
    min_confidence: float,
) -> Optional[CheckResult]:
    """
    Apply §3.10 confidence gate to a single check result.
    Returns None if the check should be skipped entirely (soft + low-conf).
    Returns a (possibly downgraded) CheckResult otherwise.
    """
    if confidence >= min_confidence:
        return result
    # Low confidence
    if result.severity == "soft":
        return None   # skip entirely
    if result.severity == "hard":
        return dataclasses.replace(
            result,
            severity="fixable",
            explanation=(
                "Document unreadable, please re-upload a clearer copy "
                f"(original check: {result.check_name})"
            ),
        )
    # Fixable → unchanged
    return result


def _gate(
    result: CheckResult,
    confidences: Dict[str, float],
    field_name: str,
    min_confidence: float,
) -> Optional[CheckResult]:
    conf = confidences.get(field_name, 1.0)
    return _apply_confidence_gate(result, conf, min_confidence)


def _prior_failed(check_name: str, prior_failures: Set[str]) -> bool:
    return check_name in prior_failures


def _cfg(config: Config, *path: str, default: Any = None) -> Any:
    """Safely walk a config attribute chain."""
    obj = config
    for key in path:
        obj = getattr(obj, key, None)
        if obj is None:
            return default
    return obj


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_all_checks(
    submission: Dict[str, Any],
    extracted_fields_by_doc: Dict[str, Dict[str, Any]],
    confidences_by_doc: Dict[str, Dict[str, float]],
    raw_text_by_doc: Dict[str, str],
    config: Config,
    prior_failures: Optional[Set[str]] = None,
    adapter: Optional[MockAdapter] = None,
    uploaded_doc_types: Optional[List[str]] = None,
    existing_bank_account_hmacs: Optional[Set[str]] = None,
    existing_pans: Optional[Dict[str, str]] = None,
) -> List[CheckResult]:
    if prior_failures is None:
        prior_failures = set()
    if adapter is None:
        adapter = MockAdapter()
    if uploaded_doc_types is None:
        uploaded_doc_types = []
    if existing_bank_account_hmacs is None:
        existing_bank_account_hmacs = set()
    if existing_pans is None:
        existing_pans = {}

    results: List[CheckResult] = []
    min_conf: float = _cfg(config, "extraction", "min_confidence", default=0.80)

    entity_type: str = submission.get("entity_type", "")
    pan: str = (submission.get("pan") or "").strip().upper()
    gstin: str = (submission.get("gstin") or "").strip().upper()
    cin: str = (submission.get("cin") or "").strip().upper()
    llpin: str = (submission.get("llpin") or "").strip().upper()
    ifsc: str = (submission.get("ifsc") or "").strip().upper()
    legal_name: str = (submission.get("legal_name") or "").strip()
    address_state_code: str = (submission.get("address_state_code") or "").strip()
    udyam_number: str = (submission.get("udyam_number") or "").strip()
    udyam_category: str = (submission.get("udyam_category") or "").strip()
    udyam_activity_type: str = (submission.get("udyam_activity_type") or "").strip()
    agreed_payment_days = submission.get("agreed_payment_days")
    bank_account_hmac: str = submission.get("bank_account_number") or ""

    # ------------------------------------------------------------------ #
    # §3.0 Document Type Verification (Fail closed if upload mismatch)
    # ------------------------------------------------------------------ #
    for doc_type in uploaded_doc_types:
        flds = extracted_fields_by_doc.get(doc_type, {})
        detected = flds.get("_doc_type_detected")
        if not detected:
            continue
        friendly_expected = doc_type.replace("_", " ")
        friendly_detected = detected.replace("_", " ")
        is_match = (
            (doc_type in ("cancelled_cheque", "bank_letter") and detected in ("cancelled_cheque", "bank_letter"))
            or (detected == doc_type)
        )
        if not is_match:
            results.append(
                CheckResult(
                    check_name=f"document_type_match_{doc_type}",
                    status="fail",
                    severity="fixable",
                    evidence={"expected_slot": doc_type, "detected_type": detected},
                    score_contribution=0.0,
                    explanation=f"This looks like a {friendly_detected}, not a {friendly_expected}.",
                )
            )
        else:
            results.append(
                CheckResult(
                    check_name=f"document_type_match_{doc_type}",
                    status="pass",
                    severity="fixable",
                    evidence={"expected_slot": doc_type, "detected_type": detected},
                    score_contribution=0.0,
                    explanation=f"Verified upload is a valid {friendly_expected}.",
                )
            )

    # ------------------------------------------------------------------ #
    # §3.1 PAN checks
    # ------------------------------------------------------------------ #
    r_pfmt = run_pan_format(pan)
    results.append(r_pfmt)

    if r_pfmt.status == "pass":
        results.append(run_pan_entity_type_match(pan, entity_type))

        pan_adapter: AdapterResult = adapter.call("PANStatusAdapter", pan)
        pan_status = pan_adapter.status
        # P3: pan_status check
        if pan_status == "valid":
            p3 = CheckResult(
                check_name="pan_status",
                status="pass",
                severity="hard",
                evidence={"pan": pan, "status": pan_status},
                score_contribution=0,
                explanation=f"PAN {pan} is valid.",
            )
        elif pan_status == "missing":
            p3 = CheckResult(
                check_name="pan_status",
                status="fail",
                severity="fixable",
                evidence={"pan": pan, "status": pan_status},
                score_contribution=0,
                explanation="PAN not found — please provide a valid PAN.",
            )
        else:  # invalid / unknown
            p3 = CheckResult(
                check_name="pan_status",
                status="fail",
                severity="hard",
                evidence={"pan": pan, "status": pan_status, **pan_adapter.raw},
                score_contribution=0,
                explanation=f"PAN {pan} is not valid per ITD records.",
            )
        results.append(p3)

    # ------------------------------------------------------------------ #
    # §3.2 GSTIN checks
    # ------------------------------------------------------------------ #
    if gstin:
        r_gfmt = run_gstin_format(gstin)
        results.append(r_gfmt)

        if r_gfmt.status == "pass":
            results.append(run_gstin_checksum(gstin))
            results.append(run_gstin_embedded_pan_match(gstin, pan))

            # G4: principal-place state from GST certificate
            gst_fields = extracted_fields_by_doc.get("gst_certificate", {})
            gst_confs = confidences_by_doc.get("gst_certificate", {})
            principal_state = gst_fields.get("principal_place_state_code")
            g4_conf = gst_confs.get("principal_place_state_code", 1.0)
            if "gst_certificate" in uploaded_doc_types and not principal_state:
                results.append(
                    CheckResult(
                        check_name="gstin_state_code_match",
                        status="fail",
                        severity="fixable",
                        evidence={"principal_place_state_code": None, "reason": "unreadable_from_cert"},
                        score_contribution=0.0,
                        explanation="Couldn't read principal place state code from GST certificate. Please upload a clear copy.",
                    )
                )
            else:
                results.append(
                    run_gstin_state_code_match(
                        gstin=gstin,
                        gst_cert_state_code=principal_state or address_state_code,
                        confidence=g4_conf,
                        min_confidence=min_conf,
                    )
                )

            # Soft check: GST certificate state differs from registered address state (multi-state operation)
            gst_effective_state = (principal_state or (gstin[:2] if len(gstin) >= 2 else "")).strip()
            addr_state = (address_state_code or "").strip()
            if gst_effective_state and addr_state:
                if gst_effective_state != addr_state:
                    results.append(
                        CheckResult(
                            check_name="gst_state_vs_address_state",
                            status="warn",
                            severity="soft",
                            score_contribution=config.risk_weights.gst_state_vs_address_state,
                            evidence={
                                "gst_cert_state": gst_effective_state,
                                "address_state": addr_state,
                            },
                            explanation=(
                                f"GST certificate state ({gst_effective_state}) differs from "
                                f"registered address state ({addr_state}) (multi-state operation)."
                            ),
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            check_name="gst_state_vs_address_state",
                            status="pass",
                            severity="soft",
                            score_contribution=0.0,
                            evidence={
                                "gst_cert_state": gst_effective_state,
                                "address_state": addr_state,
                            },
                            explanation="GST certificate state matches registered address state.",
                        )
                    )

    # ------------------------------------------------------------------ #
    # §3.3 CIN / LLPIN checks
    # ------------------------------------------------------------------ #
    is_company = entity_type in ("pvt_ltd", "pub_ltd", "section8")
    is_llp = entity_type == "llp"

    mca_result: Optional[AdapterResult] = None
    if is_company and cin:
        results.append(run_cin_format(cin))
        results.append(run_cin_entity_type_match(cin, entity_type))

        # Map 2-digit GST state code to 2-letter alpha state code if needed
        state_alpha = GST_NUM_TO_ALPHA.get(address_state_code, address_state_code)
        results.append(run_cin_state_match(cin, state_alpha))

        # C4: year from COI (confidence-gated Hard; fails closed if unreadable)
        coi_fields = extracted_fields_by_doc.get("coi", {})
        coi_confs = confidences_by_doc.get("coi", {})
        incorp_date = coi_fields.get("incorporation_date", "")
        if "coi" in uploaded_doc_types and not incorp_date:
            results.append(
                CheckResult(
                    check_name="cin_year_match",
                    status="fail",
                    severity="fixable",
                    evidence={"incorporation_date": None, "reason": "unreadable_from_coi"},
                    score_contribution=0.0,
                    explanation="Couldn't read incorporation date from Certificate of Incorporation. Please upload a clear copy.",
                )
            )
        elif incorp_date:
            try:
                year_int = int(str(incorp_date)[:4])
                c4 = run_cin_year_match(cin, year_int)
                gated = _gate(c4, coi_confs, "incorporation_date", min_conf)
                if gated is not None:
                    results.append(gated)
            except (ValueError, TypeError):
                results.append(
                    CheckResult(
                        check_name="cin_year_match",
                        status="fail",
                        severity="fixable",
                        evidence={"incorporation_date": incorp_date, "reason": "invalid_date_format"},
                        score_contribution=0.0,
                        explanation="Couldn't parse incorporation date from Certificate of Incorporation. Please upload a clear copy.",
                    )
                )

        # C5/C6: name and status from MCA adapter
        mca_result = adapter.call("MCAStatusAdapter", cin)
        mca_name = mca_result.raw.get("company_name", "")
        mca_status = mca_result.status
        if mca_name:
            results.append(_mca_name_check(cin, mca_name, legal_name))
        results.append(_mca_status_check(cin, mca_status))

    elif is_llp and llpin:
        results.append(run_llpin_format(llpin))

    # ------------------------------------------------------------------ #
    # §3.4 / §3.5 Bank / IFSC checks
    # ------------------------------------------------------------------ #
    if ifsc:
        results.append(run_ifsc_format(ifsc))

        ifsc_result: AdapterResult = adapter.call("IFSCAdapter", ifsc)
        ifsc_status = ifsc_result.status
        b2 = CheckResult(
            check_name="ifsc_lookup",
            status="pass" if ifsc_status == "found" else "fail",
            severity="fixable" if ifsc_status != "found" else "soft",
            evidence={"ifsc": ifsc, "ifsc_status": ifsc_status, **ifsc_result.raw},
            score_contribution=0,
            explanation=(
                f"IFSC {ifsc}: {ifsc_result.raw.get('bank_name', 'unknown bank')}"
                if ifsc_status == "found"
                else f"IFSC {ifsc} not found in RBI master list."
            ),
        )
        results.append(b2)

    # B3 bank name — uses LLM-extracted account holder name (fails closed if unreadable)
    cheque_fields = extracted_fields_by_doc.get(
        "cancelled_cheque",
        extracted_fields_by_doc.get("bank_letter", {}),
    )
    cheque_confs = confidences_by_doc.get(
        "cancelled_cheque",
        confidences_by_doc.get("bank_letter", {}),
    )
    gst_fields = extracted_fields_by_doc.get("gst_certificate", {})
    bank_holder = (cheque_fields.get("account_holder_name") or "").strip()

    has_cheque = "cancelled_cheque" in uploaded_doc_types or "bank_letter" in uploaded_doc_types
    if has_cheque and not bank_holder:
        results.append(
            CheckResult(
                check_name="bank_name_fuzzy_match",
                status="fail",
                severity="fixable",
                evidence={"account_holder_name": None, "reason": "unreadable_from_cheque"},
                score_contribution=0.0,
                explanation="Couldn't read account holder name from cancelled cheque. Please upload a clear document.",
            )
        )
    elif bank_holder:
        gst_legal = gst_fields.get("legal_name_on_cert", "")
        gst_trade = gst_fields.get("trade_name_on_cert", "")
        b3_failed_prev = _prior_failed("bank_name_fuzzy_match", prior_failures)
        bank_conf = cheque_confs.get("account_holder_name", 1.0)

        pass_thr = float(_cfg(config, "bank_name_match", "pass_threshold", default=90.0))
        rev_thr = float(_cfg(config, "bank_name_match", "review_threshold", default=75.0))
        fail_contrib = float(_cfg(config, "bank_name_match", "fail_score_contribution", default=10.0))

        b3 = run_bank_name_fuzzy_match(
            bank_name=bank_holder,
            legal_name=legal_name,
            failed_in_previous_run=b3_failed_prev,
            pass_threshold=pass_thr,
            review_threshold=rev_thr,
            fail_score_contribution=fail_contrib,
            gst_legal_name=gst_legal or None,
            gst_trade_name=gst_trade or None,
        )
        # Confidence gate
        if bank_conf < min_conf and b3_failed_prev:
            b3 = dataclasses.replace(
                b3,
                severity="fixable",
                explanation="Document unreadable, please re-upload a clearer copy",
            )
            results.append(b3)
        else:
            gated = _apply_confidence_gate(b3, bank_conf, min_conf)
            if gated is not None:
                results.append(gated)

    # ------------------------------------------------------------------ #
    # §3.6 Udyam / MSME (fails closed if unreadable from cert)
    # ------------------------------------------------------------------ #
    if udyam_number:
        results.append(run_udyam_format(udyam_number))

        udyam_fields = extracted_fields_by_doc.get("udyam_cert", {})
        extracted_category = udyam_fields.get("udyam_category")
        extracted_activity = udyam_fields.get("udyam_activity_type")

        if "udyam_cert" in uploaded_doc_types and (not extracted_category or not extracted_activity):
            results.append(
                CheckResult(
                    check_name="udyam_details_readable",
                    status="fail",
                    severity="fixable",
                    evidence={"udyam_category": extracted_category, "udyam_activity_type": extracted_activity},
                    score_contribution=0.0,
                    explanation="Couldn't read MSME category or activity type from Udyam certificate. Please upload a clear copy.",
                )
            )
        else:
            cat_to_use = extracted_category or udyam_category
            act_to_use = extracted_activity or udyam_activity_type

            if cat_to_use:
                results.append(run_udyam_category(cat_to_use))
            if act_to_use:
                results.append(run_udyam_activity_type(act_to_use))

            # Map agreed_payment_days to written_agreement and agreed_days
            has_agreement = agreed_payment_days is not None
            agreed_days_val = int(agreed_payment_days) if has_agreement else None

            results.append(
                run_payment_term_cap(
                    category=cat_to_use,
                    activity_type=act_to_use,
                    written_agreement=has_agreement,
                    agreed_days=agreed_days_val,
                )
            )

    # ------------------------------------------------------------------ #
    # §3.7 TDS higher-rate flag (derived from P3 result)
    # ------------------------------------------------------------------ #
    pan_status_check = next(
        (r for r in results if r.check_name == "pan_status"), None
    )
    if pan_status_check and pan_status_check.status == "fail":
        results.append(
            CheckResult(
                check_name="tds_higher_rate_flag",
                status="fail",
                severity="fixable",
                evidence={
                    "pan_status": pan_status_check.evidence.get("status", ""),
                    "note": "Higher TDS rate applies (IT Act 2025 §397(2))",
                },
                score_contribution=0,
                explanation=(
                    "No valid PAN on file. The buyer must deduct TDS at the higher "
                    "rate under IT Act 2025 Section 397(2) until a valid PAN is provided."
                ),
            )
        )

    # ------------------------------------------------------------------ #
    # §3.8 External status checks
    # ------------------------------------------------------------------ #
    if gstin:
        gstin_adp: AdapterResult = adapter.call("GSTINStatusAdapter", gstin)
        gstin_status = gstin_adp.status
        hard_gstin = gstin_status in ("cancelled", "suspended", "not_found")
        results.append(
            CheckResult(
                check_name="gstin_status_check",
                status="fail" if hard_gstin else "pass",
                severity="hard" if hard_gstin else "soft",
                evidence={"gstin": gstin, "status": gstin_status, **gstin_adp.raw},
                score_contribution=5 if gstin_status == "suspended" and not hard_gstin else 0,
                explanation=f"GSTIN status: {gstin_status}",
            )
        )

    # E3: CVC/GeM debarment (keyed by PAN)
    if pan:
        deb: AdapterResult = adapter.call("DebarmentAdapter", pan)
        deb_status = deb.status
        hard_deb = deb_status in ("debarred", "suspended")
        results.append(
            CheckResult(
                check_name="cvc_gem_debarment",
                status="fail" if hard_deb else "pass",
                severity="hard" if hard_deb else "soft",
                evidence={"pan": pan, "debarment_status": deb_status, **deb.raw},
                score_contribution=0,
                explanation=f"CVC/GeM debarment status: {deb_status}",
            )
        )

        # E4: Internal blocklist
        bl: AdapterResult = adapter.call("InternalBlocklistAdapter", pan)
        bl_status = bl.status
        hard_bl = bl_status == "blocked"
        results.append(
            CheckResult(
                check_name="internal_blocklist",
                status="fail" if hard_bl else "pass",
                severity="hard" if hard_bl else "soft",
                evidence={"pan": pan, "blocklist_status": bl_status, **bl.raw},
                score_contribution=0,
                explanation=f"Internal blocklist status: {bl_status}",
            )
        )

    # ------------------------------------------------------------------ #
    # §3.12 Duplicate Detection (DV1 & DV2)
    # ------------------------------------------------------------------ #
    if existing_pans and pan and pan in existing_pans:
        existing_name = existing_pans[pan]
        score = fuzz.token_set_ratio(legal_name.lower(), existing_name.lower())
        if score < 90:
            results.append(
                CheckResult(
                    check_name="duplicate_pan_collision",
                    status="fail",
                    severity="escalate",
                    evidence={"pan": pan, "existing_name": existing_name, "submitted_name": legal_name, "score": score},
                    score_contribution=0.0,
                    explanation=f"PAN matches existing vendor '{existing_name}' but name differs (escalated to manual review).",
                )
            )

    if bank_account_hmac and bank_account_hmac in existing_bank_account_hmacs:
        results.append(
            CheckResult(
                check_name="duplicate_bank_account",
                status="fail",
                severity="escalate",
                evidence={"bank_account_hmac": bank_account_hmac[:12] + "...", "duplicate": True},
                score_contribution=0.0,
                explanation="Bank account number matches an existing registered vendor (escalated to manual review).",
            )
        )

    # ------------------------------------------------------------------ #
    # §3.9 PDF metadata signals (soft only; never reject)
    # ------------------------------------------------------------------ #
    moddate_gap_days = _cfg(config, "pdf_metadata", "moddate_gap_days", default=30)
    for doc_type, fields in extracted_fields_by_doc.items():
        pdf_producer = fields.get("_pdf_producer", "")
        pdf_creation_date = fields.get("_pdf_creation_date", "")
        pdf_mod_date = fields.get("_pdf_mod_date", "")
        claimed_issue_date = fields.get("_claimed_issue_date", "")
        confs = confidences_by_doc.get(doc_type, {})

        if pdf_producer or pdf_creation_date or pdf_mod_date:
            m1 = run_pdf_editing_tool(pdf_producer, doc_type=doc_type)
            m2 = run_pdf_moddate_gap(
                pdf_creation_date, pdf_mod_date, gap_days=moddate_gap_days
            )
            m3 = run_pdf_impossible_creation_date(pdf_creation_date, claimed_issue_date)
            for m in (m1, m2, m3):
                if m.status in ("fail", "warn"):
                    gated = _gate(
                        m, confs, "_claimed_issue_date", min_conf
                    ) if m.check_name == "pdf_impossible_creation_date" else m
                    if gated is not None:
                        results.append(gated)

    # ------------------------------------------------------------------ #
    # §3.11 Required documents
    # ------------------------------------------------------------------ #
    required_docs: List[str] = _required_docs_for_entity(entity_type, config)
    for missing_doc in required_docs:
        if missing_doc not in uploaded_doc_types:
            results.append(
                CheckResult(
                    check_name="required_docs_present",
                    status="missing",
                    severity="fixable",
                    evidence={"missing_doc_type": missing_doc},
                    score_contribution=0,
                    explanation=f"Required document missing: {missing_doc}",
                )
            )

    # ------------------------------------------------------------------ #
    # §3.13 Cross-Document Consistency Checks (CD1–CD7)
    # ------------------------------------------------------------------ #
    cd_name_thr = float(_cfg(config, "cross_doc", "name_match_threshold", default=85.0))

    # CD1 & CD2: PAN card checks (only if pan_card was uploaded)
    if "pan_card" in uploaded_doc_types and pan:
        pan_fields = extracted_fields_by_doc.get("pan_card", {})
        pan_confs = confidences_by_doc.get("pan_card", {})
        pan_raw = raw_text_by_doc.get("pan_card", "")

        cd1 = run_cd1_pan_card_number_match(
            submitted_pan=pan,
            raw_text=pan_raw,
            extracted_pan=pan_fields.get("pan_number"),
            confidence=pan_confs.get("pan_number", 1.0),
            min_confidence=min_conf,
        )
        results.append(cd1)

        cd2_prev = _prior_failed("pan_card_name_match", prior_failures)
        cd2 = run_cd2_pan_card_name_match(
            submitted_legal_name=legal_name,
            extracted_name=pan_fields.get("name_on_pan"),
            confidence=pan_confs.get("name_on_pan", 1.0),
            min_confidence=min_conf,
            failed_in_previous_run=cd2_prev,
            threshold=cd_name_thr,
        )
        results.append(cd2)

    # CD3 & CD4: GST certificate checks (only if gst_certificate was uploaded)
    if "gst_certificate" in uploaded_doc_types and gstin:
        gst_fields = extracted_fields_by_doc.get("gst_certificate", {})
        gst_confs = confidences_by_doc.get("gst_certificate", {})
        gst_raw = raw_text_by_doc.get("gst_certificate", "")

        cd3 = run_cd3_gst_cert_gstin_match(
            submitted_gstin=gstin,
            raw_text=gst_raw,
            extracted_gstin=gst_fields.get("gstin_on_cert"),
            confidence=gst_confs.get("gstin_on_cert", 1.0),
            min_confidence=min_conf,
        )
        results.append(cd3)

        cd4_prev = _prior_failed("gst_cert_name_match", prior_failures)
        cd4 = run_cd4_gst_cert_name_match(
            submitted_legal_name=legal_name,
            extracted_legal_name=gst_fields.get("legal_name_on_cert"),
            extracted_trade_name=gst_fields.get("trade_name_on_cert"),
            confidence=gst_confs.get("legal_name_on_cert", 1.0),
            min_confidence=min_conf,
            failed_in_previous_run=cd4_prev,
            threshold=cd_name_thr,
        )
        results.append(cd4)

    # CD5a & CD5b: COI checks (company only, if coi uploaded)
    if is_company and "coi" in uploaded_doc_types and cin:
        coi_fields = extracted_fields_by_doc.get("coi", {})
        coi_confs = confidences_by_doc.get("coi", {})
        coi_raw = raw_text_by_doc.get("coi", "")

        cd5a = run_cd5a_coi_cin_match(
            submitted_cin=cin,
            raw_text=coi_raw,
            extracted_cin=coi_fields.get("cin_on_coi"),
            confidence=coi_confs.get("cin_on_coi", 1.0),
            min_confidence=min_conf,
        )
        results.append(cd5a)

        cd5b_prev = _prior_failed("coi_name_match", prior_failures)
        cd5b = run_cd5b_coi_name_match(
            submitted_legal_name=legal_name,
            extracted_company_name=coi_fields.get("company_name_on_coi"),
            confidence=coi_confs.get("company_name_on_coi", 1.0),
            min_confidence=min_conf,
            failed_in_previous_run=cd5b_prev,
            threshold=cd_name_thr,
        )
        results.append(cd5b)

    # CD6: Cheque IFSC & Account last4 match (if cancelled_cheque or bank_letter uploaded)
    has_cheque_doc = "cancelled_cheque" in uploaded_doc_types or "bank_letter" in uploaded_doc_types
    if has_cheque_doc and ifsc:
        cheque_doc_type = "cancelled_cheque" if "cancelled_cheque" in uploaded_doc_types else "bank_letter"
        chq_fields = extracted_fields_by_doc.get(cheque_doc_type, {})
        chq_confs = confidences_by_doc.get(cheque_doc_type, {})
        chq_raw = raw_text_by_doc.get(cheque_doc_type, "")

        sub_last4 = submission.get("bank_account_number_last4") or ""
        cd6 = run_cd6_cheque_ifsc_account_match(
            submitted_ifsc=ifsc,
            submitted_last4=sub_last4,
            raw_text=chq_raw,
            extracted_ifsc=chq_fields.get("ifsc_on_cheque"),
            extracted_last4=chq_fields.get("account_last4_on_cheque"),
            ifsc_conf=chq_confs.get("ifsc_on_cheque", 1.0),
            last4_conf=chq_confs.get("account_last4_on_cheque", 1.0),
            min_confidence=min_conf,
        )
        results.append(cd6)

    # CD7: GST certificate address vs address proof (if both uploaded)
    if "gst_certificate" in uploaded_doc_types and "address_proof" in uploaded_doc_types:
        gst_fields = extracted_fields_by_doc.get("gst_certificate", {})
        addr_fields = extracted_fields_by_doc.get("address_proof", {})
        gst_state = gst_fields.get("principal_place_state_code")
        proof_state = addr_fields.get("address_state_code") or address_state_code
        cd7 = run_cd7_gst_cert_address_vs_proof(
            gst_state_code=gst_state,
            proof_state_code=proof_state,
            confidence=confidences_by_doc.get("address_proof", {}).get("address_state_code", 1.0),
            min_confidence=min_conf,
        )
        if cd7 is not None:
            results.append(cd7)

    return results


# ---------------------------------------------------------------------------
# Internal helper checks
# ---------------------------------------------------------------------------

def _mca_name_check(cin: str, mca_name: str, legal_name: str) -> CheckResult:
    """C5: compare MCA-registered name vs submitted legal name."""
    from app.validators.bank_name import normalise_name
    from rapidfuzz.fuzz import token_set_ratio
    score = token_set_ratio(normalise_name(mca_name), normalise_name(legal_name))
    if score >= 85:
        return CheckResult(
            check_name="cin_registered_name_match",
            status="pass",
            severity="hard",
            evidence={"mca_name": mca_name, "legal_name": legal_name, "score": score},
            score_contribution=0,
            explanation=f"Company name matches MCA records (score={score:.0f}).",
        )
    return CheckResult(
        check_name="cin_registered_name_match",
        status="fail",
        severity="hard",
        evidence={"mca_name": mca_name, "legal_name": legal_name, "score": score},
        score_contribution=0,
        explanation=(
            f"Legal name '{legal_name}' does not match MCA-registered name "
            f"'{mca_name}' (score={score:.0f}, threshold=85)."
        ),
    )


def _mca_status_check(cin: str, mca_status: str) -> CheckResult:
    """C6: MCA company active status."""
    hard_statuses = ("struck_off", "under_liquidation")
    is_hard = mca_status in hard_statuses
    return CheckResult(
        check_name="mca_company_status",
        status="fail" if is_hard else "pass",
        severity="hard" if is_hard else "soft",
        evidence={"cin": cin, "mca_status": mca_status},
        score_contribution=0,
        explanation=f"MCA company status: {mca_status}",
    )


def _required_docs_for_entity(entity_type: str, config: Config) -> List[str]:
    defaults: Dict[str, List[str]] = {
        "proprietorship": ["pan_card", "gst_certificate", "cancelled_cheque"],
        "partnership": ["pan_card", "gst_certificate", "cancelled_cheque"],
        "llp": ["pan_card", "gst_certificate", "cancelled_cheque", "llpin_cert"],
        "pvt_ltd": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
        "pub_ltd": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
        "section8": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
    }
    rd = getattr(config, "required_documents", None)
    if rd and isinstance(rd, dict):
        return rd.get(entity_type, defaults.get(entity_type, []))
    return defaults.get(entity_type, [])
