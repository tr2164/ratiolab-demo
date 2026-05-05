"""
Stage 2: Semantic Mapping Engine

Maps edgartools standardized concept names to model line items.

Architecture (simplified):
1. DB-backed per-company DataMap records always take priority (user edits).
2. STANDARD_CONCEPT_MAP maps edgartools' ~95 standardized concepts to our template.
3. Anything still unmapped goes to the LLM for semantic mapping.
4. All mappings are persisted to DataMap so users can review/edit.

Updated for the 6-tab model with statement types:
  IS, BS, SCF, WC, PPE, DEBT, INFO
"""
import json
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.data_map import DataMap
from app.models.financial_data import FinancialData
from app.services.model_settings import get_config
from app.services.prompt_service import render_prompt

from app.services.model_template import get_default_template

logger = logging.getLogger(__name__)
settings = get_settings()

# ── EdgarTools concept → model template mapping ──
# Format: concept_name → (model_line, statement_type, sign_flip, sort_order)
#
# Statement types: IS, BS, SCF, WC, PPE, DEBT, INFO
# Lines that feed supporting schedules (WC/PPE/DEBT) are mapped to those tabs.
# The IS/BS/SCF tabs assemble results from the schedules via cross-sheet refs.

STANDARD_CONCEPT_MAP: Dict[str, Tuple[str, str, int, int]] = {
    # ── Income Statement ──
    "Revenue":                              ("Sales",                   "IS", 1, 100),
    "Revenues":                             ("Sales",                   "IS", 1, 100),
    "RevenueFromContractWithCustomerExcludingAssessedTax": ("Sales",    "IS", 1, 100),
    "RevenueFromContractWithCustomerIncludingAssessedTax": ("Sales",    "IS", 1, 100),
    "SalesRevenueNet":                      ("Sales",                   "IS", 1, 100),
    "SalesRevenueGoodsNet":                 ("Sales",                   "IS", 1, 100),
    "SalesRevenueServicesNet":              ("Sales",                   "IS", 1, 100),
    "CostOfGoodsAndServicesSold":           ("COGS",                    "WC", 1, 440),
    "CostOfRevenue":                        ("COGS",                    "WC", 1, 440),
    "CostOfGoodsSold":                      ("COGS",                    "WC", 1, 440),
    "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization": ("COGS", "WC", 1, 440),
    "ResearchAndDevelopementExpenses":       ("R&D Expense",             "IS", 1, 110),
    "ResearchAndDevelopmentExpense":         ("R&D Expense",             "IS", 1, 110),
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost": ("R&D Expense", "IS", 1, 110),
    "SellingGeneralAndAdminExpenses":        ("SG&A",                    "IS", 1, 112),
    "SellingGeneralAndAdministrativeExpense": ("SG&A",                   "IS", 1, 112),
    "GeneralAndAdministrativeExpense":       ("SG&A",                    "IS", 1, 112),
    "SellingAndMarketingExpense":            ("SG&A",                    "IS", 1, 112),
    "OperatingIncomeLoss":                  ("EBIT",                    "IS", 1, 115),
    "PretaxIncomeLoss":                     ("EBT",                     "IS", 1, 122),
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": ("EBT", "IS", 1, 122),
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments": ("EBT", "IS", 1, 122),
    "IncomeTaxes":                          ("Income Tax Expense",      "IS", 1, 124),
    "IncomeTaxExpenseBenefit":              ("Income Tax Expense",      "IS", 1, 124),
    "NetIncome":                            ("Net Income",              "IS", 1, 125),
    "NetIncomeLoss":                        ("Net Income",              "IS", 1, 125),
    "ProfitLoss":                           ("Net Income",              "IS", 1, 125),
    "NetIncomeLossAvailableToCommonStockholdersBasic": ("Net Income",   "IS", 1, 125),
    "EarningsPerShareBasic":                ("Units",                   "IS", 1, 101),
    "EarningsPerShareDiluted":              ("Units",                   "IS", 1, 101),

    # ── Balance Sheet — Assets ──
    "CashAndCashEquivalentsAtCarryingValue":("Cash",                    "BS", 1, 207),
    "CashAndMarketableSecurities":          ("Cash",                    "BS", 1, 207),
    "CashCashEquivalentsAndShortTermInvestments": ("Cash",              "BS", 1, 207),
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": ("Cash", "BS", 1, 207),
    "Cash":                                 ("Cash",                    "BS", 1, 207),
    "TradeReceivables":                     ("AR, net of allowance",    "WC", 1, 412),
    "AccountsReceivableNetCurrent":         ("AR, net of allowance",    "WC", 1, 412),
    "AccountsReceivableNet":                ("AR, net of allowance",    "WC", 1, 412),
    "ReceivablesNetCurrent":                ("AR, net of allowance",    "WC", 1, 412),
    "Inventories":                          ("Ending Inventory ($)",    "WC", 1, 413),
    "InventoryNet":                         ("Ending Inventory ($)",    "WC", 1, 413),
    "InventoryFinishedGoods":               ("Ending Inventory ($)",    "WC", 1, 413),
    "OtherNonOperatingCurrentAssets":        ("Prepaid Expenses",        "WC", 1, 414),
    "PrepaidExpenseAndOtherAssetsCurrent":   ("Prepaid Expenses",        "WC", 1, 414),
    "PrepaidExpenseCurrent":                 ("Prepaid Expenses",        "WC", 1, 414),
    "OtherAssetsCurrent":                    ("Prepaid Expenses",        "WC", 1, 414),
    "PlantPropertyEquipmentNet":            ("Ending PP&E, net",        "PPE", 1, 504),
    "PropertyPlantAndEquipmentNet":         ("Ending PP&E, net",        "PPE", 1, 504),
    "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization": ("Ending PP&E, net", "PPE", 1, 504),
    "Goodwill":                             ("Intangibles, net",        "PPE", 1, 510),
    "IntangibleAssets":                     ("Ending Intangibles",      "PPE", 1, 510),
    "IntangibleAssetsNetExcludingGoodwill":  ("Ending Intangibles",      "PPE", 1, 510),
    "FiniteLivedIntangibleAssetsNet":       ("Ending Intangibles",      "PPE", 1, 510),
    "GoodwillAndIntangibleAssetsNet":       ("Ending Intangibles",      "PPE", 1, 510),

    # ── Allowance (WC sub-schedule) ──
    "AllowanceForDoubtfulAccountsReceivableCurrent": ("Allowance",      "WC", 1, 411),

    # ── Balance Sheet — Liabilities ──
    "TradePayables":                        ("Accounts Payable",        "WC", 1, 417),
    "AccountsPayableCurrent":               ("Accounts Payable",        "WC", 1, 417),
    "AccountsPayableAndAccruedLiabilitiesCurrent": ("Accounts Payable", "WC", 1, 417),
    "DeferredRevenueCurrent":               ("Deferred Revenue",        "WC", 1, 418),
    "DeferredRevenue":                      ("Deferred Revenue",        "WC", 1, 418),
    "DeferredRevenueNoncurrent":            ("Deferred Revenue",        "WC", 1, 418),
    "ContractWithCustomerLiabilityCurrent":  ("Deferred Revenue",        "WC", 1, 418),
    "ContractWithCustomerLiability":         ("Deferred Revenue",        "WC", 1, 418),
    "OtherOperatingCurrentLiabilities":     ("Other Operating Liability","WC", 1, 419),
    "AccruedLiabilitiesCurrent":            ("Other Operating Liability","WC", 1, 419),
    "OtherLiabilitiesCurrent":              ("Other Operating Liability","WC", 1, 419),
    "EmployeeRelatedLiabilitiesCurrent":    ("Other Operating Liability","WC", 1, 419),
    "OtherSundryLiabilitiesCurrent":        ("Other Operating Liability","WC", 1, 419),
    "TaxesPayable":                         ("Accrued Income Taxes",    "WC", 1, 420),
    "AccruedIncomeTaxesCurrent":            ("Accrued Income Taxes",    "WC", 1, 420),
    "IncomeTaxesPayable":                   ("Accrued Income Taxes",    "WC", 1, 420),
    "TaxesPayableCurrent":                  ("Accrued Income Taxes",    "WC", 1, 420),
    "InterestPayableCurrent":               ("Accrued Income Taxes",    "WC", 1, 420),
    "ShortTermDebt":                        ("Ending Revolver Balance", "DEBT", 1, 610),
    "ShortTermBorrowings":                  ("Ending Revolver Balance", "DEBT", 1, 610),
    "LineOfCredit":                         ("Ending Revolver Balance", "DEBT", 1, 610),
    "CommercialPaper":                      ("Ending Revolver Balance", "DEBT", 1, 610),
    "LongTermDebt":                         ("Ending LTD Balance",      "DEBT", 1, 603),
    "LongTermDebtNoncurrent":               ("Ending LTD Balance",      "DEBT", 1, 603),
    "LongTermDebtAndCapitalLeaseObligations": ("Ending LTD Balance",    "DEBT", 1, 603),
    "FinanceLeaseLiabilityNoncurrent":      ("Ending LTD Balance",      "DEBT", 1, 603),
    "DeferredTaxNonCurrentLiabilities":     ("Deferred Income Tax",     "BS", 1, 222),
    "DeferredIncomeTaxLiabilitiesNet":       ("Deferred Income Tax",     "BS", 1, 222),
    "OtherNonOperatingNonCurrentLiabilities":("Deferred Income Tax",    "BS", 1, 222),
    "OtherLiabilitiesNoncurrent":           ("Deferred Income Tax",     "BS", 1, 222),

    # ── Balance Sheet — Equity ──
    "CommonStockValue":                     ("Paid In Capital",         "BS", 1, 225),
    "AdditionalPaidInCapitalCommonStock":   ("Paid In Capital",         "BS", 1, 225),
    "AdditionalPaidInCapital":              ("Paid In Capital",         "BS", 1, 225),
    "CommonStocksIncludingAdditionalPaidInCapital": ("Paid In Capital", "BS", 1, 225),
    "RetainedEarningsAccumulatedDeficit":   ("Retained Earnings",       "BS", 1, 226),
    "TreasuryStockValue":                   ("Paid In Capital",         "BS", -1, 225),
    "TreasuryStockCommonValue":             ("Paid In Capital",         "BS", -1, 225),
    "AccumulatedOtherComprehensiveIncomeLossNetOfTax": ("Retained Earnings", "BS", 1, 226),

    # ── Cash Flow Statement ──
    "DepreciationExpense":                  ("Depreciation",            "PPE", 1, 502),
    "DepreciationDepletionAndAmortization": ("Depreciation",            "PPE", 1, 502),
    "Depreciation":                         ("Depreciation",            "PPE", 1, 502),
    "AmortizationOfIntangibleAssets":        ("Amortization",            "PPE", 1, 512),
    "AdjustmentForAmortization":             ("Amortization",            "PPE", 1, 512),
    "ShareBasedCompensation":               ("Net Income",              "IS", 1, 125),
    "CapitalExpenses":                      ("Capital expenditures",    "PPE", -1, 501),
    "PaymentsToAcquirePropertyPlantAndEquipment":("Capital expenditures","PPE", -1, 501),
    "CapitalExpenditureReportedInInvestingActivities": ("Capital expenditures", "PPE", -1, 501),
    "PaymentsOfDividendsCommonStock":       ("Paid Dividend",           "SCF", -1, 311),
    "PaymentsOfDividends":                  ("Paid Dividend",           "SCF", -1, 311),
    "Dividends":                            ("Paid Dividend",           "SCF", -1, 311),
    "DividendsCash":                        ("Paid Dividend",           "SCF", -1, 311),
    "PaymentsForRepurchaseOfCommonStock":   ("Stock Issuance",          "SCF", -1, 315),
    "StockRepurchasedDuringPeriodValue":    ("Stock Issuance",          "SCF", -1, 315),
    "ProceedsFromIssuanceOfCommonStock":    ("Stock Issuance",          "SCF", 1, 315),
    "ProceedsFromStockOptionsExercised":    ("Stock Issuance",          "SCF", 1, 315),

    # Debt issuance / repayment (INFO tab)
    "ProceedsFromIssuanceOfLongTermDebt":   ("Debt Issuance",           "INFO", 1, 702),
    "ProceedsFromOtherDebt":                ("Debt Issuance",           "INFO", 1, 702),
    "ProceedsFromDebtNetOfIssuanceCosts":   ("Debt Issuance",           "INFO", 1, 702),
    "RepaymentsOfLongTermDebt":             ("Debt Repayment",          "INFO", 1, 703),
    "RepaymentsOfOtherDebt":                ("Debt Repayment",          "INFO", 1, 703),
    "RepaymentsOfDebt":                     ("Debt Repayment",          "INFO", 1, 703),

    # Deferred tax assets (map to BS, sign-flipped)
    "DeferredTaxNoncurrentAssets":           ("Deferred Income Tax",     "BS", -1, 222),
    "DeferredIncomeTaxAssetsNet":            ("Deferred Income Tax",     "BS", -1, 222),

    # Interest (map to debt schedule)
    "InterestExpense":                      ("LTD Interest Expense",    "DEBT", 1, 617),
    "InterestExpenseDebt":                  ("LTD Interest Expense",    "DEBT", 1, 617),
    "InterestIncomeExpenseNet":             ("LTD Interest Expense",    "DEBT", 1, 617),
}

