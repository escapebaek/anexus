from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Paper


@receiver(post_delete, sender=Paper)
def delete_pdf_from_storage(sender, instance, **kwargs):
    """
    Remove the PDF from Backblaze B2 whenever a Paper row is deleted,
    whether directly, via a queryset .delete(), or cascaded from deleting
    its Issue/Journal. Without this, B2 keeps billing for files whose
    database rows no longer exist.
    """
    if instance.pdf_file:
        instance.pdf_file.storage.delete(instance.pdf_file.name)
