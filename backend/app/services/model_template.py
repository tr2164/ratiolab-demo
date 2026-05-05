"""
Model Template Service — 6-Tab Integrated Financial Model

Defines the layout for a 6-tab financial model (plus Information input tab)
that projects 5 years forward from 3 years of historical data.

Tab architecture:
  Information → PP&E, Debt, WC (supporting schedules)
  PP&E, Debt, WC → IS (income statement assembles from schedules)
  IS → SCF (cash flows, derives Revolver plug)
  All → BS (balance sheet, must balance to zero)
  BS → SCF (circular: Revolver plug)

Cross-sheet references:
  source_ref format: "TAB:line_name" (e.g. "WC:COGS")
  font_color: green indicates a cross-sheet reference

Color coding (matches standard financial modeling convention):
  blue  — hardcoded input (user-editable)
  black — formula / calculation
  green — cross-sheet reference
"""

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class TemplateLine:
    model_line: str
    statement_type: str       # IS, BS, SCF, WC, PPE, DEBT, INFO
    sort_order: int
    row_number: int = 0       # row in the Excel layout (for reference)
    is_subtotal: bool = False
    projects: bool = False
    formula_type: str = "none"
    source_ref: Optional[str] = None  # cross-sheet: "TAB:line_name"
    display_format: str = "millions"  # millions, percent, days, per_unit, count, none
    font_color: str = "black"         # blue, black, green


@dataclass
class TemplateAssumption:
    name: str
    statement_type: str
    row_number: int
    base_value: float
    step_increment: float
    step_type: str            # "multiplicative" or "additive"
    description: str = ""
    category: str = "General"
    input_type: str = "percentage"   # percentage, currency, days, count, toggle
    display_name: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None


@dataclass
class ModelTemplate:
    name: str
    description: str
    lines: List[TemplateLine] = field(default_factory=list)
    assumptions: List[TemplateAssumption] = field(default_factory=list)
    scale_divisor: float = 1_000_000.0
    historical_periods: int = 3
    projection_periods: int = 5


# ─── Tab metadata ───────────────────────────────────────────────────────────

TAB_ORDER = ["INFO", "WC", "PPE", "DEBT", "IS", "SCF", "BS"]

TAB_DISPLAY_NAMES = {
    "INFO": "Information",
    "WC":   "Working Capital",
    "PPE":  "PP&E",
    "DEBT": "Debt",
    "IS":   "Income Statement",
    "SCF":  "Cash Flows",
    "BS":   "Balance Sheet",
}

TAB_SHEET_IDS = {
    "INFO": "info",
    "WC":   "wc",
    "PPE":  "ppe",
    "DEBT": "debt",
    "IS":   "is",
    "SCF":  "scf",
    "BS":   "bs",
}


# ═══════════════════════════════════════════════════════════════════════════
# INCOME STATEMENT  (Sheet ID: 6)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_IS_LINES = [
    # Main body
    TemplateLine("Sales",                   "IS", 100, row_number=6,  projects=True, formula_type="unit_price"),
    TemplateLine("Units",                   "IS", 101, row_number=7,  projects=True, formula_type="multiplicative"),
    TemplateLine("Unit Selling Price",      "IS", 102, row_number=8,  projects=True, formula_type="multiplicative", display_format="per_unit"),
    TemplateLine("COGS",                    "IS", 105, row_number=9,  projects=True, formula_type="cross_sheet",
                 source_ref="WC:COGS", font_color="green"),
    TemplateLine("Bad Debt Expense",        "IS", 106, row_number=10, projects=True, formula_type="cross_sheet",
                 source_ref="WC:Bad Debt Expense (implied)", font_color="green"),
    TemplateLine("R&D Expense",             "IS", 110, row_number=11, projects=True, formula_type="multiplicative",
                 font_color="blue"),
    TemplateLine("SG&A",                    "IS", 112, row_number=12, projects=True, formula_type="ratio_of_sales"),
    TemplateLine("Other Operating Expense", "IS", 113, row_number=13, projects=True, formula_type="ratio_of_sales"),
    TemplateLine("Depreciation",            "IS", 115, row_number=15, projects=True, formula_type="cross_sheet",
                 source_ref="PPE:Depreciation", font_color="green"),
    TemplateLine("Amortization",            "IS", 116, row_number=16, projects=True, formula_type="cross_sheet",
                 source_ref="PPE:Amortization", font_color="green"),
    TemplateLine("Other / Unaccounted",     "IS", 114, row_number=14, projects=True, formula_type="carry_forward",
                 font_color="blue"),
    TemplateLine("EBIT",                    "IS", 117, row_number=17, is_subtotal=True, projects=True,
                 formula_type="subtotal"),
    TemplateLine("Interest Expense",        "IS", 119, row_number=19, projects=True, formula_type="cross_sheet",
                 source_ref="DEBT:Total Interest Expense", font_color="green"),
    TemplateLine("Interest Revenue",        "IS", 120, row_number=20, projects=True, formula_type="cross_sheet",
                 source_ref="DEBT:Total Interest Revenue", font_color="green"),
    TemplateLine("Net Interest Expense",    "IS", 121, row_number=21, is_subtotal=True, projects=True,
                 formula_type="subtotal"),
    TemplateLine("EBT",                     "IS", 122, row_number=22, is_subtotal=True, projects=True,
                 formula_type="subtotal"),
    TemplateLine("Income Tax Expense",      "IS", 124, row_number=24, projects=True, formula_type="ratio_of_line"),
    TemplateLine("Net Income",              "IS", 125, row_number=25, is_subtotal=True, projects=True,
                 formula_type="subtotal"),

    # Ratios section (rows 27-32)
    TemplateLine("SG&A/Sales",              "IS", 128, row_number=28, projects=True, formula_type="additive",
                 font_color="blue", display_format="percent"),
    TemplateLine("Other OpEx/Sales",        "IS", 129, row_number=29, projects=True, formula_type="additive",
                 font_color="blue", display_format="percent"),
    TemplateLine("Tax Rate",                "IS", 130, row_number=30, projects=True, formula_type="additive",
                 font_color="blue", display_format="percent"),
    TemplateLine("Depreciation (ref)",      "IS", 131, row_number=31, projects=True, formula_type="cross_sheet",
                 source_ref="PPE:Depreciation", font_color="green"),
    TemplateLine("Amortization (ref)",      "IS", 132, row_number=32, projects=True, formula_type="cross_sheet",
                 source_ref="PPE:Amortization", font_color="green"),
]