_SKIP_CONCEPTS = frozenset({
    # Aggregation-level totals (we compute our own)
    "Assets", "AssetsCurrent", "AssetsNoncurrent",
    "CurrentAssetsTotal", "CurrentLiabilitiesTotal",
    "NonCurrentLiabilitiesTotal", "LiabilitiesAndEquity",
    "Liabilities", "LiabilitiesCurrent", "LiabilitiesNoncurrent",
    "LiabilitiesAndStockholdersEquity",
    "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "AllEquityBalance", "AllEquityBalanceIncludingMinorityInterest",
    "CommonEquity",
    "MinorityInterestBalance", "MinorityInterest",

    # Non-operating / below-the-line items
    "NonoperatingIncomeExpense",
    "MinorityInterestIncomeExpense",
    "OtherOperatingExpense",
    "TotalOperatingExpenses", "OperatingExpenses",
    "GrossProfit",
    "ComprehensiveIncomeNetOfTax",
    "OtherComprehensiveIncomeLossNetOfTax",
    "ExtraordinaryItemsIncomeExpense(PostTax)",

    # Investment / non-core items
    "LongtermInvestments", "ShortTermInvestments",
    "AvailableForSaleSecuritiesCurrent",
    "MarketableSecuritiesCurrent", "MarketableSecuritiesNoncurrent",
    "OtherNonOperatingNonCurrentAssets", "OtherAssetsNoncurrent",
    "OtherNonOperatingCurrentLiabilities",
    "DividendsPayable",
    "RetirementRelatedNonCurrentLiabilities",
    "RestructuringExpenseBenefit",
    "RestructuringAndRelatedCostIncurredCost",

    # Share counts (not dollar amounts)
    "SharesAverage", "SharesFullyDilutedAverage",
    "CommonStockSharesOutstanding", "CommonStockSharesIssued",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    "WeightedAverageNumberOfDilutedSharesOutstanding",

    "nan",
})

