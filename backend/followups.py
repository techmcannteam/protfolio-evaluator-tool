"""Durable, flag-gated followups with conservative recovery after uncertain sends."""

import json

from .agents import SLUG
from .config import DISCLAIMER
from .delivery_errors import DeliveryError
from .email_templates import cma_email_html, email_html
from .follow_up_boss import FubSender, evaluation_event
from .notifications import SmtpEmailSender
from .roster import load_roster


def resolve_routing(repository, settings, requested_slug):
    agent = (
        repository.agent(requested_slug)
        if requested_slug and SLUG.fullmatch(requested_slug)
        else None
    )
    generic = settings.fub_generic_assignee_id
    if not agent and not generic:
        generic = (load_roster(settings.roster_path).get("generic_assignee") or {}).get(
            "fub_user_id"
        )
    raw_id = agent.get("fub_user_id") if agent else generic
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


def summary_text(result, mode="portfolio"):
    def money(value):
        return "Unavailable" if value is None else f"${value:,.0f}"

    lines = []
    for row in result["properties"]:
        value, display = row.get("value") or {}, row.get("display_value") or {}
        cap = (row.get("operating") or {}).get("cap_rate")
        lines.extend(
            [
                row["address"],
                "",
                f"Most likely: {money(display.get('most_likely'))}",
                f"Condition guide: {money(value.get('low'))} needs work — {money(value.get('high'))} renovated / updated",
                "",
                display.get("explanation", "Whole-building value needs agent review."),
                "",
                f"Provider estimate: {money(value.get('estimate'))}",
                f"Monthly rent: {money((row.get('rent') or {}).get('estimate'))}",
                f"Cap rate: {cap:.2%}" if cap is not None else "Cap rate: Unavailable",
                *(["", *row["warnings"]] if row.get("warnings") else []),
                "",
            ]
        )
    totals = result["totals"]
    indicated = [
        r["display_value"]["most_likely"]
        for r in result["properties"]
        if r.get("display_value")
    ]
    cap_label = "Cap rate" if mode == "home" else "Portfolio cap rate"
    lines.extend(
        [
            f"Properties valued: {totals['properties_valued']} of {totals['properties_requested']}",
            "",
            f"Most likely total (available values): {money(sum(indicated) if indicated else None)}",
            f"Provider total (available values): {money(totals['estimated_value'] if totals['properties_valued'] else None)}",
            f"Total monthly rent: {money(totals['monthly_rent'])}",
            f"{cap_label}: {totals['cap_rate']:.2%}"
            if totals["cap_rate"] is not None
            else f"{cap_label}: Unavailable",
            "",
        ]
    )
    lines.extend(
        [
            "Cap rates use the provider estimate and operating assumptions; condition guidance changes only the displayed indication.",
            "",
            DISCLAIMER,
        ]
    )
    return "\n".join(lines)