# ═══════════════════════════════════════════════════════════════════════════
# BALANCE SHEET  (Sheet ID: 1)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_BS_LINES = [
    TemplateLine("Balance Check",           "BS", 200, row_number=4,  is_subtotal=True, projects=True,
                 formula_type="balance_check"),

    # Assets
    TemplateLine("Cash",                    "BS", 207, row_number=7,  projects=True, formula_type="ratio_of_sales"),
    TemplateLine("AR, net of allowance",    "BS", 208, row_number=8,  projects=True, formula_type="cross_sheet",
                 source_ref="WC:AR, net of allowance", font_color="green"),
    TemplateLine("Inventory",               "BS", 209, row_number=9,  projects=True, formula_type="cross_sheet",
                 source_ref="WC:Ending Inventory ($)", font_color="green"),
    TemplateLine("Prepaid Expenses",        "BS", 210, row_number=10, projects=True, formula_type="cross_sheet",
                 source_ref="WC:Prepaid Expenses", font_color="green"),
    TemplateLine("PP&E, net",               "BS", 211, row_number=11, projects=True, formula_type="cross_sheet",
                 source_ref="PPE:Ending PP&E, net", font_color="green"),
    TemplateLine("Intangibles, net",        "BS", 212, row_number=12, projects=True, formula_type="cross_sheet",
                 source_ref="PPE:Ending Intangibles", font_color="green"),
    TemplateLine("Other Assets (plug)",     "BS", 212.5, row_number=13, projects=True, formula_type="carry_forward",
                 font_color="blue"),
    TemplateLine("Total Assets",            "BS", 213, row_number=14, is_subtotal=True, projects=True,
                 formula_type="subtotal"),

    # Liabilities
    TemplateLine("Accounts Payable",        "BS", 215, row_number=16, projects=True, formula_type="cross_sheet",
                 source_ref="WC:Accounts Payable", font_color="green"),
    TemplateLine("Deferred Revenue",        "BS", 216, row_number=17, projects=True, formula_type="cross_sheet",
                 source_ref="WC:Deferred Revenue", font_color="green"),
    TemplateLine("Other Operating Liability","BS", 217, row_number=18, projects=True, formula_type="cross_sheet",
                 source_ref="WC:Other Operating Liability", font_color="green"),
    TemplateLine("Accrued Income Taxes",    "BS", 218, row_number=19, projects=True, formula_type="cross_sheet",
                 source_ref="WC:Accrued Income Taxes", font_color="green"),
    TemplateLine("Revolver",                "BS", 220, row_number=21, projects=True, formula_type="cross_sheet",
                 source_ref="DEBT:Ending Revolver Balance", font_color="green"),
    TemplateLine("Long-Term Debt",          "BS", 221, row_number=22, projects=True, formula_type="cross_sheet",
                 source_ref="DEBT:Ending LTD Balance", font_color="green"),
    TemplateLine("Deferred Income Tax",     "BS", 222, row_number=23, projects=True, formula_type="ratio_of_sales"),
    TemplateLine("Other Liabilities (plug)","BS", 222.5, row_number=24, projects=True, formula_type="carry_forward",
                 font_color="blue"),
    TemplateLine("Total Liability",         "BS", 223, row_number=25, is_subtotal=True, projects=True,
                 formula_type="subtotal"),

    # Equity
    TemplateLine("Paid In Capital",         "BS", 225, row_number=27, projects=True, formula_type="roll_forward"),
    TemplateLine("Retained Earnings",       "BS", 226, row_number=28, projects=True, formula_type="roll_forward"),
    TemplateLine("Total Equity",            "BS", 227, row_number=29, is_subtotal=True, projects=True,
                 formula_type="subtotal"),
    TemplateLine("Total L & E",             "BS", 228, row_number=30, is_subtotal=True, projects=True,
                 formula_type="subtotal"),

    # Ratios / ref section
    TemplateLine("Sales (ref)",             "BS", 230, row_number=32, projects=True, formula_type="cross_sheet",
                 source_ref="IS:Sales", font_color="green"),
    TemplateLine("Cash/Sales",              "BS", 231, row_number=33, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("DTL/Sales",               "BS", 232, row_number=34, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Net Income (ref)",        "BS", 233, row_number=35, projects=True, formula_type="cross_sheet",
                 source_ref="IS:Net Income", font_color="green"),
    TemplateLine("Paid Dividend (ref)",     "BS", 234, row_number=36, projects=True, formula_type="cross_sheet",
                 source_ref="SCF:Paid Dividend", font_color="green"),
    TemplateLine("Stock Issuance (ref)",    "BS", 235, row_number=37, projects=True, formula_type="cross_sheet",
                 source_ref="SCF:Stock Issuance", font_color="green"),
]


