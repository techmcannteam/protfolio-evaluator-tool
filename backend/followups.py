"""Persist server-calculated followups; all production senders remain stubs."""

from .agents import SLUG
from .config import DISCLAIMER
from .follow_up_boss import evaluation_event, pushToFUB
from .notifications import StubEmailSender


def resolve_routing(repository, settings, requested_slug):
    agent = (
        repository.agent(requested_slug)
        if requested_slug and SLUG.fullmatch(requested_slug)
        else None
    )
    raw_id = agent.get("fub_user_id") if agent else settings.fub_generic_assignee_id
    try:
        assignee_id = int(raw_id)
        if assignee_id <= 0:
            assignee_id = None
    except (ValueError, TypeError):
        assignee_id = None
    return {
        "kind": "agent_link" if agent else "generic_link",
        "agent_slug": agent["slug"] if agent else None,
        "assignee_id": assignee_id,
        "status": "configured" if assignee_id else "needs_configuration",
    }


def summary_text(result):
    def money(value):
        return "Unavailable" if value is None else f"${value:,.0f}"

    lines = []
    for row in result["properties"]:
        value, display = row.get("value") or {}, row.get("display_value") or {}
        cap = (row.get("operating") or {}).get("cap_rate")
        lines.extend(
            [
                row["address"],
                f"Most likely: {money(display.get('most_likely'))}",
                f"Condition guide: {money(value.get('low'))} needs work — {money(value.get('high'))} renovated / updated",
                display.get("explanation", "Whole-building value needs agent review."),
                f"Provider estimate: {money(value.get('estimate'))}",
                f"Monthly rent: {money((row.get('rent') or {}).get('estimate'))}",
                f"Cap rate: {cap:.2%}" if cap is not None else "Cap rate: Unavailable",
                *row.get("warnings", []),
                "",
            ]
        )
    totals = result["totals"]
    indicated = [
        r["display_value"]["most_likely"]
        for r in result["properties"]
        if r.get("display_value")
    ]
    lines.extend(
        [
            f"Properties valued: {totals['properties_valued']} of {totals['properties_requested']}",
            f"Most likely total (available values): {money(sum(indicated) if indicated else None)}",
            f"Provider total (available values): {money(totals['estimated_value'] if totals['properties_valued'] else None)}",
            f"Total monthly rent: {money(totals['monthly_rent'])}",
            f"Portfolio cap rate: {totals['cap_rate']:.2%}"
            if totals["cap_rate"] is not None
            else "Portfolio cap rate: Unavailable",
            "",
        ]
    )
    lines.extend(
        [
            "Cap rates use the provider estimate and operating assumptions; condition guidance changes only the displayed indication.",
            DISCLAIMER,
        ]
    )
    return "\n".join(lines)


class EvaluationFollowups:
    def __init__(self, repository, settings, email_sender=None, fub_sender=None):
        self.repository, self.settings = repository, settings
        self.email_sender = email_sender or StubEmailSender()
        self.fub_sender = fub_sender or pushToFUB

    def record(self, request, result, requested_slug):
        routing = resolve_routing(self.repository, self.settings, requested_slug)
        contact = request.contact.model_dump(mode="json")
        link = f"/evaluator/{request.mode}" + (
            f"?agent={routing['agent_slug']}" if routing["agent_slug"] else ""
        )
        summary = summary_text(result)
        internal = "\n".join(
            [
                f"Owner: {contact['name']}",
                f"Email: {contact['email']}",
                f"Phone: {contact.get('phone') or 'Not provided'}",
                f"Agent link: {link}",
                f"Routing: {routing['kind']} ({routing['status']})",
                "",
                summary,
            ]
        )
        deliveries = {
            "fub": {
                "event": evaluation_event(
                    contact, request.mode, routing["assignee_id"], internal
                ),
                "routing": routing,
            },
            "team_email": {
                "from": self.settings.email_from,
                "to": list(self.settings.internal_notification_recipients),
                "subject": f"New McCann {request.mode} evaluation",
                "text": internal,
            },
            "owner_email": {
                "from": self.settings.email_from,
                "to": [contact["email"]],
                "subject": f"Your McCann {request.mode} evaluation",
                "text": f"Hello {contact['name']},\n\n{summary}",
            },
        }
        identifier = self.repository.save_evaluation_lead(
            {
                "contact": contact,
                "mode": request.mode,
                "routing": routing,
                "agent_link": link,
                "result": result,
            },
            deliveries,
        )
        # Team and CRM events are recorded even when no property value is available.
        self.dispatch(identifier, "fub")
        self.dispatch(identifier, "team_email")
        return identifier

    def dispatch(self, identifier, kind, results_shown=False):
        payload = self.repository.claim_delivery(identifier, kind, results_shown)
        if payload is None:
            return
        try:
            if kind == "fub":
                if not self.settings.enable_fub:
                    status = "disabled"
                elif payload["routing"]["status"] != "configured":
                    status = "needs_configuration"
                else:
                    status = self.fub_sender(payload["event"])["status"]
            elif not self.settings.enable_email or (
                kind == "team_email" and not self.settings.enable_team_notifications
            ):
                status = "disabled"
            elif not payload["from"] or not payload["to"]:
                status = "needs_configuration"
            else:
                status = self.email_sender.send(payload)["status"]
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            # Delivery failures must not discard an evaluation or expose contact data.
            status = "failed"
        self.repository.finish_delivery(identifier, kind, status)
