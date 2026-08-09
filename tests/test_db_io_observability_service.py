from app.services.db_io_observability_service import render_db_io_metrics


def test_db_io_render_includes_required_metrics():
    text = render_db_io_metrics({"sender_backlog": 2, "notification_backlog_oldest_age_seconds": 300, "scrape_job_backlog_oldest_age_seconds": 120, "approx_io_churn": 9, "top_tables": [("scrape_jobs", 5)], "recent_24h": [("source_runs", 3)], "notifications_by_status": {"queued": 2}, "scrape_jobs_by_status": {"queued": 1}, "source_runs_24h": {"ok": 1}})
    assert "Sender backlog: 2" in text
    assert "notifications pendentes: 2" in text
    assert "Idade backlog notifications: 300s" in text
    assert "Idade backlog scrape_jobs: 120s" in text
    assert "scrape_jobs por status" in text
    assert "source_runs últimas 24h" in text


def test_io_migration_has_priority_indexes():
    content = open("migrations/versions/p0_03_supabase_io_indexes.py", encoding="utf-8").read()
    assert "ix_scrape_jobs_status_created" in content
    assert "ix_source_runs_created_status" in content
    assert "ix_wishlist_activity_created_status" in content