# ═══════════════════════════════════════════════════════════════════════════
# STATEMENT OF CASH FLOWS  (Sheet ID: 7)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_SCF_LINES = [
    # Operating
    TemplateLine("Net Income",              "SCF", 300, row_number=6,  projects=True, formula_type="cross_sheet",
                 source_ref="IS:Net Income", font_color="green"),
    TemplateLine("Depreciation",            "SCF", 301, row_number=7,  projects=True, formula_type="cross_sheet",
                 source_ref="IS:Depreciation", font_color="green"),
    TemplateLine("Amortization",            "SCF", 302, row_number=8,  projects=True, formula_type="cross_sheet",
                 source_ref="IS:Amortization", font_color="green"),
    TemplateLine("Change in Deferred Taxes","SCF", 303, row_number=9,  projects=True, formula_type="bs_delta"),
    TemplateLine("Change in Working Capital","SCF", 304, row_number=10, projects=True, formula_type="cross_sheet",
                 source_ref="WC:Change in Working Capital", font_color="green"),
    TemplateLine("CF from Operating",       "SCF", 305, row_number=11, is_subtotal=True, projects=True,
                 formula_type="subtotal"),

    # Investing
    TemplateLine("Capital Expenditure",     "SCF", 307, row_number=13, projects=True, formula_type="cross_sheet_negate",
                 source_ref="PPE:Capital expenditures", font_color="green"),
    TemplateLine("CF from Investing",       "SCF", 308, row_number=14, is_subtotal=True, projects=True,
                 formula_type="subtotal"),
    TemplateLine("CF available for Financing","SCF", 309, row_number=15, is_subtotal=True, projects=True,
                 formula_type="subtotal"),

    # Financing (rows 17-25 — backward-derived from Cash)
    TemplateLine("Paid Dividend",           "SCF", 311, row_number=17, projects=True, formula_type="if_then"),
    TemplateLine("Principal Repayment LTD", "SCF", 312, row_number=18, projects=True, formula_type="cross_sheet",
                 source_ref="DEBT:Repayment (principal)", font_color="green"),
    TemplateLine("Issuance of LTD",         "SCF", 313, row_number=19, projects=True, formula_type="cross_sheet",
                 source_ref="DEBT:Issuance", font_color="green"),
    TemplateLine("Revolver (PLUG)",         "SCF", 314, row_number=20, projects=True, formula_type="plug"),
    TemplateLine("Stock Issuance",          "SCF", 315, row_number=21, projects=False, formula_type="none",
                 font_color="blue"),
    TemplateLine("CF from Financing",       "SCF", 316, row_number=22, is_subtotal=True, projects=True,
                 formula_type="backward_derive"),
    TemplateLine("Change in Cash",          "SCF", 317, row_number=23, is_subtotal=True, projects=True,
                 formula_type="backward_derive"),
    TemplateLine("Beginning Cash Balance",  "SCF", 318, row_number=24, projects=True, formula_type="prior_ending_cash"),
    TemplateLine("Ending Cash Balance",     "SCF", 319, row_number=25, projects=True, formula_type="cross_sheet",
                 source_ref="BS:Cash", font_color="green"),
]


