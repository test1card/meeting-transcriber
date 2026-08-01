from __future__ import annotations

from meeting_transcriber.protocol_final import (
    render_protocol_markdown,
    sanitize_final_protocol,
    synthesis_source,
)


def test_synthesis_source_excludes_risk_and_question_inventory() -> None:
    value = synthesis_source(
        {
            "overview": ["x"],
            "topics": [],
            "decisions": [],
            "actions": [],
            "risks": [{"risk": "noise"}],
            "open_questions": [{"question": "noise"}],
        }
    )
    assert set(value) == {"overview", "topics", "decisions", "actions"}


def test_synthesis_source_includes_compact_verbatim_context() -> None:
    value = synthesis_source(
        {
            "overview": "x",
            "topics": [
                {
                    "topic": "Бюджет",
                    "summary": "Стоимость 12 млн.",
                    "evidence": ["[00:00:10]"],
                }
            ],
            "decisions": [],
            "actions": [],
        },
        ["[00:00:10] Speaker 1: Стоимость составляет 12 млн рублей."],
    )
    assert "12 млн рублей" in value["topics"][0]["source_context"]


def test_final_protocol_normalizes_common_json_aliases() -> None:
    value = sanitize_final_protocol(
        {
            "agenda": "Обсуждение бюджета",
            "discussed": [
                {
                    "subject": "Бюджет",
                    "details": "Стоимость составляет 12 млн рублей.",
                    "evidence": "[00:00:10]",
                }
            ],
            "resolutions": [
                {
                    "action": "Подготовить таблицу",
                    "responsible": "Ольга",
                    "deadline": "12 сентября",
                    "evidence": "[00:00:20]",
                }
            ],
        },
        [
            "[00:00:10] Стоимость составляет 12 млн рублей.",
            "[00:00:20] Ольга, подготовьте таблицу к 12 сентября.",
        ],
    )
    assert value["agenda"] == ["Обсуждение бюджета"]
    assert value["discussed"][0]["item"].startswith("Бюджет:")
    assert value["resolutions"][0]["owner"] == "Ольга"
    assert value["resolutions"][0]["due"] == "12 сентября"

def test_multiple_evidence_marks_support_a_compound_discussed_fact() -> None:
    value = sanitize_final_protocol(
        {
            "agenda": ["Планирование"],
            "discussed": [
                {
                    "item": "Бюджет составляет 12 млн рублей, срок — 8 месяцев.",
                    "evidence": "[00:00:10], [00:01:10]",
                }
            ],
            "resolutions": [],
        },
        [
            "[00:00:10] Бюджет составляет 12 млн рублей.",
            "[00:01:10] Срок выполнения составляет 8 месяцев.",
        ],
    )
    assert len(value["discussed"]) == 1


def test_routine_administration_is_an_optional_output_style() -> None:
    protocol = {
        "agenda": ["Статус проекта"],
        "discussed": [],
        "resolutions": [
            {
                "task": "Подготовить протокол текущего совещания",
                "owner": "Секретариат",
                "due": "до завтра",
                "evidence": "[00:00:10]",
            },
            {
                "task": "Провести переговоры с поставщиком",
                "owner": "Секретариат",
                "due": "до завтра",
                "evidence": "[00:00:10]",
            },
            {
                "task": "Подготовить проект протокола (рыбу)",
                "owner": "Секретариат",
                "due": "до завтра",
                "evidence": "[00:00:10]",
            },
        ],
    }
    lines = [
        "[00:00:10] Секретариат, подготовьте протокол текущего совещания и "
        "проведите переговоры с поставщиком до завтра.",
    ]
    compact = sanitize_final_protocol(protocol, lines)
    complete = sanitize_final_protocol(protocol, lines, include_routine_admin=True)
    assert [item["task"] for item in compact["resolutions"]] == [
        "Провести переговоры с поставщиком"
    ]
    assert len(complete["resolutions"]) == 3

def test_resolution_basis_quote_distinguishes_commitment_from_planned_status() -> None:
    lines = [
        "[00:00:10] Вы проговорите с поставщиком условия поставки.",
        "[00:00:20] Через неделю предстоит встреча с поставщиком.",
    ]
    protocol = {
        "agenda": ["Поставка"],
        "discussed": [],
        "resolutions": [
            {
                "task": "Проговорить с поставщиком условия поставки",
                "owner": "unspecified",
                "due": "unspecified",
                "evidence": "[00:00:10]",
                "basis": "assigned",
                "basis_quote": "Вы проговорите с поставщиком условия поставки.",
            },
            {
                "task": "Провести встречу с поставщиком",
                "owner": "unspecified",
                "due": "unspecified",
                "evidence": "[00:00:20]",
                "basis": "committed",
                "basis_quote": "Через неделю предстоит встреча с поставщиком.",
            },
        ],
    }
    value = sanitize_final_protocol(
        protocol,
        lines,
        require_resolution_basis=True,
    )
    assert [item["task"] for item in value["resolutions"]] == [
        "Проговорить с поставщиком условия поставки"
    ]

