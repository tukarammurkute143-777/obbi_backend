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
from app.services import email_service, itinerary_service

logger = logging.getLogger("supervisor")


class Supervisor:
    def __init__(self) -> None:
        self.route_agent = RouteAgent()
        self.hotel_agent = HotelAgent()
        self.itinerary_agent = ItineraryAgent(self.route_agent, self.hotel_agent)
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

    async def hotel(
        self,
        destination: str,
        type: str = "all",
        check_in: str = None,
        check_out: str = None,
        guests: int = 1,
    ) -> dict:
        """type: 'all' (near attractions), 'budget' or 'premium'."""
        if type == "budget":
            return await self._safe(
                self.hotel_agent.get_budget_hotels, "hotel", destination)
        if type == "premium":
            return await self._safe(
                self.hotel_agent.get_premium_hotels, "hotel", destination)
        return await self._safe(
            self.hotel_agent.search_hotels, "hotel",
            destination, check_in, check_out, guests)

    async def itinerary(self, input_data: dict) -> dict:
        return await self._safe(self.itinerary_agent.generate, "itinerary", input_data)

    async def email(self, input_data: dict, itinerary_id: str = None) -> dict:
        """
        Write -> review -> send or queue.

          {'success': True, 'status': 'sent'}                      reviewer passed it
          {'success': True, 'status': 'queued', 'queue_id': ...}   owner must approve
          {'success': True, 'status': 'already_sent'}              one email/day cap
          {'success': False, 'status': <http>, 'message': ...}

        itinerary_id (optional) attaches that itinerary's PDF and marks it
        emailed once the email actually goes out.
        """
        try:
            return await self._email(input_data, itinerary_id)
        except Exception as e:
            logger.exception("Email pipeline crashed: %s", type(e).__name__)
            return {"success": False, "status": 500,
                    "message": "Kuch galat ho gaya. Dobara try karo."}

    async def _email(self, input_data: dict, itinerary_id) -> dict:
        if not isinstance(input_data, dict):
            return {"success": False, "status": 400,
                    "message": "Input must be a JSON object."}
        data = dict(input_data)
        to_email = str(data.get("customer_email") or "").strip().lower()

        # Cheapest check first: don't pay for a draft that cannot be sent.
        if to_email and await email_service.already_sent_today(to_email):
            return {"success": True, "status": "already_sent"}

        if itinerary_id:
            row = await itinerary_service.get_itinerary(itinerary_id)
            if not row:
                return {"success": False, "status": 404,
                        "message": "Itinerary nahi mili."}
            data["itinerary_pdf_path"] = await itinerary_service.ensure_pdf(row)
            data.setdefault("destination", row.get("to_city") or "")
            summary = (row.get("itinerary_data") or {}).get("summary")
            if summary:
                data.setdefault("itinerary_summary", summary)

        draft = await self._safe(self.email_writer_agent.run, "email_writer", data)
        if not draft.get("success"):
            return draft

        review = await self._safe(
            self.email_reviewer_agent.review, "email_reviewer",
            {"subject": draft["subject"], "body": draft["body"]}, data)
        if "decision" not in review:
            return review

        if review["decision"] == "send":
            result = await email_service.send_email(
                to_email, draft["subject"], draft["body"],
                email_type=data.get("email_type", ""),
                attachment_path=draft["attachment_path"])
            if result["success"]:
                if itinerary_id and draft["has_attachment"]:
                    await itinerary_service.update_itinerary(itinerary_id, emailed=True)
                return {"success": True, "status": "sent",
                        "overall_score": review["overall_score"]}
            if result["status"] == "already_sent":
                return {"success": True, "status": "already_sent"}
            return {"success": False, "status": 502, "message": result["message"]}

        try:
            queued = await email_service.enqueue_for_review(
                customer_email=to_email,
                customer_name=data.get("customer_name"),
                email_type=data.get("email_type"),
                subject=draft["subject"],
                body=draft["body"],
                attachment_path=draft["attachment_path"],
                overall_score=review["overall_score"],
                failed_checks=review["failed_checks"],
                itinerary_id=itinerary_id,
            )
        except email_service.QueueError as e:
            # Not stored means nobody will ever review it: do NOT send.
            return {"success": False, "status": e.status, "message": e.message}
        return {"success": True, "status": "queued", "queue_id": queued.get("id"),
                "overall_score": review["overall_score"],
                "failed_checks": review["failed_checks"]}

    async def blog(self, input_data: dict) -> dict:
        """Write a blog and save it as a DRAFT. Never publishes."""
        return await self._safe(
            self.blog_writer_agent.generate, "blog_writer", input_data)

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