_CONCEPT_MAP_LOWER: Dict[str, Tuple[str, str, int, int]] = {
    k.lower(): v for k, v in STANDARD_CONCEPT_MAP.items()
}

_SKIP_LOWER = frozenset(s.lower() for s in _SKIP_CONCEPTS)


def _match_standard_concept(account_name: str) -> Optional[Tuple[str, str, int, int]]:
    """Try to match an account name against the standard concept map."""
    name = account_name.strip()
    name_lower = name.lower()

    if name_lower in _SKIP_LOWER or name in _SKIP_CONCEPTS:
        return None

    match = _CONCEPT_MAP_LOWER.get(name_lower)
    if match:
        return match

    for suffix in [", net", " (net)", " net", ", total"]:
        stripped = name_lower.rstrip().removesuffix(suffix)
        if stripped != name_lower:
            match = _CONCEPT_MAP_LOWER.get(stripped)
            if match:
                return match

    return None


async def generate_mapping_for_company(
    company_id: int, db: AsyncSession
) -> List[DataMap]:
    """Generate the data map for a company.

    Priority chain:
    1. Existing per-company DataMap records (user-saved / manual edits)
    2. Standard concept matching (edgartools standardized names)
    3. LLM fallback (for anything unmatched)
    """
    PRESERVED_METHODS = {"manual", "companyfacts", "manual_entry", "copied"}
    existing = await db.execute(
        select(DataMap).where(DataMap.company_id == company_id)
    )
    manual_maps: Dict[str, DataMap] = {}
    stale_ids = []
    for m in existing.scalars().all():
        if m.mapping_method in PRESERVED_METHODS:
            manual_maps[m.raw_account_name] = m
        else:
            stale_ids.append(m.id)

    if stale_ids:
        from sqlalchemy import delete as sa_delete
        await db.execute(
            sa_delete(DataMap).where(DataMap.id.in_(stale_ids))
        )
        logger.info(f"Cleared {len(stale_ids)} auto-generated mappings for company {company_id}")

    result = await db.execute(
        select(FinancialData)
        .where(FinancialData.company_id == company_id)
        .distinct(FinancialData.account_name)
    )
    raw_items = result.scalars().all()

    mapped = []
    unmapped = []

    for item in raw_items:
        if item.account_name in manual_maps:
            mapped.append(manual_maps[item.account_name])
            continue

        concept_match = _match_standard_concept(item.account_name)
        if concept_match:
            model_line, stmt, sign, sort = concept_match
            mapped.append(DataMap(
                company_id=company_id,
                raw_account_name=item.account_name,
                xbrl_tag=None,
                model_line=model_line,
                statement_type=stmt,
                sign_flip=sign,
                sort_order=sort,
                confidence=0.98,
                mapping_method="standard_concept",
                is_verified=True,
            ))
            continue

        unmapped.append(item)

    if unmapped:
        llm_mappings = await _llm_map_accounts(unmapped, db, company_id)
        mapped.extend(llm_mappings)

    seen = set()
    unique = []
    new_count = 0
    for m in mapped:
        key = (m.raw_account_name, m.model_line)
        if key not in seen:
            seen.add(key)
            unique.append(m)
            if m.id is None:
                db.add(m)
                new_count += 1

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning(f"Mapping commit conflict, retrying with merge: {e}")
        for m in unique:
            if m.id is None:
                await db.merge(m)
        await db.commit()

    reused = sum(1 for m in unique if m.id is not None and m.mapping_method in ("manual", "standard_concept"))
    concept_matched = sum(1 for m in unique if m.mapping_method == "standard_concept" and m.id is None)
    logger.info(
        f"Company {company_id}: {len(unique)} mappings "
        f"({reused} reused, {concept_matched} new concept matches, "
        f"{len(unmapped)} sent to LLM)"
    )
    return unique