def test_collective_commitment_and_anonymous_speaker_filter() -> None:
    protocol = {
        "agenda": ["Бюджет"],
        "discussed": [
            {
                "item": "За бюджет отвечает Speaker 4.",
                "evidence": "[00:00:10]",
            },
            {
                "item": "Обсужден бюджет проекта.",
                "evidence": "[00:00:10]",
            },
        ],
        "resolutions": [
            {
                "task": "Посчитать стоимость реконструкции",
                "owner": "unspecified",
                "due": "unspecified",
                "evidence": "[00:00:20]",
                "basis": "committed",
                "basis_quote": "Посчитаем стоимость реконструкции.",
            }
        ],
    }
    value = sanitize_final_protocol(
        protocol,
        [
            "[00:00:10] Обсужден бюджет проекта.",
            "[00:00:20] Посчитаем стоимость реконструкции.",
        ],
        require_resolution_basis=True,
    )
    assert [item["item"] for item in value["discussed"]] == [
        "Обсужден бюджет проекта."
    ]
    assert [item["task"] for item in value["resolutions"]] == [
        "Посчитать стоимость реконструкции"
    ]

def test_verified_extraction_actions_restore_missing_resolutions() -> None:
    lines = [
        "[00:00:10] Вы проговорите с Россетями и уточните свободную мощность.",
        "[00:00:20] Я проговорю с Министерством сроки финансирования.",
        "[00:00:30] Посчитаем стоимость реконструкции.",
        "[00:00:40] Через неделю предстоит встреча с поставщиком.",
        "[00:10:00] Я отправлю справочное письмо контрагенту."
    ]
    fallback = [
        {
            "task": "Провести переговоры с Россетями и уточнить свободную мощность",
            "owner": "unspecified",
            "due": "unspecified",
            "evidence": "[00:00:10]",
        },
        {
            "task": "Провести переговоры с Министерством о сроках финансирования",
            "owner": "unspecified",
            "due": "unspecified",
            "evidence": "[00:00:20]",
        },
        {
            "task": "Посчитать стоимость реконструкции",
            "owner": "unspecified",
            "due": "unspecified",
            "evidence": "[00:00:30]",
        },
        {
            "task": "Провести встречу с поставщиком",
            "owner": "unspecified",
            "due": "unspecified",
            "evidence": "[00:00:40]",
        },
        {
            "task": "Отправить справочное письмо контрагенту",
            "owner": "unspecified",
            "due": "unspecified",
            "evidence": "[00:10:00]",
        },
    ]
    value = sanitize_final_protocol(
        {"agenda": ["Проект"], "discussed": [], "resolutions": []},
        lines,
        require_resolution_basis=True,
        fallback_actions=fallback,
    )
    assert [item["task"] for item in value["resolutions"]] == [
        "Провести переговоры с Россетями и уточнить свободную мощность",
        "Провести переговоры с Министерством о сроках финансирования",
        "Посчитать стоимость реконструкции",
    ]

def test_final_protocol_is_guarded_and_rendered_deterministically() -> None:
    lines = [
        "[00:00:10] Ольга, подготовьте таблицу к 12 сентября.",
        "[00:00:20] Следующее совещание проведем 17 сентября.",
    ]
    value = sanitize_final_protocol(
        {
            "agenda": ["Проверка статуса"],
            "discussed": [{"item": "Проверен статус.", "evidence": "[00:00:10]"}],
            "resolutions": [
                {
                    "task": "Подготовить таблицу",
                    "owner": "Ольга",
                    "due": "12 сентября",
                    "evidence": "[00:00:10]",
                }
            ],
        },
        lines,
    )
    markdown = render_protocol_markdown(value)
    assert "## ПОВЕСТКА СОВЕЩАНИЯ" in markdown
    assert "## ОБСУДИЛИ" in markdown
    assert "## ПО РЕЗУЛЬТАТАМ СОВЕЩАНИЯ РЕШИЛИ" in markdown
    assert "Ольга" in markdown
    assert "12 сентября" in markdown
    assert "РИСКИ" not in markdown
