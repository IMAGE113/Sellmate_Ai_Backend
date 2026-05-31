import logging
from datetime import datetime
from app.db.database import BaseRepository

class WorkerMonitorRepository(BaseRepository):
    async def update_heartbeat(self, worker_id: str, active_jobs: int):
        query = """
            INSERT INTO worker_health (worker_id, last_heartbeat, active_jobs)
            VALUES ($1, NOW(), $2)
            ON CONFLICT (worker_id) DO UPDATE SET
            last_heartbeat = EXCLUDED.last_heartbeat,
            active_jobs = EXCLUDED.active_jobs,
            status = 'active'
        """
        await self.execute(query, worker_id, active_jobs)

    async def detect_crashed_workers(self, timeout_seconds: int = 90):
        query = """
            UPDATE worker_health SET status = 'crashed'
            WHERE last_heartbeat < NOW() - $1 * INTERVAL '1 second'
            AND status = 'active'
            RETURNING worker_id
        """
        return await self.fetch_all(query, timeout_seconds)

    async def recover_stale_jobs(self):
        query = """
            UPDATE task_queue SET status = 'retrying', worker_id = NULL
            WHERE status = 'processing'
            AND worker_id IN (SELECT worker_id FROM worker_health WHERE status = 'crashed')
        """
        await self.execute(query)

class WorkerMonitor:
    def __init__(self, repo: WorkerMonitorRepository):
        self.repo = repo

    async def heartbeat(self, worker_id: str, active_jobs: int):
        await self.repo.update_heartbeat(worker_id, active_jobs)

    async def run_recovery(self):
        crashed = await self.repo.detect_crashed_workers()
        if crashed:
            logging.warning(f"Detected {len(crashed)} crashed workers. Recovering jobs...")
            await self.repo.recover_stale_jobs()
