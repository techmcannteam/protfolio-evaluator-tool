import requests

from .delivery_errors import DeliveryError

EVENTS_URL = "https://api.followupboss.com/v1/events"


class FubSender:
    """One Events API request per claimed delivery. No implicit HTTP retries."""

    def __init__(self, settings, http=None):
        self.settings = settings
        self.http = http or requests

    @property
    def configured(self):
        s = self.settings
        return bool(s.fub_api_key and s.fub_system and s.fub_system_key)

    def __call__(self, event):
        s = self.settings
        if not s.enable_fub:
            return {"status": "disabled", "sent": False}
        if not self.configured:
            return {"status": "needs_configuration", "sent": False}
        if not event.get("person", {}).get("assignedUserId"):
            return {"status": "needs_configuration", "sent": False}
        try:
            response = self.http.post(
                EVENTS_URL,
                json=event,
                auth=(s.fub_api_key, ""),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-System": s.fub_system,
                    "X-System-Key": s.fub_system_key,
                },
                timeout=(5, 15),
                allow_redirects=False,
            )
        except requests.ConnectTimeout as exc:
            raise DeliveryError("fub_connect_timeout") from exc
        except requests.RequestException as exc:
            # A lost response can follow acceptance. Never blindly POST again.
            raise DeliveryError("fub_acceptance_unknown", "uncertain") from exc
        if response.status_code in (200, 201):
            return {"status": "sent", "sent": True}
        if response.status_code == 204:
            return {"status": "ignored", "sent": False}
        if response.status_code in (400, 401, 403, 404, 422, 429):
            raise DeliveryError(f"fub_rejected_{response.status_code}")
        raise DeliveryError("fub_acceptance_unknown", "uncertain")


def evaluation_event(contact, mode, assignee_id, description):
    """POST /v1/events shape; one lead/event can describe multiple addresses."""
    first, _, last = contact["name"].partition(" ")
    person = {
        "firstName": first,
        "lastName": last,
        "emails": [{"value": contact["email"]}],
        "tags": ["portfolio-evaluator", f"{mode}-evaluation"],
    }
    if contact.get("phone"):
        person["phones"] = [{"value": contact["phone"]}]
    if assignee_id is not None:
        person["assignedUserId"] = assignee_id
    return {
        "source": f"McCann {mode.title()} Evaluation",
        "system": "McCann Portfolio Evaluator",
        "type": "Seller Inquiry",
        "person": person,
        "message": f"Owner requested a {mode} evaluation.",
        "description": description,
    }