# ═══════════════════════════════════════════════════════════════════════════
# WORKING CAPITAL  (Sheet ID: 2)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_WC_LINES = [
    # Section A — IS line-item echo (for ratio calculations)
    TemplateLine("Sales (echo)",            "WC", 400, row_number=5,  projects=True, formula_type="cross_sheet",
                 source_ref="IS:Sales", font_color="green"),
    TemplateLine("COGS (echo)",             "WC", 401, row_number=6,  projects=True, formula_type="internal",
                 font_color="green"),
    TemplateLine("BDE (echo)",              "WC", 402, row_number=7,  projects=True, formula_type="internal",
                 font_color="green"),
    TemplateLine("SG&A (echo)",             "WC", 403, row_number=8,  projects=True, formula_type="cross_sheet",
                 source_ref="IS:SG&A", font_color="green"),
    TemplateLine("Other OpEx (echo)",       "WC", 404, row_number=9,  projects=True, formula_type="cross_sheet",
                 source_ref="IS:Other Operating Expense", font_color="green"),
    TemplateLine("Tax Expense (echo)",      "WC", 405, row_number=10, projects=True, formula_type="cross_sheet",
                 source_ref="IS:Income Tax Expense", font_color="green"),
    TemplateLine("Delta DTL (echo)",        "WC", 406, row_number=11, projects=True, formula_type="internal",
                 font_color="green"),

    # Section B — Working Capital Balances (rows 13-29)
    TemplateLine("Gross AR",                "WC", 410, row_number=14, projects=True, formula_type="days_calc"),
    TemplateLine("Allowance",               "WC", 411, row_number=15, projects=True, formula_type="ratio_calc"),
    TemplateLine("AR, net of allowance",    "WC", 412, row_number=16, projects=True, formula_type="subtotal"),
    TemplateLine("Ending Inventory ($)",    "WC", 413, row_number=17, projects=True, formula_type="wa_calc"),
    TemplateLine("Prepaid Expenses",        "WC", 414, row_number=18, projects=True, formula_type="ratio_calc"),
    TemplateLine("Total Non-Cash CA",       "WC", 415, row_number=19, is_subtotal=True, projects=True,
                 formula_type="subtotal"),
    TemplateLine("Accounts Payable",        "WC", 417, row_number=21, projects=True, formula_type="days_calc"),
    TemplateLine("Deferred Revenue",        "WC", 418, row_number=22, projects=True, formula_type="ratio_calc"),
    TemplateLine("Other Operating Liability","WC", 419, row_number=23, projects=True, formula_type="ratio_calc"),
    TemplateLine("Accrued Income Taxes",    "WC", 420, row_number=24, projects=True, formula_type="ratio_calc"),
    TemplateLine("Total Non-Cash CL",       "WC", 421, row_number=25, is_subtotal=True, projects=True,
                 formula_type="subtotal"),
    TemplateLine("Net Working Capital",     "WC", 423, row_number=27, is_subtotal=True, projects=True,
                 formula_type="subtotal"),
    TemplateLine("Change in Working Capital","WC", 425, row_number=29, projects=True, formula_type="wc_delta"),

    # Section C — Inventory Schedule (rows 31-47)
    TemplateLine("Unit Sales",              "WC", 430, row_number=32, projects=True, formula_type="cross_sheet",
                 source_ref="IS:Units", font_color="green", display_format="count"),
    TemplateLine("Desired Ending Inv (units)","WC", 431, row_number=33, projects=True, formula_type="ratio_calc",
                 display_format="count"),
    TemplateLine("Units needed",            "WC", 432, row_number=34, projects=True, formula_type="subtotal",
                 display_format="count"),
    TemplateLine("Beginning Inv (units)",   "WC", 433, row_number=35, projects=True, formula_type="prior_ref",
                 display_format="count"),
    TemplateLine("Units to purchase",       "WC", 434, row_number=36, projects=True, formula_type="subtotal",
                 display_format="count"),
    TemplateLine("Purchase price/unit",     "WC", 435, row_number=37, projects=True, formula_type="multiplicative",
                 display_format="per_unit"),
    TemplateLine("Purchase cost",           "WC", 436, row_number=38, projects=True, formula_type="product"),
    TemplateLine("Beginning inventory ($)", "WC", 438, row_number=41, projects=True, formula_type="prior_ref"),
    TemplateLine("Purchase cost ($)",       "WC", 439, row_number=42, projects=True, formula_type="echo"),
    TemplateLine("COGS",                    "WC", 440, row_number=43, projects=True, formula_type="wa_cogs"),
    TemplateLine("Weighted average price",  "WC", 442, row_number=46, projects=True, formula_type="wa_price",
                 display_format="per_unit"),
    TemplateLine("Inventory Check",         "WC", 443, row_number=47, projects=True, formula_type="check"),

    # Section D — Ratios & Assumptions (rows 49-62)
    TemplateLine("Number of days",          "WC", 450, row_number=50, display_format="none"),
    TemplateLine("Days of Payable (DPO)",   "WC", 451, row_number=51, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="days"),
    TemplateLine("Days Sales Outstanding",  "WC", 452, row_number=52, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="days"),
    TemplateLine("Allowance/Gross AR",      "WC", 453, row_number=53, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Write-offs/prev sales",   "WC", 454, row_number=54, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Write-offs",              "WC", 455, row_number=55, projects=True, formula_type="ratio_calc"),
    TemplateLine("Bad Debt Expense (implied)","WC", 456, row_number=56, projects=True, formula_type="bde_calc"),
    TemplateLine("Inventory Policy",        "WC", 457, row_number=57, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Deferred Rev/Sales",      "WC", 458, row_number=58, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Prepaid/SG&A",            "WC", 459, row_number=59, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Other Op Liab/Other OpEx","WC", 460, row_number=60, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Accrued Tax/Tax Owe",     "WC", 461, row_number=61, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Taxes Owe",               "WC", 462, row_number=62, projects=True, formula_type="tax_owe_calc"),
]


