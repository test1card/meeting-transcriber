from __future__ import annotations

from typing import Final


REFINED_PROMPTS: Final[dict[str, dict[str, str]]] = {
    "p6_deepseek_refined": {
        "label": "DeepSeek refined: human-style compression with explicit caps",
        "extract": (
            "Prepare structured source data for a short official Russian protocol. Retain "
            "load-bearing technical requirements, exact values and units, dates, contract "
            "constraints, work categories, funding, application status and explicit assignments. "
            "Exclude greetings, audibility checks, filler and repetition. Never use Speaker labels "
            "as attendees or owners. If a passage has only an anonymous Speaker label, owner is "
            "unspecified. A proposal or question is discussed, not resolved. A due date is allowed "
            "only when the passage explicitly links that date to that exact task; a project "
            "milestone is not a task deadline. Keep each item compact. JSON only. "
        ),
        "synthesize": (
            "Act as the final editor of a concise human-written Russian meeting protocol. Produce "
            "a compact agenda, 10-16 thematic discussed items when supported, and 2-6 explicit "
            "resolutions when supported. These are maximum style targets, never reasons to invent "
            "content. Merge repetitions but preserve distinct numbers, units and constraints. "
            "Delete every Speaker label from attendees and owners. Recheck each resolution against "
            "its evidence: proposals/questions stay discussed; unsupported owner and due become "
            "unspecified; meeting dates and project milestones never become task deadlines. Use "
            "infinitive tasks. No executive prose, risk/open-question sections, chronology or "
            "visible timestamps. JSON only. "
        ),
    },
}