_MAX_LLM_ITEMS = 50
_LLM_BATCH_SIZE = 50


def _pre_filter_unmapped(items: list, template_lines: list) -> tuple:
    """Template-driven filter: only send accounts to the LLM if they might
    plausibly map to one of the template's defined model lines.
    """
    template_keywords = set()
    for line_name in template_lines:
        for word in line_name.lower().replace("&", " ").replace("/", " ").split():
            cleaned = word.strip("()[],-")
            if len(cleaned) >= 3 and cleaned not in {"the", "and", "for", "net", "inc", "dec"}:
                template_keywords.add(cleaned)

    candidates = []
    skipped = []
    for item in items:
        name = (item.account_name or "").strip()
        name_lower = name.lower()
        if name in _SKIP_CONCEPTS or name_lower in _SKIP_LOWER:
            skipped.append(item)
            continue
        if any(kw in name_lower for kw in template_keywords):
            candidates.append(item)
        else:
            skipped.append(item)

    if len(candidates) > _MAX_LLM_ITEMS:
        overflow = candidates[_MAX_LLM_ITEMS:]
        candidates = candidates[:_MAX_LLM_ITEMS]
        skipped.extend(overflow)

    return candidates, skipped


async def _llm_map_accounts(
    unmapped_items: list,
    db: AsyncSession,
    company_id: int = 0,
) -> List[DataMap]:
    """Use LLM to map unmapped account names to model template lines."""
    from app.services.model_template import get_template_line_names
    template_lines = get_template_line_names()

    candidates, skipped = _pre_filter_unmapped(unmapped_items, template_lines)
    if skipped:
        logger.info(f"Pre-filtered {len(skipped)} items (no template-relevant keywords)")
    if not candidates:
        logger.info("No accounts need LLM mapping after pre-filtering")
        return []

    if not settings.openai_api_key and not settings.anthropic_api_key:
        logger.warning("No AI API key configured, skipping LLM mapping")
        return []

    known_lines = sorted(template_lines)
    all_results: List[DataMap] = []
    chunks = [
        candidates[i:i + _LLM_BATCH_SIZE]
        for i in range(0, len(candidates), _LLM_BATCH_SIZE)
    ]

    for chunk_idx, chunk in enumerate(chunks):
        chunk_results = await _llm_map_chunk(
            chunk, known_lines, company_id, db, chunk_idx, len(chunks)
        )
        all_results.extend(chunk_results)

    logger.info(f"LLM mapping complete: {len(all_results)} mappings from {len(candidates)} candidates")
    return all_results


