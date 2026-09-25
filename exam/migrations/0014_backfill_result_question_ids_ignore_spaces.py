"""0013 에서 못 채운 옛 응시 기록의 문제 ID를 한 번 더 채운다.

0013 이후에도 비어 있던 1,300여 개는 대부분 그 뒤에 문제 지문의 띄어쓰기·줄바꿈만 바뀐 경우였다
('문1.' → '문 1.'). 이번에는 공백을 모두 지운 지문끼리 비교한다. 같은 시험의 문제를 먼저 찾는다.
"""
import re

from django.db import migrations
from django.utils.html import strip_tags

_SPACES = re.compile(r"\s+")


def _compact(text):
    return _SPACES.sub("", strip_tags(str(text or "")))


def _index(questions):
    exact, prefix40 = {}, {}
    for q in questions:
        text = _compact(q.question_text)
        if len(text) < 10:
            continue
        info = (q.id, q.category.name if q.category_id else "N/A")
        exact.setdefault(text, info)
        prefix40.setdefault(text[:40], info)
    return exact, prefix40


def _find(text, indexes):
    exact, prefix40 = indexes
    return exact.get(text) or (prefix40.get(text[:40]) if len(text) >= 40 else None)


def backfill(apps, schema_editor):
    Question = apps.get_model("exam", "Question")
    ExamResult = apps.get_model("exam", "ExamResult")

    questions = list(Question.objects.select_related("category").all())
    everything = _index(questions)
    by_exam = {}
    for q in questions:
        by_exam.setdefault(q.exam_id, []).append(q)
    per_exam = {exam_id: _index(qs) for exam_id, qs in by_exam.items()}

    for result in ExamResult.objects.all().iterator():
        details = result.detailed_results
        if not isinstance(details, list):
            continue
        changed = False
        for detail in details:
            if not isinstance(detail, dict) or detail.get("question_id"):
                continue
            text = _compact(detail.get("question"))
            if len(text) < 10:
                continue
            info = None
            if result.exam_id in per_exam:
                info = _find(text, per_exam[result.exam_id])
            info = info or _find(text, everything)
            if info:
                detail["question_id"] = info[0]
                if not detail.get("category") or detail.get("category") == "N/A":
                    detail["category"] = info[1]
                changed = True
        if changed:
            ExamResult.objects.filter(pk=result.pk).update(detailed_results=details)


class Migration(migrations.Migration):

    dependencies = [
        ("exam", "0013_backfill_result_question_ids"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
