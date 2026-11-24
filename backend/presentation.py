"""Owner condition guidance is presentation only; never alters provider metrics."""


def condition_display(value, recently_updated):
    if not value:
        return None
    estimate, low, high = value["estimate"], value.get("low"), value.get("high")
    valid_range = (
        low is not None and high is not None and low <= estimate <= high and low < high
    )
    indicated = estimate
    adjusted = recently_updated is True and valid_range
    if adjusted:
        indicated = max(estimate, round(low + 0.8 * (high - low), 2))
    return {
        "most_likely": indicated,
        "low": low,
        "high": high,
        "position": (indicated - low) / (high - low) if valid_range else None,
        "recently_updated": recently_updated,
        "condition_applied": bool(adjusted),
        "explanation": (
            "You reported kitchen or bath updates within the last 5 years, so we're pointing toward the renovated / updated end of the range. Your agent can confirm the condition."
            if adjusted
            else "Recent updates noted. A complete provider range is unavailable, so we're showing the provider's estimate."
            if recently_updated is True
            else "Use the range as a condition guide: needs work at the low end, renovated / updated at the high end. Your agent can confirm where the property belongs."
        ),
    }
