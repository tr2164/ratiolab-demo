"""
Seed realistic demo data: 20 students with module sessions, events,
and checkpoint responses showing mixed performance patterns.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func as sql_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.tracking import ModuleSession, ModuleEvent
from app.models.checkpoint import CheckpointQuestion, CheckpointResponse

logger = logging.getLogger(__name__)

DEMO_STUDENTS = [
    ("Alex Chen", "ac1234@nyu.edu"),
    ("Priya Sharma", "ps5678@nyu.edu"),
    ("Marcus Johnson", "mj9012@nyu.edu"),
    ("Sofia Rodriguez", "sr3456@nyu.edu"),
    ("James O'Brien", "jo7890@nyu.edu"),
    ("Yuki Tanaka", "yt2345@nyu.edu"),
    ("Fatima Al-Hassan", "fa6789@nyu.edu"),
    ("Liam Fitzgerald", "lf0123@nyu.edu"),
    ("Wei Zhang", "wz4567@nyu.edu"),
    ("Olivia Nguyen", "on8901@nyu.edu"),
    ("Daniel Kim", "dk2346@nyu.edu"),
    ("Emma Thompson", "et5679@nyu.edu"),
    ("Raj Patel", "rp9013@nyu.edu"),
    ("Isabella Costa", "ic3457@nyu.edu"),
    ("Noah Williams", "nw7891@nyu.edu"),
    ("Aisha Mohammed", "am1235@nyu.edu"),
    ("Ethan Brooks", "eb5670@nyu.edu"),
    ("Chloe Dubois", "cd9014@nyu.edu"),
    ("Kenji Watanabe", "kw3458@nyu.edu"),
    ("Sarah Mitchell", "sm7892@nyu.edu"),
]

MODULES = ["ppe", "allowance", "ratiolab", "finmodel"]
TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "JPM", "BAC", "WMT", "HD"]
COURSE_ID = "ACCT-UB-0001-SP26"

# Mixed performance profiles: (module, layer) -> base accuracy
# Some topics are generally harder, creating realistic patterns
DIFFICULTY_MAP = {
    ("ppe", 1): 0.80,       # Easy — most get XBRL concept right
    ("ppe", 2): 0.55,       # Moderate — short answer, varies
    ("ppe", 3): 0.65,       # Moderate — asset age interpretation
    ("ppe", 4): 0.70,       # Moderate — peer comparison pitfalls
    ("allowance", 1): 0.75, # Easy — definition question
    ("allowance", 3): 0.40, # Hard — forensic flag interpretation (struggle area)
    ("ratiolab", 1): 0.60,  # Moderate — XBRL concept vs label
    ("ratiolab", 3): 0.50,  # Hard-ish — liquidity interpretation (short answer)
    ("finmodel", 1): 0.85,  # Easy — which statement connects
    ("finmodel", 2): 0.45,  # Hard — revenue growth impact (struggle area)
}

EVENT_TYPES = {
    "ppe": ["data_loaded", "layer_analyzed", "peer_compared", "chat_turn", "tag_overridden"],
    "allowance": ["data_loaded", "layer_analyzed", "forensics_run", "sensitivity_run", "peer_compared", "chat_turn"],
    "ratiolab": ["line_items_selected", "footnotes_loaded", "ratios_computed", "ratios_analyzed", "chat_turn"],
    "finmodel": ["model_generated", "assumption_changed", "driver_overridden", "sensitivity_run", "agent_chat_turn"],
}

# Student skill profiles — each student has strengths/weaknesses
STUDENT_PROFILES = [
    {"strength": "ppe", "weakness": "allowance"},      # Alex
    {"strength": "allowance", "weakness": "finmodel"},  # Priya
    {"strength": "finmodel", "weakness": "ratiolab"},   # Marcus
    {"strength": "ratiolab", "weakness": "ppe"},        # Sofia
    {"strength": "ppe", "weakness": "finmodel"},        # James
    {"strength": "finmodel", "weakness": "allowance"},  # Yuki
    {"strength": "allowance", "weakness": "ratiolab"},  # Fatima
    {"strength": "ratiolab", "weakness": "ppe"},        # Liam
    {"strength": "ppe", "weakness": "allowance"},       # Wei
    {"strength": "finmodel", "weakness": "ratiolab"},   # Olivia
    {"strength": "allowance", "weakness": "ppe"},       # Daniel
    {"strength": "ppe", "weakness": "finmodel"},        # Emma
    {"strength": "ratiolab", "weakness": "allowance"},  # Raj
    {"strength": "finmodel", "weakness": "ppe"},        # Isabella
    {"strength": "allowance", "weakness": "finmodel"},  # Noah
    {"strength": "ppe", "weakness": "ratiolab"},        # Aisha
    {"strength": "ratiolab", "weakness": "allowance"},  # Ethan
    {"strength": "finmodel", "weakness": "ppe"},        # Chloe
    {"strength": "allowance", "weakness": "ratiolab"},  # Kenji
    {"strength": "ppe", "weakness": "finmodel"},        # Sarah
]


async def seed_demo_data(db: AsyncSession) -> None:
    """Seed 20 students with realistic activity patterns."""
    existing = await db.execute(
        select(sql_func.count(User.id)).where(User.is_demo == True, User.display_name != "Demo Instructor")
    )
    count = existing.scalar()
    if count and count >= 15:
        logger.info("Demo data already seeded (%d demo students exist)", count)
        return

    questions_result = await db.execute(
        select(CheckpointQuestion).where(CheckpointQuestion.is_active == True)
    )
    all_questions = questions_result.scalars().all()
    questions_by_key: dict[tuple[str, int], list[CheckpointQuestion]] = {}
    for q in all_questions:
        key = (q.module, q.layer)
        questions_by_key.setdefault(key, []).append(q)

    base_time = datetime.now(timezone.utc) - timedelta(days=30)
    random.seed(42)

    for idx, (name, email) in enumerate(DEMO_STUDENTS):
        profile = STUDENT_PROFILES[idx]
        user = User(
            display_name=name,
            email=email,
            is_demo=True,
            created_at=base_time + timedelta(days=random.randint(0, 5)),
            last_seen_at=base_time + timedelta(days=random.randint(20, 30)),
        )
        db.add(user)
        await db.flush()

        # Each student visits 2-4 modules
        modules_to_visit = random.sample(MODULES, k=random.randint(2, 4))

        for mod in modules_to_visit:
            ticker = random.choice(TICKERS)
            session_time = base_time + timedelta(
                days=random.randint(5, 25),
                hours=random.randint(9, 20),
            )

            session = ModuleSession(
                user_id=user.id,
                course_id=COURSE_ID,
                module=mod,
                ticker=ticker,
                started_at=session_time,
                ended_at=session_time + timedelta(minutes=random.randint(10, 60)),
            )
            db.add(session)
            await db.flush()

            # Generate 2-6 events per session
            event_types = EVENT_TYPES.get(mod, [])
            for _ in range(random.randint(2, 6)):
                event = ModuleEvent(
                    session_id=session.id,
                    event_type=random.choice(event_types),
                    event_data={"ticker": ticker, "layer": random.randint(1, 4)},
                    created_at=session_time + timedelta(minutes=random.randint(1, 30)),
                )
                db.add(event)

            # Answer checkpoint questions for layers visited
            layers_visited = list(range(1, random.randint(2, 5)))
            for layer in layers_visited:
                key = (mod, layer)
                if key not in questions_by_key:
                    continue

                for q in questions_by_key[key]:
                    base_accuracy = DIFFICULTY_MAP.get(key, 0.6)

                    # Adjust accuracy based on student profile
                    if mod == profile["strength"]:
                        accuracy = min(base_accuracy + 0.20, 0.95)
                    elif mod == profile["weakness"]:
                        accuracy = max(base_accuracy - 0.25, 0.10)
                    else:
                        accuracy = base_accuracy + random.uniform(-0.10, 0.10)

                    is_correct = random.random() < accuracy

                    if q.question_type == "mc" and q.choices:
                        if is_correct:
                            correct_ids = [c["id"] for c in q.choices if c.get("is_correct")]
                            selected = correct_ids[0] if correct_ids else "a"
                        else:
                            wrong_ids = [c["id"] for c in q.choices if not c.get("is_correct")]
                            selected = random.choice(wrong_ids) if wrong_ids else "a"

                        response = CheckpointResponse(
                            question_id=q.id,
                            user_id=user.id,
                            course_id=COURSE_ID,
                            session_id=session.id,
                            selected_choice=selected,
                            is_correct=is_correct,
                            answered_at=session_time + timedelta(minutes=random.randint(5, 25)),
                        )
                    else:
                        response = CheckpointResponse(
                            question_id=q.id,
                            user_id=user.id,
                            course_id=COURSE_ID,
                            session_id=session.id,
                            text_response="[demo response]",
                            is_correct=None,
                            answered_at=session_time + timedelta(minutes=random.randint(5, 25)),
                        )

                    db.add(response)

    await db.commit()
    logger.info("Seeded %d demo students with activity data", len(DEMO_STUDENTS))
