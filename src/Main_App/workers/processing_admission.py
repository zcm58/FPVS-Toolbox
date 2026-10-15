"""Live file admission for the normal EEG process pool, without GUI state."""

from __future__ import annotations

from queue import Empty

from Main_App.workers.processing_resource_budget import build_processing_estimate
from Main_App.workers.review_resource_budget import (
    ReviewMemoryProbeError,
    memory_admission_fits,
    probe_memory_snapshot,
    probe_owned_memory,
    single_review_capacity_bytes,
)


class ProcessingAdmission:
    """Reserve whole-file credits, persistent worker floors and one fallback.

    Only PID/creation-time matched workers earn resident/private memory credit.
    A source-rate fallback borrows the single emergency reserve until its file
    completes. Uncharacterized files retain an exclusive native execution path.
    """

    def __init__(self, files, settings, event_map, context):
        self.estimates = tuple(build_processing_estimate(path, settings, event_map) for path in files)
        snapshot = self.snapshot()
        self.exclusive = tuple(
            estimate is None
            or single_review_capacity_bytes(snapshot, estimate.healthy_bytes) > snapshot.total_bytes
            for estimate in self.estimates
        )
        self.credits = tuple(
            0 if exclusive else estimate.healthy_bytes
            for estimate, exclusive in zip(self.estimates, self.exclusive, strict=True)
        )
        self.events = context.Queue()
        self.grant_events = tuple(context.Event() for _ in files)
        self.grant_status = context.Array("b", len(files), lock=False)
        self.cancel_event = context.Event()
        self.active = {}
        self.workers = {}
        self.requests = {}
        self.emergency_owner = None
        self.solo_owner = None
        self.population = 0

    @staticmethod
    def snapshot():
        snapshot = probe_memory_snapshot()
        if (type(snapshot.total_bytes) is not int or snapshot.total_bytes <= 0
                or type(snapshot.physical_available_bytes) is not int
                or not 0 <= snapshot.physical_available_bytes <= snapshot.total_bytes
                or (snapshot.commit_required and type(snapshot.commit_available_bytes) is not int)
                or (snapshot.commit_available_bytes is not None and snapshot.commit_available_bytes < 0)):
            raise ReviewMemoryProbeError("Live processing RAM/Windows commit headroom is unavailable.")
        return snapshot

    def initializer_args(self):
        return (self.events, self.grant_events, self.grant_status, self.cancel_event,
                self.estimates, self.exclusive)

    def drain(self):
        while True:
            try:
                message = self.events.get_nowait()
            except Empty:
                return
            index = message.get("index")
            if type(index) is not int or not 0 <= index < len(self.estimates):
                raise ReviewMemoryProbeError("Invalid processing memory-control job identity.")
            if message.get("type") == "started":
                self.workers[int(message["pid"])] = (float(message["created"]), index)
            elif message.get("type") == "request":
                self.requests[index] = message.get("required_bytes")
            else:
                raise ReviewMemoryProbeError("Invalid processing memory-control message.")

    def fits(self, index=None, *, population=None, solo=False, granting=None, snapshot=None):
        self.drain()
        snapshot = self.snapshot() if snapshot is None else snapshot
        population = self.population if population is None else population
        credits = dict(self.active)
        if granting is not None:
            credits[granting[0]] = granting[1]
        indices = set(credits)
        if index is not None:
            indices.add(index)
        if any(self.exclusive[item] for item in indices) and len(indices) > 1:
            return False
        if self.solo_owner is not None and indices - {self.solo_owner}:
            return False
        reserve = 0 if solo else max((
            self.estimates[item].emergency_extra_bytes
            for item in indices
            if not self.exclusive[item] and item != self.solo_owner
        ), default=0)
        owner = granting[0] if granting is not None else self.emergency_owner
        if owner is not None:
            reserve = max(0, reserve - max(0, credits[owner] - self.credits[owner]))
        active_owned, idle_owned = {}, []
        for pid, (created, item) in tuple(self.workers.items()):
            owned = probe_owned_memory(pid, created)
            if owned.uss_bytes is None and owned.private_commit_bytes is None:
                continue
            if item in credits:
                active_owned[item] = owned
            else:
                idle_owned.append(owned)
        # A reused worker can already be running the next file while its new
        # start message is still in transit. Until all active identities are
        # known, no apparent idle process earns credit against an idle floor.
        if len(active_owned) < len(credits):
            idle_owned = []
        return memory_admission_fits(
            snapshot, active_credits=credits, active_owned=active_owned,
            idle_owned=idle_owned, worker_count=population,
            candidate_credit=0 if index is None else self.credits[index],
            emergency_reserve=reserve,
        )

    def next_population(self, index, ceiling):
        """Choose only for an empty/drained pool; never resize active workers."""
        self.solo_owner = None
        if self.exclusive[index]:
            return (1, True) if self.fits(index, population=1, solo=True) else (0, False)
        for population in range(ceiling, 0, -1):
            if self.fits(index, population=population):
                return population, False
        # A healthy file need not reserve an impossible hypothetical fallback.
        if self.fits(index, population=1, solo=True):
            return 1, True
        return 0, False

    def submitted(self, index):
        self.active[index] = self.credits[index]

    def completed(self, index):
        self.active.pop(index, None)
        self.requests.pop(index, None)
        if self.emergency_owner == index:
            self.emergency_owner = None
        if self.solo_owner == index:
            self.solo_owner = None

    def reset_pool(self, population, solo_index=None):
        if self.active:
            raise RuntimeError("Cannot resize a processing pool with active files.")
        self.drain()
        self.workers.clear()
        self.population = population
        self.solo_owner = solo_index

    def grant_waiting(self):
        self.drain()
        for index, required in tuple(self.requests.items()):
            if index not in self.active:
                raise ReviewMemoryProbeError("Processing memory request has no active file.")
            estimate = self.estimates[index]
            status = 0
            if (type(required) is not int or required <= 0 or estimate is None
                    or required > estimate.healthy_bytes + estimate.emergency_extra_bytes):
                status = -1
            elif required <= self.active[index]:
                status = 1
            elif self.emergency_owner not in (None, index):
                continue
            else:
                snapshot = self.snapshot()
                if single_review_capacity_bytes(snapshot, required) > snapshot.total_bytes:
                    status = -2
                elif self.fits(granting=(index, required), snapshot=snapshot):
                    self.active[index] = required
                    self.emergency_owner = index
                    status = 1
            if status:
                self.grant_status[index] = status
                self.grant_events[index].set()
                del self.requests[index]

    def close(self):
        self.cancel_event.set()
        self.events.close()
        self.events.cancel_join_thread()


