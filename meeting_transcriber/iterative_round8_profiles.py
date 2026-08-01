from __future__ import annotations

from typing import Final

from meeting_transcriber.iterative_profiles import ITERATIVE_PROMPTS


ROUND8_PROMPTS: Final[dict[str, dict[str, str]]] = {
    "p11_gemma12_evidence_alignment": {
        "label": "Gemma 12B iteration 6: evidence alignment and final branches",
        "extract": ITERATIVE_PROMPTS["p7_gemma12_identity_date_gate"]["extract"],
        "synthesize": (
            "Сохрани компактный конкретный протокол: одна agenda, 11–13 discussed, 2–3 "
            "материальных resolved. Каждый discussed содержит проверяемый факт, не рубрику. "
            "Покрой мощность/сетевую заявку; габариты/массу/ворота/фундамент/вентиляцию; "
            "капремонт против реконструкции; ПСД и финансирование; сроки испытаний и переноса "
            "поставки; договорную привязку Пущино к явно названным в extracts организациям и "
            "последствия переноса. Не выдумывай отсутствующее. Для каждого item сначала выбери "
            "source extract, затем скопируй ровно его evidence. Evidence должен буквально "
            "поддерживать ключевое число или утверждение того же item; запрещено брать поздний "
            "timestamp только потому, что тема обсуждалась снова. Не объединяй в одном item "
            "факты с разными timestamps, если из-за этого evidence станет неточным. Копируй "
            "числа дословно, не создавай диапазоны. attendees=[]; у всех resolved "
            "owner=\"unspecified\", due=\"unspecified\". Решения — только уточнить мощность/"
            "сетевое подключение и оценить реконструкционные работы. Исключи Росатом, "
            "командировочные, следующую встречу, домашние задания и подготовку протокола. "
            "notes=[]. Каждый evidence — один [HH:MM:SS]. Только русский JSON. "
        ),
    },
    "p10_gemma26_conservative_numbers": {
        "label": "Gemma 26B iteration 5: P8 structure with conservative numbers",
        "extract": ITERATIVE_PROMPTS["p7_gemma26_russian_entity_gate"]["extract"],
        "synthesize": (
            "Верни структуру удачного конкретного русского протокола: одна agenda, 10–14 "
            "полных discussed и максимум 3 resolved. Каждый discussed содержит сам факт. "
            "Покрой мощность и заявку; габариты, массу, ворота, фундамент, вентиляцию и кран; "
            "сроки проекта; договорную привязку Пущино; капремонт/реконструкцию; финансирование "
            "и ПСД. Для числа используй только точную пару «значение + единица» из одного "
            "source extract и копируй evidence этого же extract. Не складывай массы, не "
            "расширяй диапазоны и не объединяй разные мощности. При противоречии опусти "
            "сомнительное число, сохранив качественный факт. attendees=[]; у всех resolved "
            "owner=\"unspecified\", due=\"unspecified\". Оставь только уточнение мощности/"
            "сетевого подключения и оценку реконструкционных работ. Запрещены Росатом, "
            "командировочные, следующая встреча и подготовка протокола. notes=[]. Каждый "
            "evidence — один [HH:MM:SS]. Только русский JSON. "
        ),
    },
}
