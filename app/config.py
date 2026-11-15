"""
app/config.py — Loads policy.yaml and exposes typed Config dataclass.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


@dataclass
class DecisionConfig:
    human_review_threshold: float = 20.0


@dataclass
class BankNameMatchConfig:
    pass_threshold: float = 90.0
    review_threshold: float = 75.0
    fail_score_contribution: float = 10.0


@dataclass
class ExtractionConfig:
    min_confidence: float = 0.80


@dataclass
class DuplicateDetectionConfig:
    name_fuzzy_threshold: float = 92.0
    hmac_secret: str = ""


@dataclass
class PdfMetadataConfig:
    editing_tool_score: float = 5.0
    moddate_gap_days: int = 30
    moddate_gap_score: float = 3.0
    impossible_date_score: float = 10.0
    max_total_score: float = 10.0


@dataclass
class RiskWeightsConfig:
    adapter_unavailable: float = 5.0
    bank_name_warn: float = 10.0
    pdf_editing_tool: float = 5.0
    pdf_moddate_gap: float = 3.0
    pdf_impossible_date: float = 10.0
    cin_state_mismatch: float = 5.0
    duplicate_name_fuzzy: float = 15.0
    gst_state_vs_address_state: float = 10.0


@dataclass
class AdaptersConfig:
    gstin_status: str = "mock"
    mca_status: str = "mock"
    debarment: str = "mock"
    internal_blocklist: str = "mock"
    ifsc_lookup: str = "mock"
    pan_status: str = "mock"
    notifier: str = "outbox"


@dataclass
class BuyerConfig:
    name: str = ""
    gstin: str = ""


@dataclass
class Config:
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    bank_name_match: BankNameMatchConfig = field(default_factory=BankNameMatchConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    duplicate_detection: DuplicateDetectionConfig = field(default_factory=DuplicateDetectionConfig)
    pdf_metadata: PdfMetadataConfig = field(default_factory=PdfMetadataConfig)
    risk_weights: RiskWeightsConfig = field(default_factory=RiskWeightsConfig)
    adapters: AdaptersConfig = field(default_factory=AdaptersConfig)
    buyer: BuyerConfig = field(default_factory=BuyerConfig)
    required_documents: Dict[str, List[str]] = field(default_factory=dict)
    demo_mode: bool = False


def load_config(path: str = "policy.yaml") -> Config:
    """Load configuration from a YAML file, with env-var overrides."""
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    # --- decision ---
    dec_raw = raw.get("decision", {})
    decision = DecisionConfig(
        human_review_threshold=float(dec_raw.get("human_review_threshold", 20)),
    )

    # --- bank_name_match ---
    bnm_raw = raw.get("bank_name_match", {})
    bank_name_match = BankNameMatchConfig(
        pass_threshold=float(bnm_raw.get("pass_threshold", 90)),
        review_threshold=float(bnm_raw.get("review_threshold", 75)),
        fail_score_contribution=float(bnm_raw.get("fail_score_contribution", 10)),
    )

    # --- extraction ---
    ext_raw = raw.get("extraction", {})
    extraction = ExtractionConfig(
        min_confidence=float(ext_raw.get("min_confidence", 0.80)),
    )

    # --- duplicate_detection (allow HMAC_SECRET env override) ---
    dd_raw = raw.get("duplicate_detection", {})
    hmac_secret = os.environ.get("HMAC_SECRET", dd_raw.get("hmac_secret", ""))
    duplicate_detection = DuplicateDetectionConfig(
        name_fuzzy_threshold=float(dd_raw.get("name_fuzzy_threshold", 92)),
        hmac_secret=hmac_secret,
    )

    # --- pdf_metadata ---
    pdf_raw = raw.get("pdf_metadata", {})
    pdf_metadata = PdfMetadataConfig(
        editing_tool_score=float(pdf_raw.get("editing_tool_score", 5)),
        moddate_gap_days=int(pdf_raw.get("moddate_gap_days", 30)),
        moddate_gap_score=float(pdf_raw.get("moddate_gap_score", 3)),
        impossible_date_score=float(pdf_raw.get("impossible_date_score", 10)),
        max_total_score=float(pdf_raw.get("max_total_score", 10)),
    )

    # --- risk_weights ---
    rw_raw = raw.get("risk_weights", {})
    risk_weights = RiskWeightsConfig(
        adapter_unavailable=float(rw_raw.get("adapter_unavailable", 5)),
        bank_name_warn=float(rw_raw.get("bank_name_warn", 10)),
        pdf_editing_tool=float(rw_raw.get("pdf_editing_tool", 5)),
        pdf_moddate_gap=float(rw_raw.get("pdf_moddate_gap", 3)),
        pdf_impossible_date=float(rw_raw.get("pdf_impossible_date", 10)),
        cin_state_mismatch=float(rw_raw.get("cin_state_mismatch", 5)),
        duplicate_name_fuzzy=float(rw_raw.get("duplicate_name_fuzzy", 15)),
        gst_state_vs_address_state=float(rw_raw.get("gst_state_vs_address_state", 10)),
    )

    # --- adapters ---
    adp_raw = raw.get("adapters", {})
    adapters = AdaptersConfig(
        gstin_status=adp_raw.get("gstin_status", "mock"),
        mca_status=adp_raw.get("mca_status", "mock"),
        debarment=adp_raw.get("debarment", "mock"),
        internal_blocklist=adp_raw.get("internal_blocklist", "mock"),
        ifsc_lookup=adp_raw.get("ifsc_lookup", "mock"),
        pan_status=adp_raw.get("pan_status", "mock"),
        notifier=adp_raw.get("notifier", "outbox"),
    )

    # --- buyer ---
    b_raw = raw.get("buyer", {})
    buyer = BuyerConfig(
        name=b_raw.get("name", ""),
        gstin=b_raw.get("gstin", ""),
    )

    # --- required_documents ---
    required_documents: Dict[str, List[str]] = raw.get("required_documents", {})

    return Config(
        decision=decision,
        bank_name_match=bank_name_match,
        extraction=extraction,
        duplicate_detection=duplicate_detection,
        pdf_metadata=pdf_metadata,
        risk_weights=risk_weights,
        adapters=adapters,
        buyer=buyer,
        required_documents=required_documents,
        demo_mode=bool(raw.get("demo_mode", False)),
    )