async def _llm_map_chunk(
    chunk: list,
    known_lines: list,
    company_id: int,
    db: AsyncSession,
    chunk_idx: int,
    total_chunks: int,
) -> List[DataMap]:
    """Map a single chunk of accounts via LLM."""
    raw_accounts = [i.account_name for i in chunk]

    rendered = await render_prompt(
        db, "mapping_llm_fallback",
        target_lines=json.dumps(known_lines),
        raw_accounts=json.dumps(raw_accounts),
    )

    valid_types = ["IS", "BS", "SCF", "WC", "PPE", "DEBT", "INFO"]

    prompt = rendered or f"""You are a financial data mapping assistant. Map each raw account name
to a standardized model line item. Prefer lines from this known list when there's a good match:
{json.dumps(known_lines)}

However, if an account clearly represents something not in the list, you MAY create a new
descriptive model line name. Use standard financial modeling conventions.
Mark items as "SKIP" if they are too granular for a standard financial model.

Valid statement_type values: {json.dumps(valid_types)}
Use these guidelines:
- IS: revenue, expenses, taxes, net income
- BS: assets, liabilities, equity (only items NOT in supporting schedules)
- SCF: cash flow items (dividends, stock issuance)
- WC: working capital items (AR, AP, inventory, deferred revenue, prepaid)
- PPE: fixed assets, depreciation, intangibles, amortization
- DEBT: debt balances, interest rates
- INFO: exogenous inputs (CAPEX schedules, debt issuance/repayment)

For each account, return a JSON array of objects with:
- "raw": the original account name
- "model_line": the best matching model line (or "SKIP")
- "statement_type": one of {json.dumps(valid_types)}
- "sign_flip": 1 for positive items, -1 for expense/outflow items
- "confidence": 0.0 to 1.0

Raw accounts to map:
{json.dumps(raw_accounts)}

Return ONLY the JSON array, no other text."""

    try:
        from app.config import get_anthropic_client, get_openai_client

        if settings.anthropic_api_key:
            client = get_anthropic_client()
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text if response.content else ""
        elif settings.openai_api_key:
            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.default_llm_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
            )
            text = response.choices[0].message.content or ""
        else:
            return []

        if not text or not text.strip():
            logger.warning(f"LLM returned empty response for chunk {chunk_idx+1}/{total_chunks}")
            return []

        text = text.strip()
        if text.startswith("```"):
            text = text.strip("```json").strip("```").strip()

        try:
            items = json.loads(text)
        except json.JSONDecodeError as je:
            logger.error(f"LLM response not valid JSON: {je}. Preview: {text[:200]!r}")
            return []

        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("model_line") == "SKIP":
                continue
            if not item.get("raw") or not item.get("model_line"):
                continue
            stmt = item.get("statement_type", "IS")
            if stmt not in valid_types:
                stmt = "IS"
            results.append(DataMap(
                company_id=company_id,
                raw_account_name=item["raw"],
                model_line=item["model_line"],
                statement_type=stmt,
                sign_flip=item.get("sign_flip", 1),
                sort_order=0,
                confidence=item.get("confidence", 0.7),
                mapping_method="llm",
                is_verified=False,
            ))

        logger.info(f"LLM chunk {chunk_idx+1}/{total_chunks}: {len(results)} mapped from {len(raw_accounts)} accounts")
        return results

    except Exception as e:
        logger.error(f"LLM mapping failed: {type(e).__name__}: {e}")
        return []


