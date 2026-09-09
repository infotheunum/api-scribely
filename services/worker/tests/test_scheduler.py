from __future__ import annotations

from worker_app.scheduler import DISPATCH_TICK_SECONDS, build_scheduler


def test_build_scheduler_registers_poll_cluster_and_dispatch_jobs():
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "poll_pipeline" in job_ids
    assert "cluster_dedup" in job_ids
    assert "dispatch_pipeline" in job_ids
    assert "theunum_categories_sync" in job_ids

    cluster_job = scheduler.get_job("cluster_dedup")
    assert cluster_job is not None
    assert cluster_job.max_instances == 1

    dispatch_job = scheduler.get_job("dispatch_pipeline")
    assert dispatch_job is not None
    assert dispatch_job.max_instances == 1
    assert dispatch_job.trigger.interval.total_seconds() == DISPATCH_TICK_SECONDS
