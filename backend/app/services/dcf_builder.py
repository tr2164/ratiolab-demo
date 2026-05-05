"""
DCF Valuation Model Builder

Builds a DCF valuation model on top of a 3-statement (6-tab) model.
Reuses the existing Edgar data pipeline: fetch → map → build 3-statement → extract → DCF.

Pipeline:
  1. Build (or load) the 3-statement model for the company
  2. Extract relevant line items: EBIT, D&A, CapEx, ΔNWC, Cash, Debt
  3. Compute WACC from user assumptions (CAPM + after-tax cost of debt)
  4. Build FCF schedule (historical + projected)
  5. Compute terminal value (Gordon Growth + Exit Multiple)
  6. Discount FCF and terminal value → Enterprise Value → Equity Value
  7. Persist as a new Model with template_version="dcf"
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.company import Company
from app.models.model import Model, ModelLineItem, ModelAssumption
from app.services.model_builder import build_full_model
from app.services.dcf_template import get_dcf_template, DCF_ASSUMPTIONS

logger = logging.getLogger(__name__)

YearData = Dict[str, float]
AllData = Dict[int, YearData]


async def build_dcf_model(
    company_id: int,
    db: AsyncSession,
    projection_years: int = 5,
    source_model_id: Optional[int] = None,
) -> Model:
    """Build a complete DCF valuation model for a company.

    If source_model_id is provided, uses that 3-statement model.
    Otherwise, builds a fresh one first.
    """
    company = await db.get(Company, company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    # Step 1: Get or build the source 3-statement model
    if source_model_id:
        source_model = await db.get(Model, source_model_id)
        if not source_model:
            raise ValueError(f"Source model {source_model_id} not found")
    else:
        source_model = await build_full_model(company_id, db, projection_years)

    # Step 2: Extract line items from the source model
    source_data = await _extract_source_data(source_model.id, db)

    # Step 3: Create the DCF model record
    dcf_model = Model(
        company_id=company_id,
        name=f"{company.ticker} DCF Valuation",
        status="building",
        projection_years=projection_years,
        template_version="dcf",
    )
    db.add(dcf_model)
    await db.flush()

    try:
        years = sorted(source_data.keys())
        if not years:
            raise ValueError("No data found in source model")

        last_hist = _find_last_historical(source_model, years)
        proj_years = [y for y in years if y > last_hist]

        # Step 4: Load and calibrate assumptions
        assumptions = _load_dcf_assumptions()
        _calibrate_from_source(assumptions, source_data, last_hist, company)

        await _persist_dcf_assumptions(dcf_model.id, assumptions, db)

        # Step 5: Build FCF schedule
        fcf_data = _build_fcf(source_data, assumptions, years)

        # Step 6: Compute WACC
        wacc = _compute_wacc(assumptions)

        # Step 7: Build WACC tab data (stored at year=0)
        wacc_data = _build_wacc_data(assumptions, wacc)

        # Step 8: Build DCF valuation
        dcf_valuation = _build_dcf_valuation(
            fcf_data, source_data, assumptions, wacc,
            proj_years, last_hist,
        )

        # Step 9: Write all line items
        _write_dcf_line_items(dcf_model.id, fcf_data, wacc_data,
                              dcf_valuation, years, proj_years, last_hist, db)

        dcf_model.status = "ready"
    except Exception as e:
        dcf_model.status = "error"
        logger.error(f"DCF build failed: {e}", exc_info=True)
        raise
    finally:
        await db.commit()

    return dcf_model


# ═══════════════════════════════════════════════════════════════════════════
# Extract data from the source 3-statement model
# ═══════════════════════════════════════════════════════════════════════════

async def _extract_source_data(model_id: int, db: AsyncSession) -> AllData:
    """Load line items from the source model, organized by year."""
    result = await db.execute(
        select(ModelLineItem)
        .where(ModelLineItem.model_id == model_id)
        .order_by(ModelLineItem.year)
    )
    items = result.scalars().all()

    data: AllData = {}
    for item in items:
        if item.year not in data:
            data[item.year] = {}
        key = f"{item.statement_type}:{item.model_line}"
        existing = data[item.year].get(key)
        if existing is None or abs(item.amount or 0) > abs(existing):
            data[item.year][key] = item.amount or 0

    return data


def _find_last_historical(source_model: Model, years: List[int]) -> int:
    """Infer the last historical year from the source model's projection count."""
    proj = source_model.projection_years or 5
    hist_count = len(years) - proj
    if hist_count >= 1:
        return years[hist_count - 1]
    if len(years) >= 4:
        return years[2]
    return years[-1]