# ═══════════════════════════════════════════════════════════════════════════
# PP&E  (Sheet ID: 3)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_PPE_LINES = [
    # PP&E section
    TemplateLine("Beginning PP&E, net",     "PPE", 500, row_number=5,  projects=True, formula_type="prior_ref"),
    TemplateLine("Capital expenditures",    "PPE", 501, row_number=6,  projects=True, formula_type="cross_sheet",
                 source_ref="INFO:CAPEX", font_color="green"),
    TemplateLine("Depreciation",            "PPE", 502, row_number=7,  projects=True, formula_type="dep_calc"),
    TemplateLine("Asset sales/write-offs",  "PPE", 503, row_number=8,  projects=True, formula_type="none",
                 font_color="blue"),
    TemplateLine("Ending PP&E, net",        "PPE", 504, row_number=9,  is_subtotal=True, projects=True,
                 formula_type="roll_forward"),

    # Intangibles section
    TemplateLine("Beginning Intangibles",   "PPE", 508, row_number=12, projects=True, formula_type="prior_ref"),
    TemplateLine("Amortization",            "PPE", 509, row_number=13, projects=True, formula_type="cross_sheet",
                 source_ref="INFO:Amortization", font_color="green"),
    TemplateLine("Ending Intangibles",      "PPE", 510, row_number=14, is_subtotal=True, projects=True,
                 formula_type="roll_forward"),

    # Inputs / drivers
    TemplateLine("Dep/CAPEX",               "PPE", 515, row_number=17, projects=True, formula_type="additive",
                 font_color="blue", display_format="percent"),
    TemplateLine("Amortization (input)",    "PPE", 516, row_number=18, projects=True, formula_type="cross_sheet",
                 source_ref="INFO:Amortization", font_color="green"),
]


# ═══════════════════════════════════════════════════════════════════════════
# DEBT  (Sheet ID: 5)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_DEBT_LINES = [
    # Long-Term Debt (rows 5-9)
    TemplateLine("Beginning LTD Balance",   "DEBT", 600, row_number=6,  projects=True, formula_type="prior_ref"),
    TemplateLine("Issuance",                "DEBT", 601, row_number=7,  projects=True, formula_type="cross_sheet",
                 source_ref="INFO:Debt Issuance", font_color="green"),
    TemplateLine("Repayment (principal)",   "DEBT", 602, row_number=8,  projects=True, formula_type="internal"),
    TemplateLine("Ending LTD Balance",      "DEBT", 603, row_number=9,  is_subtotal=True, projects=True,
                 formula_type="roll_forward"),

    # Revolver (rows 11-14)
    TemplateLine("Beginning Revolver Balance","DEBT", 608, row_number=12, projects=True, formula_type="prior_ref"),
    TemplateLine("Revolver issuance/(repayment)","DEBT", 609, row_number=13, projects=True, formula_type="cross_sheet",
                 source_ref="SCF:Revolver (PLUG)", font_color="green"),
    TemplateLine("Ending Revolver Balance",  "DEBT", 610, row_number=14, is_subtotal=True, projects=True,
                 formula_type="roll_forward"),

    # Interest — LTD (rows 16-19)
    TemplateLine("Average LTD Balance",     "DEBT", 615, row_number=17, projects=True, formula_type="average"),
    TemplateLine("LTD Interest Rate",       "DEBT", 616, row_number=18, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("LTD Interest Expense",    "DEBT", 617, row_number=19, projects=True, formula_type="product"),

    # Interest — Revolver (rows 21-24, IF-THEN logic)
    TemplateLine("Average Revolver Balance","DEBT", 620, row_number=21, projects=True, formula_type="average"),
    TemplateLine("Revolver Borrow Rate",    "DEBT", 621, row_number=22, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Revolver Invest Rate",    "DEBT", 622, row_number=23, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Revolver Interest",       "DEBT", 623, row_number=24, projects=True, formula_type="if_then"),

    # Total Interest Expense (row 26)
    TemplateLine("Total Interest Expense",  "DEBT", 625, row_number=26, is_subtotal=True, projects=True,
                 formula_type="if_then"),

    # Cash Interest (rows 28-32)
    TemplateLine("Cash Balance",            "DEBT", 628, row_number=28, projects=True, formula_type="cross_sheet",
                 source_ref="BS:Cash", font_color="green"),
    TemplateLine("Average Cash Balance",    "DEBT", 629, row_number=29, projects=True, formula_type="average"),
    TemplateLine("Cash Interest Rate",      "DEBT", 630, row_number=30, projects=True, formula_type="carry_forward",
                 font_color="blue", display_format="percent"),
    TemplateLine("Cash Interest Revenue",   "DEBT", 631, row_number=31, projects=True, formula_type="product"),
    TemplateLine("Total Interest Revenue",  "DEBT", 632, row_number=32, is_subtotal=True, projects=True,
                 formula_type="if_then"),

    # Repayment Decomposition (rows 34-36)
    TemplateLine("Total Debt Repayment",    "DEBT", 635, row_number=34, projects=True, formula_type="cross_sheet",
                 source_ref="INFO:Debt Repayment", font_color="green"),
    TemplateLine("Interest portion",        "DEBT", 636, row_number=35, projects=True, formula_type="internal"),
    TemplateLine("Principal portion",       "DEBT", 637, row_number=36, projects=True, formula_type="internal"),
]


