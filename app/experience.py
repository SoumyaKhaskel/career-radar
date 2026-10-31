"""Conservative deterministic experience classification."""
import re

RANGE = re.compile(r"(?<!\d)(\d+)\s*(?:-|–|—|to)\s*(\d+)\s*(?:years?|yrs?)", re.I)
MINIMUM = re.compile(r"(?:at least|minimum of|minimum|\+)\s*(\d+)\s*(?:years?|yrs?)|(?<!\d)(\d+)\s*\+\s*(?:years?|yrs?)", re.I)

def classify_experience(text: str | None, maximum: int = 3) -> tuple[str, str]:
    raw = (text or "").strip()
    low = raw.lower()
    if not raw:
        return "needs_review", "Experience not specified."
    if re.search(r"no experience required|fresh graduate|graduate programme|graduate program|entry[- ]level|junior", low):
        return "confirmed", "Entry-level wording is compatible with the configured limit."
    ranges = [(int(a), int(b)) for a, b in RANGE.findall(low)]
    if ranges:
        if any(hi > maximum for _, hi in ranges):
            return "excluded", f"An explicit experience range exceeds {maximum} years."
        return "confirmed", "Explicit experience range fits the configured limit."
    # Up-to expressions are bounded; do not infer a lower bound beyond zero.
    up_to = re.search(r"up to\s+(\d+|one|two|three|four|five)\s*(?:years?|yrs?)", low)
    if up_to:
        upper = {"one":1,"two":2,"three":3,"four":4,"five":5}.get(up_to.group(1), int(up_to.group(1)) if up_to.group(1).isdigit() else maximum + 1)
        return ("confirmed", "Explicit upper bound fits the configured limit.") if upper <= maximum else ("excluded", f"Explicit upper bound exceeds {maximum} years.")
    mins = []
    for match in MINIMUM.finditer(low):
        mins.append(int(match.group(1) or match.group(2)))
    if mins:
        if max(mins) > maximum:
            return "excluded", f"Minimum experience exceeds {maximum} years."
        return "needs_review", "A minimum is stated without an explicit upper bound."
    if re.search(r"\b\d+\s*(?:years?|yrs?)\b", low):
        return "needs_review", "Experience wording is ambiguous or has no explicit range."
    if re.search(r"experience", low):
        return "needs_review", "Experience is mentioned without a clear numeric requirement."
    return "needs_review", "Experience requirement is not stated clearly."
