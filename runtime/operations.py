"""Single-host evidence ledger for Grokbot. Records work; never dispatches tools.

Actor IDs and imported evidence are operator assertions, not authenticated
identities. This is a coordination boundary, not a security boundary against a
process with filesystem access. No public action or policy approval is issued.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
import hashlib
import json
import re
import sqlite3
import uuid

VERSION = "0.1.0"
POLICY_COMMIT = "30363791228181b986cc94491ab938ee544699f4"
LINES = {"YOUTUBE", "EMOTICON", "WEB_APP", "BLOG", "CHARACTER"}
FAILURES = {"INPUT", "PRODUCTION", "QUALITY", "TOOL", "PERMISSION"}


class OperationError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise OperationError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, field):
    require(isinstance(value, str) and bool(value.strip()), f"{field}: nonempty string required")
    require(not any(x in value for x in ("<", ">")), f"{field}: placeholder forbidden")
    return value


def integer(value, field, positive=False):
    require(type(value) is int and value >= int(positive), f"{field}: integer out of range")
    return value


def reference(value):
    require(isinstance(value, dict), "versioned reference required")
    for key in ("id", "version"):
        text(value.get(key), key)
    require(isinstance(value.get("sha256"), str) and
            re.fullmatch(r"[0-9a-f]{64}", value["sha256"]), "sha256: invalid digest")
    return value


def policy(value):
    require(value == {"version": "1.3", "commit": POLICY_COMMIT},
            "unsupported policy baseline; explicit migration is required")


def load_json(path):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, f"duplicate JSON key: {k}")
            result[k] = v
        return result
    def constant(value):
        raise OperationError(f"nonfinite JSON number: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=pairs, parse_constant=constant)


SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE actors (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE projects (id TEXT PRIMARY KEY, parent TEXT REFERENCES projects(id),
                       root_goal TEXT UNIQUE, data TEXT NOT NULL);
CREATE TABLE leases (actor TEXT PRIMARY KEY, project TEXT NOT NULL,
                     task TEXT NOT NULL, attempt TEXT NOT NULL, phase TEXT NOT NULL);
CREATE TABLE memories (id TEXT NOT NULL, version TEXT NOT NULL, data TEXT NOT NULL,
                       PRIMARY KEY(id,version));
CREATE TABLE validations (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE deployments (line TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                     project TEXT, kind TEXT NOT NULL, data TEXT NOT NULL);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER validations_no_update BEFORE UPDATE ON validations
BEGIN SELECT RAISE(ABORT,'validation evidence is append-only'); END;
CREATE TRIGGER validations_no_delete BEFORE DELETE ON validations
BEGIN SELECT RAISE(ABORT,'validation evidence is append-only'); END;
"""