# ═══════════════════════════════════════════════════════════════════════════
# INFORMATION TAB  (Sheet ID: 4)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_INFO_LINES = [
    TemplateLine("CAPEX",                   "INFO", 700, row_number=20, projects=True, formula_type="none",
                 font_color="blue"),
    TemplateLine("Debt Issuance",           "INFO", 705, row_number=25, projects=True, formula_type="none",
                 font_color="blue"),
    TemplateLine("Debt Repayment",          "INFO", 706, row_number=26, projects=True, formula_type="none",
                 font_color="blue"),
    TemplateLine("Amortization",            "INFO", 710, row_number=36, projects=True, formula_type="none",
                 font_color="blue"),
]


# ═══════════════════════════════════════════════════════════════════════════
# ASSUMPTIONS (Step Functions)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_ASSUMPTIONS = [
    # ── Revenue ──
    TemplateAssumption("Unit Growth Rate",       "IS",   7,  0.15,  0.0,   "multiplicative",
                       "Annual unit sales growth rate",
                       "Revenue", "percentage", "Unit Growth Rate", -0.5, 1.0),
    TemplateAssumption("Price Growth Rate",      "IS",   8,  0.02,  0.0,   "multiplicative",
                       "Annual selling price inflation",
                       "Revenue", "percentage", "Price Growth Rate", -0.2, 0.5),

    # ── Cost of Goods ──
    TemplateAssumption("COGS/Sales",             "IS",   9,  0.50,  0.0,   "additive",
                       "COGS as a fraction of Sales (historical avg, capped at 99%)",
                       "Expenses", "percentage", "COGS / Sales", 0.0, 0.99),
    TemplateAssumption("Other/Unaccounted Avg",  "IS",   10, 0.0,   0.0,   "additive",
                       "Avg historical Other/Unaccounted (structural income/expense not in standard lines)",
                       "Expenses", "currency", "Other / Unaccounted", -1e12, 1e12),

    # ── Expenses ──
    TemplateAssumption("R&D Growth Rate",        "IS",   11, 0.10,  0.0,   "multiplicative",
                       "R&D expense annual growth rate",
                       "Expenses", "percentage", "R&D Growth Rate", -0.5, 1.0),
    TemplateAssumption("SG&A/Sales",             "IS",   28, 0.06,  0.0,   "additive",
                       "SG&A as a fraction of Sales",
                       "Expenses", "percentage", "SG&A / Sales", 0.0, 0.5),
    TemplateAssumption("Other OpEx/Sales",       "IS",   29, 0.05,  0.0,   "additive",
                       "Other operating expense as a fraction of Sales",
                       "Expenses", "percentage", "Other OpEx / Sales", 0.0, 0.5),
    TemplateAssumption("Tax Rate",               "IS",   30, 0.21,  0.0,   "additive",
                       "Effective income tax rate",
                       "Expenses", "percentage", "Tax Rate", 0.0, 0.5),

    # ── Balance Sheet ──
    TemplateAssumption("Cash/Sales",             "BS",   31, 0.10,  0.0,   "additive",
                       "Target cash balance as a fraction of Sales",
                       "Balance Sheet", "percentage", "Cash / Sales", 0.0, 0.5),
    TemplateAssumption("DTL/Sales",              "BS",   32, 0.032, 0.0,   "additive",
                       "Deferred tax liability as a fraction of Sales",
                       "Balance Sheet", "percentage", "DTL / Sales", 0.0, 0.2),
    TemplateAssumption("Other Assets Avg",       "BS",   33, 0.0,   0.0,   "additive",
                       "Unmapped assets carried forward (plug to reconcile to EDGAR total)",
                       "Balance Sheet", "currency", "Other Assets (plug)", -1e12, 1e12),
    TemplateAssumption("Other Liabilities Avg",  "BS",   34, 0.0,   0.0,   "additive",
                       "Unmapped liabilities carried forward (plug to reconcile to EDGAR total)",
                       "Balance Sheet", "currency", "Other Liabilities (plug)", -1e12, 1e12),

    # ── Capital Expenditure ──
    TemplateAssumption("Dep/CAPEX",              "PPE",  17, 0.60,  0.10,  "additive",
                       "Depreciation as a fraction of CAPEX (steps up each period)",
                       "Capital Expenditure", "percentage", "Depreciation / CAPEX", 0.0, 2.0),

    # ── Working Capital ──
    TemplateAssumption("DSO",                    "WC",   52, 45.0,  0.0,   "additive",
                       "Days Sales Outstanding",
                       "Working Capital", "days", "DSO (Days Sales Outstanding)", 0, 365),
    TemplateAssumption("DPO",                    "WC",   51, 90.0,  0.0,   "additive",
                       "Days Payable Outstanding",
                       "Working Capital", "days", "DPO (Days Payable Outstanding)", 0, 365),
    TemplateAssumption("Allowance/Gross AR",     "WC",   53, 0.20,  0.0,   "additive",
                       "Allowance for doubtful accounts rate",
                       "Working Capital", "percentage", "Allowance / Gross AR", 0.0, 1.0),
    TemplateAssumption("Write-offs/prev sales",  "WC",   54, 0.135, 0.0,   "additive",
                       "Write-offs as a fraction of prior year Sales",
                       "Working Capital", "percentage", "Write-offs / Prior Sales", 0.0, 1.0),
    TemplateAssumption("Inventory Policy",       "WC",   57, 0.20,  0.0,   "additive",
                       "Ending inventory units as a fraction of unit sales",
                       "Working Capital", "percentage", "Inventory Policy", 0.0, 1.0),
    TemplateAssumption("Deferred Rev/Sales",     "WC",   58, 0.12,  0.0,   "additive",
                       "Deferred revenue as a fraction of Sales",
                       "Working Capital", "percentage", "Deferred Rev / Sales", 0.0, 1.0),
    TemplateAssumption("Prepaid/SG&A",           "WC",   59, 0.04,  0.0,   "additive",
                       "Prepaid expense as a fraction of SG&A",
                       "Working Capital", "percentage", "Prepaid / SG&A", 0.0, 0.5),
    TemplateAssumption("Other Op Liab/Other OpEx","WC",  60, 0.028, 0.0,   "additive",
                       "Other operating liability as a fraction of Other OpEx",
                       "Working Capital", "percentage", "Other Op Liab / Other OpEx", 0.0, 0.5),
    TemplateAssumption("Accrued Tax/Tax Owe",    "WC",   61, 0.25,  0.0,   "additive",
                       "Accrued income tax as a fraction of taxes owed",
                       "Working Capital", "percentage", "Accrued Tax / Tax Owed", 0.0, 1.0),
    TemplateAssumption("Purchase Price Growth",  "WC",   37, 0.02,  0.0,   "multiplicative",
                       "Annual purchase-price-per-unit inflation",
                       "Working Capital", "percentage", "Purchase Price Growth", -0.2, 0.5),

    # ── Debt ──
    TemplateAssumption("LTD Interest Rate",      "DEBT", 18, 0.025, 0.0,   "additive",
                       "Long-term debt interest rate",
                       "Debt", "percentage", "LTD Interest Rate", 0.0, 0.2),
    TemplateAssumption("Revolver Borrow Rate",   "DEBT", 22, 0.053, 0.0,   "additive",
                       "Revolver borrowing rate (when balance > 0)",
                       "Debt", "percentage", "Revolver Borrow Rate", 0.0, 0.2),
    TemplateAssumption("Revolver Invest Rate",   "DEBT", 23, 0.028, 0.0,   "additive",
                       "Revolver investing rate (when balance <= 0)",
                       "Debt", "percentage", "Revolver Invest Rate", 0.0, 0.2),
    TemplateAssumption("Cash Interest Rate",     "DEBT", 30, 0.0089, 0.0,  "additive",
                       "Interest earned on cash balance",
                       "Debt", "percentage", "Cash Interest Rate", 0.0, 0.1),

    # ── Capital Structure ──
    TemplateAssumption("Dividend Payout %",      "SCF",  17, 0.25,  0.0,   "additive",
                       "Dividend payout ratio (fraction of Net Income)",
                       "Capital Structure", "percentage", "Dividend Payout %", 0.0, 1.0),
]