# ---------------------------------------------------------------------------
# Template Completeness — "Master Mapper"
# ---------------------------------------------------------------------------

_COMPUTED_FORMULA_TYPES = frozenset({
    'subtotal', 'cross_sheet', 'cross_sheet_negate', 'internal',
    'balance_check', 'plug', 'backward_derive', 'prior_ending_cash',
    'echo', 'bs_delta', 'wc_delta', 'bde_calc', 'tax_owe_calc',
    'dep_calc', 'check', 'wa_cogs', 'wa_price', 'product',
    'if_then', 'average', 'negate_ref', 'prior_ref',
    'carry_forward', 'additive',
})

# Lines that are always manual inputs — no EDGAR data will ever populate them.
# They should not appear as "unmapped" in the completeness report.
_ALWAYS_MANUAL_LINES = frozenset({
    "Units",
    "Unit Selling Price",
    "Write-offs",
    "Desired Ending Inv (units)",
    "Purchase price/unit",
    "Number of days",
    "Asset sales/write-offs",
})


async def get_template_completeness(
    company_id: int, db: AsyncSession
) -> List[Dict]:
    """For each mappable line in the model template, report its mapping status.

    Excludes computed/derived lines (subtotals, cross-sheet refs, ratios)
    that don't need XBRL data — only lines requiring external data are reported.
    Lines in _ALWAYS_MANUAL_LINES are shown as "manual_input" (not "unmapped").
    """
    template = get_default_template()
    mappable_lines = [
        line for line in template.lines
        if not line.is_subtotal and line.formula_type not in _COMPUTED_FORMULA_TYPES
           and line.model_line not in _ALWAYS_MANUAL_LINES
    ]

    result = await db.execute(
        select(DataMap).where(DataMap.company_id == company_id)
    )
    maps = result.scalars().all()

    mapped_lines: Dict[str, DataMap] = {}
    for m in maps:
        key = f"{m.statement_type}:{m.model_line}"
        if key not in mapped_lines or m.confidence > (mapped_lines[key].confidence or 0):
            mapped_lines[key] = m

    data_result = await db.execute(
        select(FinancialData.account_name)
        .where(FinancialData.company_id == company_id)
        .distinct()
    )
    accounts_with_data = {r[0] for r in data_result.all()}

    completeness = []
    for line in mappable_lines:
        key = f"{line.statement_type}:{line.model_line}"
        dm = mapped_lines.get(key)
        if dm:
            has_data = dm.raw_account_name in accounts_with_data
            completeness.append({
                "model_line": line.model_line,
                "statement_type": line.statement_type,
                "sort_order": line.sort_order,
                "status": "manual_entry" if dm.mapping_method == "manual_entry" else "mapped",
                "source": dm.mapping_method,
                "raw_account_name": dm.raw_account_name,
                "sign_flip": dm.sign_flip,
                "confidence": dm.confidence,
                "has_data": has_data,
                "map_id": dm.id,
            })
        else:
            completeness.append({
                "model_line": line.model_line,
                "statement_type": line.statement_type,
                "sort_order": line.sort_order,
                "status": "unmapped",
                "source": None,
                "raw_account_name": None,
                "sign_flip": 1,
                "confidence": None,
                "has_data": False,
                "map_id": None,
            })

    return completeness


