"""
AI grading service — two-LLM approach with configurable strictness.

1. Primary Grader: reads student answer + rubric + config → score + rationale
2. Validator Judge: reviews the grader's work → agreement/adjustment
3. Reconciliation: if they agree (within threshold), score stands; otherwise flagged
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

GRADER_SYSTEM_PROMPT = """You are an expert accounting exam grader at a university level.

You will receive:
- The exam question
- The grading rubric / expected answer
- The student's response
- A strictness level (1-5, where 1=lenient, 5=strict)

Grade the response and return JSON:
{
  "score": <points awarded>,
  "max_score": <max possible points>,
  "rationale": "<1-2 sentence explanation of why this score was given>",
  "key_concepts_present": ["list", "of", "concepts", "student", "demonstrated"],
  "key_concepts_missing": ["list", "of", "concepts", "student", "missed"]
}

Strictness guidelines:
- Level 1 (lenient): Give full credit if the core concept is present, even if wording is imperfect
- Level 3 (standard): Require correct reasoning and terminology, allow minor omissions
- Level 5 (strict): Require comprehensive, precise answers with proper terminology and complete reasoning
"""

VALIDATOR_SYSTEM_PROMPT = """You are a grading quality reviewer. You verify that exam grading is fair and consistent.

You will receive:
- The exam question
- The rubric / expected answer
- The student's response
- The primary grader's assessment (score, rationale, concepts)
- The strictness level

Evaluate whether the grading is fair. Return JSON:
{
  "agrees": true/false,
  "adjusted_score": <same or different score>,
  "rationale": "<brief explanation>",
  "confidence": <0.0 to 1.0>
}

