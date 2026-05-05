"""
6-Tab Model Builder

Builds the complete integrated financial model with supporting schedules.

Build pipeline per projected year (dependency order):
  1.  Information tab (exogenous CAPEX, debt, amortization)
  2.  PP&E schedule  (depreciation, intangibles roll-forward)
  3.  IS Phase 1     (Sales, Units, Price, R&D, SG&A, Other OpEx)
  4.  BS ratios      (Cash = Cash/Sales × Sales, DTL = DTL/Sales × Sales)
  5.  Working Capital (AR, AP, inventory, BDE — reads Sales/Units from IS Phase 1)
  6.  Debt LTD       (LTD roll-forward, preliminary principal/interest split)
  7.  IS Phase 2     (EBIT → NI — reads COGS/BDE from WC, Dep/Amort from PPE)
  8.  WC finalise    (Accrued Income Taxes — needs Tax Expense from IS Phase 2)
  9.  SCF            (derives Revolver plug — Cash already set from step 4)
  10. Debt Revolver   (Revolver balance from SCF plug)
  11. BS assembly     (Total Assets, Total Liabilities, Equity, Balance Check)
  12. Circular solver (Revolver → Interest → NI → RE → Cash → Revolver)

The circular reference converges in ~5 iterations.
"""
import logging
import math
from typing import Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.company import Company
from app.models.financial_data import FinancialData
from app.models.data_map import DataMap
from app.models.model import Model, ModelLineItem, Driver, ModelAssumption
from app.services.model_template import (
    get_default_template, get_template_line_map, get_template_assumption_map,
    get_template_lines_by_tab, DEFAULT_ASSUMPTIONS, TAB_ORDER,
)

logger = logging.getLogger(__name__)

YearData = Dict[str, float]
AllData = Dict[int, YearData]


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════

