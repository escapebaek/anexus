"""예전 응시 기록(detailed_results)에 빠진 문제 ID를 한 번만 채운다.

예전에는 브라우저가 문제 '지문 텍스트'만 보내서, 결과를 볼 때마다 전체 문제를 텍스트로
다시 찾았다. 이제는 문제 ID로 저장하므로 옛 기록도 ID를 채워 두고 텍스트 검색을 없앤다.
같은 시험의 문제를 먼저 찾고, 못 찾으면 전체 문제에서 찾는다.
"""
from django.db import migrations
from django.utils.html import strip_tags


def _norm(text):
    return " ".join(strip_tags(str(text or "")).split())


def _index(questions):
    exact, prefix50, prefix20 = {}, {}, {}
    for q in questions:
        text = _norm(q.question_text)
        if not text:
            continue
        info = (q.id, q.category.name if q.category_id else "N/A")
        exact.setdefault(text, info)
        prefix50.setdefault(text[:50], info)
        if len(text) >= 20:
            prefix20.setdefault(text[:20], info)
    return exact, prefix50, prefix20


def _find(text, indexes):
    exact, prefix50, prefix20 = indexes
    return (exact.get(text) or prefix50.get(text[:50])
            or (prefix20.get(text[:20]) if len(text) >= 20 else None))


def backfill(apps, schema_editor):
    Question = apps.get_model("exam", "Question")
    ExamResult = apps.get_model("exam", "ExamResult")

    questions = list(Question.objects.select_related("category").all())
    everything = _index(questions)
    per_exam = {}
    for q in questions:
        per_exam.setdefault(q.exam_id, []).append(q)
    per_exam = {exam_id: _index(qs) for exam_id, qs in per_exam.items()}

    for result in ExamResult.objects.all().iterator():
        details = result.detailed_results
        if not isinstance(details, list):
            continue
        changed = False
        for detail in details:
            if not isinstance(detail, dict) or detail.get("question_id"):
                continue
            text = _norm(detail.get("question"))
            if not text:
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
        ("exam", "0012_add_is_special_to_exam"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
