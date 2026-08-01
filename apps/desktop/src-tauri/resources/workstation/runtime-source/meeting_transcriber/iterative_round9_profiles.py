from __future__ import annotations

from typing import Final

from meeting_transcriber.iterative_profiles import ITERATIVE_PROMPTS


ROUND9_PROMPTS: Final[dict[str, dict[str, str]]] = {
    "p8_gemma31_numeric_deadline_audit": {
        "label": "Gemma 31B iteration 3: preserve P7 coverage, audit numbers and deadlines",
        "extract": ITERATIVE_PROMPTS["p7_gemma31_coverage_repair"]["extract"],
        "synthesize": (
            "Сохрани удачную структуру предыдущего варианта: одна agenda, 10–14 конкретных "
            "discussed и 2–3 материальных resolved. Покрой мощность и сетевую заявку; сроки "
            "испытаний; габариты, массу, ворота, фундамент, вентиляцию и кран; договорную "
            "привязку Пущино и последствия переноса; капремонт против реконструкции; ПСД и "
            "финансирование. Каждый пункт должен оставаться самостоятельным проверяемым фактом. "
            "Проведи числовой аудит: копируй значение и единицу из одного source extract "
            "буквально; не объединяй противоречивые варианты в новый диапазон и не складывай "
            "числа. Если источник противоречив, опусти спорную цифру, сохранив качественный факт. "
            "Evidence копируй из того же source item, который содержит ключевой факт. "
            "Принудительно attendees=[]; у всех resolved owner=\"unspecified\" и "
            "due=\"unspecified\". Дата 17 августа — дата следующего совещания, а не срок "
            "поручений; не помещай её в due. Оставь только действия по уточнению мощности/"
            "сетевого подключения и оценке реконструкционных работ. Исключи подготовку "
            "протокола, командировочные, домашние задания и риторику. notes=[]. Только русский "
            "JSON; каждый evidence — один [HH:MM:SS]. "
        ),
    },
}