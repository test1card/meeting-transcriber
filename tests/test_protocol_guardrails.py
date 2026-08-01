from __future__ import annotations

from meeting_transcriber.protocol_guardrails import sanitize_protocol_extraction


def _payload(*, task: str, owner: str, due: str, evidence: str) -> dict:
    return {
        "overview": [],
        "topics": [],
        "decisions": [],
        "actions": [
            {
                "task": task,
                "owner": owner,
                "due": due,
                "evidence": evidence,
            }
        ],
        "risks": [],
        "open_questions": [],
    }


def test_next_meeting_date_is_not_a_task_deadline() -> None:
    lines = [
        "[01:12:58] Speaker 5: Вы проговорите с Россетями и посчитайте реконструкцию.",
        "[01:13:20] Speaker 5: Ориентировочно 17 августа встретимся на площадке.",
        "[01:13:31] Speaker 5: Через две недели окончательно решим, по какому пути идем.",
    ]
    value = sanitize_protocol_extraction(
        _payload(
            task="Провести переговоры с Россетями",
            owner="Speaker 5",
            due="17.08.2024",
            evidence="[01:13:20]",
        ),
        lines,
    )
    assert value["actions"][0]["owner"] == "unspecified"
    assert value["actions"][0]["due"] == "unspecified"


def test_explicit_supported_deadline_and_full_name_survive() -> None:
    lines = [
        "[00:10:00] Иванов Иван Иванович: Поручение подготовить расчет до 12 августа.",
    ]
    value = sanitize_protocol_extraction(
        _payload(
            task="Подготовить расчет",
            owner="Иванов Иван Иванович",
            due="12 августа",
            evidence="[00:10:00]",
        ),
        lines,
    )
    assert value["actions"][0]["owner"] == "Иванов Иван Иванович"
    assert value["actions"][0]["due"] == "12 августа"


def test_model_cannot_add_a_year_absent_from_evidence() -> None:
    lines = [
        "[00:10:00] Иванов Иван Иванович: Срок выполнения — до 12 августа.",
    ]
    value = sanitize_protocol_extraction(
        _payload(
            task="Подготовить расчет",
            owner="Иванов Иван Иванович",
            due="12.08.2027",
            evidence="[00:10:00]",
        ),
        lines,
    )
    assert value["actions"][0]["due"] == "unspecified"


def test_explicit_short_name_and_legitimate_task_survive() -> None:
    value = sanitize_protocol_extraction(
        _payload(
            task="Рассчитать командировочные расходы",
            owner="Мария",
            due="до пятницы",
            evidence="[01:14:07]",
        ),
        ["[01:14:07] Мария, рассчитайте командировочные расходы до пятницы."],
    )
    assert value["actions"][0]["owner"] == "Мария"
    assert value["actions"][0]["due"] == "до пятницы"


def test_unrelated_date_cannot_replace_the_explicit_deadline() -> None:
    lines = [
        "[00:10:00] Иванов Иван Иванович: Подготовить расчет до 12 августа.",
    ]
    value = sanitize_protocol_extraction(
        _payload(
            task="Подготовить расчет",
            owner="Иванов Иван Иванович",
            due="15 сентября",
            evidence="[00:10:00]",
        ),
        lines,
    )
    assert value["actions"][0]["due"] == "unspecified"


def test_calendar_event_without_deadline_cue_is_not_a_due_date() -> None:
    lines = [
        "[00:10:00] Обсудили смету. Следующее совещание состоится 12 августа.",
    ]
    value = sanitize_protocol_extraction(
        _payload(
            task="Подготовить расчет",
            owner="unspecified",
            due="12 августа",
            evidence="[00:10:00]",
        ),
        lines,
    )
    assert value["actions"][0]["due"] == "unspecified"

def test_owner_tokens_from_separate_people_are_not_merged() -> None:
    lines = [
        "[00:10:00] Женя, подготовь протокол. Голубев потом согласует документ.",
    ]
    value = sanitize_protocol_extraction(
        _payload(
            task="Подготовить протокол",
            owner="Женя Голубев",
            due="unspecified",
            evidence="[00:10:00]",
        ),
        lines,
    )
    assert value["actions"][0]["owner"] == "unspecified"


def test_expert_mentioned_after_collective_commitment_is_not_owner() -> None:
    lines = [
        "[00:10:00] Мы проведем уточненную оценку. Евгений Сергеевич знает объект.",
    ]
    value = sanitize_protocol_extraction(
        _payload(
            task="Провести уточненную оценку",
            owner="Евгений Сергеевич",
            due="unspecified",
            evidence="[00:10:00]",
        ),
        lines,
    )
    assert value["actions"][0]["owner"] == "unspecified"


def test_planned_meeting_is_not_assignment_despite_unrelated_need_in_line() -> None:
    from meeting_transcriber.protocol_guardrails import action_evidence_supported

    lines = [
        (
            "[00:10:00] Нужно подготовить обоснование. Через неделю предстоит "
            "встреча с руководством Росатома по проекту."
        ),
    ]
    assert not action_evidence_supported(
        "Провести встречу с руководством Росатома по проекту",
        "[00:10:00]",
        lines,
    )

def test_unsupported_number_drops_claim_but_supported_number_survives() -> None:
    payload = {
        "overview": [],
        "topics": [
            {
                "topic": "Стоимость",
                "summary": "Стоимость составляет 31,3 млн рублей.",
                "evidence": ["[00:10:00]"],
            },
            {
                "topic": "Мощность",
                "summary": "Требуется 1,3 МВт.",
                "evidence": ["[00:10:10]"],
            },
        ],
        "decisions": [],
        "actions": [],
        "risks": [],
        "open_questions": [],
    }
    value = sanitize_protocol_extraction(
        payload,
        [
            "[00:10:00] Стоимость оценивается в диапазоне 30,5–31 млн рублей.",
            "[00:10:10] Для установки требуется 1,3 МВт.",
        ],
    )
    assert [item["topic"] for item in value["topics"]] == ["Мощность"]