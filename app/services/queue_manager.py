import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any
from app.db.database import BaseRepository
from app.schemas.queue import QueuePayloadSchema

class QueueRepository(BaseRepository):
    async def enqueue(self, queue_name: str, payload: QueuePayloadSchema):
        query = """
            INSERT INTO task_queue (shop_id, queue_name, payload, correlation_id, status)
            VALUES ($1, $2, $3, $4, 'pending')
        """
        await self.execute(query, payload.shop_id, queue_name, payload.model_dump_json(), payload.correlation_id)

    async def fetch_job(self, queue_name: str, worker_id: str) -> Optional[Dict[str, Any]]:
        query = """
            UPDATE task_queue SET 
                status='processing', 
                worker_id=$2, 
                started_at=NOW(), 
                heartbeat=NOW()
            WHERE id = (
                SELECT id FROM task_queue 
                WHERE status IN ('pending', 'retrying') 
                AND queue_name = $1
                AND retry_count < 5
                ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED
            ) RETURNING *
        """
        return await self.fetch_one(query, queue_name, worker_id)

    async def mark_completed(self, job_id: int):
        query = """
            UPDATE task_queue SET 
                status='completed', 
                completed_at=NOW(), 
                duration_ms = (EXTRACT(EPOCH FROM NOW()) - EXTRACT(EPOCH FROM started_at)) * 1000
            WHERE id = $1
        """
        await self.execute(query, job_id)

    async def mark_failed(self, job_id: int, error: str, can_retry: bool = True):
        status = 'retrying' if can_retry else 'dead_letter'
        query = """
            UPDATE task_queue SET 
                status=$2, 
                retry_count=retry_count + 1, 
                error_message=$3, 
                heartbeat=NULL 
            WHERE id = $1
        """
        await self.execute(query, job_id, status, error)

class QueueManager:
    def __init__(self, repo: QueueRepository, worker_id: str):
        self.repo = repo
        self.worker_id = worker_id

    async def push(self, queue_name: str, payload: QueuePayloadSchema):
        await self.repo.enqueue(queue_name, payload)

    async def pop(self, queue_name: str) -> Optional[Dict[str, Any]]:
        return await self.repo.fetch_job(queue_name, self.worker_id)

    async def complete(self, job_id: int):
        await self.repo.mark_completed(job_id)

    async def fail(self, job_id: int, error: str, can_retry: bool = True):
        await self.repo.mark_failed(job_id, error, can_retry)
