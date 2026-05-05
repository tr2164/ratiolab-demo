"""
News Agent: Fetches news via Tavily web search (primary) or NewsAPI/GNews (fallback),
analyzes sentiment, and suggests driver adjustments.

Tavily integration follows the RCSA deep-agent pattern with proper web research.
"""
import json
import logging
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.news import NewsArticle, NewsSentiment
from app.services.prompt_service import render_prompt
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def fetch_news(ticker: str, company_id: int, db: AsyncSession, days: int = 30) -> List[NewsArticle]:
    """Fetch recent news articles for a ticker.
    Priority: Tavily > NewsAPI > GNews.
    """
    articles = []

    if settings.tavily_api_key:
        articles = await _fetch_from_tavily(ticker, company_id, db, days)

    if not articles and settings.news_api_key:
        articles = await _fetch_from_newsapi(ticker, company_id, db, days)

    if not articles:
        articles = await _fetch_from_gnews(ticker, company_id, db, days)

    return articles


async def _fetch_from_tavily(ticker: str, company_id: int, db: AsyncSession, days: int) -> List[NewsArticle]:
    """Fetch from Tavily web search API (RCSA deep-agent pattern)."""
    try:
        from tavily import AsyncTavilyClient
    except ImportError:
        logger.warning("tavily-python not installed, skipping Tavily search")
        return []

    try:
        client = AsyncTavilyClient(api_key=settings.tavily_api_key)

        queries = [
            f"{ticker} stock financial news analysis",
            f"{ticker} earnings revenue guidance outlook",
        ]

        articles = []
        for query in queries:
            results = await client.search(
                query=query,
                search_depth="advanced",
                max_results=10,
                include_raw_content=False,
            )

            for item in results.get("results", []):
                content_hash = hashlib.sha256(
                    (item.get("title", "") + item.get("url", "")).encode()
                ).hexdigest()

                article = NewsArticle(
                    company_id=company_id,
                    title=item.get("title", ""),
                    source=_extract_domain(item.get("url", "")),
                    url=item.get("url", ""),
                    published_at=item.get("published_date"),
                    snippet=item.get("content", "")[:500],
                    content_hash=content_hash,
                )
                db.add(article)
                articles.append(article)

        await db.flush()
        logger.info(f"Tavily: fetched {len(articles)} results for {ticker}")
        return articles
    except Exception as e:
        logger.error(f"Tavily search failed for {ticker}: {e}")
        return []


def _extract_domain(url: str) -> str:
    """Extract domain name from URL for source attribution."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        return domain
    except Exception:
        return "web"


async def _fetch_from_newsapi(ticker: str, company_id: int, db: AsyncSession, days: int) -> List[NewsArticle]:
    """Fetch from NewsAPI.org."""
    from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = (
        f"https://newsapi.org/v2/everything?"
        f"q={ticker}&from={from_date}&sortBy=relevancy&pageSize=20"
        f"&apiKey={settings.news_api_key}"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning(f"NewsAPI returned {resp.status_code}")
            return []
        data = resp.json()

    articles = []
    for item in data.get("articles", []):
        content_hash = hashlib.sha256(
            (item.get("title", "") + item.get("url", "")).encode()
        ).hexdigest()

        article = NewsArticle(
            company_id=company_id,
            title=item.get("title", ""),
            source=item.get("source", {}).get("name", ""),
            url=item.get("url", ""),
            published_at=item.get("publishedAt"),
            snippet=item.get("description", ""),
            content_hash=content_hash,
        )
        db.add(article)
        articles.append(article)

    await db.flush()
    return articles


async def _fetch_from_gnews(ticker: str, company_id: int, db: AsyncSession, days: int) -> List[NewsArticle]:
    """Fetch from GNews.io free API."""
    url = f"https://gnews.io/api/v4/search?q={ticker}&lang=en&max=20&token=free"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []

    articles = []
    for item in data.get("articles", []):
        content_hash = hashlib.sha256(
            (item.get("title", "") + item.get("url", "")).encode()
        ).hexdigest()
        article = NewsArticle(
            company_id=company_id,
            title=item.get("title", ""),
            source=item.get("source", {}).get("name", ""),
            url=item.get("url", ""),
            published_at=item.get("publishedAt"),
            snippet=item.get("description", ""),
            content_hash=content_hash,
        )
        db.add(article)
        articles.append(article)

    await db.flush()
    return articles


async def analyze_sentiment(articles: List[NewsArticle], ticker: str, db: AsyncSession) -> Dict:
    """Use LLM to analyze sentiment and extract financial signals."""
    if not articles:
        return {"overall": 0, "summary": "No recent news found.", "signals": []}

    article_texts = []
    for a in articles[:15]:
        article_texts.append(f"- [{a.source}] {a.title}: {a.snippet or ''}")

    rendered = await render_prompt(
        db, "sentiment_analysis",
        ticker=ticker,
        articles=chr(10).join(article_texts),
    )

    prompt = rendered or f"""Analyze these recent news articles about {ticker} for financial modeling purposes.

Articles:
{chr(10).join(article_texts)}

Return a JSON object with:
- "overall_sentiment": float from -1.0 (very bearish) to 1.0 (very bullish)
- "summary": 2-3 sentence summary of the overall news sentiment
- "signals": array of objects, each with:
  - "driver": which financial driver is affected (e.g., "Revenue Growth", "COGS % of Revenue")
  - "direction": "increase" or "decrease"
  - "magnitude": "small" (1-3%), "medium" (3-10%), or "large" (10%+)
  - "reason": brief explanation
  - "confidence": 0.0 to 1.0

Only include signals where there's a clear connection to a financial metric.
Return ONLY the JSON, no other text."""

    try:
        from app.config import get_openai_client, get_anthropic_client

        if settings.anthropic_api_key:
            client = get_anthropic_client()
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
        elif settings.openai_api_key:
            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.default_llm_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
            )
            text = response.choices[0].message.content
        else:
            return {"overall": 0, "summary": "No AI API key configured.", "signals": []}

        text = text.strip().strip("```json").strip("```").strip()
        result = json.loads(text)

        for article in articles:
            sentiment = NewsSentiment(
                article_id=article.id,
                overall_score=result.get("overall_sentiment", 0),
                driver_impacts=result.get("signals", []),
                summary=result.get("summary", ""),
            )
            db.add(sentiment)

        await db.flush()
        return result

    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        return {"overall": 0, "summary": f"Analysis error: {str(e)}", "signals": []}