# ═══════════════════════════════════════════════════════════════════════════
# Assumptions
# ═══════════════════════════════════════════════════════════════════════════

def _load_dcf_assumptions() -> Dict[str, float]:
    """Load default DCF assumptions into a flat dict."""
    return {a.name: a.base_value for a in DCF_ASSUMPTIONS}


def _calibrate_from_source(
    assumptions: Dict[str, float],
    source_data: AllData,
    last_hist: int,
    company: "Company",
):
    """Calibrate DCF assumptions from the source model's historical data."""
    last = source_data.get(last_hist, {})

    # Calibrate tax rate from IS if available
    ebt = last.get("IS:EBT", 0)
    tax = last.get("IS:Income Tax Expense", 0)
    if ebt and abs(ebt) > 1:
        effective_rate = abs(tax / ebt)
        if 0.05 < effective_rate < 0.45:
            assumptions["DCF Tax Rate"] = round(effective_rate, 4)
            assumptions["Marginal Tax Rate"] = round(effective_rate, 4)

    # Calibrate cost of debt from interest / debt
    interest = abs(last.get("IS:Interest Expense", 0))
    ltd = abs(last.get("BS:Long-Term Debt", 0))
    revolver = abs(last.get("BS:Revolver", 0))
    total_debt = ltd + revolver
    if total_debt > 1 and interest > 0:
        implied_rate = interest / total_debt
        if 0.01 < implied_rate < 0.15:
            assumptions["Pre-tax Cost of Debt"] = round(implied_rate, 4)

    # Calibrate capital structure from last historical year
    equity_book = abs(last.get("BS:Total Equity", 0))
    total_le = abs(last.get("BS:Total L & E", 0))
    if total_le > 1:
        equity_weight = equity_book / total_le
        assumptions["Equity Weight"] = round(min(max(equity_weight, 0.2), 0.95), 4)

    # Estimate shares outstanding from net income if no market data
    # This is a rough proxy; user should override
    net_income = last.get("IS:Net Income", 0)
    if abs(net_income) > 1_000_000:
        assumptions["Shares Outstanding (M)"] = round(abs(net_income) / 1_000_000 * 20, 1)


async def _persist_dcf_assumptions(
    model_id: int, assumptions: Dict[str, float], db: AsyncSession
):
    """Save DCF assumptions to the model_assumptions table."""
    for tmpl in DCF_ASSUMPTIONS:
        val = assumptions.get(tmpl.name, tmpl.base_value)
        db.add(ModelAssumption(
            model_id=model_id,
            name=tmpl.name,
            statement_type=tmpl.statement_type,
            base_value=val,
            step_increment=tmpl.step_increment,
            step_type=tmpl.step_type,
            is_overridden=False,
            category=tmpl.category,
            input_type=tmpl.input_type,
            display_name=tmpl.display_name or tmpl.name,
            description=tmpl.description,
            min_value=tmpl.min_value,
            max_value=tmpl.max_value,
        ))


# ═══════════════════════════════════════════════════════════════════════════
# Build FCF Schedule
# ═══════════════════════════════════════════════════════════════════════════