Only disagree if the grading is clearly wrong (e.g., correct answer marked wrong, or obviously wrong answer given full credit).
"""


async def _call_llm_json(system_prompt: str, user_prompt: str) -> dict:
    """Call LLM and parse JSON response. Returns empty dict on failure."""
    try:
        from app.config import get_settings, get_openai_client
        settings = get_settings()
        if not settings.openai_api_key:
            return {}

        client = get_openai_client()

        def _sync():
            return client.chat.completions.create(
                model=settings.default_llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=500,
            )

        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, _sync),
            timeout=20,
        )
        return json.loads(response.choices[0].message.content or "{}")
    except Exception as e:
        logger.warning("Grading LLM call failed: %s", e)
        return {}


def _fallback_grade_mc(student_answer: str, correct_answer: str, max_score: float) -> dict:
    """Simple MC grading without LLM."""
    correct_letter = ""
    for ch in correct_answer:
        if ch.upper() in "ABCD":
            correct_letter = ch.upper()
            break

    student_letter = ""
    for ch in (student_answer or ""):
        if ch.upper() in "ABCD":
            student_letter = ch.upper()
            break

    is_correct = student_letter == correct_letter
    return {
        "score": max_score if is_correct else 0,
        "max_score": max_score,
        "rationale": f"{'Correct' if is_correct else 'Incorrect'} — expected {correct_letter}, got {student_letter}",
        "key_concepts_present": ["correct answer selected"] if is_correct else [],
        "key_concepts_missing": [] if is_correct else ["correct answer"],
    }


async def grade_single_response(
    question_text: str,
    expected_answer: str,
    student_answer: str,
    max_score: float,
    question_type: str,
    strictness: int = 3,
) -> dict:
    """Grade a single student response."""

    if question_type == "mc":
        return _fallback_grade_mc(student_answer, expected_answer, max_score)

    user_prompt = (
        f"Question: {question_text}\n\n"
        f"Expected answer / Rubric: {expected_answer}\n\n"
        f"Student's response: {student_answer}\n\n"
        f"Max points: {max_score}\n"
        f"Strictness level: {strictness}/5"
    )

    result = await _call_llm_json(GRADER_SYSTEM_PROMPT, user_prompt)

    if not result:
        return {
            "score": 0,
            "max_score": max_score,
            "rationale": "Unable to auto-grade — requires manual review",
            "key_concepts_present": [],
            "key_concepts_missing": ["auto-grading unavailable"],
        }

    result["max_score"] = max_score
    return result


async def validate_grade(
    question_text: str,
    expected_answer: str,
    student_answer: str,
    primary_grade: dict,
    strictness: int = 3,
) -> dict:
    """Have a second LLM validate the primary grade."""

    user_prompt = (
        f"Question: {question_text}\n\n"
        f"Expected answer / Rubric: {expected_answer}\n\n"
        f"Student's response: {student_answer}\n\n"
        f"Primary grader's assessment:\n"
        f"  Score: {primary_grade.get('score')}/{primary_grade.get('max_score')}\n"
        f"  Rationale: {primary_grade.get('rationale')}\n"
        f"  Concepts present: {primary_grade.get('key_concepts_present')}\n"
        f"  Concepts missing: {primary_grade.get('key_concepts_missing')}\n\n"
        f"Strictness level: {strictness}/5"
    )

    result = await _call_llm_json(VALIDATOR_SYSTEM_PROMPT, user_prompt)

    if not result:
        return {
            "agrees": True,
            "adjusted_score": primary_grade.get("score", 0),
            "rationale": "Validator unavailable — primary grade accepted",
            "confidence": 0.5,
        }

    return result


async def grade_submission(
    exam_markdown: str,
    student_answers: list[dict],
    strictness: int = 3,
    flag_threshold: float = 1.0,
) -> dict:
    """
    Grade a full student submission.

    Returns:
    {
        "question_grades": [{score, max_score, rationale, validator, flagged}, ...],
        "total_score": float,
        "max_total": float,
        "flagged_count": int,
    }
    """
    questions = _parse_questions_from_markdown(exam_markdown)
    question_grades = []
    total_score = 0.0
    max_total = 0.0
    flagged_count = 0

    for i, q in enumerate(questions):
        student_answer = ""
        if i < len(student_answers):
            ans = student_answers[i]
            student_answer = ans.get("response", ans.get("selected_choice", ""))

        primary = await grade_single_response(
            question_text=q["text"],
            expected_answer=q.get("answer", ""),
            student_answer=student_answer,
            max_score=q.get("points", 5),
            question_type=q.get("type", "short_answer"),
            strictness=strictness,
        )

        validator = None
        flagged = False

        if q.get("type") != "mc":
            validator = await validate_grade(
                question_text=q["text"],
                expected_answer=q.get("answer", ""),
                student_answer=student_answer,
                primary_grade=primary,
                strictness=strictness,
            )

            if validator and not validator.get("agrees", True):
                score_diff = abs(primary.get("score", 0) - validator.get("adjusted_score", 0))
                if score_diff >= flag_threshold:
                    flagged = True
                    flagged_count += 1
                    primary["score"] = validator["adjusted_score"]

        final_score = primary.get("score", 0)
        max_score = primary.get("max_score", q.get("points", 5))
        total_score += final_score
        max_total += max_score

        question_grades.append({
            "question_num": i + 1,
            "question_text": q["text"][:100],
            "question_type": q.get("type", "unknown"),
            "score": final_score,
            "max_score": max_score,
            "rationale": primary.get("rationale", ""),
            "key_concepts_present": primary.get("key_concepts_present", []),
            "key_concepts_missing": primary.get("key_concepts_missing", []),
            "validator": validator,
            "flagged": flagged,
        })

    return {
        "question_grades": question_grades,
        "total_score": total_score,
        "max_total": max_total,
        "flagged_count": flagged_count,
    }


def _parse_questions_from_markdown(markdown: str) -> list[dict]:
    """Extract questions, answers, and point values from exam markdown."""
    import re

    questions = []
    lines = markdown.split("\n")
    current_q = None
    current_answer = None
    current_type = "short_answer"
    current_points = 5
    options = []

    def flush():
        nonlocal current_q, current_answer, current_type, current_points, options
        if current_q:
            questions.append({
                "text": current_q.strip(),
                "answer": (current_answer or "").strip(),
                "type": current_type,
                "points": current_points,
                "options": options if current_type == "mc" else [],
            })
        current_q = None
        current_answer = None
        current_type = "short_answer"
        options = []

    section_points = 5

    for line in lines:
        line_stripped = line.strip()

        pts_match = re.search(r'(\d+)\s*points?\s*each', line_stripped, re.IGNORECASE)
        if pts_match:
            section_points = int(pts_match.group(1))

        if re.match(r'^##\s+Part.*Multiple\s*Choice', line_stripped, re.IGNORECASE):
            flush()
            current_type = "mc"
            continue

        if re.match(r'^##\s+Part.*(Short|Problem|Calc)', line_stripped, re.IGNORECASE):
            flush()
            current_type = "short_answer"
            continue

        q_match = re.match(r'^\*\*(\d+)\.\*\*\s*(.*)', line_stripped)
        if q_match:
            flush()
            current_q = q_match.group(2)
            q_pts = re.search(r'\((\d+)\s*points?\)', current_q, re.IGNORECASE)
            current_points = int(q_pts.group(1)) if q_pts else section_points
            continue

        opt_match = re.match(r'^([A-D])\)\s*(.*)', line_stripped)
        if opt_match and current_q:
            current_type = "mc"
            options.append({"letter": opt_match.group(1), "text": opt_match.group(2)})
            continue

        ans_match = re.match(r'^\*\*Answer:\s*([A-D])\*\*', line_stripped)
        if ans_match:
            current_answer = ans_match.group(1)
            continue

        if line_stripped.startswith("*Expected answer:") or line_stripped.startswith("*Expected answer"):
            current_answer = line_stripped.replace("*Expected answer:", "").replace("*Expected answer", "").strip().rstrip("*")
            continue

        if current_answer is not None and line_stripped and not line_stripped.startswith("#") and not line_stripped.startswith("---") and not line_stripped.startswith("**"):
            current_answer = (current_answer + " " + line_stripped.rstrip("*")).strip()

    flush()
    return questions
