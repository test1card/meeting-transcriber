from __future__ import annotations


def protocol_model_suffix(*, provider: str, model: str, stage: str) -> str:
    """Return a small production prompt suffix tuned to the selected text model."""
    key = model.lower()
    if provider == "deepseek" or "deepseek" in key:
        suffix = (
            " Preserve the human-secretary compression of the base instruction. "
            "Silently verify every resolution against evidence before answering; do not "
            "expand the document into a transcript inventory. Discover subjects only "
            "from the supplied transcript. A statement that no decision was made or that "
            "a decision was postponed is status, not a decision; an explicit choice not "
            "to perform an action is a decision. Copy stated quantitative values only: "
            "do not calculate differences, totals or new ranges."
        )
        if stage == "synthesis":
            suffix += (
                " Write each discussed item as a complete content-bearing factual "
                "sentence, never as a bare heading. Make agenda items mutually distinct. "
                "Apply the substantive-outcome test strictly: do not copy every extracted "
                "action into resolutions."
            )
        return suffix
    if "e4b" in key:
        return (
            " Use short Russian sentences and the requested structure only. Anonymous "
            "Speaker labels are never people or owners. Never guess a task, owner or due "
            "date. Keep the result a draft because this compact model has limited recall."
        )
    if "31b" in key:
        return (
            " Compress aggressively and answer in Russian only. Do not explain reasoning. "
            "Anonymous Speaker labels are never attendees or owners. A due date must be "
            "explicitly linked to the same task in the same evidence passage; a calendar "
            "event, forecast or next-meeting date is not automatically a task deadline. "
            "Copy quantitative values literally instead of constructing new ranges. "
            "Do not calculate differences, totals, ratios or any other derived values."
        )
    if "26b" in key:
        return (
            " Answer in Russian only. Copy exact stated numbers and units before returning; "
            "never calculate a difference, total, ratio or new range. Keep independently "
            "stated quantitative facts in separate topic items with their own evidence. "
            "Anonymous Speaker labels are never attendees or owners. Veto any resolution "
            "that is only a proposal or question. A calendar event, forecast or nearby "
            "date is not a task deadline unless explicitly linked to that task. Conversely, "
            "when a task sentence explicitly links a deadline marker and date to the task, "
            "copy that due value literally rather than returning unspecified."
        )
    if "12b" in key:
        suffix = (
            " Follow the detailed base instruction without shortening it. Answer in "
            "Russian only. Anonymous Speaker labels are never attendees or owners. Owner "
            "and due date require explicit support in the same evidence passage; otherwise "
            "use unspecified. Roles, teams, departments and organizations are valid owners "
            "when the passage directly assigns them; copy that role or unit instead of "
            "returning unspecified. A calendar event or forecast is not a task deadline."
        )
        if stage == "synthesis":
            suffix += (
                " Do not output topic labels alone: every discussed item must state the "
                "material fact, status, constraint or value in a complete sentence. "
                "Select resolutions rather than copying the action list wholesale."
            )
        return suffix
    if stage == "synthesis":
        return " Keep the final protocol concise and do not infer owners or deadlines."
    return " Do not infer owners or deadlines."
