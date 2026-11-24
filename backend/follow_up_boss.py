def pushToFUB(request):
    """Simulated Events API sender. Enabling a flag cannot send real traffic."""
    return {"status": "simulated", "sent": False}


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
