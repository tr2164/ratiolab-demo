"""
Prompt Service: Centralized prompt management with versioning.
Adapted from RCSA's prompt_service pattern.

All LLM prompts are stored in the database and can be edited via the admin panel.
Falls back to hardcoded defaults when no DB prompt exists.
"""
import re
import logging
from typing import Any, Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.admin import Prompt, PromptVersion

logger = logging.getLogger(__name__)

_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_prompt_text(prompt_text: str, variables: Dict[str, Any]) -> str:
    """
    Render prompt text using {{var}} placeholders.
    Avoids collisions with JSON braces. Missing variables are replaced with empty string.
    """
    def _replace(match: re.Match) -> str:
        key = match.group(1)
        val = variables.get(key)
        return "" if val is None else str(val)

    return _VAR_PATTERN.sub(_replace, prompt_text)


async def get_prompt(
    session: AsyncSession,
    name: str,
    version: Optional[int] = None,
) -> Optional[Prompt]:
    """Fetch a prompt by name, optionally at a specific version."""
    stmt = select(Prompt).where(Prompt.name == name, Prompt.is_active == True)  # noqa: E712
    result = await session.execute(stmt)
    prompt = result.scalar_one_or_none()
    return prompt


async def render_prompt(
    session: AsyncSession,
    name: str,
    **variables: Any,
) -> Optional[str]:
    """
    Fetch and render a prompt by name with the given variables.
    Returns None if the prompt doesn't exist (caller should use fallback).
    """
    prompt = await get_prompt(session, name)
    if not prompt:
        return None
    return render_prompt_text(prompt.prompt_text, variables)


async def list_prompts(
    session: AsyncSession,
    category: Optional[str] = None,
) -> list[Prompt]:
    """List all prompts, optionally filtered by category."""
    stmt = select(Prompt)
    if category:
        stmt = stmt.where(Prompt.category == category)
    stmt = stmt.order_by(Prompt.name.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_prompt(
    session: AsyncSession,
    *,
    name: str,
    prompt_text: str,
    category: str,
    description: Optional[str] = None,
    variables: Optional[list] = None,
) -> Prompt:
    """Create a new prompt."""
    prompt = Prompt(
        name=name,
        prompt_text=prompt_text,
        category=category,
        description=description,
        variables=variables or [],
        is_active=True,
        version=1,
    )
    session.add(prompt)

    version = PromptVersion(
        prompt=prompt,
        version=1,
        prompt_text=prompt_text,
        variables=variables or [],
        is_active=True,
        created_by="admin",
    )
    session.add(version)

    await session.commit()
    await session.refresh(prompt)
    return prompt


async def update_prompt(
    session: AsyncSession,
    name: str,
    *,
    prompt_text: Optional[str] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    variables: Optional[list] = None,
) -> Optional[Prompt]:
    """Update a prompt and create a new version."""
    prompt = await get_prompt(session, name)
    if not prompt:
        return None

    if prompt_text is not None:
        prompt.prompt_text = prompt_text
        prompt.version += 1

        version = PromptVersion(
            prompt_id=prompt.id,
            version=prompt.version,
            prompt_text=prompt_text,
            variables=variables or prompt.variables,
            is_active=True,
            created_by="admin",
        )
        session.add(version)

    if category is not None:
        prompt.category = category
    if description is not None:
        prompt.description = description
    if variables is not None:
        prompt.variables = variables

    await session.commit()
    await session.refresh(prompt)
    return prompt
