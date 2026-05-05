"""
Seed checkpoint questions for each module layer.

Called at startup to ensure questions exist. Skips if already seeded.
"""

from __future__ import annotations

import logging
from sqlalchemy import select, func as sql_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checkpoint import CheckpointQuestion

logger = logging.getLogger(__name__)

SEED_QUESTIONS = [
    # -- PP&E Module --
    {
        "module": "ppe", "layer": 1, "question_type": "mc", "sort_order": 1,
        "question_text": "The XBRL concept 'PropertyPlantAndEquipmentNet' represents:",
        "choices": [
            {"id": "a", "text": "Gross PP&E before accumulated depreciation", "is_correct": False},
            {"id": "b", "text": "Net PP&E after subtracting accumulated depreciation", "is_correct": True},
            {"id": "c", "text": "Annual depreciation expense for the period", "is_correct": False},
            {"id": "d", "text": "Capital expenditures for new equipment", "is_correct": False},
        ],
        "correct_answer": "Net PP&E after subtracting accumulated depreciation",
        "explanation": "PropertyPlantAndEquipmentNet is the balance sheet carrying value after accumulated depreciation has been subtracted from the gross cost.",
    },
    {
        "module": "ppe", "layer": 2, "question_type": "short_answer", "sort_order": 1,
        "question_text": "Based on the disclosure you just read, what depreciation method does this company primarily use? What is the longest useful life estimate mentioned?",
        "correct_answer": "Look for: straight-line method (most common), and useful lives typically ranging from 3-40 years depending on asset class.",
        "explanation": "Most public companies use straight-line depreciation. Buildings often have the longest useful lives (20-40 years), while IT equipment has the shortest (3-5 years).",
    },
    {
        "module": "ppe", "layer": 3, "question_type": "mc", "sort_order": 1,
        "question_text": "A company has $500M gross PP&E and $400M accumulated depreciation. What does an 80% depreciated asset base most likely indicate?",
        "choices": [
            {"id": "a", "text": "The company has been investing heavily in new assets", "is_correct": False},
            {"id": "b", "text": "Assets are relatively old and may need replacement soon", "is_correct": True},
            {"id": "c", "text": "The company uses accelerated depreciation", "is_correct": False},
            {"id": "d", "text": "The company has very long useful life estimates", "is_correct": False},
        ],
        "correct_answer": "Assets are relatively old and may need replacement soon",
        "explanation": "An 80% asset age ratio suggests the asset base is near the end of its useful life. This often signals upcoming capex needs for replacement.",
    },
    {
        "module": "ppe", "layer": 4, "question_type": "mc", "sort_order": 1,
        "question_text": "When comparing PP&E metrics across peer companies, which factor could make a direct comparison misleading?",
        "choices": [
            {"id": "a", "text": "Different fiscal year end dates", "is_correct": False},
            {"id": "b", "text": "One company leases most of its assets while another owns them", "is_correct": True},
            {"id": "c", "text": "Companies are in the same industry", "is_correct": False},
            {"id": "d", "text": "Both companies use GAAP accounting", "is_correct": False},
        ],
        "correct_answer": "One company leases most of its assets while another owns them",
        "explanation": "Lease vs. own decisions dramatically affect reported PP&E. A company that leases will show lower PP&E even if it uses similar physical assets.",
    },

    # -- Allowance Module --
    {
        "module": "allowance", "layer": 1, "question_type": "mc", "sort_order": 1,
        "question_text": "What does the 'Allowance for Doubtful Accounts' represent on the balance sheet?",
        "choices": [
            {"id": "a", "text": "Cash set aside for expected bad debts", "is_correct": False},
            {"id": "b", "text": "A contra-asset that reduces gross receivables to their expected collectible value", "is_correct": True},
            {"id": "c", "text": "A liability for amounts owed to creditors", "is_correct": False},
            {"id": "d", "text": "An expense account on the income statement", "is_correct": False},
        ],
        "correct_answer": "A contra-asset that reduces gross receivables to their expected collectible value",
        "explanation": "The allowance is a contra-asset to Accounts Receivable. It represents management's estimate of receivables that won't be collected.",
    },
    {
        "module": "allowance", "layer": 3, "question_type": "mc", "sort_order": 1,
        "question_text": "A forensic flag shows the allowance ratio dropped from 4.2% to 1.8% while DSO increased. What does this most likely suggest?",
        "choices": [
            {"id": "a", "text": "The company is getting better at collecting receivables", "is_correct": False},
            {"id": "b", "text": "Credit quality is improving across the customer base", "is_correct": False},
            {"id": "c", "text": "Potential earnings management — the company may be under-reserving", "is_correct": True},
            {"id": "d", "text": "A change in revenue recognition policy", "is_correct": False},
        ],
        "correct_answer": "Potential earnings management — the company may be under-reserving",
        "explanation": "When DSO rises (collections are slower) but the allowance ratio drops, it suggests management may be understating the reserve to boost reported earnings.",
    },

    # -- Ratio Lab Module --
    {
        "module": "ratiolab", "layer": 1, "question_type": "mc", "sort_order": 1,
        "question_text": "When selecting XBRL line items for analysis, why is it important to check the 'concept' rather than just the 'label'?",
        "choices": [
            {"id": "a", "text": "Labels are always incorrect", "is_correct": False},
            {"id": "b", "text": "Different companies may use different labels for the same underlying concept", "is_correct": True},
            {"id": "c", "text": "Concepts are easier to read than labels", "is_correct": False},
            {"id": "d", "text": "The SEC requires concept-based selection", "is_correct": False},
        ],
        "correct_answer": "Different companies may use different labels for the same underlying concept",
        "explanation": "Companies have flexibility in labeling XBRL elements. 'Revenue', 'Net Sales', and 'Net Revenue' might all map to the same concept.",
    },
    {
        "module": "ratiolab", "layer": 3, "question_type": "short_answer", "sort_order": 1,
        "question_text": "You computed a current ratio of 0.8x. What does this mean for the company's short-term liquidity, and what would you want to investigate next?",
        "correct_answer": "A current ratio below 1.0 means current liabilities exceed current assets, raising liquidity concerns. Investigate: credit facility availability, cash flow from operations trend, and whether specific current liabilities (like deferred revenue) don't actually require cash outflow.",
        "explanation": "While a sub-1.0 current ratio is a red flag, context matters. Some businesses with strong recurring cash flows operate comfortably below 1.0.",
    },

    # -- FinModel Module --
    {
        "module": "finmodel", "layer": 1, "question_type": "mc", "sort_order": 1,
        "question_text": "In a 3-statement financial model, which statement connects the other two?",
        "choices": [
            {"id": "a", "text": "Income Statement", "is_correct": False},
            {"id": "b", "text": "Balance Sheet", "is_correct": False},
            {"id": "c", "text": "Cash Flow Statement", "is_correct": True},
            {"id": "d", "text": "Working Capital Schedule", "is_correct": False},
        ],
        "correct_answer": "Cash Flow Statement",
        "explanation": "The Cash Flow Statement bridges Net Income (from the IS) to the ending cash balance (on the BS), making it the connecting statement.",
    },
    {
        "module": "finmodel", "layer": 2, "question_type": "mc", "sort_order": 1,
        "question_text": "You changed revenue growth from 5% to 8%. Which financial statement line item is NOT directly affected by this change?",
        "choices": [
            {"id": "a", "text": "Revenue", "is_correct": False},
            {"id": "b", "text": "Accounts Receivable", "is_correct": False},
            {"id": "c", "text": "Accumulated Depreciation", "is_correct": True},
            {"id": "d", "text": "Cash from Operations", "is_correct": False},
        ],
        "correct_answer": "Accumulated Depreciation",
        "explanation": "Accumulated Depreciation is driven by the PP&E schedule (capex and useful lives), not by revenue growth. Revenue drives AR (via DSO), COGS, and ultimately cash from operations.",
    },
]


async def seed_checkpoint_questions(db: AsyncSession) -> None:
    """Insert seed questions if the table is empty."""
    result = await db.execute(select(sql_func.count(CheckpointQuestion.id)))
    count = result.scalar()
    if count and count > 0:
        logger.info("Checkpoint questions already seeded (%d exist)", count)
        return

    for q_data in SEED_QUESTIONS:
        db.add(CheckpointQuestion(**q_data))

    await db.commit()
    logger.info("Seeded %d checkpoint questions", len(SEED_QUESTIONS))
