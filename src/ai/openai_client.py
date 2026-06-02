"""
OpenAI API Client for generating trading recommendations.
Uses OpenAI Responses API with native Web Search capability.
Implements sentiment caching to reduce token usage.
"""
import logging
import json
from openai import OpenAI
from src.config.settings import settings
from src.models.trading import TradingRecommendation, PortfolioSnapshot
from src.ai.prompts import TRADING_SYSTEM_PROMPT, TRADING_USER_PROMPT_TEMPLATE
from src.utils.sentiment_cache import SentimentCache

logger = logging.getLogger(__name__)

class OpenAIClient:
    """Client for interacting with OpenAI's API with Native Web Search."""
    
    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not set")
            
        self.client = OpenAI(api_key=settings.openai_api_key)
        # Use GPT-5 with Responses API for web search
        self.model_name = "gpt-5"
        # Sentiment cache to reduce token usage
        self.sentiment_cache = SentimentCache(refresh_minutes=settings.news_refresh_minutes)

    def get_trading_recommendation(
        self,
        portfolio: PortfolioSnapshot, 
        market_context: str = "",
        ticker: str = "",
        news_context: str = ""  # Unused, kept for backwards compatibility
    ) -> tuple[TradingRecommendation, dict]:
        """
        Get a trading recommendation using OpenAI's native web search.
        Uses the Responses API with web_search_preview tool.
        """
        if settings.use_mock_ai:
            logger.info("[MOCK MODE] Returning dummy recommendation")
            return TradingRecommendation(
                action="BUY",
                symbol="MOCK",
                quantity=10,
                order_type="LIMIT",
                reasoning="Mock AI mode enabled for testing.",
                confidence=0.99
            ), {"mode": "mock"}

        logger.info("Requesting trading recommendation from OpenAI (Responses API + Web Search)...")
        
        # Get strategy context from settings
        from src.config.settings import settings as app_settings
        strategy_ctx = app_settings.strategy_context or "No additional strategy instructions."
        
        # Build focused portfolio context (only show relevant ticker position + account summary)
        relevant_position = None
        for pos in portfolio.positions:
            if pos.symbol == ticker:
                relevant_position = pos
                break
        
        portfolio_context = f"""Account Summary:
- Net Liquidation: ${portfolio.account.net_liquidation:,.2f}
- Cash Available: ${portfolio.account.total_cash_value:,.2f}
- Buying Power: ${portfolio.account.buying_power:,.2f}

Current Position in {ticker}: """
        
        if relevant_position:
            portfolio_context += f"{relevant_position.quantity} shares @ ${relevant_position.avg_cost:.2f}"
            if relevant_position.unrealized_pnl:
                portfolio_context += f" (P/L: ${relevant_position.unrealized_pnl:+,.2f})"
        else:
            portfolio_context += "No current position"
        
        # Check sentiment cache - only do web search if cache is stale
        cached_sentiment = self.sentiment_cache.get_sentiment()
        needs_web_search = cached_sentiment is None
        
        if cached_sentiment:
            news_context = f"CACHED SENTIMENT (refresh in {settings.news_refresh_minutes}m): {cached_sentiment}"
            logger.info(f"Using cached sentiment: {self.sentiment_cache.get_direction()}")
        else:
            news_context = "(AI will search the web for latest semiconductor news)"
            logger.info("Sentiment cache stale - web search enabled")
        
        # Build prompt content
        user_content = TRADING_USER_PROMPT_TEMPLATE.format(
            portfolio_context=portfolio_context,
            market_context=market_context,
            news_context=news_context,
            strategy_context=strategy_ctx
        )
        
        try:
            # Only enable web search if cache is stale
            tools = [{"type": "web_search_preview"}] if needs_web_search else []
            
            logger.info(f"Calling OpenAI (web_search={'enabled' if needs_web_search else 'disabled'})...")
            response = self.client.responses.create(
                model=self.model_name,
                tools=tools if tools else None,
                input=[
                    {"role": "system", "content": TRADING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
            
            # Log web search usage and extract sentiment for caching
            web_search_used = False
            for item in response.output:
                if hasattr(item, 'type') and item.type == 'web_search_call':
                    logger.info(f"AI performed web search: {item}")
                    web_search_used = True
            
            # Extract the text response
            response_text = None
            for item in response.output:
                if hasattr(item, 'type') and item.type == 'message':
                    for content_block in item.content:
                        if hasattr(content_block, 'text'):
                            response_text = content_block.text
                            break
            
            if not response_text:
                raise ValueError("No text response from OpenAI Responses API")
            
            logger.info(f"Raw AI Response: {response_text[:200]}...")
            
            # Parse the response into TradingRecommendation
            # The AI should output JSON matching our schema
            try:
                rec_data = json.loads(response_text)
                rec = TradingRecommendation(**rec_data)
            except (json.JSONDecodeError, Exception) as parse_error:
                # If parsing fails, try to get structured output via Chat Completions
                logger.warning(f"Direct parse failed ({parse_error}), using Chat Completions for structure...")
                structured_response = self.client.beta.chat.completions.parse(
                    model="gpt-4o-2024-08-06",
                    messages=[
                        {"role": "system", "content": "Convert the following trading analysis into the required JSON format."},
                        {"role": "user", "content": response_text},
                    ],
                    response_format=TradingRecommendation,
                )
                rec = structured_response.choices[0].message.parsed
            
            if rec:
                logger.info(f"OpenAI Recommendation: {rec.action} {rec.symbol} (Confidence: {rec.confidence:.2f})")
                
                # Update sentiment cache if web search was used
                if web_search_used and rec.reasoning:
                    # Determine direction from recommendation
                    if rec.action == "BUY" and rec.symbol == "SOXL":
                        direction = "BULLISH"
                    elif rec.action == "BUY" and rec.symbol == "SOXS":
                        direction = "BEARISH"
                    elif rec.action == "SELL":
                        direction = "CLOSING POSITION"
                    else:
                        direction = "NEUTRAL"
                    
                    # Cache the reasoning as sentiment
                    self.sentiment_cache.update(rec.reasoning, direction)
                    logger.info(f"Cached new sentiment: {direction}")
                
                # Log full prompts for debugging
                logger.info("=== RAW PROMPT SENT ===")
                logger.info(f"System Prompt:\n{TRADING_SYSTEM_PROMPT[:500]}...")
                logger.info(f"User Prompt:\n{user_content[:500]}...")
                logger.info("=== RAW RESPONSE RECEIVED ===")
                logger.info(f"Full Response:\n{response_text}")
                logger.info("=== END ===")
                
                context_data = {
                    "system_prompt": TRADING_SYSTEM_PROMPT,
                    "user_prompt": user_content,
                    "raw_response": response_text,
                    "model": self.model_name,
                    "web_search_used": web_search_used,
                    "sentiment_cache_status": self.sentiment_cache.get_cache_info()
                }
                return rec, context_data
            else:
                raise ValueError("Empty response from OpenAI")

        except Exception as e:
            logger.error(f"OpenAI API Error: {str(e)}")
            # Return None on error - do not create fake recommendations
            return None, {"error": str(e)}
