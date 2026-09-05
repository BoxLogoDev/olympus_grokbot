"""Durable, single-host LOCAL_SIMULATION journal using only Python's stdlib.

Identities and review assertions are fixture inputs, not authentication. This
module never calls models/tools, issues approvals, or certifies production
readiness. Project/task identities are immutable; dynamic retry cards are not
supported. An interrupted RUNNING/UNKNOWN attempt cannot be started again until
an independent simulation reviewer explicitly reconciles its outcome.
"""

from contextlib import contextmanager
import hashlib
import json
import re
import sqlite3
import uuid


class LedgerError(ValueError):
    """A simulation contract or state transition was rejected."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise LedgerError(message)


def units(value, name):
    require(type(value) is int and value >= 0, f"{name} must be a nonnegative integer")
    return value


SCHEMA = """
CREATE TABLE IF NOT EXISTS actors (
    id TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('WORKER','REVIEWER'))
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, spec TEXT NOT NULL, workflow_version TEXT NOT NULL,
    policy_version TEXT NOT NULL, policy_commit TEXT NOT NULL,
    budget_limit INTEGER NOT NULL, spent INTEGER NOT NULL DEFAULT 0,
    reserved INTEGER NOT NULL DEFAULT 0, concurrency_limit INTEGER NOT NULL,
    review_limit INTEGER NOT NULL,
    CHECK(spent >= 0 AND reserved >= 0 AND spent + reserved <= budget_limit)
);
CREATE TABLE IF NOT EXISTS tasks (
    project_id TEXT NOT NULL REFERENCES projects(id), id TEXT NOT NULL,
    lineage_id TEXT NOT NULL UNIQUE, owner TEXT NOT NULL REFERENCES actors(id),
    reviewer TEXT NOT NULL REFERENCES actors(id), input TEXT NOT NULL,
    output_schema TEXT NOT NULL, done_when TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'READY', generation INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0, current_attempt TEXT,
    PRIMARY KEY(project_id,id)
);
CREATE TABLE IF NOT EXISTS dependencies (
    project_id TEXT NOT NULL, task_id TEXT NOT NULL, dependency_id TEXT NOT NULL,
    PRIMARY KEY(project_id,task_id,dependency_id),
    FOREIGN KEY(project_id,task_id) REFERENCES tasks(project_id,id),
    FOREIGN KEY(project_id,dependency_id) REFERENCES tasks(project_id,id)
);
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, task_id TEXT NOT NULL,
    lineage_id TEXT NOT NULL, generation INTEGER NOT NULL, revision INTEGER NOT NULL,
    input_digest TEXT NOT NULL, status TEXT NOT NULL,
    reservation INTEGER NOT NULL, actual_cost INTEGER,
    result TEXT, result_digest TEXT,
    FOREIGN KEY(project_id,task_id) REFERENCES tasks(project_id,id)
);
CREATE TABLE IF NOT EXISTS leases (
    owner TEXT PRIMARY KEY REFERENCES actors(id), project_id TEXT NOT NULL,
    task_id TEXT NOT NULL, attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id)
);
CREATE TABLE IF NOT EXISTS failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT, lineage_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL REFERENCES attempts(id), failure_key TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id),
    reviewer TEXT NOT NULL, accepted INTEGER NOT NULL, evidence TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    project_id TEXT, task_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS reviews_no_update BEFORE UPDATE ON reviews
