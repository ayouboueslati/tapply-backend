from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text
from app.db.session import SessionLocal

def purge_old_data():
    """
    Deletes submissions older than the organization's retention_days.
    This runs daily.
    """
    print("Running data retention purge job...")
    with SessionLocal() as db:
        # We find submissions where created_at is older than retention_days
        # Using Postgres interval logic
        try:
            result = db.execute(text("""
                DELETE FROM submissions
                USING organizations
                WHERE submissions.org_id = organizations.id
                  AND submissions.created_at < NOW() - (organizations.retention_days || ' days')::interval
                RETURNING submissions.id
            """))
            deleted_count = result.rowcount
            db.commit()
            print(f"Purged {deleted_count} old submissions.")
        except Exception as e:
            print(f"Error purging old data: {e}")
            db.rollback()

scheduler = BackgroundScheduler()
scheduler.add_job(purge_old_data, 'cron', hour=2, minute=0) # Run daily at 2 AM

def start_jobs():
    scheduler.start()

def shutdown_jobs():
    scheduler.shutdown()
