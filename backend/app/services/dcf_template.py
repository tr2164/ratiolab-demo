"""
DCF Valuation Model Template

Defines the layout for a 3-tab DCF valuation model:
  FCF  — Free Cash Flow build-up (multi-year, historical + projected)
  WACC — Weighted Average Cost of Capital (single-column parameters)
  DCF  — DCF valuation with terminal value and equity bridge

The DCF model is built on top of the 3-statement model data.
It reuses the existing Edgar data pipeline and extracts the
relevant line items (EBIT, D&A, CapEx, ΔNWC, Cash, Debt).

Color coding (matches the 3-statement model):
  blue  — hardcoded input (user-editable assumption)
  black — formula / calculation
  green — cross-model reference (from 3-statement model)
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
from app.services.model_template import TemplateLine, TemplateAssumption, ModelTemplate


# ─── Tab metadata ───────────────────────────────────────────────────────────

DCF_TAB_ORDER = ["FCF", "WACC", "DCF"]

DCF_TAB_DISPLAY_NAMES = {
    "FCF":  "Free Cash Flow",
    "WACC": "WACC",
    "DCF":  "DCF Valuation",
}

DCF_TAB_SHEET_IDS = {
    "FCF":  "fcf",
    "WACC": "wacc",
    "DCF":  "dcf",
}

DCF_TAB_TITLES = {
    "FCF":  "Unlevered Free Cash Flow Build-Up",
    "WACC": "Weighted Average Cost of Capital",
    "DCF":  "DCF Valuation",
}


# ═══════════════════════════════════════════════════════════════════════════
# FREE CASH FLOW TAB
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_FCF_LINES = [
    TemplateLine("Revenue",                 "FCF", 800, row_number=5,  projects=True, formula_type="source_model",
                 source_ref="IS:Sales", font_color="green"),
    TemplateLine("Revenue Growth",          "FCF", 801, row_number=6,  projects=True, formula_type="pct_change",
                 display_format="percent"),

    TemplateLine("EBIT",                    "FCF", 805, row_number=9,  projects=True, formula_type="source_model",
                 source_ref="IS:EBIT", font_color="green"),
    TemplateLine("EBIT Margin",             "FCF", 806, row_number=10, projects=True, formula_type="ratio",
                 display_format="percent"),

    TemplateLine("Tax Rate",                "FCF", 808, row_number=12, projects=True, formula_type="assumption",
                 font_color="blue", display_format="percent"),
    TemplateLine("Taxes on EBIT",           "FCF", 809, row_number=13, projects=True, formula_type="product"),
    TemplateLine("NOPAT",                   "FCF", 810, row_number=14, is_subtotal=True, projects=True,
                 formula_type="subtotal"),

    TemplateLine("Depreciation",            "FCF", 813, row_number=17, projects=True, formula_type="source_model",
                 source_ref="IS:Depreciation", font_color="green"),
    TemplateLine("Amortization",            "FCF", 814, row_number=18, projects=True, formula_type="source_model",
                 source_ref="IS:Amortization", font_color="green"),
    TemplateLine("Capital Expenditure",     "FCF", 816, row_number=20, projects=True, formula_type="source_model",
                 source_ref="SCF:Capital Expenditure", font_color="green"),
    TemplateLine("Increase in NWC",         "FCF", 818, row_number=22, projects=True, formula_type="source_model",
                 source_ref="WC:Change in Working Capital", font_color="green"),

    TemplateLine("Unlevered Free Cash Flow","FCF", 820, row_number=24, is_subtotal=True, projects=True,
                 formula_type="subtotal"),

    TemplateLine("UFCF Margin",             "FCF", 825, row_number=27, projects=True, formula_type="ratio",
                 display_format="percent"),
    TemplateLine("UFCF Growth",             "FCF", 826, row_number=28, projects=True, formula_type="pct_change",
                 display_format="percent"),
]


# ═══════════════════════════════════════════════════════════════════════════
# WACC TAB (single-column parameters, stored at year=0)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_WACC_LINES = [
    # Cost of Equity (CAPM)
    TemplateLine("Risk-Free Rate",          "WACC", 900, row_number=6,  formula_type="assumption",
                 font_color="blue", display_format="percent"),
    TemplateLine("Equity Risk Premium",     "WACC", 901, row_number=7,  formula_type="assumption",
                 font_color="blue", display_format="percent"),
    TemplateLine("Beta",                    "WACC", 902, row_number=8,  formula_type="assumption",
                 font_color="blue", display_format="none"),
    TemplateLine("Size Premium",            "WACC", 903, row_number=9,  formula_type="assumption",
                 font_color="blue", display_format="percent"),
    TemplateLine("Cost of Equity",          "WACC", 905, row_number=10, is_subtotal=True,
                 formula_type="subtotal", display_format="percent"),

    # Cost of Debt
    TemplateLine("Pre-tax Cost of Debt",    "WACC", 910, row_number=13, formula_type="assumption",
                 font_color="blue", display_format="percent"),
    TemplateLine("Marginal Tax Rate",       "WACC", 911, row_number=14, formula_type="assumption",
                 font_color="blue", display_format="percent"),
    TemplateLine("After-tax Cost of Debt",  "WACC", 912, row_number=15, is_subtotal=True,
                 formula_type="subtotal", display_format="percent"),

    # Capital Structure
    TemplateLine("Equity Weight",           "WACC", 920, row_number=18, formula_type="assumption",
                 font_color="blue", display_format="percent"),
    TemplateLine("Debt Weight",             "WACC", 921, row_number=19, formula_type="subtotal",
                 display_format="percent"),

    # WACC
    TemplateLine("WACC",                    "WACC", 930, row_number=22, is_subtotal=True,
                 formula_type="subtotal", display_format="percent"),
]


# ═══════════════════════════════════════════════════════════════════════════
# DCF VALUATION TAB
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_DCF_LINES = [
    # Present Value of FCF (projected years only)
    TemplateLine("Unlevered FCF",           "DCF", 1000, row_number=5,  projects=True, formula_type="source_tab",
                 source_ref="FCF:Unlevered Free Cash Flow", font_color="green"),
    TemplateLine("Discount Period",         "DCF", 1001, row_number=6,  projects=True, formula_type="sequence"),
    TemplateLine("Discount Factor",         "DCF", 1002, row_number=7,  projects=True, formula_type="discount_factor"),
    TemplateLine("PV of UFCF",              "DCF", 1003, row_number=8,  projects=True, formula_type="product"),
    TemplateLine("Cumulative PV of UFCF",   "DCF", 1004, row_number=9,  is_subtotal=True, projects=True,
                 formula_type="running_sum"),

    # Terminal Value
    TemplateLine("Terminal Growth Rate",    "DCF", 1010, row_number=12, formula_type="assumption",
                 font_color="blue", display_format="percent"),
    TemplateLine("Terminal Year UFCF",      "DCF", 1011, row_number=13, formula_type="terminal_fcf"),
    TemplateLine("Terminal Value (Gordon Growth)","DCF", 1012, row_number=14, formula_type="gordon_growth"),
    TemplateLine("Exit EV/EBITDA Multiple", "DCF", 1013, row_number=15, formula_type="assumption",
                 font_color="blue", display_format="none"),
    TemplateLine("Terminal Year EBITDA",    "DCF", 1014, row_number=16, formula_type="terminal_ebitda"),
    TemplateLine("Terminal Value (Exit Multiple)","DCF", 1015, row_number=17, formula_type="exit_multiple"),
    TemplateLine("PV of Terminal Value (Gordon)", "DCF", 1016, row_number=18, formula_type="pv_terminal"),
    TemplateLine("PV of Terminal Value (Exit)",   "DCF", 1017, row_number=19, formula_type="pv_terminal"),

    # Enterprise → Equity Bridge
    TemplateLine("Enterprise Value (Gordon Growth)","DCF", 1020, row_number=22, is_subtotal=True,
                 formula_type="subtotal"),
    TemplateLine("Enterprise Value (Exit Multiple)","DCF", 1021, row_number=23, is_subtotal=True,
                 formula_type="subtotal"),
    TemplateLine("Less: Total Debt",        "DCF", 1025, row_number=25, formula_type="source_model",
                 source_ref="BS:Total Liability", font_color="green"),
    TemplateLine("Plus: Cash",              "DCF", 1026, row_number=26, formula_type="source_model",
                 source_ref="BS:Cash", font_color="green"),
    TemplateLine("Equity Value (Gordon Growth)",  "DCF", 1030, row_number=28, is_subtotal=True,
                 formula_type="subtotal"),
    TemplateLine("Equity Value (Exit Multiple)",  "DCF", 1031, row_number=29, is_subtotal=True,
                 formula_type="subtotal"),
    TemplateLine("Shares Outstanding (M)",  "DCF", 1035, row_number=31, formula_type="assumption",
                 font_color="blue", display_format="none"),
    TemplateLine("Implied Price (Gordon Growth)", "DCF", 1040, row_number=33, is_subtotal=True,
                 formula_type="subtotal", display_format="per_unit"),
    TemplateLine("Implied Price (Exit Multiple)", "DCF", 1041, row_number=34, is_subtotal=True,
                 formula_type="subtotal", display_format="per_unit"),
    TemplateLine("Current Market Price",    "DCF", 1045, row_number=36, formula_type="assumption",
                 font_color="blue", display_format="per_unit"),
    TemplateLine("Upside / (Downside) Gordon",    "DCF", 1046, row_number=37,
                 formula_type="subtotal", display_format="percent"),
    TemplateLine("Upside / (Downside) Exit",      "DCF", 1047, row_number=38,
                 formula_type="subtotal", display_format="percent"),
]


# ═══════════════════════════════════════════════════════════════════════════
# DCF ASSUMPTIONS
# ═══════════════════════════════════════════════════════════════════════════

DCF_ASSUMPTIONS = [
    # FCF
    TemplateAssumption("DCF Tax Rate",           "FCF",  12, 0.21,  0.0, "additive",
                       "Tax rate applied to EBIT for NOPAT calculation",
                       "Free Cash Flow", "percentage", "Tax Rate", 0.0, 0.5),

    # WACC — Cost of Equity
    TemplateAssumption("Risk-Free Rate",         "WACC",  6, 0.043, 0.0, "additive",
                       "10-year U.S. Treasury yield",
                       "Cost of Equity", "percentage", "Risk-Free Rate", 0.0, 0.15),
    TemplateAssumption("Equity Risk Premium",    "WACC",  7, 0.055, 0.0, "additive",
                       "Market equity risk premium",
                       "Cost of Equity", "percentage", "Equity Risk Premium", 0.0, 0.12),
    TemplateAssumption("Beta",                   "WACC",  8, 1.10,  0.0, "additive",
                       "Levered beta of the company",
                       "Cost of Equity", "percentage", "Beta", 0.0, 3.0),
    TemplateAssumption("Size Premium",           "WACC",  9, 0.0,   0.0, "additive",
                       "Small-cap size premium (0 for large-cap)",
                       "Cost of Equity", "percentage", "Size Premium", 0.0, 0.06),

    # WACC — Cost of Debt
    TemplateAssumption("Pre-tax Cost of Debt",   "WACC", 13, 0.05,  0.0, "additive",
                       "Pre-tax cost of debt",
                       "Cost of Debt", "percentage", "Pre-tax Cost of Debt", 0.0, 0.2),
    TemplateAssumption("Marginal Tax Rate",      "WACC", 14, 0.21,  0.0, "additive",
                       "Marginal tax rate for interest tax shield",
                       "Cost of Debt", "percentage", "Marginal Tax Rate", 0.0, 0.5),

    # WACC — Capital Structure
    TemplateAssumption("Equity Weight",          "WACC", 18, 0.80,  0.0, "additive",
                       "Equity as a fraction of total capital (market value basis)",
                       "Capital Structure", "percentage", "Equity / Total Capital", 0.0, 1.0),

    # Terminal Value
    TemplateAssumption("Terminal Growth Rate",   "DCF",  12, 0.025, 0.0, "additive",
                       "Long-term perpetual growth rate for Gordon Growth model",
                       "Terminal Value", "percentage", "Terminal Growth Rate", 0.0, 0.05),
    TemplateAssumption("Exit EV/EBITDA Multiple","DCF",  15, 12.0,  0.0, "additive",
                       "Exit EV/EBITDA multiple for terminal value",
                       "Terminal Value", "percentage", "Exit EV/EBITDA", 0.0, 30.0),

    # Equity Bridge
    TemplateAssumption("Shares Outstanding (M)", "DCF",  31, 100.0, 0.0, "additive",
                       "Diluted shares outstanding in millions",
                       "Equity Bridge", "currency", "Shares Outstanding (M)", 0.1, 50000.0),
    TemplateAssumption("Current Market Price",   "DCF",  36, 100.0, 0.0, "additive",
                       "Current stock price for upside/downside calculation",
                       "Equity Bridge", "currency", "Current Market Price", 0.01, 100000.0),
]


# ═══════════════════════════════════════════════════════════════════════════
# Section breaks for visual layout
# ═══════════════════════════════════════════════════════════════════════════

DCF_SECTION_BREAKS = {
    "FCF": [
        (805, ""),
        (808, ""),
        (813, "Adjustments"),
        (820, ""),
        (825, "Key Metrics"),
    ],
    "WACC": [
        (910, "Cost of Debt"),
        (920, "Capital Structure"),
        (930, ""),
    ],
    "DCF": [
        (1010, "Terminal Value"),
        (1020, "Enterprise to Equity Bridge"),
        (1030, ""),
        (1035, ""),
        (1040, "Implied Valuation"),
        (1045, ""),
    ],
}

DCF_INDENT_SORT_ORDERS = set([
    801,  # Revenue Growth
    806,  # EBIT Margin
    808, 809,  # Tax Rate, Taxes
    813, 814, 816, 818,  # Adjustments
    825, 826,  # Metrics
    901, 902, 903,  # CAPM inputs
    911,  # Tax rate
    921,  # Debt weight
    1001, 1002, 1003,  # Discount calcs
    1011, 1012, 1013, 1014, 1015, 1016, 1017,  # Terminal value
    1025, 1026,  # Debt/Cash
    1035,  # Shares
    1045, 1046, 1047,  # Market price & upside
])


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════

def get_dcf_template() -> ModelTemplate:
    all_lines = DEFAULT_FCF_LINES + DEFAULT_WACC_LINES + DEFAULT_DCF_LINES
    return ModelTemplate(
        name="DCF Valuation Model",
        description=(
            "Discounted Cash Flow valuation with WACC, terminal value "
            "(Gordon Growth & Exit Multiple), and equity bridge"
        ),
        lines=all_lines,
        assumptions=DCF_ASSUMPTIONS,
        scale_divisor=1_000_000.0,
        historical_periods=3,
        projection_periods=5,
    )
