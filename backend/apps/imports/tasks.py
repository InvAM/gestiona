from celery import shared_task


@shared_task(acks_late=False, ignore_result=True)
def run_import(job_id: int) -> None:
    # acks_late=False: a long import must not be re-run from scratch if the worker restarts;
    # the job stays "running" and an admin can relaunch it.
    from .jira_importer import run_job

    run_job(job_id)