# ═══════════════════════════════════════════════════════════════════════════
# Cross-sheet reference map (for documentation / builder use)
# ═══════════════════════════════════════════════════════════════════════════

CROSS_SHEET_REFS: Dict[Tuple[str, str], Tuple[str, str, bool]] = {
    # (target_tab, target_line): (source_tab, source_line, negate)
    # IS ← schedules
    ("IS", "COGS"):                     ("WC",   "COGS",                         True),
    ("IS", "Bad Debt Expense"):         ("WC",   "Bad Debt Expense (implied)",   False),
    ("IS", "Depreciation (ref)"):       ("PPE",  "Depreciation",                 False),
    ("IS", "Amortization (ref)"):       ("PPE",  "Amortization",                 False),
    ("IS", "Interest Expense"):         ("DEBT", "Total Interest Expense",       False),
    ("IS", "Interest Revenue"):         ("DEBT", "Total Interest Revenue",       False),
    # BS ← schedules
    ("BS", "AR, net of allowance"):     ("WC",   "AR, net of allowance",         False),
    ("BS", "Inventory"):                ("WC",   "Ending Inventory ($)",         False),
    ("BS", "Prepaid Expenses"):         ("WC",   "Prepaid Expenses",             False),
    ("BS", "PP&E, net"):                ("PPE",  "Ending PP&E, net",             False),
    ("BS", "Intangibles, net"):         ("PPE",  "Ending Intangibles",           False),
    ("BS", "Accounts Payable"):         ("WC",   "Accounts Payable",             False),
    ("BS", "Deferred Revenue"):         ("WC",   "Deferred Revenue",             False),
    ("BS", "Other Operating Liability"):("WC",   "Other Operating Liability",    False),
    ("BS", "Accrued Income Taxes"):     ("WC",   "Accrued Income Taxes",         False),
    ("BS", "Revolver"):                 ("DEBT", "Ending Revolver Balance",      False),
    ("BS", "Long-Term Debt"):           ("DEBT", "Ending LTD Balance",           False),
    # SCF ← IS/WC/PPE/DEBT
    ("SCF", "Net Income"):              ("IS",   "Net Income",                   False),
    ("SCF", "Depreciation"):            ("IS",   "Depreciation",                 False),
    ("SCF", "Amortization"):            ("IS",   "Amortization",                 False),
    ("SCF", "Change in Working Capital"):("WC",  "Change in Working Capital",    False),
    ("SCF", "Capital Expenditure"):     ("PPE",  "Capital expenditures",         True),
    ("SCF", "Principal Repayment LTD"): ("DEBT", "Repayment (principal)",        False),
    ("SCF", "Issuance of LTD"):         ("DEBT", "Issuance",                     False),
    ("SCF", "Ending Cash Balance"):     ("BS",   "Cash",                         False),
    # DEBT ← SCF/BS
    ("DEBT", "Revolver issuance/(repayment)"):("SCF", "Revolver (PLUG)",         False),
    ("DEBT", "Cash Balance"):           ("BS",   "Cash",                         False),
    # WC ← IS
    ("WC", "Sales (echo)"):             ("IS",   "Sales",                        False),
    ("WC", "SG&A (echo)"):             ("IS",   "SG&A",                         False),
    ("WC", "Other OpEx (echo)"):        ("IS",   "Other Operating Expense",      False),
    ("WC", "Tax Expense (echo)"):       ("IS",   "Income Tax Expense",           False),
    ("WC", "Unit Sales"):               ("IS",   "Units",                        False),
    # PPE ← INFO
    ("PPE", "Capital expenditures"):    ("INFO", "CAPEX",                        False),
    ("PPE", "Amortization"):            ("INFO", "Amortization",                 False),
    ("PPE", "Amortization (input)"):    ("INFO", "Amortization",                 False),
    # DEBT ← INFO
    ("DEBT", "Issuance"):               ("INFO", "Debt Issuance",                False),
    ("DEBT", "Total Debt Repayment"):   ("INFO", "Debt Repayment",               False),
    # BS ratios ← IS/SCF
    ("BS", "Sales (ref)"):              ("IS",   "Sales",                        False),
    ("BS", "Net Income (ref)"):         ("IS",   "Net Income",                   False),
    ("BS", "Paid Dividend (ref)"):      ("SCF",  "Paid Dividend",                False),
    ("BS", "Stock Issuance (ref)"):     ("SCF",  "Stock Issuance",               False),
}


