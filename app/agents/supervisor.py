"""
Supervisor: the single entry point to every agent.

Routes and services call Supervisor methods instead of importing agents
directly, so adding or swapping an agent only touches this file.
"""

import logging

from app.agents.blog_writer_agent import BlogWriterAgent
from app.agents.email_reviewer_agent import EmailReviewerAgent
from app.agents.email_writer_agent import EmailWriterAgent
from app.agents.fraud_detection_agent import FraudDetectionAgent, FraudResult
from app.agents.hotel_agent import HotelAgent
from app.agents.itinerary_agent import ItineraryAgent
from app.agents.route_agent import RouteAgent

logger = logging.getLogger("supervisor")


class Supervisor:
    def __init__(self) -> None:
        self.route_agent = RouteAgent()
        self.hotel_agent = HotelAgent()
        self.itinerary_agent = ItineraryAgent()
        self.email_writer_agent = EmailWriterAgent()
        self.email_reviewer_agent = EmailReviewerAgent()
        self.blog_writer_agent = BlogWriterAgent()
        self.fraud_agent = FraudDetectionAgent

    async def route(self, origin: str, destination: str, detail: str = "basic") -> dict:
        """detail: 'basic' (distance/time), 'full' (waypoints) or 'multi' (options)."""
        if detail == "full":
            return await self.route_agent.get_route_info(origin, destination)
        if detail == "multi":
            return await self.route_agent.get_multiple_routes(origin, destination)
        return await self.route_agent.get_distance_and_time(origin, destination)

    async def hotel(self, *args, **kwargs) -> dict:
        return await self._safe(self.hotel_agent.run, "hotel", *args, **kwargs)

    async def itinerary(self, *args, **kwargs) -> dict:
        return await self._safe(self.itinerary_agent.run, "itinerary", *args, **kwargs)

    async def email(self, *args, **kwargs) -> dict:
        """Draft with the writer, then pass the draft to the reviewer."""
        draft = await self._safe(self.email_writer_agent.run, "email_writer",
                                 *args, **kwargs)
        if not draft.get("success"):
            return draft
        return await self._safe(self.email_reviewer_agent.run, "email_reviewer",
                                draft)

    async def blog(self, *args, **kwargs) -> dict:
        return await self._safe(self.blog_writer_agent.run, "blog_writer",
                                *args, **kwargs)

    async def fraud_check(self, ip: str, identifier: str = None,
                          device_fingerprint: str = None) -> FraudResult:
        return await self.fraud_agent.analyze(ip, identifier, device_fingerprint)

    @staticmethod
    async def _safe(fn, name: str, *args, **kwargs) -> dict:
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            logger.exception("Agent %s crashed: %s", name, type(e).__name__)
            return {"success": False, "status": 500,
                    "message": "Kuch galat ho gaya. Dobara try karo."}


supervisor = Supervisor()
