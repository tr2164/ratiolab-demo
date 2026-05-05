"""
Allowance for Doubtful Accounts data extraction from SEC EDGAR.

Uses the same two-source strategy as PP&E:
  1. edgartools XBRL  — text blocks, dimensioned facts from the latest filing
  2. Company Facts API — historical time series for ratio trending

Key computation:
    Gross AR  = AR_net + Allowance
    Allowance Ratio = Allowance / Gross AR
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.services.sec_data import (
    get_xbrl_filing,
    get_annual_values,
    extract_text_blocks,
    _clean_member,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# XBRL concept lists (ordered by specificity — first match wins)
# ---------------------------------------------------------------------------

AR_NET_CONCEPTS = [
    "us-gaap:AccountsReceivableNetCurrent",
    "us-gaap:AccountsReceivableNet",
    "us-gaap:AccountsNotesAndLoansReceivableNetCurrent",
    "us-gaap:AccountsAndOtherReceivablesNetCurrent",
    "us-gaap:ReceivablesNetCurrent",
    "us-gaap:TradeAndOtherReceivablesNetCurrent",
]

ALLOWANCE_CONCEPTS = [
    "us-gaap:AllowanceForDoubtfulAccountsReceivableCurrent",
    "us-gaap:AllowanceForDoubtfulAccountsReceivable",
    "us-gaap:AllowanceForCreditLossesOnFinancingReceivablesCurrent",
    "us-gaap:FinancingReceivableAllowanceForCreditLosses",
    "us-gaap:AllowanceForNotesAndLoansReceivableCurrent",
    "us-gaap:AllowanceForLoanAndLeaseLosses",
]

BAD_DEBT_EXPENSE_CONCEPTS = [
    "us-gaap:ProvisionForDoubtfulAccounts",
    "us-gaap:ProvisionForLoanLeaseAndOtherLosses",
    "us-gaap:ProvisionForLoanAndLeaseLosses",
    "us-gaap:AllowanceForCreditLossesPurchasedWithCreditDeteriorationAmountNotPreviouslyRecognized",
]

REVENUE_CONCEPTS = [
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "us-gaap:Revenues",
    "us-gaap:SalesRevenueNet",
    "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
]

TOTAL_ASSETS_CONCEPTS = [
    "us-gaap:Assets",
]

WRITEOFF_CONCEPTS = [
    "us-gaap:AllowanceForDoubtfulAccountsReceivableWriteOffs",
    "us-gaap:FinancingReceivableAllowanceForCreditLossesWriteOffs",
    "us-gaap:AllowanceForCreditLossesOnFinancingReceivablesChargedOff",
]

RECOVERY_CONCEPTS = [
    "us-gaap:AllowanceForDoubtfulAccountsReceivableRecoveries",
    "us-gaap:FinancingReceivableAllowanceForCreditLossesRecovery",
]

ALLOWANCE_TEXT_BLOCK_CONCEPTS = [
    "AllowanceForCreditLossesTextBlock",
    "CreditLossFinancialInstrumentTextBlock",
    "AllowanceForCreditLossesOnFinancingReceivablesTableTextBlock",
    "LoansNotesTradeAndOtherReceivablesDisclosureTextBlock",
    "TradeAndOtherAccountsReceivablePolicy",
    "ReceivablesPolicyTextBlock",
    "FinancingReceivablesTextBlock",
    "AccountsReceivableAllowanceForCreditLossTableTextBlock",
    "ScheduleOfAccountsNotesLoansAndFinancingReceivableTextBlock",
    "AccountsReceivableTextBlock",
]

# Company Facts API concepts (shorter names without namespace)
HISTORICAL_AR_NET = [
    "AccountsReceivableNetCurrent",
    "AccountsReceivableNet",
    "AccountsNotesAndLoansReceivableNetCurrent",
]

HISTORICAL_ALLOWANCE = [
    "AllowanceForDoubtfulAccountsReceivableCurrent",
    "AllowanceForDoubtfulAccountsReceivable",
    "FinancingReceivableAllowanceForCreditLosses",
    "AllowanceForLoanAndLeaseLosses",
]

HISTORICAL_BAD_DEBT = [
    "ProvisionForDoubtfulAccounts",
    "ProvisionForLoanLeaseAndOtherLosses",
]

HISTORICAL_REVENUE = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]

HISTORICAL_WRITEOFFS = [
    "AllowanceForDoubtfulAccountsReceivableWriteOffs",
    "FinancingReceivableAllowanceForCreditLossesWriteOffs",
]

HISTORICAL_RECOVERIES = [
    "AllowanceForDoubtfulAccountsReceivableRecoveries",
    "FinancingReceivableAllowanceForCreditLossesRecovery",
]


# ---------------------------------------------------------------------------
# XBRL extraction helpers
# ---------------------------------------------------------------------------

def _extract_undimensioned(
    facts_df: pd.DataFrame, concept_list: list[str]
) -> dict | None:
    """Find the first matching concept with undimensioned numeric values."""
    is_dim = facts_df.get(
        "is_dimensioned", pd.Series(False, index=facts_df.index)
    ).astype(bool)

    for concept in concept_list:
        mask = (
            (facts_df["concept"] == concept)
            & (facts_df["numeric_value"].notna())
            & (~is_dim)
        )
        matches = facts_df[mask]
        if matches.empty:
            continue

        values: dict[int, float] = {}
        for _, row in matches.iterrows():
            fy = row.get("fiscal_year")
            if pd.notna(fy):
                values[int(fy)] = float(row["numeric_value"])

        if values:
            return {
                "xbrl_concept": concept,
                "values": dict(sorted(values.items())),
            }
    return None


def _get_historical(
    ticker: str, concept_list: list[str], instant: bool = True
) -> dict[int, float]:
    """Try multiple Company Facts API concepts, return first that has data."""
    for concept in concept_list:
        try:
            vals = get_annual_values(ticker, concept, instant=instant)
            if vals:
                return vals
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# Receivable segment extraction (dimensioned AR breakdown)
# ---------------------------------------------------------------------------

_AR_GROSS_CONCEPTS = [
    "us-gaap:AccountsReceivableGrossCurrent",
    "us-gaap:AccountsReceivableGross",
    "us-gaap:AccountsNotesAndLoansReceivableGrossCurrent",
]

_AR_NET_SEGMENT_CONCEPTS = [
    "us-gaap:AccountsReceivableNetCurrent",
    "us-gaap:AccountsReceivableNet",
]

_AR_SEGMENT_AXES = [
    "dim_srt_ProductOrServiceAxis",
    "dim_us-gaap_AccountsNotesLoansAndFinancingReceivableByReceivableTypeAxis",
    "dim_us-gaap_ConcentrationRiskByBenchmarkAxis",
    "dim_us-gaap_FinancialInstrumentAxis",
]


def extract_receivable_segments(facts_df: pd.DataFrame) -> list[dict]:
    """
    Extract accounts receivable broken down by segment/product type.
    Casino companies like LVS report casino, hotel, mall receivables separately.
    Returns list of {segment_label, xbrl_member, xbrl_concept, dimension_axis, values}.
    """
    available_axes = [ax for ax in _AR_SEGMENT_AXES if ax in facts_df.columns]
    if not available_axes:
        return []

    # Try gross AR concepts first (preferred — shows full receivable before allowance)
    all_concepts = _AR_GROSS_CONCEPTS + _AR_NET_SEGMENT_CONCEPTS
    concept_mask = pd.Series(False, index=facts_df.index)
    matched_concept = None

    for concept in all_concepts:
        m = (facts_df["concept"] == concept) & (facts_df["numeric_value"].notna())
        if m.any():
            concept_mask = concept_mask | m
            if matched_concept is None:
                matched_concept = concept

    if not concept_mask.any() or matched_concept is None:
        return []

    dim_rows = facts_df[concept_mask].copy()

    if "fiscal_period" in dim_rows.columns:
        fy_rows = dim_rows[dim_rows["fiscal_period"] == "FY"]
        if not fy_rows.empty:
            dim_rows = fy_rows

    segments: list[dict] = []
    seen: set[str] = set()

    for ax in available_axes:
        if ax not in dim_rows.columns:
            continue
        ax_rows = dim_rows[dim_rows[ax].notna()]
        if ax_rows.empty:
            continue

        for member, grp in ax_rows.groupby(ax):
            member_str = str(member)
            member_label = _clean_member(member_str)
            if member_label in seen:
                continue
            seen.add(member_label)

            year_vals: dict[int, float] = {}
            concept_used = matched_concept
            for _, row in grp.iterrows():
                fy = row.get("fiscal_year")
                if pd.notna(fy):
                    yr = int(fy)
                    val = float(row["numeric_value"])
                    if yr not in year_vals or abs(val) > abs(year_vals[yr]):
                        year_vals[yr] = val
                        concept_used = row["concept"]

            if year_vals:
                segments.append({
                    "segment_label": member_label,
                    "xbrl_member": member_str,
                    "xbrl_concept": concept_used,
                    "dimension_axis": ax.replace("dim_", ""),
                    "values": dict(sorted(year_vals.items())),
                })

    return segments


# ---------------------------------------------------------------------------
# Main extraction functions
# ---------------------------------------------------------------------------

def extract_allowance_totals(
    ticker: str, facts_df: pd.DataFrame
) -> dict[str, dict]:
    """
    Extract consolidated allowance-related totals from XBRL + Company Facts.
    Returns dict with keys: ar_net, allowance, revenue, total_assets, bad_debt_expense.
    """
    totals: dict[str, dict] = {}

    # --- XBRL undimensioned first ---
    xbrl_fields = {
        "ar_net": AR_NET_CONCEPTS,
        "allowance": ALLOWANCE_CONCEPTS,
        "bad_debt_expense": BAD_DEBT_EXPENSE_CONCEPTS,
        "revenue": REVENUE_CONCEPTS,
        "total_assets": TOTAL_ASSETS_CONCEPTS,
    }

    for key, concepts in xbrl_fields.items():
        result = _extract_undimensioned(facts_df, concepts)
        if result:
            totals[key] = result

    # --- Company Facts API fallback ---
    fallback_fields = {
        "ar_net": (HISTORICAL_AR_NET, True),
        "allowance": (HISTORICAL_ALLOWANCE, True),
        "bad_debt_expense": (HISTORICAL_BAD_DEBT, False),
        "revenue": (HISTORICAL_REVENUE, False),
        "total_assets": (["Assets"], True),
    }

    for key, (concepts, instant) in fallback_fields.items():
        if key in totals:
            continue
        vals = _get_historical(ticker, concepts, instant=instant)
        if vals:
            concept_used = next(
                (c for c in concepts if get_annual_values(ticker, c, instant=instant)),
                concepts[0],
            )
            totals[key] = {
                "xbrl_concept": f"us-gaap:{concept_used} (via Company Facts API)",
                "values": dict(sorted(vals.items())),
            }
            logger.info(f"{key}: using Company Facts API fallback ({concept_used})")

    # --- Compute Gross AR ---
    if "ar_net" in totals and "allowance" in totals:
        ar_vals = totals["ar_net"]["values"]
        allow_vals = totals["allowance"]["values"]
        gross_vals: dict[int, float] = {}
        for yr in set(ar_vals.keys()) | set(allow_vals.keys()):
            ar = ar_vals.get(yr)
            al = allow_vals.get(yr)
            if ar is not None and al is not None:
                gross_vals[yr] = ar + abs(al)
        if gross_vals:
            totals["gross_ar"] = {
                "xbrl_concept": "Computed: AR Net + Allowance",
                "values": dict(sorted(gross_vals.items())),
            }

    return totals


def compute_ratios(
    totals: dict[str, dict],
) -> dict[str, dict[int, float | None]]:
    """
    Compute derived ratios from totals:
      - allowance_ratio: Allowance / Gross AR
      - bad_debt_to_revenue: Bad Debt Expense / Revenue
      - dso: (AR Net / Revenue) * 365
    """
    computed: dict[str, dict[int, float | None]] = {}

    # Allowance Ratio
    if "gross_ar" in totals and "allowance" in totals:
        gross_vals = totals["gross_ar"]["values"]
        allow_vals = totals["allowance"]["values"]
        ratio: dict[int, float | None] = {}
        for yr in sorted(set(gross_vals.keys()) | set(allow_vals.keys())):
            g = gross_vals.get(yr)
            a = allow_vals.get(yr)
            if g and a:
                ratio[yr] = (abs(a) / g) * 100
            else:
                ratio[yr] = None
        computed["allowance_ratio"] = ratio

    # Bad Debt / Revenue
    if "bad_debt_expense" in totals and "revenue" in totals:
        bde_vals = totals["bad_debt_expense"]["values"]
        rev_vals = totals["revenue"]["values"]
        bd_rev: dict[int, float | None] = {}
        for yr in sorted(set(bde_vals.keys()) | set(rev_vals.keys())):
            b = bde_vals.get(yr)
            r = rev_vals.get(yr)
            if b is not None and r:
                bd_rev[yr] = (abs(b) / r) * 100
            else:
                bd_rev[yr] = None
        computed["bad_debt_to_revenue"] = bd_rev

    # Days Sales Outstanding
    if "ar_net" in totals and "revenue" in totals:
        ar_vals = totals["ar_net"]["values"]
        rev_vals = totals["revenue"]["values"]
        dso: dict[int, float | None] = {}
        for yr in sorted(set(ar_vals.keys()) | set(rev_vals.keys())):
            a = ar_vals.get(yr)
            r = rev_vals.get(yr)
            if a is not None and r:
                dso[yr] = (abs(a) / r) * 365
            else:
                dso[yr] = None
        computed["dso"] = dso

    return computed


def extract_allowance_disclosures(facts_df: pd.DataFrame) -> list[dict]:
    """Pull all relevant credit-loss/allowance text block disclosures."""
    blocks: list[dict] = []
    seen_concepts: set[str] = set()

    for concept_substr in ALLOWANCE_TEXT_BLOCK_CONCEPTS:
        for b in extract_text_blocks(facts_df, concept_substr):
            if b["xbrl_concept"] not in seen_concepts:
                seen_concepts.add(b["xbrl_concept"])
                blocks.append(b)

    return blocks


def extract_rollforward(ticker: str) -> dict[str, dict[int, float]] | None:
    """
    Attempt to extract the allowance rollforward components
    (provision, write-offs, recoveries) from Company Facts API.
    """
    result: dict[str, dict[int, float]] = {}

    provision = _get_historical(ticker, HISTORICAL_BAD_DEBT, instant=False)
    if provision:
        result["provision"] = provision

    writeoffs = _get_historical(ticker, HISTORICAL_WRITEOFFS, instant=False)
    if writeoffs:
        result["write_offs"] = writeoffs

    recoveries = _get_historical(ticker, HISTORICAL_RECOVERIES, instant=False)
    if recoveries:
        result["recoveries"] = recoveries

    return result if result else None


def get_historical_series(ticker: str) -> dict[str, dict[int, float]]:
    """
    Build a full historical time series for trend analysis.
    Returns labelled series for charting.
    """
    series: dict[str, dict[int, float]] = {}

    ar = _get_historical(ticker, HISTORICAL_AR_NET, instant=True)
    if ar:
        series["AR Net"] = ar

    allowance = _get_historical(ticker, HISTORICAL_ALLOWANCE, instant=True)
    if allowance:
        series["Allowance"] = allowance

    # Compute Gross AR and Allowance Ratio from the historical series
    if ar and allowance:
        gross: dict[int, float] = {}
        ratio: dict[int, float] = {}
        for yr in set(ar.keys()) & set(allowance.keys()):
            g = ar[yr] + abs(allowance[yr])
            gross[yr] = g
            if g > 0:
                ratio[yr] = round((abs(allowance[yr]) / g) * 100, 2)
        if gross:
            series["Gross AR"] = gross
        if ratio:
            series["Allowance Ratio %"] = ratio

    bde = _get_historical(ticker, HISTORICAL_BAD_DEBT, instant=False)
    if bde:
        series["Bad Debt Expense"] = bde

    revenue = _get_historical(ticker, HISTORICAL_REVENUE, instant=False)
    if revenue:
        series["Revenue"] = revenue

    return series


def compute_forensic_flags(
    totals: dict[str, dict],
    computed: dict[str, dict[int, float | None]],
    historical: dict[str, dict[int, float]],
) -> list[dict]:
    """
    Automated earnings management detection flags.
    Returns list of {severity, flag, detail, year} dicts.
    """
    flags: list[dict] = []

    ratio_series = computed.get("allowance_ratio", {})
    years = sorted(yr for yr, v in ratio_series.items() if v is not None)

    # Flag 1: Ratio dropped >3% while revenue fell
    rev_series = historical.get("Revenue", {})
    for i in range(1, len(years)):
        yr = years[i]
        prev_yr = years[i - 1]
        curr_ratio = ratio_series.get(yr)
        prev_ratio = ratio_series.get(prev_yr)
        curr_rev = rev_series.get(yr)
        prev_rev = rev_series.get(prev_yr)

        if curr_ratio is None or prev_ratio is None:
            continue

        ratio_change = curr_ratio - prev_ratio

        if ratio_change < -3 and curr_rev and prev_rev and curr_rev < prev_rev:
            flags.append({
                "severity": "red",
                "flag": "Ratio dropped while revenue fell",
                "detail": (
                    f"Allowance ratio fell {abs(ratio_change):.1f}pp "
                    f"({prev_ratio:.1f}% → {curr_ratio:.1f}%) while revenue also "
                    f"declined — possible reserve release to prop up income."
                ),
                "year": yr,
            })

    # Flag 2: Ratio diverges significantly from prior year (>5pp swing)
    for i in range(1, len(years)):
        yr = years[i]
        prev_yr = years[i - 1]
        curr = ratio_series.get(yr)
        prev = ratio_series.get(prev_yr)
        if curr is None or prev is None:
            continue
        swing = abs(curr - prev)
        if swing > 5:
            direction = "increased" if curr > prev else "decreased"
            flags.append({
                "severity": "yellow",
                "flag": f"Large ratio swing ({swing:.1f}pp)",
                "detail": (
                    f"Allowance ratio {direction} from {prev:.1f}% to {curr:.1f}% — "
                    f"a {swing:.1f} percentage-point swing warrants investigation."
                ),
                "year": yr,
            })

    # Flag 3: Write-offs exceeding prior allowance
    allow_series = historical.get("Allowance", {})
    wo_series = historical.get("Bad Debt Expense", {})  # proxy
    writeoff_series = {
        yr: v for k, vals in historical.items()
        if "write" in k.lower() or "charge" in k.lower()
        for yr, v in vals.items()
    }
    # Use bad debt expense as proxy for under-provisioning check
    if allow_series and wo_series:
        for yr in sorted(set(allow_series.keys()) & set(wo_series.keys())):
            if yr - 1 in allow_series:
                prior_allowance = abs(allow_series[yr - 1])
                expense = abs(wo_series[yr])
                if prior_allowance > 0 and expense > prior_allowance * 1.5:
                    flags.append({
                        "severity": "red",
                        "flag": "Bad debt expense exceeds prior allowance",
                        "detail": (
                            f"Expense of {expense:,.0f} significantly exceeded the "
                            f"prior year's allowance of {prior_allowance:,.0f} — "
                            f"suggests under-provisioning in the prior period."
                        ),
                        "year": yr,
                    })

    # Flag 4: Stable and well-provisioned (positive signal)
    if len(years) >= 3:
        recent_ratios = [
            ratio_series[yr] for yr in years[-3:]
            if ratio_series.get(yr) is not None
        ]
        if len(recent_ratios) >= 3:
            max_swing = max(recent_ratios) - min(recent_ratios)
            if max_swing < 3:
                flags.append({
                    "severity": "green",
                    "flag": "Ratio stable over recent period",
                    "detail": (
                        f"Allowance ratio has been stable at "
                        f"{sum(recent_ratios)/len(recent_ratios):.1f}% "
                        f"(±{max_swing:.1f}pp) over the last {len(recent_ratios)} years — "
                        f"consistent provisioning."
                    ),
                    "year": years[-1],
                })

    return flags