# ═══════════════════════════════════════════════════════════════════════════
# Public API (preserves backward-compatible function signatures)
# ═══════════════════════════════════════════════════════════════════════════

def get_default_template() -> ModelTemplate:
    all_lines = (
        DEFAULT_IS_LINES + DEFAULT_BS_LINES + DEFAULT_SCF_LINES +
        DEFAULT_WC_LINES + DEFAULT_PPE_LINES + DEFAULT_DEBT_LINES +
        DEFAULT_INFO_LINES
    )
    return ModelTemplate(
        name="6-Tab Integrated Financial Model",
        description=(
            "Integrated model with supporting schedules (WC, PP&E, Debt), "
            "Revolver plug, and step-function projections"
        ),
        lines=all_lines,
        assumptions=DEFAULT_ASSUMPTIONS,
        scale_divisor=1_000_000.0,
        historical_periods=3,
        projection_periods=5,
    )


def get_template_line_names(template: "ModelTemplate | None" = None) -> List[str]:
    t = template or get_default_template()
    return [line.model_line for line in t.lines]


def get_template_line_map(template: "ModelTemplate | None" = None) -> Dict[str, TemplateLine]:
    t = template or get_default_template()
    return {line.model_line: line for line in t.lines}


def get_template_lines_by_tab(template: "ModelTemplate | None" = None) -> Dict[str, List[TemplateLine]]:
    t = template or get_default_template()
    by_tab: Dict[str, List[TemplateLine]] = {}
    for line in t.lines:
        by_tab.setdefault(line.statement_type, []).append(line)
    for tab in by_tab:
        by_tab[tab].sort(key=lambda x: x.sort_order)
    return by_tab


def get_template_assumption_map(template: "ModelTemplate | None" = None) -> Dict[str, TemplateAssumption]:
    t = template or get_default_template()
    return {a.name: a for a in t.assumptions}


# Backward-compat alias — old code referenced TemplateDriver; now TemplateAssumption
TemplateDriver = TemplateAssumption


def get_template_driver_map(template: "ModelTemplate | None" = None) -> Dict[str, TemplateAssumption]:
    """Backward-compatible alias for get_template_assumption_map."""
    return get_template_assumption_map(template)
