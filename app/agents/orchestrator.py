from typing import Any, Dict

from .strategy_agent import StrategyAgent
from .trends_agent import TrendsAgent
from .content_agent import ContentAgent
from .promo_agent import PromoAgent
from .analytics_agent import AnalyticsAgent


class OrchestratorAgent:
    def __init__(self) -> None:
        self.strategy_agent = StrategyAgent()
        self.trends_agent = TrendsAgent()
        self.content_agent = ContentAgent()
        self.promo_agent = PromoAgent()
        self.analytics_agent = AnalyticsAgent()

    async def run_full_pipeline(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        strategy = await self.strategy_agent.run(brief)
        trends = await self.trends_agent.run(brief)
        content = await self.content_agent.run(brief)
        promo = await self.promo_agent.run(brief)
        analytics = await self.analytics_agent.run(brief)

        return {
            "strategy": strategy,
            "trends": trends,
            "content": content,
            "promo": promo,
            "analytics": analytics,
        }