"""서버 채점.

브라우저는 "문제 ID → 고른 선택지 번호(1~5)"만 보내고, 정답 비교는 여기서 한다.
정답(correct_option)은 '다', '㉯', '가/가(GPT5)', '4.' 처럼 자유 형식이라
맨 앞의 선택지 기호를 번호로 바꿔 비교한다.
"""
from django.utils.html import strip_tags

OPTION_LABELS = ("가나다라마", "㉮㉯㉰㉱㉲", "12345", "①②③④⑤", "ABCDE")
OPTION_LETTERS = "ABCDE"
EMPTY_OPTION_VALUES = {"", "default"}
MAX_QUESTIONS_PER_RESULT = 2000


def is_blank_option(text):
    return (text or "").replace("​", "").strip().lower() in EMPTY_OPTION_VALUES


def answer_index(correct_option):
    """정답 문자열 → 선택지 번호(1~5). 정답이 없거나 '미정'이면 None (채점 제외)."""
    text = (correct_option or "").replace("​", "").replace("﻿", "").strip()
    text = text.lstrip("/ ").strip()
    if not text or text.lower() == "default" or text.startswith("미정"):
        return None
    first = text[0].upper()
    for labels in OPTION_LABELS:
        pos = labels.find(first)
        if pos >= 0:
            return pos + 1
    return None


def _selected_index(value):
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if 1 <= index <= 5 else None


def grade(questions, answers):
    """questions: 화면에 나온 순서대로의 Question 목록, answers: {문제ID(str): 선택지 번호}.
    반환: (개수 dict, 문제별 결과 list)"""
    counts = {"correct": 0, "incorrect": 0, "unanswered": 0, "noanswer": 0}
    details = []
    for question in questions:
        selected = _selected_index(answers.get(str(question.id)))
        correct = answer_index(question.correct_option)
        if correct is None:
            result = "noanswer"
        elif selected is None:
            result = "unanswered"
        elif selected == correct:
            result = "correct"
        else:
            result = "incorrect"
        counts[result] += 1
        details.append({
            "question_id": question.id,
            "question": " ".join(strip_tags(question.question_text).split()),
            "selected": selected,
            "selected_answer": getattr(question, f"option{selected}") if selected else "",
            "correct_answer": question.correct_option or "",
            "result": result,
            "category": question.category.name if question.category else "N/A",
        })
    return counts, details
