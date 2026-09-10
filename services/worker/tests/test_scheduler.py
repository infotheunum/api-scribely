from __future__ import annotations

from worker_app.scheduler import build_scheduler


def test_build_scheduler_registers_poll_and_cluster_jobs():
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "poll_pipeline" in job_ids
    assert "cluster_dedup" in job_ids
    assert "theunum_categories_sync" in job_ids

    cluster_job = scheduler.get_job("cluster_dedup")
    assert cluster_job is not None
    assert cluster_job.max_instances == 1