class EvaluationFollowups:
    def __init__(self, repository, settings, email_sender=None, fub_sender=None):
        self.repository, self.settings = repository, settings
        self.email_sender = email_sender or SmtpEmailSender(settings)
        self.fub_sender = fub_sender or FubSender(settings)

    def record(self, request, result, requested_slug):
        routing = resolve_routing(self.repository, self.settings, requested_slug)
        contact = request.contact.model_dump(mode="json")
        link = f"/evaluator/{request.mode}" + (
            f"?agent={routing['agent_slug']}" if routing["agent_slug"] else ""
        )
        summary = summary_text(result, request.mode)
        internal = "\n".join(
            [
                f"Owner: {contact['name']}",
                f"Email: {contact['email']}",
                f"Phone: {contact.get('phone') or 'Not provided'}",
                "",
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
                "html": email_html(
                    result, request.mode, contact, routing=routing, agent_link=link
                ),
            },
            "owner_email": {
                "from": self.settings.email_from,
                "to": [contact["email"]],
                "subject": f"Your McCann {request.mode} evaluation",
                "text": f"Hello {contact['name']},\n\n{summary}",
                "html": email_html(result, request.mode, contact),
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

    def record_cma(self, request, estimate):
        snapshot = json.loads(estimate["payload"])
        mode = snapshot.get("evaluation_mode", "portfolio")
        routing = resolve_routing(
            self.repository, self.settings, estimate["agent_slug"]
        )
        contact = {
            "name": request.owner_name,
            "email": str(request.email),
            "phone": request.phone,
        }
        description = "\n".join(
            [
                "Owner requested an agent CMA.",
                estimate["address"],
                f"Provider estimate: ${snapshot['value']['estimate']:,.0f}",
                f"Owner expected value: {request.expected_value if request.expected_value is not None else 'Not provided'}",
                f"Owner note: {request.note}",
            ]
        )
        event = evaluation_event(contact, mode, routing["assignee_id"], description)
        event["person"]["tags"].append("cma-request")
        event["message"] = f"Owner requested a CMA after a {mode} evaluation."
        link = f"/evaluator/{mode}" + (
            f"?agent={routing['agent_slug']}" if routing["agent_slug"] else ""
        )
        internal = "\n".join(
            [
                f"Owner: {contact['name']}",
                f"Email: {contact['email']}",
                f"Phone: {contact.get('phone') or 'Not provided'}",
                "",
                f"Agent link: {link}",
                f"Routing: {routing['kind']} ({routing['status']})",
                "",
                description,
                "",
                DISCLAIMER,
            ]
        )
        identifier = self.repository.save_cma(
            request,
            estimate,
            "pending",
            lead={"kind": "cma", "contact": contact, "mode": mode, "routing": routing},
            deliveries={
                "fub": {"event": event, "routing": routing},
                "team_email": {
                    "from": self.settings.email_from,
                    "to": list(self.settings.internal_notification_recipients),
                    "subject": f"New McCann {mode} CMA request",
                    "text": internal,
                    "html": cma_email_html(
                        mode,
                        contact,
                        routing,
                        link,
                        estimate["address"],
                        snapshot["value"]["estimate"],
                        request.expected_value,
                        request.note,
                    ),
                },
            },
        )
        self.dispatch(identifier, "fub")
        self.dispatch(identifier, "team_email")
        return identifier

    def recover(self, limit=10):
        recovered = []
        for row in self.repository.recoverable_deliveries(limit):
            self.dispatch(row["evaluation_id"], row["kind"], retry=True)
            recovered.append(
                {
                    **row,
                    "status": self.repository.delivery_statuses(row["evaluation_id"])[
                        row["kind"]
                    ],
                }
            )
        return recovered

    def dispatch(self, identifier, kind, results_shown=False, *, retry=False):
        payload = self.repository.claim_delivery(
            identifier, kind, results_shown, retry=retry
        )
        if payload is None:
            return
        error = None
        try:
            if kind == "fub":
                if not self.settings.enable_fub:
                    status = "disabled"
                else:
                    if payload["routing"]["status"] != "configured":
                        routing = resolve_routing(
                            self.repository,
                            self.settings,
                            payload["routing"]["agent_slug"],
                        )
                        # A formerly valid agent must not silently become a generic lead.
                        if (
                            payload["routing"]["kind"] == "agent_link"
                            and routing["kind"] != "agent_link"
                        ):
                            routing = payload["routing"]
                        payload["routing"] = routing
                        if routing["assignee_id"]:
                            payload["event"]["person"]["assignedUserId"] = routing[
                                "assignee_id"
                            ]
                    if payload["routing"]["status"] != "configured" or not getattr(
                        self.fub_sender, "configured", True
                    ):
                        status = "needs_configuration"
                    elif self.repository.begin_delivery_attempt(
                        identifier, kind, payload
                    ):
                        status = self.fub_sender(payload["event"])["status"]
                    else:
                        return
            elif not self.settings.enable_email or (
                kind == "team_email" and not self.settings.enable_team_notifications
            ):
                status = "disabled"
            else:
                payload["from"] = payload["from"] or self.settings.email_from
                if kind == "team_email" and not payload["to"]:
                    payload["to"] = list(self.settings.internal_notification_recipients)
                if (
                    not payload["from"]
                    or not payload["to"]
                    or not getattr(self.email_sender, "configured", True)
                ):
                    status = "needs_configuration"
                elif self.repository.begin_delivery_attempt(identifier, kind, payload):
                    status = self.email_sender.send(payload)["status"]
                else:
                    return
        except DeliveryError as exc:
            status, error = exc.status, exc.code
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            # Delivery failures must not discard an evaluation or expose contact data.
            status, error = "uncertain", "unexpected_delivery_error"
        self.repository.finish_delivery(
            identifier, kind, status, token=payload["_claim_token"], error=error
        )
