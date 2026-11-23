from celery import shared_task


@shared_task(ignore_result=True)
def prune_audit():
    from .services import prune

    prune()