def _build_fcf(
    source_data: AllData,
    assumptions: Dict[str, float],
    years: List[int],
) -> AllData:
    """Build the Free Cash Flow schedule from source model data."""
    fcf_data: AllData = {}
    tax_rate = assumptions.get("DCF Tax Rate", 0.21)

    prev_revenue = 0.0
    prev_ufcf = 0.0

    for year in years:
        src = source_data.get(year, {})
        d: YearData = {}

        revenue = src.get("IS:Sales", 0)
        ebit = src.get("IS:EBIT", 0)
        dep = src.get("IS:Depreciation", 0)
        amort = src.get("IS:Amortization", 0)
        capex = src.get("SCF:Capital Expenditure", 0)
        delta_nwc = src.get("WC:Change in Working Capital", 0)

        d["Revenue"] = revenue
        d["Revenue Growth"] = ((revenue / prev_revenue) - 1) if prev_revenue and abs(prev_revenue) > 1 else 0
        d["EBIT"] = ebit
        d["EBIT Margin"] = (ebit / revenue) if revenue and abs(revenue) > 1 else 0
        d["Tax Rate"] = tax_rate
        d["Taxes on EBIT"] = -abs(ebit * tax_rate)
        nopat = ebit - abs(ebit * tax_rate)
        d["NOPAT"] = nopat

        d["Depreciation"] = abs(dep) if dep else 0
        d["Amortization"] = abs(amort) if amort else 0
        d["Capital Expenditure"] = capex  # negative in SCF convention
        d["Increase in NWC"] = -delta_nwc if delta_nwc else 0

        ufcf = nopat + abs(dep) + abs(amort) + capex - (-delta_nwc if delta_nwc else 0)
        d["Unlevered Free Cash Flow"] = ufcf
        d["UFCF Margin"] = (ufcf / revenue) if revenue and abs(revenue) > 1 else 0
        d["UFCF Growth"] = ((ufcf / prev_ufcf) - 1) if prev_ufcf and abs(prev_ufcf) > 1 else 0

        prev_revenue = revenue
        prev_ufcf = ufcf
        fcf_data[year] = d

    return fcf_data


# ═══════════════════════════════════════════════════════════════════════════
# Compute WACC
# ═══════════════════════════════════════════════════════════════════════════

def _compute_wacc(assumptions: Dict[str, float]) -> float:
    """Compute WACC from assumptions."""
    rf = assumptions.get("Risk-Free Rate", 0.043)
    erp = assumptions.get("Equity Risk Premium", 0.055)
    beta = assumptions.get("Beta", 1.1)
    size_premium = assumptions.get("Size Premium", 0.0)
    ke = rf + beta * erp + size_premium

    kd_pre = assumptions.get("Pre-tax Cost of Debt", 0.05)
    tax = assumptions.get("Marginal Tax Rate", 0.21)
    kd_at = kd_pre * (1 - tax)

    we = assumptions.get("Equity Weight", 0.80)
    wd = 1 - we

    wacc = we * ke + wd * kd_at
    return wacc