async def set_manual_entry(
    company_id: int, model_line: str, statement_type: str, db: AsyncSession
) -> DataMap:
    """Mark a template line as 'manual entry'."""
    result = await db.execute(
        select(DataMap).where(
            DataMap.company_id == company_id,
            DataMap.model_line == model_line,
            DataMap.statement_type == statement_type,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.mapping_method = "manual_entry"
        existing.raw_account_name = f"[manual] {model_line}"
        existing.confidence = 1.0
        existing.is_verified = True
    else:
        existing = DataMap(
            company_id=company_id,
            raw_account_name=f"[manual] {model_line}",
            model_line=model_line,
            statement_type=statement_type,
            sign_flip=1,
            sort_order=0,
            confidence=1.0,
            mapping_method="manual_entry",
            is_verified=True,
        )
        db.add(existing)

    await db.commit()
    await db.refresh(existing)
    return existing


async def fetch_companyfacts_and_map(
    company_id: int, db: AsyncSession, unmapped_lines: List[str] = None
) -> List[DataMap]:
    """Fetch raw SEC companyfacts JSON and use LLM to find XBRL tags
    for template lines that edgartools didn't cover.
    """
    from app.models.company import Company

    company = await db.get(Company, company_id)
    if not company or not company.cik:
        logger.warning(f"Company {company_id} has no CIK, cannot fetch companyfacts")
        return []

    from app.services.finmodel_sec_cache import get_companyfacts

    facts_data = await get_companyfacts(str(company.cik))
    if not facts_data:
        return []

    us_gaap = facts_data.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        logger.warning(f"No us-gaap facts found for company {company_id} (CIK {company.cik})")
        return []

    tag_summary = []
    for tag_name, tag_data in us_gaap.items():
        label = tag_data.get("label", tag_name)
        units = list(tag_data.get("units", {}).keys())
        unit_str = units[0] if units else "unknown"
        count = sum(len(v) for v in tag_data.get("units", {}).values())
        if count > 0:
            tag_summary.append({"tag": tag_name, "label": label, "unit": unit_str, "count": count})

    if not tag_summary:
        return []

    if unmapped_lines is None:
        completeness = await get_template_completeness(company_id, db)
        unmapped_lines = [
            f"{c['statement_type']}:{c['model_line']}"
            for c in completeness if c["status"] == "unmapped"
        ]

    if not unmapped_lines:
        logger.info("All template lines already mapped, no companyfacts fallback needed")
        return []

    tag_summary.sort(key=lambda t: -t["count"])
    tag_summary = tag_summary[:300]

    valid_types = ["IS", "BS", "SCF", "WC", "PPE", "DEBT", "INFO"]

    prompt = f"""You are a financial data mapping expert. I have a list of XBRL tags from a company's SEC filings,
and a list of unmapped model lines from an integrated financial model.

The model uses these statement types: {json.dumps(valid_types)}
- IS: income statement items
- BS: balance sheet items not in supporting schedules (Cash, DTL, equity)
- SCF: cash flow items
- WC: working capital (AR, AP, inventory, deferred revenue, prepaid, accrued taxes)
- PPE: fixed assets, depreciation, intangibles
- DEBT: debt balances, revolver
- INFO: exogenous inputs (CAPEX, debt schedules)

UNMAPPED MODEL LINES (format: "StatementType:LineName"):
{json.dumps(unmapped_lines)}

AVAILABLE XBRL TAGS (format: tag, label, unit, datapoint_count):
{json.dumps(tag_summary[:200])}

For each unmapped line where you find a reasonable match, return a JSON array:
[
  {{
    "model_line": "Cash",
    "statement_type": "BS",
    "xbrl_tag": "CashAndCashEquivalentsAtCarryingValue",
    "label": "Cash and Cash Equivalents",
    "sign_flip": 1,
    "confidence": 0.9
  }},
  ...
]

Only include matches where you have reasonable confidence (>=0.6).
Return ONLY the JSON array."""

    try:
        from app.config import get_anthropic_client, get_openai_client

        if settings.anthropic_api_key:
            client = get_anthropic_client()
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text if response.content else ""
        elif settings.openai_api_key:
            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.default_llm_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
            )
            text = response.choices[0].message.content or ""
        else:
            logger.warning("No AI API key configured, cannot do companyfacts mapping")
            return []

        if not text or not text.strip():
            return []

        text = text.strip()
        if text.startswith("```"):
            text = text.strip("```json").strip("```").strip()

        items = json.loads(text)
        results = []

        for item in items:
            if not isinstance(item, dict) or not item.get("model_line"):
                continue
            xbrl_tag = item.get("xbrl_tag", "")
            if not xbrl_tag:
                continue

            stmt = item.get("statement_type", "BS")
            if stmt not in valid_types:
                stmt = "BS"

            existing_map = await db.execute(
                select(DataMap).where(
                    DataMap.company_id == company_id,
                    DataMap.model_line == item["model_line"],
                    DataMap.statement_type == stmt,
                )
            )
            existing = existing_map.scalar_one_or_none()
            if existing:
                existing.raw_account_name = xbrl_tag
                existing.xbrl_tag = xbrl_tag
                existing.sign_flip = item.get("sign_flip", 1)
                existing.confidence = item.get("confidence", 0.7)
                existing.mapping_method = "companyfacts"
                results.append(existing)
            else:
                dm = DataMap(
                    company_id=company_id,
                    raw_account_name=xbrl_tag,
                    xbrl_tag=xbrl_tag,
                    model_line=item["model_line"],
                    statement_type=stmt,
                    sign_flip=item.get("sign_flip", 1),
                    sort_order=0,
                    confidence=item.get("confidence", 0.7),
                    mapping_method="companyfacts",
                    is_verified=False,
                )
                db.add(dm)
                results.append(dm)

            tag_facts = us_gaap.get(xbrl_tag, {})
            usd_data = tag_facts.get("units", {}).get("USD", [])

            stored_count = 0
            for dp in usd_data:
                if dp.get("form") not in ("10-K", "10-K/A"):
                    continue
                if dp.get("fp", "") != "FY":
                    continue
                year_str = dp.get("end", "")[:4]
                try:
                    year = int(year_str)
                except (ValueError, TypeError):
                    continue
                amount = dp.get("val", 0)
                join_key = f"{xbrl_tag}_{year}"

                existing_fd = await db.execute(
                    select(FinancialData).where(
                        FinancialData.company_id == company_id,
                        FinancialData.join_key == join_key,
                    )
                )
                if existing_fd.scalar_one_or_none():
                    continue

                db.add(FinancialData(
                    company_id=company_id,
                    account_name=xbrl_tag,
                    xbrl_tag=xbrl_tag,
                    year=year,
                    amount=amount,
                    statement_type=stmt,
                    join_key=join_key,
                    source_api="companyfacts",
                ))
                stored_count += 1

            logger.info(
                f"CompanyFacts mapped: {xbrl_tag} → {item['model_line']} "
                f"({stored_count} new data points)"
            )

        await db.commit()
        logger.info(f"CompanyFacts fallback: {len(results)} mappings for company {company_id}")
        return results

    except json.JSONDecodeError as je:
        logger.error(f"CompanyFacts LLM response not valid JSON: {je}")
        await db.rollback()
        return []
    except Exception as e:
        logger.error(f"CompanyFacts mapping failed: {type(e).__name__}: {e}")
        await db.rollback()
        return []
