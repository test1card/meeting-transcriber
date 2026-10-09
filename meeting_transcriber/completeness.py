"""Evidence for coverage, never a claim of reference-text accuracy."""
import math
import re


def union_intervals(intervals):
    result = []
    for start, end in sorted(intervals):
        if not all(math.isfinite(v) for v in (start, end)) or end <= start:
            raise ValueError("Invalid interval")
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


def uncovered_intervals(speech, transcript):
    covered = union_intervals(transcript)
    missing = []
    for start, end in union_intervals(speech):
        cursor = start
        for left, right in covered:
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                missing.append([cursor, min(left, end)])
            cursor = max(cursor, right)
            if cursor >= end:
                break
        if cursor < end:
            missing.append([cursor, end])
    return missing


def normalize_words(text):
    return re.findall(r"[а-яёa-z0-9]+", text.lower().replace("ё", "е"))


def owned_word(word, window_start, core_start, core_end):
    """Assign overlapping-window words by midpoint; retain unknown timing separately."""
    start, end = word["timestamp"]
    if start is None or end is None or end < start:
        return None
    start, end = window_start + float(start), window_start + float(end)
    if not core_start <= (start + end) / 2 < core_end:
        return None
    return {"start": start, "end": end, "text": word["text"]}
