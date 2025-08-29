from django.db import models

# Create your models here.
class Coag(models.Model):
    drugName = models.CharField(max_length=100, default='default')

    # 부제목을 추가
    subtitle = models.CharField(max_length=255, blank=True, null=True)

    nx_hold_b_p = models.TextField(default='default')
    nx_restart_a_p = models.TextField(default='default')
    nx_hold_b_c = models.TextField(default='default')
    nx_restart_a_c = models.TextField(default='default')

    db_hold_b_p = models.TextField(default='default')
    db_restart_a_p = models.TextField(default='default')
    db_hold_b_c = models.TextField(default='default')
    db_restart_a_c = models.TextField(default='default')

    sp_hold_b_p = models.TextField(default='default')
    sp_restart_a_p = models.TextField(default='default')
    sp_hold_b_c = models.TextField(default='default')
    sp_restart_a_c = models.TextField(default='default')

    ap_hold_b_p = models.TextField(default='default')
    ap_restart_a_p = models.TextField(default='default')
    ap_hold_b_c = models.TextField(default='default')
    ap_restart_a_c = models.TextField(default='default')

    def __str__(self):
        return self.drugName
