from typing import List, Optional, Dict, Any
from app.db.database import BaseRepository

class DeadLetterRepository(BaseRepository):
    async def list_dead_jobs(self, queue_name: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM task_queue WHERE status = 'dead_letter' AND shop_id = $1"
        args = [self.shop_id]
        if queue_name:
            query += " AND queue_name = $2"
            args.append(queue_name)
        return await self.fetch_all(query, *args)

    async def retry_job(self, job_id: int):
        query = """
            UPDATE task_queue 
            SET status = 'retrying', retry_count = 0, error_message = NULL, started_at = NULL, completed_at = NULL
            WHERE id = $1 AND shop_id = $2 AND status = 'dead_letter'
        """
        await self.execute(query, job_id, self.shop_id)

    async def archive_job(self, job_id: int):
        query = "UPDATE task_queue SET status = 'archived' WHERE id = $1 AND shop_id = $2"
        await self.execute(query, job_id, self.shop_id)

class DeadLetterService:
    def __init__(self, repo: DeadLetterRepository):
        self.repo = repo

    async def get_all_dead_jobs(self, queue_name: Optional[str] = None):
        return await self.repo.list_dead_jobs(queue_name)

    async def recover_job(self, job_id: int):
        # Full audit trail is handled by the audit_logs table during the process
        await self.repo.retry_job(job_id)

    async def cleanup_job(self, job_id: int):
        await self.repo.archive_job(job_id)
