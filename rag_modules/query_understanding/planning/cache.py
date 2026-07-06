"""Thread-safe query-plan cache and single-flight coordination."""

from __future__ import annotations

import threading
from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy

from ...contracts import QueryPlan


class QueryPlannerCache:
    def __init__(self) -> None:
        self._cache: "OrderedDict[str, QueryPlan]" = OrderedDict()
        self._cache_lock = threading.Lock()
        self._inflight: dict[str, Future[QueryPlan]] = {}

    def remember(self, cache_key: str, plan: QueryPlan, *, cache_size: int) -> None:
        if not cache_size or not cache_key:
            return
        snapshot = deepcopy(plan)
        snapshot.used_cache = False
        with self._cache_lock:
            self._cache[cache_key] = snapshot
            self._cache.move_to_end(cache_key)
            while len(self._cache) > cache_size:
                self._cache.popitem(last=False)

    def cached_plan(self, cache_key: str, *, cache_size: int) -> QueryPlan | None:
        if not cache_size or not cache_key:
            return None
        with self._cache_lock:
            plan = self._cache.get(cache_key)
            if plan is None:
                return None
            self._cache.move_to_end(cache_key)
            return deepcopy(plan)

    def claim_planning(self, cache_key: str) -> tuple[Future[QueryPlan], bool]:
        if not cache_key:
            return Future(), True
        with self._cache_lock:
            future = self._inflight.get(cache_key)
            if future is not None:
                return future, False
            future = Future()
            self._inflight[cache_key] = future
            return future, True

    def release_planning(
        self,
        cache_key: str,
        future: Future[QueryPlan],
    ) -> None:
        if not cache_key:
            return
        with self._cache_lock:
            if self._inflight.get(cache_key) is future:
                self._inflight.pop(cache_key, None)


__all__ = ["QueryPlannerCache"]
