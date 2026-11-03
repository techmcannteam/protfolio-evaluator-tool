"""Server-only Google Places access. Do not log or cache search content."""
import requests
from fastapi import HTTPException

BASE = "https://places.googleapis.com/v1/places"


def lookup(key, token, query=None, place_id=None):
    headers = {"X-Goog-Api-Key": key}
    try:
        if query is not None:
            response = requests.post(
                BASE + ":autocomplete",
                headers=headers,
                json={
                    "input": query,
                    "sessionToken": token,
                    "includedRegionCodes": ["us"],
                    "includedPrimaryTypes": ["street_address", "premise", "subpremise"],
                    "locationBias": {"circle": {
                        "center": {"latitude": 39.9526, "longitude": -75.1652},
                        "radius": 50000,
                    }},
                }, timeout=(3, 7), allow_redirects=False,
            )
        else:
            headers["X-Goog-FieldMask"] = "addressComponents"
            response = requests.get(
                BASE + "/" + place_id, headers=headers,
                params={"sessionToken": token}, timeout=(3, 7), allow_redirects=False,
            )
        response.raise_for_status()
        data = response.json()
        if query is not None:
            return {"suggestions": [
                {"id": p["placeId"], "label": p["text"]["text"]}
                for item in data.get("suggestions", [])[:5]
                if (p := item.get("placePrediction")) and p.get("placeId")
            ]}
        parts = {}
        for part in data.get("addressComponents", []):
            for kind in part.get("types", []):
                parts[kind] = part.get("shortText", part.get("longText", ""))
        street = " ".join(filter(None, [parts.get("street_number"), parts.get("route")]))
        if parts.get("subpremise"):
            street += " Unit " + parts["subpremise"]
        city = parts.get("locality") or parts.get("sublocality_level_1")
        state, zipcode = parts.get("administrative_area_level_1"), parts.get("postal_code")
        if not all([parts.get("street_number"), parts.get("route"), city, state, zipcode]):
            raise HTTPException(422, "Please enter the complete street address, city, state and ZIP manually.")
        return {"address": f"{street}, {city}, {state} {zipcode}"}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Address suggestions are unavailable. You can still enter the full address manually.") from None
