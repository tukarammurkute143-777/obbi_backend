"""
Supervisor: the single entry point to every agent.

Routes and services call Supervisor methods instead of importing agents
directly, so adding or swapping an agent only touches this file.
"""

import logging

from app.agents.avatar_agent import AvatarAgent
from app.agents.blog_writer_agent import BlogWriterAgent
from app.agents.email_reviewer_agent import EmailReviewerAgent
from app.agents.email_writer_agent import EmailWriterAgent
from app.agents.fraud_detection_agent import FraudDetectionAgent, FraudResult
from app.agents.hotel_agent import HotelAgent
from app.agents.itinerary_agent import ItineraryAgent
from app.agents.response_verifier_agent import ResponseVerifierAgent
from app.agents.route_agent import RouteAgent
from app.services import blog_service, email_service, itinerary_service

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
        self.verifier = ResponseVerifierAgent(self.route_agent)
        self.avatar_agent = AvatarAgent(self)

    # ---------------------------------------------------------- verification

    async def verify(self, response_type: str, content, context: dict = None,
                     deep: bool = True) -> dict:
        """Run the Response Verifier on anything (e.g. a chat reply)."""
        return await self.verifier.verify(response_type, content, context, deep)

    @staticmethod
    def _summary(verdict: dict) -> dict:
        """What callers get to see of a verdict. Issue details stay in the logs."""
        return {
            "status": verdict["status"],
            "overall_score": verdict["overall_score"],
            "warnings": sum(1 for i in verdict["issues"] if i["severity"] == "warning"),
        }

    async def _verified(self, name: str, produce, response_type: str, build,
                        discard=None) -> dict:
        """
        Generate, verify, and on a failed verdict generate once more (fresh,
        bypassing caches); a second failure is a 503. Anything the agent itself
        reports as failed is returned untouched.

        produce(fresh) -> agent result     build(result) -> (content, context)
        discard(result) -> undo a rejected result (evict a cache entry, delete a draft)
        """
        for attempt in range(2):
            result = await self._safe(produce, name, attempt > 0)
            if not result.get("success"):
                return result
            content, context = build(result)
            verdict = await self.verifier.verify(response_type, content, context)
            if verdict["acceptable"]:
                result["verification"] = self._summary(verdict)
                result["_verdict"] = verdict
                return result
            logger.warning("%s response rejected by verifier (attempt %d): score %s",
                           name, attempt + 1, verdict["overall_score"])
            if discard:
                await discard(result)
        return {"success": False, "status": 503,
                "message": "Response verify nahi ho paya. Try again."}

    @staticmethod
    def _payload(result: dict) -> dict:
        """The agent's data without per-call flags, so identical content always
        hashes to the same verification cache entry."""
        return {k: v for k, v in result.items() if k not in ("success", "cached")}

    @staticmethod
    def _public(result: dict) -> dict:
        return {k: v for k, v in result.items() if not k.startswith("_")}

    # ---------------------------------------------------------------- agents

    async def route(self, origin: str, destination: str, detail: str = "basic") -> dict:
        """detail: 'basic' (distance/time), 'full' (waypoints) or 'multi' (options)."""
        method = {"full": self.route_agent.get_route_info,
                  "multi": self.route_agent.get_multiple_routes}.get(
                      detail, self.route_agent.get_distance_and_time)
        result = await self._verified(
            "route",
            lambda fresh: method(origin, destination, use_cache=not fresh),
            "route",
            lambda r: (self._payload(r), {"from_city": origin, "to_city": destination}))
        return self._public(result)

    async def hotel(
        self,
        destination: str,
        type: str = "all",
        check_in: str = None,
        check_out: str = None,
        guests: int = 1,
    ) -> dict:
        """type: 'all' (near attractions), 'budget' or 'premium'."""
        def produce(fresh):
            if type == "budget":
                return self.hotel_agent.get_budget_hotels(destination, use_cache=not fresh)
            if type == "premium":
                return self.hotel_agent.get_premium_hotels(destination, use_cache=not fresh)
            return self.hotel_agent.search_hotels(
                destination, check_in, check_out, guests, use_cache=not fresh)

        result = await self._verified(
            "hotel", produce, "hotel",
            lambda r: (self._payload(r), {"to_city": destination}))
        return self._public(result)

    async def itinerary(self, input_data: dict) -> dict:
        """Generate an itinerary and verify it before it can reach the customer."""
        async def discard(_result):
            # A plan that failed verification must not be served from cache.
            await self.itinerary_agent.evict(input_data)

        def build(r):
            trip = r.get("trip") or {}
            return ({"itinerary": r["itinerary"], "route": r.get("route")},
                    {"from_city": trip.get("from"), "to_city": trip.get("to"),
                     "trip_type": trip.get("trip_type"), "days": trip.get("days"),
                     "allowed_hotels": r.get("hotels_offered")})

        result = await self._verified(
            "itinerary",
            lambda fresh: self.itinerary_agent.generate(input_data, use_cache=not fresh),
            "itinerary", build, discard)
        return self._public(result)

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

        # Write, then verify; one fresh draft if the first is rejected.
        draft = None
        for attempt in range(2):
            candidate = await self._safe(self.email_writer_agent.run, "email_writer", data)
            if not candidate.get("success"):
                return candidate
            verdict = await self.verifier.verify(
                "email", {"subject": candidate["subject"], "body": candidate["body"]},
                {"customer_name": data.get("customer_name")})
            if verdict["acceptable"]:
                draft = candidate
                break
            logger.warning("Email draft rejected by verifier (attempt %d): score %s",
                           attempt + 1, verdict["overall_score"])
        if draft is None:
            return {"success": False, "status": 503,
                    "message": "Response verify nahi ho paya. Try again."}

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
        """Write a blog, verify it, and keep it as a DRAFT. Never publishes."""
        async def discard(result):
            # The agent saves a draft before verification; remove a rejected one.
            try:
                await blog_service.delete_blog(result["id"])
            except blog_service.BlogError as e:
                logger.error("Could not delete rejected draft %s: %s", result["id"], e.message)

        def build(r):
            full = r["content"]
            meta = r["blog"]
            return ({"title": meta["title"], "meta_description": meta["meta_description"],
                     "content": full, "confidence_score": meta.get("confidence_score")},
                    {"target_keyword": meta.get("target_keyword"),
                     "target_word_count": input_data.get("word_count")
                     if isinstance(input_data, dict) else None})

        result = await self._verified(
            "blog_writer", lambda fresh: self.blog_writer_agent.generate(input_data),
            "blog", build, discard)
        if result.get("success"):
            verdict = result.get("_verdict") or {}
            result["verification"] = {**result["verification"],
                                      "issues": verdict.get("issues", [])}
        result.pop("content", None)
        return self._public(result)

    async def chat(self, message: str, user: dict, session_id: str = None,
                   language: str = None) -> dict:
        """One Safar chat turn. Raises avatar_agent.SessionAccessError for someone
        else's session id; everything else comes back as a reply."""
        return await self.avatar_agent.chat(message, user, session_id, language)

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