def _build_wacc_data(assumptions: Dict[str, float], wacc: float) -> YearData:
    """Build WACC tab data (single-column, stored at year=0)."""
    rf = assumptions.get("Risk-Free Rate", 0.043)
    erp = assumptions.get("Equity Risk Premium", 0.055)
    beta = assumptions.get("Beta", 1.1)
    size_premium = assumptions.get("Size Premium", 0.0)
    ke = rf + beta * erp + size_premium

    kd_pre = assumptions.get("Pre-tax Cost of Debt", 0.05)
    tax = assumptions.get("Marginal Tax Rate", 0.21)
    kd_at = kd_pre * (1 - tax)

    we = assumptions.get("Equity Weight", 0.80)
    wd = 1 - we

    return {
        "Risk-Free Rate": rf,
        "Equity Risk Premium": erp,
        "Beta": beta,
        "Size Premium": size_premium,
        "Cost of Equity": ke,
        "Pre-tax Cost of Debt": kd_pre,
        "Marginal Tax Rate": tax,
        "After-tax Cost of Debt": kd_at,
        "Equity Weight": we,
        "Debt Weight": wd,
        "WACC": wacc,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Build DCF Valuation
# ═══════════════════════════════════════════════════════════════════════════

def _build_dcf_valuation(
    fcf_data: AllData,
    source_data: AllData,
    assumptions: Dict[str, float],
    wacc: float,
    proj_years: List[int],
    last_hist: int,
) -> Dict:
    """Build the DCF valuation: PV of UFCF, terminal value, equity bridge."""
    terminal_growth = assumptions.get("Terminal Growth Rate", 0.025)
    exit_multiple = assumptions.get("Exit EV/EBITDA Multiple", 12.0)
    shares = assumptions.get("Shares Outstanding (M)", 100.0)
    market_price = assumptions.get("Current Market Price", 100.0)

    # PV of projected year UFCFs
    pv_by_year: Dict[int, YearData] = {}
    cumulative_pv = 0.0

    for i, year in enumerate(proj_years):
        d: YearData = {}
        ufcf = fcf_data.get(year, {}).get("Unlevered Free Cash Flow", 0)
        period = i + 1
        discount_factor = 1 / ((1 + wacc) ** period)
        pv = ufcf * discount_factor
        cumulative_pv += pv

        d["Unlevered FCF"] = ufcf
        d["Discount Period"] = float(period)
        d["Discount Factor"] = discount_factor
        d["PV of UFCF"] = pv
        d["Cumulative PV of UFCF"] = cumulative_pv

        pv_by_year[year] = d

    # Terminal value calculations
    last_proj_year = proj_years[-1] if proj_years else last_hist
    terminal_ufcf = fcf_data.get(last_proj_year, {}).get("Unlevered Free Cash Flow", 0)
    terminal_ufcf_grown = terminal_ufcf * (1 + terminal_growth)

    # Gordon Growth: TV = UFCF × (1+g) / (WACC - g)
    gordon_tv = 0
    if wacc > terminal_growth:
        gordon_tv = terminal_ufcf_grown / (wacc - terminal_growth)

    # Exit Multiple: TV = EBITDA × Multiple
    last_ebit = fcf_data.get(last_proj_year, {}).get("EBIT", 0)
    last_da = (fcf_data.get(last_proj_year, {}).get("Depreciation", 0) +
               fcf_data.get(last_proj_year, {}).get("Amortization", 0))
    terminal_ebitda = last_ebit + last_da
    exit_tv = terminal_ebitda * exit_multiple

    # PV of terminal values
    n = len(proj_years)
    terminal_discount = 1 / ((1 + wacc) ** n) if n > 0 else 1
    pv_gordon_tv = gordon_tv * terminal_discount
    pv_exit_tv = exit_tv * terminal_discount

    # Enterprise Value
    ev_gordon = cumulative_pv + pv_gordon_tv
    ev_exit = cumulative_pv + pv_exit_tv

    # Equity Bridge (use last historical year's balance sheet)
    last_src = source_data.get(last_hist, {})
    total_debt = abs(last_src.get("BS:Long-Term Debt", 0)) + abs(last_src.get("BS:Revolver", 0))
    cash = abs(last_src.get("BS:Cash", 0))

    equity_gordon = ev_gordon - total_debt + cash
    equity_exit = ev_exit - total_debt + cash

    price_gordon = equity_gordon / shares if shares > 0 else 0
    price_exit = equity_exit / shares if shares > 0 else 0

    upside_gordon = (price_gordon / market_price - 1) if market_price > 0 else 0
    upside_exit = (price_exit / market_price - 1) if market_price > 0 else 0

    valuation_summary = {
        "pv_by_year": pv_by_year,
        "Terminal Growth Rate": terminal_growth,
        "Terminal Year UFCF": terminal_ufcf_grown,
        "Terminal Value (Gordon Growth)": gordon_tv,
        "Exit EV/EBITDA Multiple": exit_multiple,
        "Terminal Year EBITDA": terminal_ebitda,
        "Terminal Value (Exit Multiple)": exit_tv,
        "PV of Terminal Value (Gordon)": pv_gordon_tv,
        "PV of Terminal Value (Exit)": pv_exit_tv,
        "Enterprise Value (Gordon Growth)": ev_gordon,
        "Enterprise Value (Exit Multiple)": ev_exit,
        "Less: Total Debt": -total_debt,
        "Plus: Cash": cash,
        "Equity Value (Gordon Growth)": equity_gordon,
        "Equity Value (Exit Multiple)": equity_exit,
        "Shares Outstanding (M)": shares,
        "Implied Price (Gordon Growth)": price_gordon,
        "Implied Price (Exit Multiple)": price_exit,
        "Current Market Price": market_price,
        "Upside / (Downside) Gordon": upside_gordon,
        "Upside / (Downside) Exit": upside_exit,
    }

    return valuation_summary


# ═══════════════════════════════════════════════════════════════════════════
# Persist line items
# ═══════════════════════════════════════════════════════════════════════════

def _write_dcf_line_items(
    model_id: int,
    fcf_data: AllData,
    wacc_data: YearData,
    dcf_valuation: Dict,
    years: List[int],
    proj_years: List[int],
    last_hist: int,
    db: AsyncSession,
):
    """Write all DCF line items to the database."""
    template = get_dcf_template()
    line_to_templates: Dict[str, List] = {}
    for tl in template.lines:
        line_to_templates.setdefault(tl.model_line, []).append(tl)

    # Write FCF tab items (all years)
    for year in years:
        is_proj = year > last_hist
        d = fcf_data.get(year, {})
        for ml, amount in d.items():
            targets = line_to_templates.get(ml, [])
            for tl in targets:
                if tl.statement_type == "FCF":
                    db.add(ModelLineItem(
                        model_id=model_id,
                        model_line=ml,
                        statement_type="FCF",
                        year=year,
                        amount=amount,
                        is_projected=is_proj,
                        sort_order=tl.sort_order,
                    ))

    # Write WACC tab items (year=0, single column)
    for ml, amount in wacc_data.items():
        targets = line_to_templates.get(ml, [])
        for tl in targets:
            if tl.statement_type == "WACC":
                db.add(ModelLineItem(
                    model_id=model_id,
                    model_line=ml,
                    statement_type="WACC",
                    year=0,
                    amount=amount,
                    is_projected=False,
                    sort_order=tl.sort_order,
                ))

    # Write DCF tab items (projected years for PV rows)
    pv_by_year = dcf_valuation.get("pv_by_year", {})
    for year in proj_years:
        pv = pv_by_year.get(year, {})
        for ml, amount in pv.items():
            targets = line_to_templates.get(ml, [])
            for tl in targets:
                if tl.statement_type == "DCF":
                    db.add(ModelLineItem(
                        model_id=model_id,
                        model_line=ml,
                        statement_type="DCF",
                        year=year,
                        amount=amount,
                        is_projected=True,
                        sort_order=tl.sort_order,
                    ))

    # Write DCF summary items (single values, stored at year=0)
    summary_lines = [
        "Terminal Growth Rate", "Terminal Year UFCF",
        "Terminal Value (Gordon Growth)", "Exit EV/EBITDA Multiple",
        "Terminal Year EBITDA", "Terminal Value (Exit Multiple)",
        "PV of Terminal Value (Gordon)", "PV of Terminal Value (Exit)",
        "Enterprise Value (Gordon Growth)", "Enterprise Value (Exit Multiple)",
        "Less: Total Debt", "Plus: Cash",
        "Equity Value (Gordon Growth)", "Equity Value (Exit Multiple)",
        "Shares Outstanding (M)",
        "Implied Price (Gordon Growth)", "Implied Price (Exit Multiple)",
        "Current Market Price",
        "Upside / (Downside) Gordon", "Upside / (Downside) Exit",
    ]
    for ml in summary_lines:
        amount = dcf_valuation.get(ml, 0)
        targets = line_to_templates.get(ml, [])
        for tl in targets:
            if tl.statement_type == "DCF":
                db.add(ModelLineItem(
                    model_id=model_id,
                    model_line=ml,
                    statement_type="DCF",
                    year=0,
                    amount=amount,
                    is_projected=False,
                    sort_order=tl.sort_order,
                ))