async def build_full_model(company_id: int, db: AsyncSession, projection_years: int = 5) -> Model:
    """Build the complete 6-tab integrated model for a company."""
    company = await db.get(Company, company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    model = Model(
        company_id=company_id,
        name=f"{company.ticker} 6-Tab Financial Model",
        status="building",
        projection_years=projection_years,
        template_version="v2",
    )
    db.add(model)
    await db.flush()

    try:
        hist_data = await _aggregate_historical(company_id, model.id, db)
        all_years = sorted(hist_data.keys())
        if not all_years:
            raise ValueError(f"No historical data found for company {company_id}")

        # Keep only the 3 most recent historical years
        HIST_YEARS = 3
        if len(all_years) > HIST_YEARS:
            for y in all_years[:-HIST_YEARS]:
                del hist_data[y]
        years = sorted(hist_data.keys())

        last_hist = max(years)
        assumptions = _load_default_assumptions()

        _derive_missing_cash(hist_data)
        _calibrate_assumptions(assumptions, hist_data, last_hist)
        _backfill_historical_subtotals(hist_data)
        _post_backfill_calibration(assumptions, hist_data)

        await _persist_assumptions(model.id, assumptions, db)

        all_data: AllData = dict(hist_data)

        for offset in range(1, projection_years + 1):
            proj_year = last_hist + offset
            period_idx = offset
            prev = all_data.get(proj_year - 1, {})
            d: YearData = {}

            # Pipeline — each step reads only from d (current year) or prev
            _project_info(d, prev, assumptions, period_idx)
            _project_ppe(d, prev, assumptions, period_idx)
            _project_is_revenue(d, prev, assumptions, period_idx)
            _project_bs_ratios(d, prev, assumptions, period_idx)
            _project_wc(d, prev, all_data, assumptions, period_idx)
            _project_debt_ltd(d, prev, assumptions, period_idx)
            _project_is_expenses(d, prev, assumptions, period_idx)
            _project_wc_taxes(d, prev, assumptions, period_idx)
            _project_scf(d, prev, all_data, assumptions, period_idx)
            _project_debt_revolver(d, prev)
            _project_bs_assemble(d, prev, assumptions, period_idx)
            _solve_circular(d, prev, all_data, assumptions, period_idx)

            all_data[proj_year] = d

        _write_line_items(model.id, all_data, years, projection_years, last_hist, db)

        model.status = "ready"
    except Exception as e:
        model.status = "error"
        logger.error(f"Model build failed: {e}", exc_info=True)
        raise
    finally:
        await db.commit()

    return model


# ═══════════════════════════════════════════════════════════════════════════
# Stage 1: Aggregate Historical Data
# ═══════════════════════════════════════════════════════════════════════════

async def _aggregate_historical(
    company_id: int, model_id: int, db: AsyncSession
) -> AllData:
    """Load historical data using DataMap as the source of truth."""
    result = await db.execute(
        select(FinancialData).where(FinancialData.company_id == company_id)
    )
    raw_data = result.scalars().all()

    result = await db.execute(
        select(DataMap).where(DataMap.company_id == company_id)
    )
    all_maps = result.scalars().all()

    map_by_name: Dict[str, Tuple[str, int, int, str]] = {}
    for m in all_maps:
        map_by_name[m.raw_account_name] = (m.model_line, m.sign_flip, m.sort_order, m.statement_type)

    contributions: Dict[Tuple[int, str], list] = {}
    line_meta: Dict[str, Tuple[str, int]] = {}

    for raw in raw_data:
        mapping = map_by_name.get(raw.account_name)
        if not mapping:
            continue
        ml, sign, sort, stmt = mapping
        year = raw.year
        amount = (raw.amount or 0) * sign
        line_meta[ml] = (stmt, sort)
        key = (year, ml)
        if key not in contributions:
            contributions[key] = []
        contributions[key].append((amount, raw.account_name))

    agg: AllData = {}
    for (year, ml), contribs in contributions.items():
        if len(contribs) > 1:
            best = max(contribs, key=lambda c: abs(c[0]))
            amount = best[0]
        else:
            amount = contribs[0][0]
        if year not in agg:
            agg[year] = {}
        agg[year][ml] = amount

    # Capture unmapped totals needed for derivation (e.g. Cash from CurrentAssetsTotal)
    _SUPPLEMENTARY = {
        "CurrentAssetsTotal": "_CurrentAssetsTotal",
        "TotalOperatingExpenses": "_TotalOperatingExpenses",
        "Assets": "_ReportedTotalAssets",
        "Liabilities": "_ReportedTotalLiabilities",
    }
    for raw in raw_data:
        internal_key = _SUPPLEMENTARY.get(raw.account_name)
        if internal_key:
            if raw.year not in agg:
                agg[raw.year] = {}
            agg[raw.year][internal_key] = raw.amount or 0

    return agg


# ═══════════════════════════════════════════════════════════════════════════
# Assumptions
# ═══════════════════════════════════════════════════════════════════════════

def _load_default_assumptions() -> Dict[str, dict]:
    """Load default assumptions as a dict keyed by name."""
    result = {}
    for a in DEFAULT_ASSUMPTIONS:
        result[a.name] = {
            "base": a.base_value,
            "step": a.step_increment,
            "type": a.step_type,
            "stmt": a.statement_type,
            "category": a.category,
            "input_type": a.input_type,
            "display_name": a.display_name or a.name,
            "description": a.description,
            "min_value": a.min_value,
            "max_value": a.max_value,
        }
    return result


def _get_assumption_value(assumptions: Dict[str, dict], name: str, period_idx: int) -> float:
    """Compute the assumption value for a given projection period.

    period_idx: 1 = first projected year, 2 = second, etc.
    For additive: base + (period_idx - 1) * step
    For multiplicative: base (constant — the rate itself doesn't step)
    """
    a = assumptions.get(name)
    if not a:
        return 0.0
    if a["type"] == "additive":
        return a["base"] + (period_idx - 1) * a["step"]
    return a["base"]


def _calibrate_assumptions(assumptions: Dict[str, dict], hist_data: AllData, last_hist: int):
    """Override default assumption base values with company-specific historical ratios.

    Uses the most recent historical year's actual data so that the first
    projected year continues the company's trend rather than snapping to
    generic defaults.
    """
    prev = hist_data.get(last_hist, {})
    sales = abs(prev.get("Sales", 0))
    if not sales:
        return

    def _set_base(name: str, value: float, allow_zero: bool = False):
        if name in assumptions and (value or allow_zero) and math.isfinite(value):
            assumptions[name]["base"] = value

    # IS ratios — use allow_zero so companies without these items don't inherit defaults
    sga = abs(prev.get("SG&A", 0))
    _set_base("SG&A/Sales", sga / sales if sga else 0, allow_zero=True)
    opex = abs(prev.get("Other Operating Expense", 0))
    _set_base("Other OpEx/Sales", opex / sales if opex else 0, allow_zero=True)

    # COGS/Sales: average across all historical years, cap at 99% to prevent
    # negative gross profit from anomalous years (e.g., large write-downs).
    cogs_ratios = []
    for yr in sorted(hist_data.keys()):
        yr_sales = abs(hist_data[yr].get("Sales", 0))
        yr_cogs = abs(hist_data[yr].get("COGS", 0))
        if yr_sales and yr_cogs:
            cogs_ratios.append(yr_cogs / yr_sales)
    if cogs_ratios:
        avg_cogs_ratio = sum(cogs_ratios) / len(cogs_ratios)
        avg_cogs_ratio = min(avg_cogs_ratio, 0.99)
        _set_base("COGS/Sales", avg_cogs_ratio)

    # BS ratios
    cash = abs(prev.get("Cash", 0))
    if cash:
        _set_base("Cash/Sales", cash / sales)
    dtl = prev.get("Deferred Income Tax", 0)
    if dtl:
        _set_base("DTL/Sales", abs(dtl / sales))

    # WC: DSO, DPO
    ar = abs(prev.get("AR, net of allowance", 0))
    if ar:
        _set_base("DSO", (ar / sales) * 365)
    cogs = abs(prev.get("COGS", 0))
    ap = abs(prev.get("Accounts Payable", 0))
    if ap and cogs:
        _set_base("DPO", (ap / cogs) * 365)

    # WC: other ratios
    defrev = abs(prev.get("Deferred Revenue", 0))
    _set_base("Deferred Rev/Sales", defrev / sales if defrev else 0, allow_zero=True)
    prepaid = abs(prev.get("Prepaid Expenses", 0))
    if sga:
        _set_base("Prepaid/SG&A", prepaid / sga, allow_zero=True)
    other_liab = abs(prev.get("Other Operating Liability", 0))
    if opex:
        _set_base("Other Op Liab/Other OpEx", other_liab / opex, allow_zero=True)
    else:
        _set_base("Other Op Liab/Other OpEx", 0, allow_zero=True)

    # Allowance/Write-off: set to 0 if company doesn't report these items
    gross_ar = abs(prev.get("Gross AR", 0))
    allowance = abs(prev.get("Allowance", 0))
    if gross_ar and allowance:
        _set_base("Allowance/Gross AR", allowance / gross_ar, allow_zero=True)
    else:
        _set_base("Allowance/Gross AR", 0, allow_zero=True)
    _set_base("Write-offs/prev sales", 0, allow_zero=True)

    # Tax rate from EBT/Tax — use absolute values so loss years still calibrate
    ebt = prev.get("EBT", 0)
    tax = prev.get("Income Tax Expense", 0)
    if ebt and abs(ebt) > 0 and tax:
        rate = abs(tax) / abs(ebt)
        if rate < 1.0:
            _set_base("Tax Rate", rate)

    # LTD interest rate from historical interest / avg LTD balance
    hist_ltd_rate = prev.get("LTD Interest Rate", 0)
    if hist_ltd_rate and 0 < hist_ltd_rate < 0.20:
        _set_base("LTD Interest Rate", hist_ltd_rate)

    # Revenue growth: use last 3 years, filter outliers, cap at ±30%
    years = sorted(hist_data.keys())
    recent = years[-4:] if len(years) >= 4 else years
    if len(recent) >= 2:
        growths = []
        for i in range(1, len(recent)):
            s_prev = hist_data[recent[i-1]].get("Sales", 0)
            s_curr = hist_data[recent[i]].get("Sales", 0)
            if s_prev and s_curr and s_prev > 0:
                g = s_curr / s_prev - 1
                if abs(g) < 1.0:
                    growths.append(g)
        if growths:
            avg_growth = max(-0.30, min(0.30, sum(growths) / len(growths)))
            _set_base("Unit Growth Rate", avg_growth)
            _set_base("Price Growth Rate", 0.0)

    logger.info(f"Calibrated {len(assumptions)} assumptions from historical data")


def _post_backfill_calibration(assumptions: Dict[str, dict], hist_data: AllData):
    """Calibrate assumptions that depend on values computed during backfill
    (e.g., Other / Unaccounted plug, which is derived in _backfill_historical_subtotals)."""
    other_vals = []
    for yr in sorted(hist_data.keys()):
        ov = hist_data[yr].get("Other / Unaccounted", 0)
        if ov:
            other_vals.append(ov)
    if other_vals and "Other/Unaccounted Avg" in assumptions:
        avg = sum(other_vals) / len(other_vals)
        if math.isfinite(avg):
            assumptions["Other/Unaccounted Avg"]["base"] = avg

    last_yr = max(hist_data.keys())
    for plug_key, assumption_key in [
        ("Other Assets (plug)", "Other Assets Avg"),
        ("Other Liabilities (plug)", "Other Liabilities Avg"),
    ]:
        val = hist_data[last_yr].get(plug_key, 0)
        if assumption_key in assumptions and val and math.isfinite(val):
            assumptions[assumption_key]["base"] = val


def _derive_missing_cash(hist_data: AllData):
    """Derive Cash from CurrentAssetsTotal when EDGAR doesn't provide a
    standalone cash field (Cash = CA Total - AR - Inventory - Prepaid)."""
    for year in sorted(hist_data.keys()):
        d = hist_data[year]
        if "Cash" not in d:
            ca_total = d.get("_CurrentAssetsTotal", 0)
            if ca_total:
                ar = d.get("AR, net of allowance", 0)
                inv = d.get("Ending Inventory ($)", d.get("Inventory", 0))
                prepaid = d.get("Prepaid Expenses", 0)
                derived_cash = ca_total - ar - inv - prepaid
                d["Cash"] = max(derived_cash, 0)
                logger.info(f"Derived Cash for {year}: {d['Cash']:,.0f} "
                            f"(CA Total {ca_total:,.0f} - AR {ar:,.0f} "
                            f"- Inv {inv:,.0f} - Prepaid {prepaid:,.0f})")


def _backfill_historical_subtotals(hist_data: AllData):
    """Compute derived subtotals for historical years so that the first
    projected year's deltas (ΔWC, ΔRE, etc.) are correct.

    Without this, prior_nwc = 0 and prior_re = 0, which creates enormous
    first-year swings and a broken balance check.
    """
    for year in sorted(hist_data.keys()):
        d = hist_data[year]

        ar = d.get("AR, net of allowance", 0)
        inv = d.get("Ending Inventory ($)", d.get("Inventory", 0))
        prepaid = d.get("Prepaid Expenses", 0)
        total_ca = ar + inv + prepaid
        d.setdefault("Total Non-Cash CA", total_ca)

        ap = d.get("Accounts Payable", 0)
        defrev = d.get("Deferred Revenue", 0)
        other_liab = d.get("Other Operating Liability", 0)
        accrued_tax = d.get("Accrued Income Taxes", 0)
        total_cl = ap + defrev + other_liab + accrued_tax
        d.setdefault("Total Non-Cash CL", total_cl)

        nwc = total_ca - total_cl
        d.setdefault("Net Working Capital", nwc)

        # BS-side values needed for the first projection
        cash = d.get("Cash", 0)
        ppe = d.get("Ending PP&E, net", d.get("PP&E, net", 0))
        intang = d.get("Ending Intangibles", d.get("Intangibles, net", 0))

        mapped_assets = cash + ar + inv + prepaid + ppe + intang
        reported_assets = d.get("_ReportedTotalAssets", 0)
        other_assets = (reported_assets - mapped_assets) if reported_assets else 0
        d["Other Assets (plug)"] = other_assets
        total_assets = mapped_assets + other_assets
        d.setdefault("Total Assets", total_assets)

        revolver = d.get("Ending Revolver Balance", d.get("Revolver", 0))
        ltd = d.get("Ending LTD Balance", d.get("Long-Term Debt", 0))
        dtl = d.get("Deferred Income Tax", 0)

        mapped_liab = ap + defrev + other_liab + accrued_tax + revolver + ltd + dtl
        reported_liab = d.get("_ReportedTotalLiabilities", 0)
        other_liab_plug = (reported_liab - mapped_liab) if reported_liab else 0
        d["Other Liabilities (plug)"] = other_liab_plug
        total_liab = mapped_liab + other_liab_plug
        d.setdefault("Total Liability", total_liab)

        # Derive equity from the BS equation: Equity = Assets - Liabilities
        total_equity = total_assets - total_liab
        d.setdefault("Total Equity", total_equity)

        stock_issue = d.get("Stock Issuance", 0)
        d.setdefault("Paid In Capital", stock_issue)

        re = total_equity - d["Paid In Capital"]
        d.setdefault("Retained Earnings", re)

    # All IS expense values must be positive (professor's convention).
    for year in sorted(hist_data.keys()):
        d = hist_data[year]
        for key in ("COGS", "Bad Debt Expense", "Depreciation", "Amortization",
                     "SG&A", "Other Operating Expense", "R&D Expense"):
            if key in d:
                d[key] = abs(d[key])

    # Derive EBIT when EDGAR doesn't provide OperatingIncomeLoss directly.
    # Fallback: Revenue - COGS - TotalOperatingExpenses, or EBT + Interest.
    for year in sorted(hist_data.keys()):
        d = hist_data[year]
        if "EBIT" not in d:
            ebt = d.get("EBT", 0)
            interest = d.get("LTD Interest Expense", 0)
            if ebt:
                d["EBIT"] = ebt + abs(interest)
                logger.info(f"Derived EBIT for {year}: {d['EBIT']:,.0f} "
                            f"(EBT {ebt:,.0f} + Interest {abs(interest):,.0f})")

    # Compute "Other / Unaccounted" residual so EBIT subtotal formula foots
    # to the EDGAR-reported value.  EBIT = Sales - SUM(all expenses).
    for year in sorted(hist_data.keys()):
        d = hist_data[year]
        ebit_reported = d.get("EBIT", 0)
        sales = d.get("Sales", 0)
        cogs = abs(d.get("COGS", 0))
        bde = abs(d.get("Bad Debt Expense", 0))
        rd = abs(d.get("R&D Expense", 0))
        sga = abs(d.get("SG&A", 0))
        opex = abs(d.get("Other Operating Expense", 0))
        dep = abs(d.get("Depreciation", 0))
        amort = abs(d.get("Amortization", 0))
        computed_ebit = sales - cogs - bde - rd - sga - opex - dep - amort
        d["Other / Unaccounted"] = computed_ebit - ebit_reported

    # Alias WC/PPE/DEBT names to their BS counterparts so both tabs have data.
    # _project_bs_assemble does this for projected years; we replicate for historical.
    _BS_ALIASES = {
        "Inventory": "Ending Inventory ($)",
        "PP&E, net": "Ending PP&E, net",
        "Intangibles, net": "Ending Intangibles",
        "Revolver": "Ending Revolver Balance",
        "Long-Term Debt": "Ending LTD Balance",
    }
    for year in hist_data:
        d = hist_data[year]
        for bs_name, source_key in _BS_ALIASES.items():
            if source_key in d:
                d.setdefault(bs_name, d[source_key])

    # Derive beginning balances and deltas from sequential year data
    years = sorted(hist_data.keys())
    for i, year in enumerate(years):
        d = hist_data[year]
        if i > 0:
            prev = hist_data[years[i - 1]]
            prior_nwc = prev.get("Net Working Capital", 0)
            d.setdefault("Beginning PP&E, net",
                         prev.get("Ending PP&E, net", prev.get("PP&E, net", 0)))
            d.setdefault("Beginning Intangibles",
                         prev.get("Ending Intangibles", prev.get("Intangibles, net", 0)))
            d.setdefault("Beginning LTD Balance",
                         prev.get("Ending LTD Balance", prev.get("Long-Term Debt", 0)))
            d.setdefault("Beginning Revolver Balance",
                         prev.get("Ending Revolver Balance", prev.get("Revolver", 0)))
        else:
            prior_nwc = d.get("Net Working Capital", 0)
        d.setdefault("Change in Working Capital", -(d.get("Net Working Capital", 0) - prior_nwc))

    # ── Backfill ratio / echo / cross-tab values for historical years ──
    # Without these, carry_forward and additive formulas in the first
    # projected year reference empty cells → 0 or #DIV/0!.
    for i, year in enumerate(years):
        d = hist_data[year]
        sales = abs(d.get("Sales", 0))
        cogs = abs(d.get("COGS", 0))
        sga = abs(d.get("SG&A", 0))
        opex = abs(d.get("Other Operating Expense", 0))
        ebt = d.get("EBT", 0)
        tax_exp = abs(d.get("Income Tax Expense", 0))
        ni = d.get("Net Income", 0)
        cash = d.get("Cash", 0)
        dtl = d.get("Deferred Income Tax", 0)
        dep = abs(d.get("Depreciation", 0))
        capex = abs(d.get("Capital expenditures", 0))
        ar = d.get("AR, net of allowance", 0)
        ap = d.get("Accounts Payable", 0)
        defrev = d.get("Deferred Revenue", 0)
        other_liab = d.get("Other Operating Liability", 0)
        accrued_tax = d.get("Accrued Income Taxes", 0)

        # IS ratios
        if sales:
            d.setdefault("SG&A/Sales", sga / sales)
            d.setdefault("Other OpEx/Sales", opex / sales)
        if ebt and abs(ebt) > 0:
            d.setdefault("Tax Rate", abs(tax_exp / ebt) if tax_exp else 0.21)

        # WC echo values (IS lines mirrored onto WC tab)
        d.setdefault("Sales (echo)", d.get("Sales", 0))
        d.setdefault("COGS (echo)", cogs)
        d.setdefault("BDE (echo)", abs(d.get("Bad Debt Expense", 0)))
        d.setdefault("SG&A (echo)", sga)
        d.setdefault("Other OpEx (echo)", opex)
        d.setdefault("Tax Expense (echo)", tax_exp)
        if i > 0:
            prev_d = hist_data[years[i - 1]]
            prev_dtl = prev_d.get("Deferred Income Tax", 0)
            d.setdefault("Delta DTL (echo)", dtl - prev_dtl)
        else:
            d.setdefault("Delta DTL (echo)", 0)

        # WC ratios (derived from EDGAR balances)
        if sales:
            d.setdefault("Days Sales Outstanding", (ar / sales) * 365 if ar else 0)
            d.setdefault("Deferred Rev/Sales", defrev / sales if defrev else 0)
        if cogs:
            d.setdefault("Days of Payable (DPO)", (ap / cogs) * 365 if ap else 0)
        if sga:
            d.setdefault("Prepaid/SG&A", d.get("Prepaid Expenses", 0) / sga)
        if opex:
            d.setdefault("Other Op Liab/Other OpEx", other_liab / opex if other_liab else 0)

        # Gross AR / Allowance (estimate if not available)
        gross_ar = d.get("Gross AR", 0)
        allowance = d.get("Allowance", 0)
        if not gross_ar and ar:
            d.setdefault("Gross AR", ar)
            d.setdefault("Allowance", 0)
        if gross_ar:
            d.setdefault("Allowance/Gross AR", abs(allowance) / gross_ar if allowance else 0)

        # Taxes Owe and ratio
        delta_dtl = d.get("Delta DTL (echo)", 0)
        taxes_owe = tax_exp - delta_dtl
        d.setdefault("Taxes Owe", taxes_owe)
        if taxes_owe:
            d.setdefault("Accrued Tax/Tax Owe", accrued_tax / taxes_owe if accrued_tax else 0)

        # Write-offs (default 0 for historical)
        d.setdefault("Write-offs/prev sales", 0)
        d.setdefault("Write-offs", 0)
        d.setdefault("Bad Debt Expense (implied)", abs(d.get("Bad Debt Expense", 0)))

        # BS refs and ratios
        d.setdefault("Sales (ref)", d.get("Sales", 0))
        if sales:
            d.setdefault("Cash/Sales", cash / sales if cash else 0)
            d.setdefault("DTL/Sales", abs(dtl) / sales if dtl else 0)
        d.setdefault("Net Income (ref)", ni)
        d.setdefault("Paid Dividend (ref)", 0)
        d.setdefault("Stock Issuance (ref)", d.get("Stock Issuance", 0))

        # PPE ratios
        if capex:
            d.setdefault("Dep/CAPEX", dep / capex)

        # Inventory schedule (static for historical)
        d.setdefault("Ending Inventory ($)", d.get("Inventory", 0))
        d.setdefault("Number of days", 365)

        # ── DEBT tab: backfill interest lines for historical years ──
        ltd_int = abs(d.get("LTD Interest Expense", 0))
        d.setdefault("LTD Interest Expense", ltd_int)
        d.setdefault("Total Interest Expense", ltd_int)
        d.setdefault("Interest Expense", ltd_int)
        d.setdefault("Revolver Interest", 0)

        # Derive interest rate from average balance if possible
        beg_ltd = d.get("Beginning LTD Balance", 0)
        end_ltd = d.get("Ending LTD Balance", d.get("Long-Term Debt", 0))
        avg_ltd = (beg_ltd + end_ltd) / 2 if (beg_ltd or end_ltd) else 0
        d.setdefault("Average LTD Balance", avg_ltd)
        if avg_ltd and ltd_int:
            d.setdefault("LTD Interest Rate", ltd_int / avg_ltd)

        # Cash interest revenue (derive from cash balance if rate available)
        cash_int = 0
        if cash:
            cash_rate = 0.0089
            cash_int = cash * cash_rate
        d.setdefault("Cash Interest Revenue", cash_int)
        d.setdefault("Total Interest Revenue", cash_int)
        d.setdefault("Interest Revenue", cash_int)
        d.setdefault("Cash Balance", cash)
        d.setdefault("Average Cash Balance", cash)
        d.setdefault("Cash Interest Rate", 0.0089)

        # Net Interest
        d.setdefault("Net Interest Expense", ltd_int - cash_int)

        # Revolver
        d.setdefault("Average Revolver Balance", 0)
        d.setdefault("Revolver Borrow Rate", 0.053)
        d.setdefault("Revolver Invest Rate", 0.028)

    logger.info(f"Backfilled subtotals for {len(hist_data)} historical years")


async def _persist_assumptions(model_id: int, assumptions: Dict[str, dict], db: AsyncSession):
    """Write assumption records to the DB."""
    for name, a in assumptions.items():
        db.add(ModelAssumption(
            model_id=model_id,
            name=name,
            statement_type=a["stmt"],
            base_value=a["base"],
            step_increment=a["step"],
            step_type=a["type"],
            category=a.get("category", "General"),
            input_type=a.get("input_type", "percentage"),
            display_name=a.get("display_name", name),
            description=a.get("description", ""),
            min_value=a.get("min_value"),
            max_value=a.get("max_value"),
        ))
    await db.flush()


# ═══════════════════════════════════════════════════════════════════════════
# Step 1: Information Tab
# ═══════════════════════════════════════════════════════════════════════════

def _project_info(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """Exogenous inputs: CAPEX, debt issuance/repayment, amortization.

    Historical data may store these under different keys (e.g. 'Capital expenditures'
    instead of 'CAPEX'), so we check multiple names.
    """
    prior_capex = prev.get("CAPEX", 0) or abs(prev.get("Capital expenditures", 0))
    d["CAPEX"] = prior_capex * 1.10 if prior_capex else 0

    d["Debt Issuance"] = prev.get("Debt Issuance", 0)
    d["Debt Repayment"] = prev.get("Debt Repayment", 0)

    prior_amort = prev.get("Amortization", prev.get("Amortization (input)", 0))
    if prior_amort and abs(prior_amort) > 10:
        d["Amortization"] = prior_amort * 0.8
    else:
        d["Amortization"] = prior_amort


# ═══════════════════════════════════════════════════════════════════════════
# Step 2: PP&E Schedule
# ═══════════════════════════════════════════════════════════════════════════

def _project_ppe(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """PP&E roll-forward and intangibles."""
    beg_ppe = prev.get("Ending PP&E, net", prev.get("PP&E, net", 0))
    d["Beginning PP&E, net"] = beg_ppe

    capex = d.get("CAPEX", 0)
    d["Capital expenditures"] = capex

    dep_capex_ratio = _get_assumption_value(assumptions, "Dep/CAPEX", period_idx)
    dep_capex_ratio = min(dep_capex_ratio, 1.0)
    depreciation = abs(capex) * dep_capex_ratio
    d["Depreciation"] = depreciation
    d["Asset sales/write-offs"] = 0

    d["Ending PP&E, net"] = beg_ppe + abs(capex) - depreciation

    beg_intang = prev.get("Ending Intangibles", 0)
    d["Beginning Intangibles"] = beg_intang
    amort_val = d.get("Amortization", 0)
    d["Amortization"] = abs(amort_val)
    d["Ending Intangibles"] = beg_intang - d["Amortization"]

    d["Dep/CAPEX"] = dep_capex_ratio
    d["Amortization (input)"] = d["Amortization"]


# ═══════════════════════════════════════════════════════════════════════════
# Step 3: IS Phase 1 — Revenue + Operating Expenses
# ═══════════════════════════════════════════════════════════════════════════

def _project_is_revenue(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """Compute Sales, Units, Price, and ratio-based operating expenses.

    These values are needed by WC before we can finish the IS.

    When unit-level data is unavailable (typical for EDGAR data), falls back
    to growing aggregate Sales by the combined unit+price growth rate.
    """
    unit_growth = _get_assumption_value(assumptions, "Unit Growth Rate", period_idx)
    price_growth = _get_assumption_value(assumptions, "Price Growth Rate", period_idx)

    prior_units = prev.get("Units", 0)
    prior_price = prev.get("Unit Selling Price", 0)
    prior_sales = prev.get("Sales", 0)

    has_unit_data = bool(prior_units and prior_price)

    if has_unit_data:
        units = math.ceil(prior_units * (1 + unit_growth))
        price = prior_price * (1 + price_growth)
        sales = units * price
    else:
        combined_growth = (1 + unit_growth) * (1 + price_growth) - 1
        sales = prior_sales * (1 + combined_growth) if prior_sales else 0
        units = 0
        price = 0

    d["Units"] = units
    d["Unit Selling Price"] = price
    d["Sales"] = sales
    d["_has_unit_data"] = 1.0 if has_unit_data else 0.0

    rd_growth = _get_assumption_value(assumptions, "R&D Growth Rate", period_idx)
    prior_rd = prev.get("R&D Expense", 0)
    if period_idx == 1 and not prior_rd:
        d["R&D Expense"] = 100 * 1_000_000
    else:
        d["R&D Expense"] = prior_rd * (1 + rd_growth) if prior_rd else 0

    sga_ratio = _get_assumption_value(assumptions, "SG&A/Sales", period_idx)
    d["SG&A/Sales"] = sga_ratio
    d["SG&A"] = abs(sales) * sga_ratio

    opex_ratio = _get_assumption_value(assumptions, "Other OpEx/Sales", period_idx)
    d["Other OpEx/Sales"] = opex_ratio
    d["Other Operating Expense"] = abs(sales) * opex_ratio


# ═══════════════════════════════════════════════════════════════════════════
# Step 4: BS Ratios — Cash & DTL
# ═══════════════════════════════════════════════════════════════════════════

def _project_bs_ratios(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """Set Cash and Deferred Income Tax from Sales ratios.

    Must run before SCF so that Ending Cash Balance is known.

    On the first projected year, derives ratios from prior-year actuals
    if the assumption base value is a poor fit for the company.
    """
    sales = d.get("Sales", 0)
    abs_sales = abs(sales) if sales else 1

    cash_ratio = _get_assumption_value(assumptions, "Cash/Sales", period_idx)
    d["Cash/Sales"] = cash_ratio
    d["Cash"] = abs_sales * cash_ratio

    # DTL may be negative for some companies; preserve the sign from history
    dtl_ratio = _get_assumption_value(assumptions, "DTL/Sales", period_idx)
    prior_dtl = prev.get("Deferred Income Tax", 0)
    dtl_sign = -1 if prior_dtl < 0 else 1
    d["DTL/Sales"] = dtl_ratio
    d["Deferred Income Tax"] = abs_sales * dtl_ratio * dtl_sign


# ═══════════════════════════════════════════════════════════════════════════
# Step 5: Working Capital Schedule
# ═══════════════════════════════════════════════════════════════════════════

def _project_wc(d: YearData, prev: YearData, all_data: AllData, assumptions: Dict, period_idx: int):
    """Working capital: AR, AP, inventory, BDE, and all WC ratios.

    Reads Sales, Units, SG&A, Other Operating Expense from d (set by IS Phase 1).
    Does NOT compute Accrued Income Taxes — that needs Tax Expense from IS Phase 2.

    When unit-level data is unavailable, COGS is projected using the historical
    COGS/Sales ratio instead of the weighted-average inventory model.
    """
    sales = d.get("Sales", 0)
    units = d.get("Units", 0)
    sga = d.get("SG&A", 0)
    other_opex = d.get("Other Operating Expense", 0)
    has_unit_data = d.get("_has_unit_data", 0) > 0

    dso = _get_assumption_value(assumptions, "DSO", period_idx)
    dpo = _get_assumption_value(assumptions, "DPO", period_idx)
    allowance_rate = _get_assumption_value(assumptions, "Allowance/Gross AR", period_idx)
    writeoff_rate = _get_assumption_value(assumptions, "Write-offs/prev sales", period_idx)
    inv_policy = _get_assumption_value(assumptions, "Inventory Policy", period_idx)
    def_rev_ratio = _get_assumption_value(assumptions, "Deferred Rev/Sales", period_idx)
    prepaid_ratio = _get_assumption_value(assumptions, "Prepaid/SG&A", period_idx)
    other_liab_ratio = _get_assumption_value(assumptions, "Other Op Liab/Other OpEx", period_idx)

    d["Days Sales Outstanding"] = dso
    d["Days of Payable (DPO)"] = dpo
    d["Allowance/Gross AR"] = allowance_rate
    d["Write-offs/prev sales"] = writeoff_rate
    d["Inventory Policy"] = inv_policy
    d["Deferred Rev/Sales"] = def_rev_ratio
    d["Prepaid/SG&A"] = prepaid_ratio
    d["Other Op Liab/Other OpEx"] = other_liab_ratio

    # AR / Allowance / BDE
    gross_ar = (dso / 365.0) * abs(sales) if sales else 0
    d["Gross AR"] = gross_ar
    d["Allowance"] = -gross_ar * allowance_rate
    d["AR, net of allowance"] = gross_ar + d["Allowance"]

    prior_sales = prev.get("Sales", 0)
    writeoffs = writeoff_rate * abs(prior_sales)
    prior_gross_ar = prev.get("Gross AR", 0)
    prior_allowance_abs = abs(prior_gross_ar) * allowance_rate
    current_allowance_abs = gross_ar * allowance_rate
    bde = writeoffs + current_allowance_abs - prior_allowance_abs
    d["Write-offs"] = writeoffs
    d["Bad Debt Expense (implied)"] = bde

    if has_unit_data:
        # Full inventory schedule with weighted-average costing
        proj_units = units
        d["Unit Sales"] = proj_units

        desired_end_inv = math.ceil(proj_units * inv_policy) if proj_units else 0
        d["Desired Ending Inv (units)"] = desired_end_inv

        beg_inv_units = prev.get("Desired Ending Inv (units)", 0)
        d["Beginning Inv (units)"] = beg_inv_units

        units_needed = proj_units + desired_end_inv
        d["Units needed"] = units_needed
        units_to_purchase = units_needed - beg_inv_units
        d["Units to purchase"] = units_to_purchase

        price_growth = _get_assumption_value(assumptions, "Purchase Price Growth", period_idx)
        prior_pprice = prev.get("Purchase price/unit", 0)
        purchase_price = prior_pprice * (1 + price_growth) if prior_pprice else 0
        d["Purchase price/unit"] = purchase_price

        purchase_cost = units_to_purchase * purchase_price
        d["Purchase cost"] = purchase_cost
        d["Purchase cost ($)"] = purchase_cost

        beg_inv_dollars = prev.get("Ending Inventory ($)", 0)
        d["Beginning inventory ($)"] = beg_inv_dollars

        prior_wa = prev.get("Weighted average price", 0)
        total_units_avail = beg_inv_units + units_to_purchase
        if total_units_avail > 0:
            wa_price = (beg_inv_units * prior_wa + units_to_purchase * purchase_price) / total_units_avail
        else:
            wa_price = purchase_price
        d["Weighted average price"] = wa_price

        cogs = proj_units * wa_price
        d["COGS"] = cogs

        ending_inv = desired_end_inv * wa_price
        d["Ending Inventory ($)"] = ending_inv

        d["Inventory Check"] = beg_inv_dollars + purchase_cost - cogs - ending_inv

        d["Accounts Payable"] = (dpo / 365.0) * abs(purchase_cost) if purchase_cost else 0
    else:
        # Ratio-based fallback: use calibrated COGS/Sales assumption (historical avg,
        # capped at 99%) rather than carrying the prior year's ratio forward.
        prior_cogs = abs(prev.get("COGS", 0))
        cogs_ratio = _get_assumption_value(assumptions, "COGS/Sales", period_idx)
        if not cogs_ratio:
            cogs_ratio = prior_cogs / abs(prior_sales) if prior_sales and prior_cogs else 0.50
            cogs_ratio = min(cogs_ratio, 0.99)
        cogs = abs(sales) * cogs_ratio
        d["COGS"] = cogs
        d["COGS/Sales"] = cogs_ratio

        # Inventory grows proportionally to COGS
        prior_inv = prev.get("Ending Inventory ($)", prev.get("Inventory", 0))
        if prior_cogs:
            inv_ratio = abs(prior_inv) / prior_cogs if prior_cogs else 0
        else:
            inv_ratio = 0
        d["Ending Inventory ($)"] = cogs * inv_ratio
        d["Beginning inventory ($)"] = prior_inv

        # AP from DPO on COGS
        d["Accounts Payable"] = (dpo / 365.0) * abs(cogs) if cogs else 0

    # Other WC balances (same for both paths)
    d["Prepaid Expenses"] = sga * prepaid_ratio
    d["Deferred Revenue"] = abs(sales) * def_rev_ratio
    d["Other Operating Liability"] = abs(other_opex) * other_liab_ratio

    d["Sales (echo)"] = sales
    d["SG&A (echo)"] = sga
    d["Other OpEx (echo)"] = other_opex

    # Subtotals (Accrued Taxes added later in _project_wc_taxes)
    total_ca = d["AR, net of allowance"] + d["Ending Inventory ($)"] + d.get("Prepaid Expenses", 0)
    d["Total Non-Cash CA"] = total_ca

    total_cl = d["Accounts Payable"] + d["Deferred Revenue"] + d["Other Operating Liability"]
    d["Total Non-Cash CL"] = total_cl

    nwc = total_ca - total_cl
    d["Net Working Capital"] = nwc

    prior_nwc = prev.get("Net Working Capital", 0)
    d["Change in Working Capital"] = -(nwc - prior_nwc)

    d["Number of days"] = 365


# ═══════════════════════════════════════════════════════════════════════════
# Step 6: Debt LTD Schedule (preliminary)
# ═══════════════════════════════════════════════════════════════════════════

def _project_debt_ltd(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """LTD roll-forward with preliminary interest split.

    Interest is refined during the circular solver.

    When Total Debt Repayment = 0 (no blended payment), both interest and
    principal portions are 0. Interest expense still accrues on the IS via
    the debt interest calculation, but it doesn't reduce the LTD balance.
    """
    beg_ltd = prev.get("Ending LTD Balance", prev.get("Long-Term Debt", 0))
    d["Beginning LTD Balance"] = beg_ltd

    ltd_issue = d.get("Debt Issuance", 0)
    d["Issuance"] = ltd_issue

    total_repay = d.get("Debt Repayment", 0)
    d["Total Debt Repayment"] = total_repay

    # Only decompose if there's an actual payment
    if total_repay:
        d["Interest portion"] = 0
        principal = total_repay
    else:
        d["Interest portion"] = 0
        principal = 0

    d["Principal portion"] = principal
    d["Repayment (principal)"] = principal

    ending_ltd = beg_ltd + ltd_issue + principal
    d["Ending LTD Balance"] = ending_ltd
    d["Long-Term Debt"] = ending_ltd


# ═══════════════════════════════════════════════════════════════════════════
# Step 7: IS Phase 2 — EBIT through Net Income
# ═══════════════════════════════════════════════════════════════════════════

def _project_is_expenses(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """Assemble the IS from EBIT through NI.

    Reads COGS, BDE from WC; Depreciation, Amortization from PPE.
    """
    sales = d.get("Sales", 0)

    cogs = d.get("COGS", 0)
    d["COGS"] = abs(cogs)

    bde = d.get("Bad Debt Expense (implied)", 0)
    d["Bad Debt Expense"] = abs(bde)

    dep = d.get("Depreciation", 0)
    d["Depreciation (ref)"] = abs(dep)

    amort = d.get("Amortization", 0)
    d["Amortization (ref)"] = abs(amort)

    other_unaccounted = assumptions.get("Other/Unaccounted Avg", {}).get("base", 0)
    d["Other / Unaccounted"] = other_unaccounted

    ebit = (sales
            - d["COGS"]
            - d["Bad Debt Expense"]
            - abs(d.get("R&D Expense", 0))
            - abs(d.get("SG&A", 0))
            - abs(d.get("Other Operating Expense", 0))
            - abs(dep)
            - abs(amort)
            - d["Other / Unaccounted"])
    d["EBIT"] = ebit

    # Use prior-year interest as initial estimate; circular solver refines it
    int_exp = d.get("Interest Expense", prev.get("Interest Expense", 0))
    int_rev = d.get("Interest Revenue", prev.get("Interest Revenue", 0))
    d["Interest Expense"] = int_exp
    d["Interest Revenue"] = int_rev
    net_int = int_exp - int_rev
    d["Net Interest Expense"] = net_int

    ebt = ebit - net_int
    d["EBT"] = ebt

    tax_rate = _get_assumption_value(assumptions, "Tax Rate", period_idx)
    d["Tax Rate"] = tax_rate
    tax = abs(ebt) * tax_rate if ebt > 0 else 0
    d["Income Tax Expense"] = tax

    ni = ebt - tax
    d["Net Income"] = ni


# ═══════════════════════════════════════════════════════════════════════════
# Step 8: WC Finalise — Accrued Income Taxes
# ═══════════════════════════════════════════════════════════════════════════

def _project_wc_taxes(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """Compute Accrued Income Taxes (needs Tax Expense from IS Phase 2).

    Also recalculates Total Non-Cash CL, NWC, and ΔWC to include
    the accrued taxes that were deferred from the main WC pass.
    """
    accrued_tax_ratio = _get_assumption_value(assumptions, "Accrued Tax/Tax Owe", period_idx)
    d["Accrued Tax/Tax Owe"] = accrued_tax_ratio

    tax_expense = d.get("Income Tax Expense", 0)
    delta_dtl = d.get("Deferred Income Tax", 0) - prev.get("Deferred Income Tax", 0)
    taxes_owe = tax_expense - delta_dtl
    d["Taxes Owe"] = taxes_owe
    d["Accrued Income Taxes"] = abs(taxes_owe) * accrued_tax_ratio
    d["Tax Expense (echo)"] = tax_expense
    d["Delta DTL (echo)"] = delta_dtl

    # Recalculate CL/NWC/ΔWC with accrued taxes included
    total_cl = (d.get("Accounts Payable", 0)
                + d.get("Deferred Revenue", 0)
                + d.get("Other Operating Liability", 0)
                + d["Accrued Income Taxes"])
    d["Total Non-Cash CL"] = total_cl

    total_ca = d.get("Total Non-Cash CA", 0)
    nwc = total_ca - total_cl
    d["Net Working Capital"] = nwc

    prior_nwc = prev.get("Net Working Capital", 0)
    d["Change in Working Capital"] = -(nwc - prior_nwc)


# ═══════════════════════════════════════════════════════════════════════════
# Step 9: Statement of Cash Flows
# ═══════════════════════════════════════════════════════════════════════════

def _project_scf(d: YearData, prev: YearData, all_data: AllData, assumptions: Dict, period_idx: int):
    """Build the SCF with backward-derived Revolver plug.

    Cash is already set (from _project_bs_ratios), so ΔCash and
    the Revolver plug can be derived.
    """
    ni = d.get("Net Income", 0)
    dep = d.get("Depreciation", 0)
    amort = d.get("Amortization", 0)

    dtl_current = d.get("Deferred Income Tax", 0)
    dtl_prior = prev.get("Deferred Income Tax", 0)
    delta_dtl = dtl_current - dtl_prior
    d["Change in Deferred Taxes"] = delta_dtl

    delta_wc = d.get("Change in Working Capital", 0)

    cf_operating = ni + abs(dep) + abs(amort) + delta_dtl + delta_wc
    d["CF from Operating"] = cf_operating

    capex = d.get("Capital expenditures", d.get("CAPEX", 0))
    d["Capital Expenditure"] = -abs(capex)
    cf_investing = -abs(capex)
    d["CF from Investing"] = cf_investing

    cf_avail = cf_operating + cf_investing
    d["CF available for Financing"] = cf_avail

    payout = _get_assumption_value(assumptions, "Dividend Payout %", period_idx)
    if ni > 0:
        dividend = -abs(ni * payout)
    else:
        dividend = 0
    d["Paid Dividend"] = dividend

    ltd_repay = d.get("Repayment (principal)", d.get("Principal Repayment LTD", 0))
    d["Principal Repayment LTD"] = ltd_repay

    ltd_issue = d.get("Issuance", d.get("Debt Issuance", 0))
    d["Issuance of LTD"] = ltd_issue

    stock_issue = prev.get("Stock Issuance", 0)
    d["Stock Issuance"] = stock_issue

    ending_cash = d.get("Cash", 0)
    beg_cash = prev.get("Cash", 0)
    delta_cash = ending_cash - beg_cash
    d["Change in Cash"] = delta_cash
    d["Beginning Cash Balance"] = beg_cash
    d["Ending Cash Balance"] = ending_cash

    cf_financing = delta_cash - cf_avail
    d["CF from Financing"] = cf_financing

    revolver = cf_financing - dividend - ltd_repay - ltd_issue - stock_issue
    d["Revolver (PLUG)"] = revolver


# ═══════════════════════════════════════════════════════════════════════════
# Step 10: Debt Revolver
# ═══════════════════════════════════════════════════════════════════════════

def _project_debt_revolver(d: YearData, prev: YearData):
    """Set Revolver balance from SCF plug."""
    beg_revolver = prev.get("Ending Revolver Balance", prev.get("Revolver", 0))
    d["Beginning Revolver Balance"] = beg_revolver

    revolver_change = d.get("Revolver (PLUG)", 0)
    d["Revolver issuance/(repayment)"] = revolver_change
    ending_revolver = beg_revolver + revolver_change
    d["Ending Revolver Balance"] = ending_revolver
    d["Revolver"] = ending_revolver


# ═══════════════════════════════════════════════════════════════════════════
# Step 11: BS Assembly
# ═══════════════════════════════════════════════════════════════════════════

def _project_bs_assemble(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """Assemble the balance sheet from all schedule values."""
    d.setdefault("AR, net of allowance", 0)
    d.setdefault("Ending Inventory ($)", 0)
    d.setdefault("Prepaid Expenses", 0)
    d.setdefault("Ending PP&E, net", 0)
    d.setdefault("Ending Intangibles", 0)

    d["PP&E, net"] = d["Ending PP&E, net"]
    d["Intangibles, net"] = d["Ending Intangibles"]
    d["Inventory"] = d["Ending Inventory ($)"]

    cash = d.get("Cash", 0)
    other_assets = _get_assumption_value(assumptions, "Other Assets Avg", period_idx)
    d["Other Assets (plug)"] = other_assets
    total_assets = (cash + d["AR, net of allowance"] + d["Ending Inventory ($)"] +
                    d["Prepaid Expenses"] + d["Ending PP&E, net"] + d["Ending Intangibles"] +
                    other_assets)
    d["Total Assets"] = total_assets

    d.setdefault("Accounts Payable", 0)
    d.setdefault("Deferred Revenue", 0)
    d.setdefault("Other Operating Liability", 0)
    d.setdefault("Accrued Income Taxes", 0)

    ending_revolver = d.get("Ending Revolver Balance", d.get("Revolver", 0))
    ending_ltd = d.get("Ending LTD Balance", d.get("Long-Term Debt", 0))
    dtl = d.get("Deferred Income Tax", 0)
    other_liab = _get_assumption_value(assumptions, "Other Liabilities Avg", period_idx)
    d["Other Liabilities (plug)"] = other_liab

    total_liab = (d["Accounts Payable"] + d["Deferred Revenue"] +
                  d["Other Operating Liability"] + d["Accrued Income Taxes"] +
                  ending_revolver + ending_ltd + dtl + other_liab)
    d["Total Liability"] = total_liab

    prior_pic = prev.get("Paid In Capital", 0)
    stock_issue = d.get("Stock Issuance", 0)
    d["Paid In Capital"] = prior_pic + stock_issue

    prior_re = prev.get("Retained Earnings", 0)
    ni = d.get("Net Income", 0)
    div = d.get("Paid Dividend", 0)
    d["Retained Earnings"] = prior_re + ni + div

    total_equity = d["Paid In Capital"] + d["Retained Earnings"]
    d["Total Equity"] = total_equity
    d["Total L & E"] = total_liab + total_equity

    d["Balance Check"] = round(total_assets - total_liab - total_equity, 3)

    d["Sales (ref)"] = d.get("Sales", 0)
    d["Net Income (ref)"] = ni
    d["Paid Dividend (ref)"] = div
    d["Stock Issuance (ref)"] = stock_issue


# ═══════════════════════════════════════════════════════════════════════════
# Step 12: Circular Reference Solver
# ═══════════════════════════════════════════════════════════════════════════

def _solve_circular(d: YearData, prev: YearData, all_data: AllData, assumptions: Dict, period_idx: int):
    """Iteratively solve:
    Revolver → Interest → NI → Tax → Accrued Taxes → ΔWC → RE → SCF → Revolver.
    """
    MAX_ITER = 10
    TOLERANCE = 0.01

    for iteration in range(MAX_ITER):
        old_revolver = d.get("Revolver (PLUG)", 0)

        _compute_debt_interest(d, prev, assumptions, period_idx)
        _recompute_ni(d, assumptions, period_idx)
        _recompute_wc_taxes(d, prev, assumptions, period_idx)
        _recompute_bs_equity(d, prev, assumptions, period_idx)
        _recompute_scf_plug(d, prev, assumptions, period_idx)
        _recompute_debt_balances(d, prev)

        new_revolver = d.get("Revolver (PLUG)", 0)

        if abs(new_revolver - old_revolver) < TOLERANCE:
            logger.debug(f"Circular ref converged in {iteration + 1} iterations")
            break
    else:
        logger.warning(f"Circular ref did not converge after {MAX_ITER} iterations "
                       f"(delta={abs(d.get('Revolver (PLUG)', 0) - old_revolver):.2f})")

    d["Balance Check"] = round(d.get("Total Assets", 0) - d.get("Total L & E", 0), 3)


def _compute_debt_interest(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """Compute interest expense/revenue based on current debt balances."""
    avg_ltd = (d.get("Beginning LTD Balance", 0) + d.get("Ending LTD Balance", 0)) / 2
    d["Average LTD Balance"] = avg_ltd
    ltd_rate = _get_assumption_value(assumptions, "LTD Interest Rate", period_idx)
    d["LTD Interest Rate"] = ltd_rate
    ltd_interest = avg_ltd * ltd_rate
    d["LTD Interest Expense"] = ltd_interest

    # Only decompose repayment if there's an actual blended payment
    total_repay = d.get("Total Debt Repayment", 0)
    if total_repay:
        d["Interest portion"] = -abs(ltd_interest)
        principal = total_repay - d["Interest portion"]
    else:
        d["Interest portion"] = 0
        principal = 0
    d["Principal portion"] = principal
    d["Repayment (principal)"] = principal
    d["Ending LTD Balance"] = d["Beginning LTD Balance"] + d.get("Issuance", 0) + principal
    d["Long-Term Debt"] = d["Ending LTD Balance"]

    avg_revolver = (d.get("Beginning Revolver Balance", 0) + d.get("Ending Revolver Balance", 0)) / 2
    d["Average Revolver Balance"] = avg_revolver
    borrow_rate = _get_assumption_value(assumptions, "Revolver Borrow Rate", period_idx)
    invest_rate = _get_assumption_value(assumptions, "Revolver Invest Rate", period_idx)
    d["Revolver Borrow Rate"] = borrow_rate
    d["Revolver Invest Rate"] = invest_rate

    if avg_revolver > 0:
        revolver_interest = avg_revolver * borrow_rate
    else:
        revolver_interest = avg_revolver * invest_rate
    d["Revolver Interest"] = revolver_interest

    if revolver_interest > 0:
        d["Total Interest Expense"] = ltd_interest + revolver_interest
    else:
        d["Total Interest Expense"] = ltd_interest

    cash_bal = d.get("Cash", 0)
    prior_cash = prev.get("Cash", 0)
    avg_cash = (prior_cash + cash_bal) / 2
    d["Cash Balance"] = cash_bal
    d["Average Cash Balance"] = avg_cash
    cash_rate = _get_assumption_value(assumptions, "Cash Interest Rate", period_idx)
    d["Cash Interest Rate"] = cash_rate
    cash_interest = avg_cash * cash_rate
    d["Cash Interest Revenue"] = cash_interest

    if revolver_interest < 0:
        d["Total Interest Revenue"] = abs(revolver_interest) + cash_interest
    else:
        d["Total Interest Revenue"] = cash_interest

    d["Interest Expense"] = d["Total Interest Expense"]
    d["Interest Revenue"] = d["Total Interest Revenue"]


def _recompute_ni(d: YearData, assumptions: Dict, period_idx: int):
    """Recompute NI after interest changes."""
    int_exp = d.get("Total Interest Expense", 0)
    int_rev = d.get("Total Interest Revenue", 0)
    net_int = int_exp - int_rev
    d["Net Interest Expense"] = net_int

    ebit = d.get("EBIT", 0)
    ebt = ebit - net_int
    d["EBT"] = ebt

    tax_rate = _get_assumption_value(assumptions, "Tax Rate", period_idx)
    tax = abs(ebt) * tax_rate if ebt > 0 else 0
    d["Income Tax Expense"] = tax

    ni = ebt - tax
    d["Net Income"] = ni


def _recompute_wc_taxes(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """Recompute Accrued Taxes and WC subtotals after Tax Expense changes."""
    accrued_tax_ratio = _get_assumption_value(assumptions, "Accrued Tax/Tax Owe", period_idx)
    tax_expense = d.get("Income Tax Expense", 0)
    delta_dtl = d.get("Deferred Income Tax", 0) - prev.get("Deferred Income Tax", 0)
    taxes_owe = tax_expense - delta_dtl
    d["Taxes Owe"] = taxes_owe
    d["Accrued Income Taxes"] = abs(taxes_owe) * accrued_tax_ratio
    d["Tax Expense (echo)"] = tax_expense

    total_cl = (d.get("Accounts Payable", 0)
                + d.get("Deferred Revenue", 0)
                + d.get("Other Operating Liability", 0)
                + d["Accrued Income Taxes"])
    d["Total Non-Cash CL"] = total_cl

    total_ca = d.get("Total Non-Cash CA", 0)
    nwc = total_ca - total_cl
    d["Net Working Capital"] = nwc

    prior_nwc = prev.get("Net Working Capital", 0)
    d["Change in Working Capital"] = -(nwc - prior_nwc)


def _recompute_bs_equity(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """Recompute BS equity items after NI changes."""
    ni = d.get("Net Income", 0)

    payout = _get_assumption_value(assumptions, "Dividend Payout %", period_idx)
    if ni > 0:
        dividend = -abs(ni * payout)
    else:
        dividend = 0
    d["Paid Dividend"] = dividend

    prior_re = prev.get("Retained Earnings", 0)
    d["Retained Earnings"] = prior_re + ni + dividend

    d["Total Equity"] = d["Paid In Capital"] + d["Retained Earnings"]
    d["Total L & E"] = d["Total Liability"] + d["Total Equity"]

    d["Net Income (ref)"] = ni
    d["Paid Dividend (ref)"] = dividend


def _recompute_scf_plug(d: YearData, prev: YearData, assumptions: Dict, period_idx: int):
    """Recompute the SCF and Revolver plug after NI/dividend/ΔWC changes."""
    ni = d.get("Net Income", 0)
    dep = d.get("Depreciation", 0)
    amort = d.get("Amortization", 0)
    delta_dtl = d.get("Change in Deferred Taxes", 0)
    delta_wc = d.get("Change in Working Capital", 0)

    cf_op = ni + abs(dep) + abs(amort) + delta_dtl + delta_wc
    d["CF from Operating"] = cf_op

    cf_inv = d.get("CF from Investing", 0)
    cf_avail = cf_op + cf_inv
    d["CF available for Financing"] = cf_avail

    ending_cash = d.get("Cash", 0)
    beg_cash = prev.get("Cash", 0)
    delta_cash = ending_cash - beg_cash
    d["Change in Cash"] = delta_cash
    d["Beginning Cash Balance"] = beg_cash
    d["Ending Cash Balance"] = ending_cash

    cf_financing = delta_cash - cf_avail
    d["CF from Financing"] = cf_financing

    dividend = d.get("Paid Dividend", 0)
    ltd_repay = d.get("Principal Repayment LTD", d.get("Repayment (principal)", 0))
    ltd_issue = d.get("Issuance of LTD", d.get("Issuance", 0))
    stock_issue = d.get("Stock Issuance", 0)

    revolver = cf_financing - dividend - ltd_repay - ltd_issue - stock_issue
    d["Revolver (PLUG)"] = revolver


def _recompute_debt_balances(d: YearData, prev: YearData):
    """Update debt ending balances and Total Liability after Revolver plug changes."""
    revolver_change = d.get("Revolver (PLUG)", 0)
    d["Revolver issuance/(repayment)"] = revolver_change
    beg_revolver = d.get("Beginning Revolver Balance", 0)
    ending_revolver = beg_revolver + revolver_change
    d["Ending Revolver Balance"] = ending_revolver
    d["Revolver"] = ending_revolver

    ending_ltd = d.get("Ending LTD Balance", 0)
    dtl = d.get("Deferred Income Tax", 0)
    other_liab_plug = d.get("Other Liabilities (plug)", 0)
    total_liab = (d.get("Accounts Payable", 0) + d.get("Deferred Revenue", 0) +
                  d.get("Other Operating Liability", 0) + d.get("Accrued Income Taxes", 0) +
                  ending_revolver + ending_ltd + dtl + other_liab_plug)
    d["Total Liability"] = total_liab
    d["Total L & E"] = total_liab + d.get("Total Equity", 0)


# ═══════════════════════════════════════════════════════════════════════════
# Write to DB
# ═══════════════════════════════════════════════════════════════════════════

def _write_line_items(
    model_id: int, all_data: AllData, hist_years: List[int],
    projection_years: int, last_hist: int, db: AsyncSession,
):
    """Write all line items to the database.

    Items that appear on multiple tabs (e.g. "AR, net of allowance" on
    both WC and BS) are written once per tab so each sheet has data.
    """
    template = get_default_template()
    line_to_templates: Dict[str, List] = {}
    for tl in template.lines:
        line_to_templates.setdefault(tl.model_line, []).append(tl)

    for year, lines in all_data.items():
        is_proj = year > last_hist
        for ml, amount in lines.items():
            targets = line_to_templates.get(ml)
            if not targets:
                continue
            for tl in targets:
                db.add(ModelLineItem(
                    model_id=model_id,
                    model_line=ml,
                    statement_type=tl.statement_type,
                    year=year,
                    amount=amount,
                    is_projected=is_proj,
                    sort_order=tl.sort_order,
                ))