class Operations:
    def __init__(self, db_path, artifact_root):
        self.root = Path(artifact_root).resolve(strict=True)
        require(self.root.is_dir(), "artifact root must be a directory")
        self.db = sqlite3.connect(str(db_path), timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=15000")
        try:
            # Lock before detecting/creating a database, including concurrent first use.
            self.db.execute("BEGIN IMMEDIATE")
            tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tables:
                # executescript would commit our lock; execute individual statements instead.
                buf = ""
                for line in SCHEMA.splitlines():
                    buf += line + "\n"
                    if sqlite3.complete_statement(buf):
                        self.db.execute(buf)
                        buf = ""
                self.db.executemany("INSERT INTO meta VALUES (?,?)", [
                    ("mode", "OPERATIONS_EVIDENCE"), ("schema", "1"),
                    ("artifact_root", str(self.root))])
            else:
                require("meta" in tables, "refusing simulation or foreign database")
                meta = dict(self.db.execute("SELECT key,value FROM meta"))
                require(meta.get("mode") == "OPERATIONS_EVIDENCE" and meta.get("schema") == "1",
                        "unsupported operational database")
                require(meta.get("artifact_root") == str(self.root), "artifact root changed; explicit migration required")
            self.db.execute("COMMIT")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self, readonly=False):
        self.db.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def event(self, project, kind, data):
        self.db.execute("INSERT INTO events(at,project,kind,data) VALUES (?,?,?,?)",
                        (now(), project, kind, canonical(data)))

    def artifact(self, ref):
        reference(ref)
        rel = Path(text(ref.get("path"), "artifact.path"))
        require(not rel.is_absolute() and not rel.anchor and not PureWindowsPath(str(ref["path"])).anchor
                and ".." not in rel.parts, "artifact paths must be relative to private artifact root")
        path = (self.root / rel).resolve(strict=True)
        require(path.is_relative_to(self.root) and path.is_file(), "artifact escapes root or is not a file")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        require(actual == ref["sha256"], "artifact digest mismatch")
        return ref

    def actor(self, actor_id):
        row = self.db.execute("SELECT data FROM actors WHERE id=?", (actor_id,)).fetchone()
        require(row is not None, "unregistered human")
        actor = json.loads(row[0])
        require(actor["status"] == "ACTIVE", "human is not active")
        return actor

    def register(self, data):
        """Explicit import of an existing Bot binding; never creates a Grokbot Bot."""
        text(data.get("human_id"), "human_id")
        text(data.get("bot_id"), "bot_id")
        text(data.get("slot_id"), "slot_id")
        catalog = load_json(Path(__file__).parents[1] / "spec/process-slots-v1.json")
        slot = catalog["slots"].get(data["slot_id"])
        require(slot is not None and data.get("owner_god") == slot["department"], "unknown slot or department mismatch")
        require(data.get("single_job") == slot["single_job"], "single job must match slot")
        require(data.get("status") in {"ACTIVE", "DORMANT", "QUARANTINED", "SUPERSEDED", "ARCHIVED"}, "invalid human state")
        reference(data.get("skill_ref"))
        require(isinstance(data.get("tools"), list) and all(isinstance(t, str) for t in data["tools"]), "tools list required")
        self.artifact(data.get("binding_evidence"))
        with self.transaction():
            previous = self.db.execute("SELECT data FROM actors WHERE id=?", (data["human_id"],)).fetchone()
            require(previous is None, "binding already exists; no identity overwrite")
            for row in self.db.execute("SELECT data FROM actors"):
                require(json.loads(row[0])["bot_id"] != data["bot_id"], "Bot already bound to a human")
            self.db.execute("INSERT INTO actors VALUES (?,?)", (data["human_id"], canonical(data)))
            self.event(None, "BINDING_IMPORTED", data)
        return {"human_id": data["human_id"], "identity_authenticated": False}

    def project(self, project_id):
        row = self.db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
        require(row is not None, "unknown project")
        return json.loads(row[0])

    def save(self, project):
        self.db.execute("UPDATE projects SET data=? WHERE id=?", (canonical(project), project["project_id"]))

    def ancestors(self, project):
        result = [project]
        while result[-1]["parent_project_id"]:
            result.append(self.project(result[-1]["parent_project_id"]))
        return result

    def descendant_ids(self, ancestor_id):
        result = {ancestor_id}
        rows = list(self.db.execute("SELECT id,parent FROM projects"))
        changed = True
        while changed:
            changed = False
            for r in rows:
                if r[1] in result and r[0] not in result:
                    result.add(r[0]); changed = True
        return result

    def scoped_leases(self, project_id):
        ids = self.descendant_ids(project_id)
        return [dict(r) for r in self.db.execute("SELECT * FROM leases") if r["project"] in ids]

    def pending(self, project_id):
        return sum(t["state"] in {"REVIEW", "REVIEWING"}
                   for pid in self.descendant_ids(project_id)
                   for t in self.project(pid)["tasks"].values())

    def create(self, data):
        require(data.get("mode") == "OPERATIONS_EVIDENCE", "explicit operations mode required")
        text(data.get("project_id"), "project_id")
        require(data.get("product_line") in LINES, "unknown product line")
        policy(data.get("policy_ref")); reference(data.get("workflow_ref"))
        self.artifact(data.get("plan_ref"))
        text(data.get("budget_unit"), "budget_unit")
        require(data["budget_unit"] != "SIMULATION_UNIT", "simulation currency is forbidden")
        for k in ("max_cost_units", "max_active_tasks", "max_pending_reviews", "review_capacity", "review_budget_reserve_units"):
            integer(data.get(k), k, positive=True)
        require(data["review_budget_reserve_units"] < data["max_cost_units"], "review reserve must leave production budget")
        require(data.get("data_origin") in {"REAL", "TEST"}, "data_origin REAL or TEST required")
        specs = data.get("tasks")
        require(isinstance(specs, list) and bool(specs), "tasks required")
        task_map = {}
        with self.transaction():
            require(not self.db.execute("SELECT 1 FROM projects WHERE id=?", (data["project_id"],)).fetchone(), "project already exists")
            selected_row = self.db.execute("SELECT data FROM deployments WHERE line=?", (data["product_line"],)).fetchone()
            if selected_row and data["data_origin"] == "REAL":
                selected = json.loads(selected_row[0])
                require(selected["status"] != "SUSPENDED", "line suspended")
                if selected["workflow_ref"] != data["workflow_ref"]:
                    self.artifact(data.get("comparison_plan_ref"))
            parent_id = data.get("parent_project_id")
            if parent_id:
                parent = self.project(parent_id)
                require(parent["budget_unit"] == data["budget_unit"] and parent["data_origin"] == data["data_origin"], "parent currency/origin mismatch")
                require(parent["policy_ref"] == data["policy_ref"], "parent policy mismatch")
                root_goal = None
            else:
                root_goal = text(data.get("root_goal_id"), "root_goal_id")
                require(not self.db.execute("SELECT 1 FROM projects WHERE root_goal=?", (root_goal,)).fetchone(), "goal already has a root budget")
            for spec in specs:
                tid = text(spec.get("task_id"), "task_id")
                require(tid not in task_map, "duplicate task ID")
                require(not spec.get("retry_of_task_id"), "use retry on existing lineage, not a new project/task")
                owner, reviewer = self.actor(spec.get("owner_human_id")), self.actor(spec.get("reviewer_human_id"))
                require(owner["human_id"] != reviewer["human_id"], "self review forbidden")
                require(spec.get("slot_id") == owner["slot_id"], "owner slot mismatch")
                require(spec.get("runtime_binding") == {"bot_id": owner["bot_id"], "skill_ref": owner["skill_ref"], "tools": owner["tools"]}, "runtime binding mismatch")
                require(spec.get("effect") in {"INTERNAL", "EXTERNAL"}, "effect required")
                text(spec.get("done_when"), "done_when")
                require(isinstance(spec.get("required_checks"), list) and bool(spec["required_checks"])
                        and all(isinstance(x, str) and x for x in spec["required_checks"])
                        and len(set(spec["required_checks"])) == len(spec["required_checks"]), "unique required_checks required")
                require(isinstance(spec.get("inputs"), list) and bool(spec["inputs"]), "versioned input files required")
                for ref in spec["inputs"]: self.artifact(ref)
                require(isinstance(spec.get("memory_refs", []), list), "memory_refs must be a list")
                context = spec.get("context", {})
                require(isinstance(context, dict), "context must be an object")
                if data["product_line"] in {"CHARACTER", "EMOTICON"} or "canon_ref" in context:
                    # This validates evidence bytes, not the authenticity of Zeus' decision.
                    self.artifact(context.get("canon_ref"))
                    self.artifact(context.get("canon_approval_evidence"))
                task_map[tid] = dict(spec, state="DRAFT", generation=0, revision=0,
                                     attempts=[], failures={}, current_attempt=None, block_reason=None)
            deps = {tid: set(t.get("depends_on", [])) for tid, t in task_map.items()}
            require(all(isinstance(t.get("depends_on", []), list) for t in task_map.values()), "depends_on list required")
            require(all(v <= task_map.keys() for v in deps.values()), "unknown dependency")
            while deps:
                ready = {k for k, v in deps.items() if not v}
                require(ready, "cyclic workflow")
                deps = {k: v - ready for k, v in deps.items() if k not in ready}
            project = dict(data, parent_project_id=parent_id, tasks=task_map, spent=0, reserved=0,
                           created_at=now(), halted=False, external_execution="NOT_PERFORMED")
            project["workflow_definition_hash"] = self.workflow_definition(project)
            for row in self.db.execute("SELECT data FROM projects"):
                prior = json.loads(row[0])
                if (prior["data_origin"] == project["data_origin"] == "REAL"
                        and prior["workflow_ref"] == project["workflow_ref"]):
                    require(prior["workflow_definition_hash"] == project["workflow_definition_hash"],
                            "workflow behavior changed without a new version")
            self.refresh(project)
            self.db.execute("INSERT INTO projects VALUES (?,?,?,?)", (data["project_id"], parent_id, root_goal, canonical(project)))
            self.event(data["project_id"], "PROJECT_CREATED", project)
        return self.status(data["project_id"])

    def workflow_definition(self, project):
        fields = ("slot_id", "effect", "required_checks", "depends_on")
        return digest({tid: {**{k: t.get(k, []) for k in fields},
                              "skill_ref": t["runtime_binding"]["skill_ref"],
                              "tools": t["runtime_binding"]["tools"],
                              "review_slot": self.actor(t["reviewer_human_id"])["slot_id"]}
                       for tid, t in project["tasks"].items()})

    def validation_snapshot(self, project):
        return digest({"workflow": project["workflow_ref"], "policy": project["policy_ref"],
                       "definition": project["workflow_definition_hash"],
                       "tasks": {tid: {k: t.get(k) for k in ("generation", "inputs", "context",
                                 "memory_refs", "current_attempt", "runtime_binding", "attempts")}
                                 for tid, t in project["tasks"].items()}})

    def verify_completed(self, project, task):
        require(task["state"] == "DONE", "task incomplete")
        self.check_inputs(project, task)
        attempt = task["attempts"][-1]
        self.verify_result(attempt["result"], task)
        require(attempt["review"]["accepted"] is True, "accepted review required")
        self.artifact(attempt["review"]["evidence_ref"])

    def verify_validations(self, line, workflow_ref, policy_ref):
        matched = [json.loads(r[0]) for r in self.db.execute("SELECT data FROM validations")]
        matched = [r for r in matched if r["workflow_ref"] == workflow_ref
                   and r["product_line"] == line and r["policy_ref"] == policy_ref]
        require(len(matched) >= 2, "two distinct actual manual runs required")
        require(len({r["workflow_definition_hash"] for r in matched}) == 1, "mixed workflow behavior")
        for run in matched:
            self.artifact(run["evidence_ref"]); self.artifact(run["hestia_review_ref"])
            project = self.project(run["project_id"])
            require(run["snapshot_hash"] == self.validation_snapshot(project), "validation run changed")
            for task in project["tasks"].values(): self.verify_completed(project, task)
        return matched

    def refresh(self, project):
        for t in project["tasks"].values():
            if t["state"] in {"DRAFT", "READY"}:
                t["state"] = "READY" if all(project["tasks"][x]["state"] == "DONE" for x in t.get("depends_on", [])) else "DRAFT"

    def task(self, project, task_id):
        require(task_id in project["tasks"], "unknown task")
        return project["tasks"][task_id]

    def limits(self, task):
        return (len(task["attempts"]) < 6 and task["revision"] <= 2
                and sum(a["revision"] == task["revision"] for a in task["attempts"]) < 2
                and max(task["failures"].values(), default=0) < 2)

    def check_inputs(self, project, task):
        context = task.get("context", {})
        if "canon_ref" in context:
            self.artifact(context["canon_ref"]); self.artifact(context["canon_approval_evidence"])
        for ref in task["inputs"]: self.artifact(ref)
        for dep_id in task.get("depends_on", []):
            dep = self.task(project, dep_id)
            require(dep["state"] == "DONE", "dependency incomplete")
            self.verify_completed(project, dep)
        for ref in task.get("memory_refs", []):
            reference(ref)
            row = self.db.execute("SELECT data FROM memories WHERE id=? AND version=?", (ref["id"], ref["version"])).fetchone()
            require(row, "unknown memory")
            memory = json.loads(row[0])
            require(memory["content_hash"] == ref["sha256"] and memory["status"] == "ACTIVE", "memory not active or changed")
            require(datetime.fromisoformat(memory["valid_from"]) <= datetime.now(timezone.utc) < datetime.fromisoformat(memory["expires_at"]), "memory outside validity")
            actual_scope = {"project_id": project["project_id"], "product_line": project["product_line"],
                            "slot_id": task["slot_id"], "skill_sha256": task["runtime_binding"]["skill_ref"]["sha256"]}
            require(all(actual_scope.get(k) == v for k, v in memory["scope"].items()), "memory scope mismatch")
            for evidence in memory["evidence_refs"]: self.artifact(evidence)

    def claim(self, project_id, task_id, actor_id, max_cost_units, phase="PRODUCTION"):
        integer(max_cost_units, "max_cost_units")
        require(phase in {"PRODUCTION", "REVIEW"}, "unknown phase")
        with self.transaction():
            p = self.project(project_id); t = self.task(p, task_id)
            self.actor(actor_id)
            require(not self.db.execute("SELECT 1 FROM leases WHERE actor=?", (actor_id,)).fetchone(), "human already owns a task")
            if phase == "PRODUCTION":
                require(t["state"] == "READY" and self.limits(t), "task not ready or retry limit reached")
                require(t["owner_human_id"] == actor_id, "wrong owner")
                selected_row = self.db.execute("SELECT data FROM deployments WHERE line=?", (p["product_line"],)).fetchone()
                if selected_row and p["data_origin"] == "REAL":
                    selected = json.loads(selected_row[0])
                    require(selected["status"] != "SUSPENDED", "line suspended")
                    require(selected["workflow_ref"] == p["workflow_ref"] or p.get("comparison_plan_ref"),
                            "new assignments stopped for replaced workflow")
                require(t["effect"] == "INTERNAL", "EXTERNAL_ACTION_REQUIRES_AUTHENTICATED_GATEWAY; no dispatch implemented")
                require(self.actor(actor_id)["skill_ref"] == t["runtime_binding"]["skill_ref"], "binding skill changed")
                self.check_inputs(p, t)
            else:
                require(t["state"] == "REVIEW" and t["reviewer_human_id"] == actor_id, "review not ready or wrong reviewer")
            chain = self.ancestors(p)
            for parent in chain:
                leases = self.scoped_leases(parent["project_id"])
                prod = sum(x["phase"] == "PRODUCTION" for x in leases)
                reviews = sum(x["phase"] == "REVIEW" for x in leases)
                require(not parent["halted"], "project halted")
                reserve_floor = parent["review_budget_reserve_units"] if phase == "PRODUCTION" else 0
                require(parent["max_cost_units"] - parent["spent"] - parent["reserved"] - max_cost_units >= reserve_floor, "budget unavailable")
                if phase == "PRODUCTION":
                    require(prod < parent["max_active_tasks"], "active task limit")
                    require(self.pending(parent["project_id"]) + prod < parent["max_pending_reviews"], "REVIEW_BACKPRESSURE")
                else:
                    require(reviews < parent["review_capacity"], "review capacity exhausted")
            if phase == "PRODUCTION":
                aid = str(uuid.uuid4())
                a = {"attempt_id": aid, "generation": t["generation"], "revision": t["revision"],
                     "started_at": now(), "status": "RUNNING", "reserved": max_cost_units,
                     "actual_cost_units": None, "input_digest": self.input_fingerprint(p, t)}
                t["attempts"].append(a); t["current_attempt"] = aid; t["state"] = "RUNNING"
            else:
                a = t["attempts"][-1]; aid = a["attempt_id"]
                a["review_claim"] = {"started_at": now(), "reserved": max_cost_units}
                t["state"] = "REVIEWING"
            for parent in chain:
                parent["reserved"] += max_cost_units; self.save(parent)
            self.save(p)
            self.db.execute("INSERT INTO leases VALUES (?,?,?,?,?)", (actor_id, project_id, task_id, aid, phase))
            self.event(project_id, "CLAIMED", {"task_id": task_id, "attempt_id": aid, "actor": actor_id, "phase": phase, "reservation": max_cost_units})
        return {"attempt_id": aid, "phase": phase, "identity_authenticated": False}

    def current(self, p, task_id, attempt_id):
        t = self.task(p, task_id)
        require(t["current_attempt"] == attempt_id and t["attempts"], "stale or unknown attempt")
        a = t["attempts"][-1]
        require(a["generation"] == t["generation"], "stale input generation")
        return t, a

    def cost(self, value):
        require(isinstance(value, dict), "cost object required")
        integer(value.get("units"), "cost.units")
        self.artifact(value.get("evidence_ref"))
        return value["units"]

    def settle(self, p, reservation, cost):
        for parent in self.ancestors(p):
            parent["reserved"] -= reservation
            require(parent["reserved"] >= 0, "reservation invariant violated")
            parent["spent"] += cost
            if cost > reservation or parent["spent"] + parent["reserved"] > parent["max_cost_units"]:
                parent["halted"] = True
            self.save(parent)

    def verify_result(self, result, task):
        require(isinstance(result, dict) and result.get("simulation") is False, "non-simulation result required")
        require(isinstance(result.get("artifacts"), list) and result["artifacts"], "output files required")
        for ref in result["artifacts"]: self.artifact(ref)
        checks = result.get("checks")
        require(isinstance(checks, list), "checks required")
        found = set()
        for check in checks:
            require(isinstance(check, dict) and type(check.get("passed")) is bool, "typed check required")
            text(check.get("id"), "check.id")
            require(check["id"] not in found, "duplicate check")
            found.add(check["id"]); self.artifact(check.get("evidence_ref"))
        require(set(task["required_checks"]) <= found, "missing required check")
        require(all(c["passed"] for c in checks), "deterministic check failed")
        require(result.get("external_execution", "NOT_PERFORMED") == "NOT_PERFORMED", "this ledger does not certify external execution")

    def submit(self, project_id, task_id, attempt_id, actor_id, result, cost):
        with self.transaction():
            p = self.project(project_id); t, a = self.current(p, task_id, attempt_id)
            require(actor_id == t["owner_human_id"], "wrong owner")
            if a.get("submission_digest"):
                require(a["submission_digest"] == digest({"result": result, "cost": cost}), "conflicting duplicate submission")
                return {"idempotent": True, "result_digest": a["result_digest"]}
            require(t["state"] == "RUNNING", "attempt is not running")
            self.check_inputs(p, t); self.verify_result(result, t)
            a.update(result=result, result_digest=digest(result), ended_at=now(), submission_digest=digest({"result": result, "cost": cost}))
            if cost is None:
                a["status"] = "UNKNOWN"; t["state"] = "BLOCKED"; t["block_reason"] = "COST_UNMEASURED"
            else:
                amount = self.cost(cost); self.settle(p, a["reserved"], amount)
                a.update(status="REVIEW", actual_cost_units=amount, cost_evidence=cost)
                t["state"] = "REVIEW"; a["submitted_at"] = now()
                self.db.execute("DELETE FROM leases WHERE actor=? AND attempt=?", (actor_id, attempt_id))
            self.save(p); self.event(project_id, "RESULT_SUBMITTED", {"task_id": task_id, "attempt": a})
        return {"state": t["state"], "result_digest": a["result_digest"]}

    def record_failure(self, t, failure_key):
        text(failure_key, "failure_key")
        t["failures"][failure_key] = t["failures"].get(failure_key, 0) + 1

    def review(self, project_id, task_id, attempt_id, actor_id, result_digest, accepted,
               evidence_ref, cost, failed_checks=None, repair_tasks=None, reusable_tasks=None,
               failure_class=None, failure_key=None):
        require(type(accepted) is bool, "accepted must be boolean")
        with self.transaction():
            p = self.project(project_id); t, a = self.current(p, task_id, attempt_id)
            require(t["state"] == "REVIEWING" and actor_id == t["reviewer_human_id"], "review must be claimed by designated reviewer")
            require(result_digest == a["result_digest"], "review targets a different result")
            self.artifact(evidence_ref); self.verify_result(a["result"], t)
            if accepted: self.check_inputs(p, t)
            amount = self.cost(cost)
            decision = dict(accepted=accepted, actor=actor_id, result_digest=result_digest, evidence_ref=evidence_ref,
                            failed_checks=failed_checks, repair_tasks=repair_tasks, reusable_tasks=reusable_tasks,
                            failure_class=failure_class, failure_key=failure_key, cost=cost, at=now())
            if not accepted:
                require(failure_class in FAILURES and isinstance(failed_checks, list) and bool(failed_checks), "rejection needs failure class and failed checks")
                require(isinstance(repair_tasks, list) and task_id in repair_tasks and set(repair_tasks) <= p["tasks"].keys(), "repair tasks must include rejected task")
                require(isinstance(reusable_tasks, list) and set(reusable_tasks) <= p["tasks"].keys()
                        and not set(reusable_tasks) & set(repair_tasks), "invalid reusable tasks")
                self.record_failure(t, failure_key); t["revision"] += 1
            self.settle(p, a["review_claim"]["reserved"], amount)
            a["review"] = decision; a["status"] = "ACCEPTED" if accepted else "REJECTED"
            t["state"] = "DONE" if accepted else ("READY" if self.limits(t) else "BLOCKED")
            t["block_reason"] = None if accepted or self.limits(t) else "RETRY_LIMIT"
            self.db.execute("DELETE FROM leases WHERE actor=? AND attempt=? AND phase='REVIEW'", (actor_id, attempt_id))
            self.refresh(p); self.save(p); self.event(project_id, "REVIEW_RECORDED", {"task_id": task_id, "attempt_id": attempt_id, **decision})
        return {"state": t["state"], "external_execution": "NOT_PERFORMED"}

    def block(self, project_id, task_id, reason):
        text(reason, "reason")
        with self.transaction():
            p = self.project(project_id); t = self.task(p, task_id)
            require(t["state"] not in {"DONE", "BLOCKED"}, "cannot block completed or already blocked task")
            t["blocked_from"] = t["state"]; t["state"] = "BLOCKED"; t["block_reason"] = reason
            if t["attempts"] and t["blocked_from"] in {"RUNNING", "REVIEWING"}:
                t["attempts"][-1]["status"] = "UNKNOWN"
            self.save(p); self.event(project_id, "BLOCKED", {"task_id": task_id, "reason": reason, "previous": t["blocked_from"]})
        return {"state": "BLOCKED", "reservations_and_leases_retained": True}

    def reconcile(self, project_id, task_id, attempt_id, actor_id, outcome, evidence_ref, cost=None,
                  result=None, failure_key=None, failure_class=None):
        require(outcome in {"SUCCEEDED", "FAILED", "RESUME"}, "unknown reconciliation outcome")
        with self.transaction():
            p = self.project(project_id); t = self.task(p, task_id)
            require(t["state"] == "BLOCKED" and actor_id == t["reviewer_human_id"], "blocked task and designated independent reviewer required")
            self.actor(actor_id); self.artifact(evidence_ref)
            require(not self.db.execute("SELECT 1 FROM leases WHERE actor=? AND NOT(project=? AND task=? AND phase='REVIEW')", (actor_id, project_id, task_id)).fetchone(), "reviewer busy")
            if outcome == "RESUME":
                require(not self.db.execute("SELECT 1 FROM leases WHERE project=? AND task=?", (project_id, task_id)).fetchone(), "unknown active attempt must be settled first")
                require(self.limits(t) and t["effect"] == "INTERNAL", "cannot bypass retry/approval gate")
                self.check_inputs(p, t)
                t["state"] = "DRAFT"; self.refresh(p)
            else:
                t, a = self.current(p, task_id, attempt_id)
                lease = self.db.execute("SELECT * FROM leases WHERE project=? AND task=? AND attempt=?", (project_id, task_id, attempt_id)).fetchone()
                require(lease is not None, "no unresolved lease")
                if lease["phase"] == "REVIEW":
                    # Review computation may have cost money, but must be reviewed again.
                    require(outcome == "FAILED", "interrupted review must be closed then reclaimed")
                    reservation = a["review_claim"]["reserved"]
                    a.setdefault("interrupted_reviews", []).append({"claim": a.pop("review_claim"), "cost": cost, "evidence": evidence_ref})
                    t["state"] = "REVIEW"; a["status"] = "REVIEW"
                else:
                    reservation = a["reserved"]
                    if outcome == "SUCCEEDED":
                        resolved = result or a.get("result"); self.verify_result(resolved, t)
                        a.update(result=resolved, result_digest=digest(resolved), status="REVIEW", submitted_at=now())
                        t["state"] = "REVIEW"
                    else:
                        require(failure_class in FAILURES, "failure class required")
                        self.record_failure(t, failure_key); a["status"] = "FAILED"
                        t["state"] = "READY" if self.limits(t) else "BLOCKED"
                    a["actual_cost_units"] = self.cost(cost); a["cost_evidence"] = cost; a["ended_at"] = now()
                self.settle(p, reservation, self.cost(cost))
                self.db.execute("DELETE FROM leases WHERE project=? AND task=? AND attempt=?", (project_id, task_id, attempt_id))
            t["block_reason"] = "RETRY_LIMIT" if t["state"] == "BLOCKED" else None
            self.save(p); self.event(project_id, "RECONCILED", {"task_id": task_id, "attempt_id": attempt_id, "outcome": outcome, "evidence_ref": evidence_ref, "cost": cost, "failure_key": failure_key, "failure_class": failure_class})
        return {"state": t["state"]}

    def change_input(self, project_id, task_id, inputs, reason, context=None, retry_card_id=None, memory_refs=None):
        text(reason, "reason")
        require(isinstance(inputs, list) and inputs, "inputs required")
        for ref in inputs: self.artifact(ref)
        with self.transaction():
            p = self.project(project_id); t = self.task(p, task_id)
            affected = {task_id}
            while True:
                updated = affected | {k for k, x in p["tasks"].items() if set(x.get("depends_on", [])) & affected}
                if updated == affected: break
                affected = updated
            require(not any(r["task"] in affected for r in self.db.execute("SELECT task FROM leases WHERE project=?", (project_id,))), "affected worker/reviewer outcome unresolved")
            require(all(p["tasks"][k]["state"] not in {"REVIEW", "REVIEWING"} for k in affected), "finish or reconcile affected review first")
            require(all(p["tasks"][k]["revision"] < 2 for k in affected), "revision limit reached")
            if retry_card_id:
                text(retry_card_id, "retry_card_id")
                require(not self.db.execute("SELECT 1 FROM events WHERE kind='INPUT_CHANGED' AND json_extract(data,'$.retry_card_id')=?", (retry_card_id,)).fetchone(), "retry card already recorded")
            if context is not None:
                require(isinstance(context, dict), "context must be object")
                if p["product_line"] in {"CHARACTER", "EMOTICON"} or "canon_ref" in context:
                    self.artifact(context.get("canon_ref")); self.artifact(context.get("canon_approval_evidence"))
                t["context"] = context
            t["inputs"] = inputs
            if memory_refs is not None:
                require(isinstance(memory_refs, list), "memory_refs must be a list")
                for ref in memory_refs: reference(ref)
                t["memory_refs"] = memory_refs
            for k in affected:
                item = p["tasks"][k]
                item["generation"] += 1; item["revision"] += 1; item["current_attempt"] = None
                item["state"] = "DRAFT" if self.limits(item) else "BLOCKED"
                item["block_reason"] = None if self.limits(item) else "RETRY_LIMIT"
            self.refresh(p); self.save(p)
            self.event(project_id, "INPUT_CHANGED", {"task_id": task_id, "inputs": inputs, "context": context,
                       "reason": reason, "affected": sorted(affected), "retry_card_id": retry_card_id})
        return {"affected_tasks": sorted(affected), "history_preserved": True}

    def memory(self, action, record):
        require(action in {"propose", "verify", "activate", "revoke", "expire"}, "unknown memory action")
        mid, version = text(record.get("id"), "id"), text(record.get("version"), "version")
        with self.transaction():
            row = self.db.execute("SELECT data FROM memories WHERE id=? AND version=?", (mid, version)).fetchone()
            if action == "propose":
                require(row is None, "memory version already exists")
                text(record.get("statement"), "statement")
                require(record.get("kind") in {"FACT", "PROCEDURE", "PREFERENCE", "HYPOTHESIS"}, "invalid memory kind")
                require(record.get("evidence_refs"), "evidence required")
                for ref in record["evidence_refs"]: self.artifact(ref)
                self.actor(record.get("proposed_by"))
                scope = record.get("scope")
                require(isinstance(scope, dict) and scope and "project_id" in scope and set(scope) <= {"project_id", "product_line", "slot_id", "skill_sha256"}, "explicit project memory scope required")
                self.project(scope["project_id"])
                start, end = datetime.fromisoformat(record["valid_from"]), datetime.fromisoformat(record["expires_at"])
                require(start.tzinfo is not None and end.tzinfo is not None and start < end, "timezone and positive memory validity required")
                value = dict(record, status="PROPOSED", content_hash=digest(record))
                self.db.execute("INSERT INTO memories VALUES (?,?,?)", (mid, version, canonical(value)))
            else:
                require(row, "unknown memory"); value = json.loads(row[0])
                actor = self.actor(record.get("actor_id")); self.artifact(record.get("evidence_ref"))
                if action == "verify":
                    require(value["status"] == "PROPOSED" and actor["human_id"] != value["proposed_by"], "independent verification required")
                    value.update(status="VERIFIED", verified_by=actor["human_id"], verification_ref=record["evidence_ref"])
                elif action == "activate":
                    require(value["status"] == "VERIFIED", "unverified memory")
                    require(record.get("hestia_write_validation_ref"), "Hestia write validation evidence required")
                    self.artifact(record["hestia_write_validation_ref"])
                    value["status"] = "ACTIVE"
                else:
                    require(value["status"] not in {"REVOKED", "EXPIRED"}, "memory already withdrawn")
                    text(record.get("reason"), "reason")
                    value["status"] = "REVOKED" if action == "revoke" else "EXPIRED"
                self.db.execute("UPDATE memories SET data=? WHERE id=? AND version=?", (canonical(value), mid, version))
            self.event(None, "MEMORY_" + action.upper(), {"request": record, "record": value})
        return value

    def status(self, project_id):
        with self.transaction(readonly=True):
            p = self.project(project_id)
            complete = all(t["state"] == "DONE" for t in p["tasks"].values())
            invalid = {}
            for tid, task in p["tasks"].items():
                if task["state"] == "DONE":
                    try:
                        self.verify_completed(p, task)
                    except (OperationError, OSError) as exc:
                        invalid[tid] = str(exc)
            complete = complete and not invalid
            return {"mode": "OPERATIONS_EVIDENCE", "implementation_version": VERSION,
                    "project": p, "leases": self.scoped_leases(project_id),
                    "production_status": "COMPLETED" if complete else "INCOMPLETE",
                    "review_required": invalid,
                    "external_execution": "NOT_PERFORMED", "runtime_verified": False,
                    "identity_authenticated": False, "evidence_trust": "OPERATOR_SUPPLIED"}

    def export(self, project_id):
        # Keep state and history in one read transaction, not two snapshots.
        with self.transaction(readonly=True):
            p = self.project(project_id)
            events = [dict(r) for r in self.db.execute("SELECT * FROM events WHERE project=? ORDER BY seq", (project_id,))]
            for e in events: e["data"] = json.loads(e["data"])
            payload = {"mode": "OPERATIONS_EVIDENCE", "project": p, "events": events,
                       "runtime_verified": False, "evidence_trust": "OPERATOR_SUPPLIED"}
            return {"payload": payload, "sha256": digest(payload)}

    def validation(self, record):
        """Record evidence, not an authenticated assertion of production readiness."""
        with self.transaction():
            p = self.project(record.get("project_id"))
            require(p["data_origin"] == "REAL", "TEST cannot count as manual validation")
            require(all(t["state"] == "DONE" for t in p["tasks"].values()), "run incomplete")
            for t in p["tasks"].values():
                self.verify_completed(p, t)
            require(record.get("actual_manual_e2e") is True and type(record.get("unexpected_interventions")) is int and record["unexpected_interventions"] == 0,
                    "actual manual pass without unexpected intervention required")
            self.actor(record.get("reviewed_by"))
            require(all(record["reviewed_by"] != t["owner_human_id"] for t in p["tasks"].values()), "independent reviewer required")
            for k in ("evidence_ref", "hestia_review_ref"): self.artifact(record.get(k))
            text(record.get("run_id"), "run_id")
            for r in self.db.execute("SELECT data FROM validations"):
                require(json.loads(r[0])["project_id"] != p["project_id"], "project already counted")
            value = dict(record, workflow_ref=p["workflow_ref"], product_line=p["product_line"], policy_ref=p["policy_ref"],
                         recorded_at=now(), snapshot_hash=self.validation_snapshot(p),
                         workflow_definition_hash=p["workflow_definition_hash"],
                         evidence_trust="OPERATOR_SUPPLIED", external_execution_verified=False)
            self.db.execute("INSERT INTO validations VALUES (?,?)", (record["run_id"], canonical(value)))
            self.event(p["project_id"], "MANUAL_VALIDATION_RECORDED", value)
        return value

    def deployment(self, action, record):
        """Only records selection for new tasks; never edits app settings."""
        require(action in {"activate", "rollback", "suspend"}, "unknown deployment action")
        line = record.get("product_line"); require(line in LINES, "unknown line")
        self.artifact(record.get("hestia_decision_ref"))
        with self.transaction():
            row = self.db.execute("SELECT data FROM deployments WHERE line=?", (line,)).fetchone()
            previous = json.loads(row[0]) if row else None
            if action == "activate":
                reference(record.get("workflow_ref")); policy(record.get("policy_ref"))
                self.verify_validations(line, record["workflow_ref"], record["policy_ref"])
                value = dict(record, status="SELECTED_FOR_NEW_TASKS", prior=previous, selected_at=now())
            elif action == "rollback":
                require(previous and previous.get("prior"), "no previous version")
                value = previous["prior"]; policy(value["policy_ref"])
                require(value["status"] == "SELECTED_FOR_NEW_TASKS", "previous version suspended")
                self.verify_validations(line, value["workflow_ref"], value["policy_ref"])
                value = dict(value, rollback_evidence=record["hestia_decision_ref"])
            else:
                require(previous, "no selected version")
                value = dict(previous, status="SUSPENDED", suspension_evidence=record["hestia_decision_ref"])
            self.db.execute("INSERT INTO deployments VALUES (?,?) ON CONFLICT(line) DO UPDATE SET data=excluded.data", (line, canonical(value)))
            self.event(None, "DEPLOYMENT_" + action.upper(), {"request": record, "selection": value})
        return {"selection": value, "grokbot_settings_modified": False, "routine_activated": False}

    def report(self):
        """Real-only metrics; unsettled costs stay unknown."""
        with self.transaction(readonly=True):
            projects = [json.loads(r[0]) for r in self.db.execute("SELECT data FROM projects")]
            real = [p for p in projects if p["data_origin"] == "REAL"]
            reports = {}
            for line in sorted(LINES):
                group = [p for p in real if p["product_line"] == line]
                tasks = [t for p in group for t in p["tasks"].values()]
                reviewed = [t for t in tasks if any("review" in a for a in t["attempts"])]
                first = sum(next(a["review"]["accepted"] for a in t["attempts"] if "review" in a) for t in reviewed)
                valid_outputs = set()
                for project in group:
                    for tid, task in project["tasks"].items():
                        try:
                            self.verify_completed(project, task)
                            valid_outputs.add((project["project_id"], tid))
                        except (OperationError, OSError):
                            pass
                accepted = len(valid_outputs)
                costs = {}; unknown = 0; waits = []; elapsed = []
                for p in group:
                    # Sum own attempts, not ancestor aggregates: no double counting.
                    amount = 0
                    for t in p["tasks"].values():
                        for a in t["attempts"]:
                            if a.get("actual_cost_units") is None: unknown += 1
                            else: amount += a["actual_cost_units"]
                            if "review" in a:
                                amount += a["review"]["cost"]["units"]
                                waits.append((datetime.fromisoformat(a["review_claim"]["started_at"]) - datetime.fromisoformat(a["submitted_at"])).total_seconds())
                            elif "review_claim" in a: unknown += 1
                            for old in a.get("interrupted_reviews", []): amount += old["cost"]["units"]
                    costs[p["budget_unit"]] = costs.get(p["budget_unit"], 0) + amount
                    if all((p["project_id"], tid) in valid_outputs for tid in p["tasks"]):
                        end = max(t["attempts"][-1]["review"]["at"] for t in p["tasks"].values())
                        elapsed.append((datetime.fromisoformat(end) - datetime.fromisoformat(p["created_at"])).total_seconds())
                observations = [json.loads(e[0]) for p in group for e in self.db.execute(
                    "SELECT data FROM events WHERE project=? AND kind='OBSERVATION'", (p["project_id"],))]
                changes = [o for o in observations if o["kind"] == "USER_CHANGE"]
                approvals = [o for o in observations if o["kind"] == "APPROVAL_WAIT"]
                reports[line] = {
                    "measurement_status": "OBSERVED" if group else "UNMEASURED",
                    "project_count": len(group), "task_count": len(tasks), "reviewed_output_count": len(reviewed),
                    "accepted_output_count": accepted, "first_pass_rate": first / len(reviewed) if reviewed else None,
                    "final_adoption_rate": accepted / len(tasks) if tasks else None,
                    "settled_cost_by_unit": costs, "unknown_cost_attempts": unknown,
                    "cost_per_accepted_output": next(iter(costs.values())) / accepted if accepted and len(costs) == 1 and not unknown else None,
                    "mean_completion_seconds": sum(elapsed) / len(elapsed) if elapsed else None,
                    "unfinished_projects": len(group) - len(elapsed),
                    "mean_review_wait_seconds": sum(waits) / len(waits) if waits else None,
                    "retry_count": sum(max(0, len(t["attempts"]) - 1) for t in tasks),
                    "user_revision_count": len(changes) if changes else None,
                    "quality_fix_count": sum(o["change_class"] == "QUALITY_FIX" for o in changes) if changes else None,
                    "scope_change_count": sum(o["change_class"] == "SCOPE_CHANGE" for o in changes) if changes else None,
                    "approval_wait_seconds": sum((datetime.fromisoformat(o["ended_at"]) - datetime.fromisoformat(o["started_at"])).total_seconds() for o in approvals) if approvals else None,
                    "limitations": ["Operator-supplied cost/review evidence", "User changes and approval waits need external records", "No performance gain inferred"]}
            return {"as_of": now(), "data_origin": "REAL", "excluded_test_projects": len(projects) - len(real),
                    "lines": reports, "runtime_verified": False}

    def observe(self, project_id, record):
        """Import source-backed user-change/approval-wait observations."""
        text(record.get("observation_id"), "observation_id")
        require(record.get("kind") in {"USER_CHANGE", "APPROVAL_WAIT"}, "unsupported observation")
        self.artifact(record.get("evidence_ref"))
        if record["kind"] == "USER_CHANGE":
            require(record.get("change_class") in {"QUALITY_FIX", "SCOPE_CHANGE"}, "change class required")
        else:
            start, end = datetime.fromisoformat(record["started_at"]), datetime.fromisoformat(record["ended_at"])
            require(start.tzinfo is not None and end.tzinfo is not None and end >= start, "valid wait interval required")
        with self.transaction():
            self.project(project_id)
            rows = self.db.execute("SELECT data FROM events WHERE project=? AND kind='OBSERVATION'", (project_id,))
            for row in rows:
                old = json.loads(row[0])
                if old["observation_id"] == record["observation_id"]:
                    require(old == record, "conflicting observation ID")
                    return {"idempotent": True}
            self.event(project_id, "OBSERVATION", record)
        return {"recorded": True, "evidence_trust": "OPERATOR_SUPPLIED"}

    def update_binding(self, human_id, skill_ref, tools, evidence_ref):
        """Keep the existing identity/slot; record a version change after all work settles."""
        reference(skill_ref); self.artifact(evidence_ref)
        require(isinstance(tools, list) and all(isinstance(x, str) for x in tools), "tools list required")
        with self.transaction():
            before = self.actor(human_id)
            require(not self.db.execute("SELECT 1 FROM leases WHERE actor=?", (human_id,)).fetchone(), "human busy")
            after = dict(before, skill_ref=skill_ref, tools=tools, binding_evidence=evidence_ref)
            self.db.execute("UPDATE actors SET data=? WHERE id=?", (canonical(after), human_id))
            self.event(None, "BINDING_VERSION_CHANGED", {"before": before, "after": after})
        return {"human_id": human_id, "grokbot_settings_modified": False, "identity_authenticated": False}

    def change_reference(self, old_ref, new_ref, reason, impact_review_ref, canon_approval_evidence=None):
        """Atomically invalidate every direct consumer and descendant across the ledger."""
        reference(old_ref); self.artifact(new_ref); self.artifact(impact_review_ref); text(reason, "reason")
        require(old_ref["id"] == new_ref["id"] and old_ref != new_ref, "same asset ID and a new reference required")
        def matches(ref):
            return all(ref.get(k) == old_ref[k] for k in ("id", "version", "sha256"))
        with self.transaction():
            changes = []
            for row in self.db.execute("SELECT data FROM projects"):
                project = json.loads(row[0]); direct = set(); affected = set()
                for tid, task in project["tasks"].items():
                    if any(matches(ref) for ref in task["inputs"]) or matches(task.get("context", {}).get("canon_ref", {})):
                        direct.add(tid)
                if not direct: continue
                affected = set(direct)
                while True:
                    updated = affected | {k for k, t in project["tasks"].items() if set(t.get("depends_on", [])) & affected}
                    if updated == affected: break
                    affected = updated
                require(not any(r["task"] in affected for r in self.db.execute(
                    "SELECT task FROM leases WHERE project=?", (project["project_id"],))), "affected outcome unresolved")
                require(all(project["tasks"][k]["state"] not in {"REVIEW", "REVIEWING"} for k in affected), "finish affected review first")
                require(all(project["tasks"][k]["revision"] < 2 for k in affected), "revision limit reached")
                for tid in direct:
                    task = project["tasks"][tid]
                    task["inputs"] = [new_ref if matches(ref) else ref for ref in task["inputs"]]
                    if matches(task.get("context", {}).get("canon_ref", {})):
                        self.artifact(canon_approval_evidence)
                        task["context"].update(canon_ref=new_ref, canon_approval_evidence=canon_approval_evidence)
                for tid in affected:
                    task = project["tasks"][tid]
                    task.update(generation=task["generation"] + 1, revision=task["revision"] + 1, current_attempt=None)
                    task["state"] = "DRAFT" if self.limits(task) else "BLOCKED"
                    task["block_reason"] = None if self.limits(task) else "RETRY_LIMIT"
                changes.append((project, sorted(affected)))
            require(changes, "no matching consumers")
            for project, affected in changes:
                self.refresh(project); self.save(project)
                self.event(project["project_id"], "SHARED_REFERENCE_CHANGED", {
                    "old_ref": old_ref, "new_ref": new_ref, "reason": reason,
                    "impact_review_ref": impact_review_ref, "affected": affected,
                    "canon_approval_evidence": canon_approval_evidence})
        return {"affected": {p["project_id"]: tasks for p, tasks in changes}, "history_preserved": True}

    def input_fingerprint(self, project, task):
        return digest({"inputs": task["inputs"], "context": task.get("context", {}),
                       "dependencies": [self.task(project, x)["attempts"][-1]["result_digest"] for x in task.get("depends_on", [])],
                       "memories": task.get("memory_refs", []), "binding": task["runtime_binding"],
                       "policy": project["policy_ref"], "workflow": project["workflow_ref"],
                       "slot": task["slot_id"], "checks": task["required_checks"], "done_when": task["done_when"]})

    def reuse(self, project_id, task_id):
        """Find verified candidates. Reuse still goes through submit and independent review."""
        with self.transaction(readonly=True):
            project = self.project(project_id); task = self.task(project, task_id)
            require(task["state"] == "READY" and task["effect"] == "INTERNAL", "ready internal task required")
            self.check_inputs(project, task); fingerprint = self.input_fingerprint(project, task)
            candidates = []
            for row in self.db.execute("SELECT data FROM projects"):
                source = json.loads(row[0])
                if source["data_origin"] != project["data_origin"] or source["product_line"] != project["product_line"]: continue
                for tid, item in source["tasks"].items():
                    if item["state"] != "DONE" or item["attempts"][-1]["input_digest"] != fingerprint: continue
                    try: self.verify_completed(source, item)
                    except (OperationError, OSError): continue
                    candidates.append({"project_id": source["project_id"], "task_id": tid,
                                       "attempt_id": item["current_attempt"], "result": item["attempts"][-1]["result"]})
            return {"input_digest": fingerprint, "candidates": candidates,
                    "next_action": "claim, submit reused result with usage evidence, then independent review",
                    "automatic_completion": False}

    def handoff(self, project_id, task_id):
        with self.transaction(readonly=True):
            project = self.project(project_id); task = self.task(project, task_id)
            phase = "REVIEW" if task["state"] in {"REVIEW", "REVIEWING"} else "PRODUCTION"
            return {"project_id": project_id, "task_id": task_id, "attempt_id": task["current_attempt"], "state": task["state"],
                    "owner_human_id": task["reviewer_human_id"] if phase == "REVIEW" else task["owner_human_id"],
                    "next_action": "reconcile" if task["state"] == "BLOCKED" else phase.lower(),
                    "inputs": task["inputs"], "context": task.get("context", {}),
                    "dependencies": {d: {"state": project["tasks"][d]["state"],
                        "artifacts": project["tasks"][d]["attempts"][-1].get("result", {}).get("artifacts", [])
                        if project["tasks"][d]["attempts"] else []} for d in task.get("depends_on", [])},
                    "done_when": task["done_when"], "required_checks": task["required_checks"],
                    "workflow_ref": project["workflow_ref"], "policy_ref": project["policy_ref"],
                    "block_reason": task["block_reason"],
                    "remaining_limits": {p["project_id"]: {
                        "cost_units": p["max_cost_units"] - p["spent"] - p["reserved"],
                        "unit": p["budget_unit"]} for p in self.ancestors(project)},
                    "remaining_attempts": 6 - len(task["attempts"]), "evidence_trust": "OPERATOR_SUPPLIED"}
