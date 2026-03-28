import asyncio
import logging
from contextlib import suppress
from typing import Any, Dict, Optional

from config import settings
from llm_gateway import LLMGateway

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("resource_scheduler")


class ResourceAwareScheduler:
    def __init__(self):
        self.gateway = LLMGateway(settings.REDIS_URL)
        self.shutdown_event = asyncio.Event()
        self.tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        await self.gateway.connect()
        scheduler_task = asyncio.create_task(self.schedule_loop())
        reaper_task = asyncio.create_task(self.reaper_loop())
        self.tasks.update({scheduler_task, reaper_task})
        try:
            await asyncio.gather(scheduler_task, reaper_task)
        finally:
            self.shutdown_event.set()
            for task in list(self.tasks):
                task.cancel()
            for task in list(self.tasks):
                with suppress(asyncio.CancelledError):
                    await task
            await self.gateway.close()

    async def schedule_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                scheduled = await self.schedule_once()
                runtime_state = await self.gateway.get_runtime_state()
                await self.gateway.report_scheduler_heartbeat({
                    "scheduled": scheduled,
                    "pending_total": sum(runtime_state["pending"].values()),
                    "targets": runtime_state["targets"],
                    "workers": runtime_state["workers"],
                })
                if not scheduled:
                    await asyncio.sleep(settings.SCHEDULER_LOOP_INTERVAL_SECONDS)
            except Exception:
                logger.exception("Scheduler loop failed")
                await asyncio.sleep(settings.SCHEDULER_LOOP_INTERVAL_SECONDS)

    async def schedule_once(self) -> int:
        workers = await self.gateway.list_active_workers()
        if not workers:
            return 0

        targets = {target["target_id"]: target for target in await self.gateway.list_active_targets()}
        if not targets:
            return 0

        active_pairs = {(worker.get("worker_pool"), worker.get("target_id")) for worker in workers}
        candidates = await self.gateway.list_pending_candidates(settings.SCHEDULER_QUEUE_SCAN_DEPTH)
        admitted = 0

        for queue_key, job in candidates:
            target = await self.pick_target(job, targets, active_pairs)
            if not target:
                continue
            if await self.gateway.try_admit_job(job["id"], queue_key, target):
                admitted += 1
        return admitted

    async def pick_target(
        self,
        job: Dict[str, Any],
        targets: Dict[str, Dict[str, Any]],
        active_pairs: set[tuple[Optional[str], Optional[str]]],
    ) -> Optional[Dict[str, Any]]:
        workload_class = job["workload_class"]
        worker_pool = job["worker_pool"]
        model_key = job["model_key"]
        eligible: list[tuple[tuple[Any, ...], Dict[str, Any]]] = []

        for target in targets.values():
            target_id = target["target_id"]
            if (worker_pool, target_id) not in active_pairs:
                continue

            usage = await self.gateway.get_target_usage(target_id)
            warm = model_key in set(target.get("loaded_models") or []) or model_key in set(target.get("pinned_models") or [])
            free_score = int(target.get("vram_free_mb") or target.get("ram_free_mb") or 0)
            score = (
                0 if warm else 1,
                usage["active_jobs"],
                -free_score,
                target_id,
            )
            eligible.append((score, target))

        if not eligible:
            return None
        eligible.sort(key=lambda item: item[0])
        return eligible[0][1]

    async def reaper_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                recovered = await self.gateway.requeue_stale_jobs()
                if recovered:
                    logger.warning("Recovered %s stale LLM jobs", recovered)
            except Exception:
                logger.exception("Stale-job reaper failed")
            await asyncio.sleep(settings.SCHEDULER_REAPER_INTERVAL_SECONDS)


async def main() -> None:
    scheduler = ResourceAwareScheduler()
    await scheduler.start()


if __name__ == "__main__":
    asyncio.run(main())