BEGIN SELECT RAISE(ABORT,'reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS reviews_no_delete BEFORE DELETE ON reviews
BEGIN SELECT RAISE(ABORT,'reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS failures_no_update BEFORE UPDATE ON failures
BEGIN SELECT RAISE(ABORT,'failures are append-only'); END;
CREATE TRIGGER IF NOT EXISTS failures_no_delete BEFORE DELETE ON failures
BEGIN SELECT RAISE(ABORT,'failures are append-only'); END;
"""


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = FULL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    @contextmanager
    def _transaction(self, read_only=False):
        self.db.execute("BEGIN" if read_only else "BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _event(self, project, task, kind, **payload):
        self.db.execute(
            "INSERT INTO events(project_id,task_id,kind,payload) VALUES(?,?,?,?)",
            (project, task, kind, canonical(dict(mode="LOCAL_SIMULATION", **payload))),
        )

    def _actor(self, actor, role):
        row = self.db.execute("SELECT role FROM actors WHERE id=?", (actor,)).fetchone()
        require(row is not None and row["role"] == role, f"registered simulation {role} required")

    def register_actor(self, actor, role):
        require(isinstance(actor, str) and bool(actor.strip()), "actor id required")
        require(role in ("WORKER", "REVIEWER"), "invalid simulation role")
        with self._transaction():
            prior = self.db.execute("SELECT role FROM actors WHERE id=?", (actor,)).fetchone()
            if prior:
                require(prior["role"] == role, "actor roles are immutable")
                return
            self.db.execute("INSERT INTO actors VALUES(?,?)", (actor, role))
            self._event(None, None, "ACTOR_REGISTERED", actor=actor, role=role)

    def create_workflow(self, spec):
        """Register one fixed DAG. Schema describes simulated result fields only."""
        require(spec.get("mode") == "LOCAL_SIMULATION", "only LOCAL_SIMULATION is supported")
        for key in ("project_id", "workflow_version", "policy_version", "policy_commit"):
            require(isinstance(spec.get(key), str) and bool(spec[key].strip()), f"{key} required")
        require(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", spec["policy_commit"]) is not None,
                "policy_commit must be an immutable full commit hash")
        budget = units(spec.get("budget_units"), "budget_units")
        concurrency = units(spec.get("concurrency_limit"), "concurrency_limit")
        review_limit = units(spec.get("review_limit", concurrency), "review_limit")
        require(concurrency > 0 and review_limit > 0, "limits must be positive")
        tasks = spec.get("tasks")
        require(isinstance(tasks, list) and bool(tasks), "tasks required")
        ids = [t.get("id") for t in tasks]
        require(all(isinstance(i, str) and i.strip() for i in ids), "task ids required")
        require(len(ids) == len(set(ids)), "duplicate task id")
        deps = {}
        for task in tasks:
            require(task.get("action_kind") == "LOCAL_SIMULATION" and task.get("external_action") is False,
                    "external or unspecified actions are not supported")
            require(not task.get("retry_of_task_id"), "dynamic retry cards are not supported")
            require(isinstance(task.get("input"), dict), "task input object required")
            require(isinstance(task.get("done_when"), str) and task["done_when"].strip(), "done_when required")
            schema = task.get("output_schema")
            require(isinstance(schema, dict) and bool(schema), "nonempty output_schema required")
            require(all(isinstance(k, str) and v in ("str", "int", "float", "bool", "list", "dict")
                        for k, v in schema.items()), "unsupported output schema")
            require(task.get("owner") != task.get("reviewer"), "self-review is forbidden")
            d = task.get("dependencies", [])
            require(isinstance(d, list) and all(isinstance(x, str) for x in d), "invalid dependencies")
            require(len(d) == len(set(d)) and set(d) <= set(ids), "unknown or duplicate dependency")
            deps[task["id"]] = set(d)
        remaining = dict(deps)
        while remaining:
            ready = {k for k, v in remaining.items() if not v}
            require(bool(ready), "workflow must be acyclic")
            remaining = {k: v - ready for k, v in remaining.items() if k not in ready}
        project = spec["project_id"]
        with self._transaction():
            require(self.db.execute("SELECT 1 FROM projects WHERE id=?", (project,)).fetchone() is None,
                    "project already exists; cannot reset its history")
            for t in tasks:
                self._actor(t.get("owner"), "WORKER")
                self._actor(t.get("reviewer"), "REVIEWER")
            self.db.execute(
                "INSERT INTO projects(id,spec,workflow_version,policy_version,policy_commit,budget_limit,concurrency_limit,review_limit) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (project, canonical(spec), spec["workflow_version"], spec["policy_version"], spec["policy_commit"],
                 budget, concurrency, review_limit),
            )
            for t in tasks:
                self.db.execute(
                    "INSERT INTO tasks(project_id,id,lineage_id,owner,reviewer,input,output_schema,done_when,state) VALUES(?,?,?,?,?,?,?,?,?)",
                    (project, t["id"], canonical([project, t["id"]]), t["owner"], t["reviewer"], canonical(t["input"]),
                     canonical(t["output_schema"]), t["done_when"], "DRAFT" if deps[t["id"]] else "READY"),
                )
            for task, dependencies in deps.items():
                self.db.executemany("INSERT INTO dependencies VALUES(?,?,?)", [(project, task, d) for d in sorted(dependencies)])
            self._event(project, None, "WORKFLOW_REGISTERED", spec=spec, spec_digest=digest(spec))

    def _task(self, project, task):
        row = self.db.execute("SELECT * FROM tasks WHERE project_id=? AND id=?", (project, task)).fetchone()
        require(row is not None, "unknown task")
        return row

    def _attempt(self, attempt_id):
        row = self.db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        require(row is not None, "unknown attempt")
        return row

    def _refresh_ready(self, project):
        """Only reviewed dependency outputs satisfy the input portion of Ready."""
        tasks = self.db.execute("SELECT * FROM tasks WHERE project_id=? AND state IN ('DRAFT','READY')", (project,)).fetchall()
        for task in tasks:
            missing = self.db.execute(
                "SELECT 1 FROM dependencies d JOIN tasks t ON t.project_id=d.project_id AND t.id=d.dependency_id "
                "WHERE d.project_id=? AND d.task_id=? AND t.state!='DONE' LIMIT 1", (project, task["id"])
            ).fetchone()
            state = "DRAFT" if missing else "READY"
            if state != task["state"]:
                self.db.execute("UPDATE tasks SET state=? WHERE project_id=? AND id=?", (state, project, task["id"]))
                self._event(project, task["id"], "READINESS_CHANGED", previous_state=task["state"], next_state=state)

    def _limits(self, task):
        line = task["lineage_id"]
        total = self.db.execute("SELECT COUNT(*) FROM attempts WHERE lineage_id=?", (line,)).fetchone()[0]
        per_revision = self.db.execute("SELECT COUNT(*) FROM attempts WHERE lineage_id=? AND revision=?",
                                       (line, task["revision"])).fetchone()[0]
        repeated = self.db.execute("SELECT 1 FROM failures WHERE lineage_id=? GROUP BY failure_key HAVING COUNT(*)>=2", (line,)).fetchone()
        rejected = self.db.execute("SELECT COUNT(*) FROM reviews r JOIN attempts a ON a.id=r.attempt_id "
                                   "WHERE a.lineage_id=? AND r.accepted=0", (line,)).fetchone()[0]
        require(not repeated, "same failure occurred twice; manual escalation required")
        require(rejected < 3, "quality revision limit reached")
        require(total < 6, "lineage total attempt limit reached")
        require(per_revision < 2, "revision attempt limit reached")

    def start(self, project, task_id, owner, max_cost_units):
        reservation = units(max_cost_units, "max_cost_units")
        with self._transaction():
            task = self._task(project, task_id)
            self._actor(owner, "WORKER")
            require(task["owner"] == owner, "task belongs to another simulation worker")
            require(task["state"] == "READY", "task not READY; unresolved outcomes require reconciliation")
            self._limits(task)
            dependencies = self.db.execute(
                "SELECT t.*,a.result_digest FROM dependencies d JOIN tasks t "
                "ON t.project_id=d.project_id AND t.id=d.dependency_id "
                "LEFT JOIN attempts a ON a.id=t.current_attempt WHERE d.project_id=? AND d.task_id=?",
                (project, task_id),
            ).fetchall()
            require(all(d["state"] == "DONE" and d["result_digest"] for d in dependencies),
                    "all dependencies require independent accepted reviews")
            p = self.db.execute("SELECT * FROM projects WHERE id=?", (project,)).fetchone()
            require(p["spent"] + p["reserved"] + reservation <= p["budget_limit"], "project budget exhausted")
            count = self.db.execute("SELECT COUNT(*) FROM leases WHERE project_id=?", (project,)).fetchone()[0]
            require(count < p["concurrency_limit"], "project concurrency limit reached")
            review_count = self.db.execute("SELECT COUNT(*) FROM tasks WHERE project_id=? AND state='REVIEW'", (project,)).fetchone()[0]
            require(review_count < p["review_limit"], "review queue is full")
            require(self.db.execute("SELECT 1 FROM leases WHERE owner=?", (owner,)).fetchone() is None,
                    "simulation worker already owns another task")
            attempt = uuid.uuid4().hex
            input_digest = digest({"input": json.loads(task["input"]), "dependencies": {d["id"]: d["result_digest"] for d in dependencies}})
            self.db.execute(
                "INSERT INTO attempts(id,project_id,task_id,lineage_id,generation,revision,input_digest,status,reservation) VALUES(?,?,?,?,?,?,?,'RUNNING',?)",
                (attempt, project, task_id, task["lineage_id"], task["generation"], task["revision"], input_digest, reservation),
            )
            self.db.execute("INSERT INTO leases VALUES(?,?,?,?)", (owner, project, task_id, attempt))
            self.db.execute("UPDATE projects SET reserved=reserved+? WHERE id=?", (reservation, project))
            self.db.execute("UPDATE tasks SET state='RUNNING',current_attempt=? WHERE project_id=? AND id=?", (attempt, project, task_id))
            self._event(project, task_id, "ATTEMPT_STARTED", attempt_id=attempt, owner=owner,
                        generation=task["generation"], revision=task["revision"], input_digest=input_digest, reserved_units=reservation)
            return attempt

    def _validate_result(self, task, result):
        require(isinstance(result, dict) and result.get("simulation") is True, "result must identify itself as a simulation")
        types = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}
        for field, kind in json.loads(task["output_schema"]).items():
            require(field in result and type(result[field]) is types[kind], f"invalid result field: {field}")
        canonical(result)

    def _settle(self, attempt, actual_cost):
        cost = units(actual_cost, "actual_cost_units")
        require(cost <= attempt["reservation"], "actual cost exceeds reserved ceiling; reconcile cost evidence externally")
        self.db.execute("UPDATE projects SET reserved=reserved-?,spent=spent+? WHERE id=?",
                        (attempt["reservation"], cost, attempt["project_id"]))
        self.db.execute("UPDATE attempts SET actual_cost=? WHERE id=?", (cost, attempt["id"]))

    def _active(self, attempt_id, owner):
        attempt = self._attempt(attempt_id)
        task = self._task(attempt["project_id"], attempt["task_id"])
        require(task["owner"] == owner, "only assigned simulation worker can complete")
        require(attempt["status"] == "RUNNING" and task["state"] == "RUNNING" and task["current_attempt"] == attempt_id,
                "attempt is not active; unknown outcomes must be reconciled")
        require(task["generation"] == attempt["generation"], "stale attempt completion")
        return attempt, task

    def _stage(self, attempt, task, result, actual_cost):
        self._validate_result(task, result)
        self._settle(attempt, actual_cost)
        self.db.execute("UPDATE attempts SET status='STAGED',result=?,result_digest=? WHERE id=?",
                        (canonical(result), digest(result), attempt["id"]))
        self.db.execute("UPDATE tasks SET state='REVIEW' WHERE project_id=? AND id=?", (task["project_id"], task["id"]))
        self._event(task["project_id"], task["id"], "RESULT_STAGED", attempt_id=attempt["id"], result_digest=digest(result), actual_cost_units=actual_cost)

    def stage_result(self, attempt_id, owner, result, actual_cost_units):
        with self._transaction():
            attempt, task = self._active(attempt_id, owner)
            self._stage(attempt, task, result, actual_cost_units)

    def _record_failure(self, attempt, failure_key, source):
        require(isinstance(failure_key, str) and bool(failure_key.strip()), "stable failure_key required")
        self.db.execute("INSERT INTO failures(lineage_id,attempt_id,failure_key,source) VALUES(?,?,?,?)",
                        (attempt["lineage_id"], attempt["id"], failure_key, source))

    def _ready_or_blocked(self, task):
        try:
            self._limits(task)
            return "READY"
        except LedgerError:
            return "BLOCKED"

    def _fail(self, attempt, task, failure_key, actual_cost):
        self._record_failure(attempt, failure_key, "EXECUTION")
        self._settle(attempt, actual_cost)
        self.db.execute("UPDATE attempts SET status='FAILED' WHERE id=?", (attempt["id"],))
        self.db.execute("DELETE FROM leases WHERE attempt_id=?", (attempt["id"],))
        state = self._ready_or_blocked(task)
        self.db.execute("UPDATE tasks SET state=? WHERE project_id=? AND id=?", (state, task["project_id"], task["id"]))
        self._event(task["project_id"], task["id"], "ATTEMPT_FAILED", attempt_id=attempt["id"], failure_key=failure_key,
                    actual_cost_units=actual_cost, next_state=state)

    def fail(self, attempt_id, owner, failure_key, actual_cost_units):
        with self._transaction():
            attempt, task = self._active(attempt_id, owner)
            self._fail(attempt, task, failure_key, actual_cost_units)

    def review(self, project, task_id, reviewer, accepted, evidence, failure_key=None, *,
               expected_attempt_id, expected_result_digest):
        """Review exactly the attempt and result observed by the reviewer."""
        require(type(accepted) is bool, "accepted must be boolean")
        require(isinstance(evidence, str) and bool(evidence.strip()), "review evidence required")
        with self._transaction():
            task = self._task(project, task_id)
            self._actor(reviewer, "REVIEWER")
            require(task["reviewer"] == reviewer and task["owner"] != reviewer, "independent assigned reviewer required")
            require(task["state"] == "REVIEW", "task not awaiting review")
            require(task["current_attempt"] == expected_attempt_id, "stale review: attempt changed")
            attempt = self._attempt(task["current_attempt"])
            require(attempt["status"] == "STAGED" and attempt["generation"] == task["generation"], "stale review")
            require(attempt["result_digest"] == expected_result_digest, "stale review: result digest changed")
            self.db.execute("INSERT INTO reviews(attempt_id,reviewer,accepted,evidence) VALUES(?,?,?,?)",
                            (attempt["id"], reviewer, int(accepted), evidence))
            if accepted:
                state = "DONE"
            else:
                self._record_failure(attempt, failure_key, "REVIEW")
                if task["revision"] < 2:
                    self.db.execute("UPDATE tasks SET revision=revision+1 WHERE project_id=? AND id=?", (project, task_id))
                    state = self._ready_or_blocked(self._task(project, task_id))
                else:
                    state = "BLOCKED"
            self.db.execute("UPDATE attempts SET status=? WHERE id=?", ("ACCEPTED" if accepted else "REJECTED", attempt["id"]))
            self.db.execute("UPDATE tasks SET state=? WHERE project_id=? AND id=?", (state, project, task_id))
            self.db.execute("DELETE FROM leases WHERE attempt_id=?", (attempt["id"],))
            self._event(project, task_id, "SIMULATION_REVIEW", attempt_id=attempt["id"], reviewer=reviewer,
                        accepted=accepted, evidence=evidence, failure_key=failure_key, next_state=state,
                        result_digest=expected_result_digest,
                        production_verified=False, approval_issued=False)
            self._refresh_ready(project)

    def _affected(self, project, task_id):
        self._task(project, task_id)
        affected = {task_id}
        edges = self.db.execute("SELECT task_id,dependency_id FROM dependencies WHERE project_id=?", (project,)).fetchall()
        while True:
            added = {e["task_id"] for e in edges if e["dependency_id"] in affected} - affected
            if not added:
                return affected
            affected |= added

    def change_input(self, project, task_id, new_input, reason):
        """Invalidate only affected nodes; never delete artifacts/costs/counters."""
        require(isinstance(new_input, dict), "input object required")
        require(isinstance(reason, str) and reason.strip(), "change reason required")
        with self._transaction():
            target = self._task(project, task_id)
            require(canonical(new_input) != target["input"], "input did not change")
            affected = self._affected(project, task_id)
            for name in affected:
                row = self._task(project, name)
                require(row["state"] not in ("RUNNING", "REVIEW") and
                        not self.db.execute("SELECT 1 FROM leases WHERE project_id=? AND task_id=?", (project, name)).fetchone(),
                        "affected task is active or unresolved; reconcile/review first")
            self.db.execute("UPDATE tasks SET input=? WHERE project_id=? AND id=?", (canonical(new_input), project, task_id))
            for name in sorted(affected):
                row = self._task(project, name)
                state = self._ready_or_blocked(row)
                self.db.execute("UPDATE tasks SET state=?,generation=generation+1,current_attempt=NULL WHERE project_id=? AND id=?", (state, project, name))
                self._event(project, name, "INPUT_INVALIDATED", cause_task=task_id, reason=reason,
                            generation=row["generation"] + 1, previous_attempt=row["current_attempt"], next_state=state,
                            new_input=new_input if name == task_id else None)
            self._refresh_ready(project)
            return sorted(affected)

    def mark_interrupted(self, project, reason):
        """Explicit local operator declaration, never a timeout-based retry."""
        require(isinstance(reason, str) and reason.strip(), "interruption reason required")
        with self._transaction():
            rows = self.db.execute("SELECT * FROM attempts WHERE project_id=? AND status='RUNNING'", (project,)).fetchall()
            for attempt in rows:
                self.db.execute("UPDATE attempts SET status='UNKNOWN' WHERE id=?", (attempt["id"],))
                self.db.execute("UPDATE tasks SET state='BLOCKED' WHERE project_id=? AND id=?", (project, attempt["task_id"]))
                self._event(project, attempt["task_id"], "ATTEMPT_UNKNOWN", attempt_id=attempt["id"], reason=reason)
            return [a["id"] for a in rows]

    def reconcile(self, attempt_id, reviewer, outcome, evidence, actual_cost_units, result=None, failure_key=None):
        """Settle persisted UNKNOWN outcome using explicit simulation evidence."""
        require(isinstance(evidence, str) and evidence.strip(), "reconciliation evidence required")
        require(outcome in ("STAGED", "FAILED"), "outcome must be STAGED or FAILED")
        with self._transaction():
            attempt = self._attempt(attempt_id)
            task = self._task(attempt["project_id"], attempt["task_id"])
            self._actor(reviewer, "REVIEWER")
            require(reviewer == task["reviewer"] and reviewer != task["owner"], "independent assigned reviewer required")
            require(attempt["status"] == "UNKNOWN" and task["current_attempt"] == attempt_id,
                    "declare interruption before reconciliation")
            require(task["generation"] == attempt["generation"], "cannot reconcile stale generation")
            if outcome == "STAGED":
                self._stage(attempt, task, result, actual_cost_units)
            else:
                self._fail(attempt, task, failure_key, actual_cost_units)
            self._event(task["project_id"], task["id"], "OUTCOME_RECONCILED", attempt_id=attempt_id,
                        reviewer=reviewer, outcome=outcome, evidence=evidence)

    def snapshot(self, project):
        # A WAL reader keeps the same database version even if another connection
        # commits between these SELECTs. Do not combine separate autocommit reads.
        with self._transaction(read_only=True):
            p = self.db.execute("SELECT * FROM projects WHERE id=?", (project,)).fetchone()
            require(p is not None, "unknown project")
            return {"mode": "LOCAL_SIMULATION", "approval_issued": False, "production_verified": False,
                    "project_id": project, "workflow_version": p["workflow_version"],
                    "policy_version": p["policy_version"], "policy_commit": p["policy_commit"],
                    "budget": {"limit": p["budget_limit"], "spent": p["spent"], "reserved": p["reserved"]},
                    "tasks": [dict(r) for r in self.db.execute("SELECT id,lineage_id,state,generation,revision,current_attempt FROM tasks WHERE project_id=? ORDER BY id", (project,))],
                    "attempts": [dict(r) for r in self.db.execute("SELECT * FROM attempts WHERE project_id=? ORDER BY rowid", (project,))],
                    "events": [dict(r) for r in self.db.execute("SELECT * FROM events WHERE project_id=? ORDER BY sequence", (project,))]}
