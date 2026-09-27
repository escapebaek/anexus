from django.db import models


class DailyVisit(models.Model):
    """하루 방문 수. 방문 = 같은 브라우저에서 30분 넘게 쉬었다가 다시 들어온 것 (anhub.middleware.VisitCounterMiddleware)."""
    date = models.DateField(unique=True)
    count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.date}: {self.count}"