class ProcessingWorkerAdmission:
    """One child's phase barriers; no settings, EEG values or results mutate."""

    def __init__(self, events, grants, statuses, cancelled, estimates, exclusive):
        self.events, self.grants, self.statuses = events, grants, statuses
        self.cancelled, self.estimates, self.exclusive = cancelled, estimates, exclusive
        self.index = None
        self.credit = 0
        events.cancel_join_thread()

    def start(self, index):
        import os
        import psutil

        self.index = index
        estimate = self.estimates[index]
        self.credit = estimate.healthy_bytes if estimate is not None else 0
        self.events.put({"type": "started", "index": index, "pid": os.getpid(),
                         "created": psutil.Process().create_time()})

    def request(self, required):
        index = self.index
        if index is None or self.exclusive[index] or required <= self.credit:
            return
        self.statuses[index] = 0
        self.grants[index].clear()
        self.events.put({"type": "request", "index": index, "required_bytes": required})
        while not self.cancelled.is_set():
            if self.grants[index].wait(0.1):
                status = self.statuses[index]
                if status == 1:
                    self.credit = required
                    return
                if status == -2:
                    raise MemoryError("Actual processing phase plus worker/host reserve exceeds physical RAM.")
                raise MemoryError("Actual processing phase exceeds its validated memory reservation.")
        raise InterruptedError("Processing cancelled while awaiting memory admission.")

    def before_kurtosis(self, *shape):
        import math
        from Main_App.workers.review_resource_budget import actual_scoring_bytes

        if self.index is not None and not self.exclusive[self.index]:
            estimate = self.estimates[self.index]
            geometry = estimate.geometry
            target_samples = math.ceil(
                geometry.source_n_times * geometry.target_rate_hz / geometry.source_rate_hz)
            # Repairs and cache publication follow scoring before the tail
            # barrier. Source-rate fallback therefore needs its complete file
            # credit now, even when kurtosis alone fits the healthy reservation.
            prefix = (estimate.fullrate_bytes
                      if shape[1] == geometry.source_n_times or shape[1] > target_samples
                      else estimate.healthy_bytes)
            self.request(max(prefix, actual_scoring_bytes(*shape)))

    def before_tail(self, raw):
        if self.index is not None and not self.exclusive[self.index]:
            estimate = self.estimates[self.index]
            self.request(estimate.tail_bytes(len(raw.ch_names), int(raw.n_times), float(raw.info["sfreq"])))

    def before_finish(self, raw):
        """Always guard repairs/cache publication, including disabled kurtosis."""
        if self.index is not None and not self.exclusive[self.index]:
            estimate = self.estimates[self.index]
            actual_tail = estimate.tail_bytes(len(raw.ch_names), int(raw.n_times), float(raw.info["sfreq"]))
            required = (estimate.fullrate_bytes
                        if float(raw.info["sfreq"]) == estimate.geometry.source_rate_hz
                        else estimate.healthy_bytes)
            self.request(max(required, actual_tail))
