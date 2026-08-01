from __future__ import annotations

from typing import Final


MODEL_TUNED_PROMPTS: Final[dict[str, dict[str, str]]] = {
    "p5_deepseek_tuned": {
        "label": "DeepSeek tuned: evidence-first editorial pass",
        "extract": (
            "Act as an evidence-first senior Russian meeting secretary. Work directly from "
            "the supplied transcript section and silently perform three checks before returning "
            "JSON: (1) retain every load-bearing technical fact, number, unit, date, funding or "
            "contract constraint; (2) reject speech noise, repetition and speculative narrative; "
            "(3) verify that each attendee, assignment, owner and due date is literally supported "
            "by the cited timestamp. A discussed proposal is not a resolution. A due date belongs "
            "in resolved only when the same local passage explicitly connects that date to the "
            "task; otherwise use unspecified. Never convert a meeting date, historical date or "
            "project milestone into an assignment deadline. Prefer compact thematic facts over a "
            "chronological retelling. Preserve Russian names and organizations exactly and Latin "
            "technical terms in Latin. Return no explanation or chain of thought. "
        ),
        "synthesize": (
            "Edit the section extracts into a terse human-quality Russian protocol. Before "
            "returning JSON, silently audit every discussed item and resolution against its "
            "evidence. Merge duplicates without losing exact numbers or units. Discard any "
            "unsupported attendee, owner, due date or action. Keep proposals, questions and "
            "forecasts in discussed; resolved contains only explicit adopted decisions, assigned "
            "tasks or explicit personal commitments. Never reuse a date merely because it appears "
            "nearby. Use unspecified when evidence is incomplete. Keep agenda compact, discussed "
            "thematic, and tasks in the infinitive. No executive summary, risks, open questions, "
            "speaker narrative or visible timestamps. Return no explanation or chain of thought. "
        ),
    },
    "p5_gemma12_tuned": {
        "label": "Gemma 12B tuned: short rules and hard deadline gate",
        "extract": (
            "Create a Russian protocol fact sheet from this transcript section. Follow these "
            "rules exactly. 1) Copy important technical numbers, units, dates, funding, work "
            "categories and contract constraints. 2) Remove greetings, audibility checks, filler "
            "and repeated wording. 3) Attendees are real personal names only; Speaker labels are "
            "never names. 4) A resolution exists only after explicit words of decision, assignment "
            "or commitment. 5) Owner and due date must be explicit in the same evidence passage; "
            "otherwise write unspecified. A project date is not a task deadline. Do not guess. "
            "One fact per item. JSON only, no reasoning. "
        ),
        "synthesize": (
            "Merge the fact sheets into one concise Russian protocol. Keep all supported technical "
            "values but merge repetitions. Delete unsupported names, actions and dates. Recheck "
            "each resolution: if the evidence does not explicitly assign the task, move it to "
            "discussed or omit it; if owner or deadline is not explicit, write unspecified. Never "
            "turn a milestone or meeting date into a deadline. Use infinitive verbs for tasks. "
            "JSON only, no commentary. "
        ),
    },
    "p5_gemma26_tuned": {
        "label": "Gemma 26B tuned: resolution veto and numeric reconciliation",
        "extract": (
            "Prepare evidence-grounded source data for a formal Russian protocol. Silently "
            "separate FACTS, PROPOSALS and EXPLICIT DECISIONS, but return only the required JSON. "
            "Put FACTS and material PROPOSALS in discussed. Put an item in resolved only if the "
            "quoted local passage explicitly records an adopted decision, assignment, or speaker "
            "commitment. Veto inferred tasks. Owner and due date require direct textual support "
            "from that same passage; otherwise unspecified. Historical dates, meeting dates and "
            "project milestones are never assignment deadlines without explicit linkage. Reconcile "
            "numbers and units character-for-character and record contradictions in notes. Exclude "
            "speech noise and repetition. Attendees are explicit real names only, never Speaker "
            "labels. Return compact JSON without explanation. "
        ),
        "synthesize": (
            "Produce a terse official Russian protocol from the extracts. First silently reconcile "
            "duplicate technical facts and numbers. Then apply a veto audit to every resolution: "
            "keep it only with explicit decision/assignment evidence; never promote a proposal, "
            "question, recommendation or future possibility. Remove every inferred owner or due "
            "date, especially dates copied from milestones or unrelated context. Preserve exact "
            "dimensions, power, heat, money, schedule, organizations, contract location and work "
            "category. Use infinitive tasks and unspecified for missing fields. Return only JSON. "
        ),
    },
    "p5_gemma31_tuned": {
        "label": "Gemma 31B tuned: low-verbosity evidence compression",
        "extract": (
            "Compress this transcript section into protocol evidence, not prose. Output only "
            "load-bearing Russian facts: technical parameters, exact numbers/units/dates, funding, "
            "contract constraints, work categories, status, and explicit decisions. Do not "
            "retell speakers or explain reasoning. Merge repetition inside the section. A resolution "
            "requires explicit decision, assignment or commitment language. A task deadline must "
            "be explicitly linked to that task in the same passage; all other dates are facts or "
            "milestones and must not populate due. Do not infer owners. Attendees are explicit "
            "personal names only. Keep each item to one compact sentence. Return JSON only. "
        ),
        "synthesize": (
            "Create one concise Russian protocol. Compress aggressively while preserving distinct "
            "material facts and exact values. Merge duplicates. Perform a final evidence veto: "
            "delete unsupported attendees and resolutions; change unsupported owner or due fields "
            "to unspecified; never use meeting, historical or milestone dates as task deadlines. "
            "Resolved must be explicit, actionable and start with an infinitive. No chronology, "
            "executive narrative, risk section, open questions or visible timestamps. Return JSON "
            "only and keep the response brief. "
        ),
    },
    "p5_e4b_tuned": {
        "label": "Gemma e4b tuned: simplified extraction with strict labels",
        "extract": (
            "Fill the JSON from the Russian transcript. Use short sentences. Keep only important "
            "technical facts, numbers, dates, money and explicit tasks. Ignore greetings, sound "
            "checks and repetition. Speaker 1, Speaker 2 and similar labels are not people: never "
            "put them in attendees. Put a real name in attendees only when the transcript says it. "
            "Put a task in resolved only after explicit words meaning decided, assign, or I will "
            "do it. Never guess owner or deadline; use unspecified. Project dates are not task "
            "deadlines. Copy one timestamp into each evidence field. JSON only. "
        ),
        "synthesize": (
            "Merge the JSON extracts. Keep a short agenda, supported technical facts, and only "
            "explicit tasks. Remove duplicates and all Speaker labels. Delete any guessed action. "
            "For every task, use unspecified unless owner and deadline are stated explicitly. "
            "Never copy a project date into due. Use infinitive task wording. Output exactly the "
            "required JSON and nothing else. "
        ),
    },
}
