# SPDX-License-Identifier: BUSL-1.1
"""SAP v7 Q7 harness (§14) on hand-written fake BFCL data.

No BFCL entry is read: the data directory below is invented, and its hashes
are passed in place of the §14.2 pins. Model clients and the environment are
fakes, and sockets are blocked.
"""
from __future__ import annotations

import hashlib
import json
import socket
from types import SimpleNamespace

import pytest

from experiments.routing_baselines import arms, labels, pins, split, study, trajectory
from experiments.sap_v7_addenda import seal
from experiments.sap_v7_addenda.budget import BudgetExceeded, ModelReply, Usage


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access in an offline test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _doc(name, props=None, required=()):
    return {"name": name, "description": f"{name} does a thing.",
            "parameters": {"type": "dict", "properties": props or {}, "required": list(required)},
            "response": {}}


DOCS = {
    "GorillaFileSystem": [_doc("ls"), _doc("cd", {"folder": {"type": "string"}}, ["folder"]),
                          _doc("mv", {"source": {"type": "string"},
                                      "destination": {"type": "string"}},
                               ["source", "destination"])],
    "MathAPI": [_doc("add", {"a": {"type": "float"}, "b": {"type": "float"}}, ["a", "b"])],
    "TwitterAPI": [_doc("post_tweet", {"content": {"type": "string"},
                                       "tags": {"type": "array", "items": {"type": "string"}}},
                        ["content"])],
}
WRITE = frozenset({"mv", "post_tweet"})
N_ENTRIES = 12


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "data"
    (root / "possible_answer").mkdir(parents=True)
    (root / "multi_turn_func_doc").mkdir()
    for cls, rel in pins.CLASS_FILES.items():
        (root / rel).write_text("".join(json.dumps(d) + "\n" for d in DOCS.get(cls, [])))
    for category in pins.CATEGORIES:
        rows, answers = [], []
        for i in range(N_ENTRIES):
            entry_id = f"{category}_{i}"
            question = [[{"role": "user", "content": "Move report.txt into archive."}],
                        [{"role": "user", "content": "Now list the files."}]]
            truth = [["mv(source='report.txt', destination='archive')"], ["ls()"]]
            row = {"id": entry_id, "question": question, "initial_config": {"n": i},
                   "path": [], "involved_classes": ["GorillaFileSystem"]}
            if category == "multi_turn_miss_func":
                row["missed_function"] = {"1": ["ls"]}
            rows.append(row)
            answers.append({"id": entry_id, "ground_truth": truth})
        (root / f"BFCL_v4_{category}.json").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (root / "possible_answer" / f"BFCL_v4_{category}.json").write_text(
            "".join(json.dumps(a) + "\n" for a in answers))
    files = {rel: _sha(root / rel) for rel in pins.FILES}
    catalogue, owner = labels.load_catalogue(root)
    return SimpleNamespace(root=root, files=files, catalogue=catalogue, owner=owner)


def _lock(tmp_path, **extra):
    (tmp_path / "h.txt").write_text("h")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"status": seal.STATUS_LOCKED, "seed": seal.SEED,
                                "files": {"h.txt": seal.lf_sha256(tmp_path / "h.txt")}, **extra}))
    return seal.open_locked_manifest(path, tmp_path, ["h.txt"])


# ── pins and split ──────────────────────────────────────────────────────


def test_pins_are_the_plans(data):
    assert pins.COMMIT == "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
    assert len(pins.FILES) == 16 and len(pins.CLASS_FILES) == 8
    with pytest.raises(seal.RunRefused, match="differs from the pin"):
        pins.verify_data(data.root)
    pins.verify_data(data.root, data.files)


def test_seeded_split_is_a_quarter_and_deterministic():
    keys = [str(i) for i in range(split.N_BASE)]
    dev = split.seeded_dev(keys)
    assert len(dev) == 50 and dev == split.seeded_dev(reversed(keys))
    assert dev != split.seeded_dev(keys, seed=1)


def test_all_four_categories_of_an_index_go_to_one_side(data):
    s = split.draw_split(split.structural_fields(data.root))
    assert s.unit == "index" and not (s.dev & s.test)
    assert len(s.dev) + len(s.test) == 4 * N_ENTRIES
    for i in range(N_ENTRIES):
        sides = {f"{c}_{i}" in s.dev for c in pins.CATEGORIES}
        assert len(sides) == 1
    assert s.cluster("multi_turn_miss_param_3") == "index:3"


def test_misaligned_categories_fall_back_to_entry_split(data):
    structure = split.structural_fields(data.root)
    structure["multi_turn_long_context_0"] = (("MathAPI",), "{}")
    s = split.draw_split(structure)
    assert s.unit == "entry" and s.cluster("multi_turn_base_1") == "multi_turn_base_1"


def test_builders_never_release_the_test_split_without_a_lock(data, tmp_path):
    s = split.draw_split(split.structural_fields(data.root))
    assert s.test, "the fake data must put some entries in test"
    with pytest.raises(seal.RunRefused, match="locked manifest"):
        split.load_entries(data.root, s, "test", files=data.files)
    with pytest.raises(seal.RunRefused):
        split.load_entries(data.root, s, "test", lock=SimpleNamespace(), files=data.files)
    dev = split.load_entries(data.root, s, "dev", files=data.files)
    assert {e.entry_id for e in dev} == set(s.dev)
    assert not {e.entry_id for e in dev} & s.test
    test = split.load_entries(data.root, s, "test", lock=_lock(tmp_path), files=data.files)
    assert {e.entry_id for e in test} == set(s.test)


def test_runner_split_mode_reads_structure_only(repo_root, data, monkeypatch, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("rrb", repo_root / "scripts" / "run_routing_baselines.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.pins, "FILES", data.files)
    assert mod.main(["--split", str(data.root)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["unit"] == "index" and "Move report" not in json.dumps(printed)


# ── label matcher ───────────────────────────────────────────────────────


def test_parse_call_is_literal_only():
    assert labels.parse_call("mv(source='a', destination='b')") == ("mv", {"source": "a", "destination": "b"})
    assert labels.parse_call("ls()") == ("ls", {})
    for bad in ("mv('a')", "os.system('x')", "f(x=open('y'))", "f(**k)", "not a call"):
        with pytest.raises(labels.GroundTruthError):
            labels.parse_call(bad)


def test_each_label(data):
    cat = data.catalogue
    gt = ["mv(source='report.txt', destination='archive')", "add(a=1, b=2.5)"]
    assert labels.label_call("mv", {"destination": "archive", "source": "report.txt"}, gt, cat) == labels.GOLD
    assert labels.label_call("add", {"a": "1", "b": 2.5}, gt, cat) == labels.GOLD  # coercion
    assert labels.label_call("mv", {"source": "report.txt", "destination": "x"}, gt, cat) == labels.WRONG_ARGUMENT
    assert labels.label_call("cd", {"folder": "x"}, gt, cat) == labels.WRONG_TOOL
    assert labels.label_call("cd", {"folder": "x"}, [], cat) == labels.IRRELEVANT_CALL
    assert labels.label_call("rm_rf", {}, gt, cat) == labels.MALFORMED
    assert labels.label_call("mv", '{"source": ', gt, cat) == labels.MALFORMED


def test_primary_and_secondary_sets():
    assert labels.in_primary_wrong_set(labels.WRONG_TOOL, "mv", WRITE)
    assert not labels.in_primary_wrong_set(labels.WRONG_TOOL, "ls", WRITE)
    assert not labels.in_primary_wrong_set(labels.GOLD, "mv", WRITE)
    assert not labels.in_primary_wrong_set(labels.MALFORMED, "mv", WRITE)
    assert labels.in_secondary_set(labels.IRRELEVANT_CALL) and not labels.in_secondary_set(labels.MALFORMED)


def test_adjudication_sample_is_seeded():
    ids = [f"c{i}" for i in range(500)]
    sample = labels.adjudication_sample(ids)
    assert len(sample) == 200 and sample == labels.adjudication_sample(list(reversed(ids)))
    assert labels.adjudication_sample(ids[:10]) == sorted(ids[:10])


# ── arms ─────────────────────────────────────────────────────────────────


def _ctx(data, name="mv", args=None, turns=("Move report.txt into archive.",)):
    transcript = ({"role": "user", "content": turns[0]},
                  {"role": "assistant", "content": "", "tool_calls": [
                      {"id": "1", "type": "function", "function": {"name": "ls", "arguments": {}}}]},
                  {"role": "tool", "tool_call_id": "1", "content": '{"files": ["report.txt"]}'})
    return arms.CallContext("c1", "multi_turn_base_0", 0, name,
                            args if args is not None else {"source": "report.txt",
                                                           "destination": "archive"},
                            tuple(turns), transcript,
                            tuple(DOCS["GorillaFileSystem"]), ("GorillaFileSystem",))


def test_control_and_allow(data):
    assert not arms.control(_ctx(data)).passed and arms.allow(_ctx(data)).passed


def test_n1_is_the_committed_rule(data):
    n1 = arms.NameOverlapN1()
    mod = arms._posthoc_module()
    ctx = _ctx(data, "post_tweet", turns=("Please post a tweet about cats.",))
    expected = len(mod.name_tokens("post_tweet") & mod.task_words(ctx.task_text)) >= 2
    assert n1(ctx).passed is expected is True
    assert not n1(_ctx(data, "mv")).passed


class _Judge:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def send(self, request):
        self.requests.append(request)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _r(text, stop="end_turn"):
    return ModelReply(text, stop, Usage(1, 1))


def test_judge_request_and_accept(data):
    template = arms.JUDGE_PROMPT.read_text(encoding="utf-8")
    client = _Judge([_r('{"decision": "ACCEPT", "risk": 12}')])
    d = arms.LLMJudge(client, template)(_ctx(data))
    assert d.passed and d.risk == 12
    req = client.requests[0]
    assert (req.model, req.effort, req.max_tokens) == ("claude-sonnet-5-5", "low", 2048)
    assert req.json_schema == arms.JUDGE_SCHEMA and not req.sampling
    prompt = req.messages[0]["content"]
    assert "report.txt" in prompt and "{proposed_call}" not in prompt
    j2 = arms.LLMJudge(_Judge([_r('{"decision": "VERIFY", "risk": 50}')]), template, name="J2",
                       model=arms.J2_MODEL, provider="groq")
    assert j2.request(_ctx(data)).sampling == {"temperature": 0.0}


def test_judge_retries_once_then_verify(data):
    client = _Judge([_r("", "refusal"), _r('{"decision": "ABSTAIN", "risk": 90}')])
    d = arms.LLMJudge(client, "{proposed_call}")(_ctx(data))
    assert not d.passed and d.decision == "abstain" and d.detail["failures"] == ["refusal"]
    d = arms.LLMJudge(_Judge([_r("nope"), RuntimeError("down")]), "{proposed_call}")(_ctx(data))
    assert (d.passed, d.decision, d.risk) == (False, "verify", None)
    for bad in ('{"decision": "ACCEPT", "risk": 101}', '{"decision": "YES", "risk": 1}',
                '{"decision": "ACCEPT", "risk": true}', "[]"):
        assert arms.parse_judge(bad) is None
    with pytest.raises(BudgetExceeded):
        arms.LLMJudge(_Judge([BudgetExceeded("cap")]), "{proposed_call}")(_ctx(data))


def test_j_tau_and_calibration():
    d = arms.ArmDecision("J", False, "verify", risk=30)
    assert arms.j_tau(d, 30).passed and not arms.j_tau(d, 29).passed
    assert not arms.j_tau(arms.ArmDecision("J", False, "verify"), 100).passed
    rows = [(10, True), (20, True), (90, True), (5, False)] + [(95, True)] * 97
    assert arms.calibrate_tau(rows, 0.0) == 19  # 1 % target: 1 of 100 wrong calls may pass
    assert arms.calibrate_tau(rows, 0.02) == 89
    with pytest.raises(ValueError):
        arms.calibrate_tau([(1, False)], 0.0)
    with pytest.raises(ValueError):
        arms.calibrate_tau([(0, True)], 0.0)


def test_ig_parameters_and_value_tags(data):
    assert arms.value_type_tag(3, "float") == "float" and arms.value_type_tag(3.0, "integer") == "integer"
    assert arms.value_type_tag(True, "integer") == "boolean" and arms.value_type_tag([1], "tuple") == "tuple"
    p = arms.ig_parameters(_ctx(data, "cd", {"folder": 3}), data.catalogue, data.owner, WRITE)
    assert p["allowed_tools"] == ["cd", "ls", "mv"] and p["pending_type_pairs"] == [["string", "integer"]]
    assert p["pending_required"] == ["folder"] and p["pending_is_write"] is False
    assert p["seen_text"] == ["Move report.txt into archive.", '{"files": ["report.txt"]}']


def test_invariant_arm_blocks_on_violation_or_exception(data):
    seen = {}

    class Policy:
        def __init__(self, errors=(), boom=False):
            self.errors, self.boom = errors, boom

        def analyze_pending(self, past, pending, **params):
            seen.update(params, past=past, pending=pending)
            if self.boom:
                raise RuntimeError("engine")
            return SimpleNamespace(errors=[SimpleNamespace(args=(e,)) for e in self.errors])

    ok = arms.InvariantArm(Policy(), data.catalogue, data.owner, WRITE)(_ctx(data))
    assert ok.passed and seen["pending"][0]["tool_calls"][0]["function"]["name"] == "mv"
    assert len(seen["past"]) == 3
    blocked = arms.InvariantArm(Policy(["write_value_unseen"]), data.catalogue, data.owner, WRITE)(_ctx(data))
    assert not blocked.passed and blocked.reasons == ("write_value_unseen",)
    err = arms.InvariantArm(Policy(boom=True), data.catalogue, data.owner, WRITE)(_ctx(data))
    assert not err.passed and err.decision == "error"


def test_committed_ig_dev_check_matches_the_rule_file(repo_root):
    """§15.5 item 5: the recorded run used the rule file and trace as committed."""
    base = repo_root / "experiments" / "routing_baselines"
    record = json.loads((base / "ig_dev_check_v1.json").read_text(encoding="utf-8"))
    assert record["invariant_ai_version"] == "0.3.5" and record["all_as_expected"]
    assert record["rules_sha256_lf"] == seal.lf_sha256(base / "ig_rules_v1.gr")
    assert record["trace_sha256_lf"] == seal.lf_sha256(base / "ig_dev_trace_v1.json")
    trace = json.loads((base / "ig_dev_trace_v1.json").read_text(encoding="utf-8"))
    assert [c["case"] for c in record["cases"]] == [c["case"] for c in trace["cases"]]
    assert "LocalPolicy" in (base / "arms.py").read_text(encoding="utf-8")


def test_remora_arms_route_offline(data):
    for strict in (False, True):
        arm = arms.RemoraRouting(WRITE, data.owner, strict=strict)
        d = arm(_ctx(data))
        assert d.arm == ("R-strict" if strict else "R")
        assert d.decision in {"accept", "verify", "escalate", "abstain"}
        assert d.passed == (d.decision == "accept")
    assert not arms.RemoraRouting(WRITE, data.owner)(_ctx(data, args="{bad")).passed
    assert arms.observed_state_values(['{"a": ["x", 2]}', "plain"]) == {"x", "2", "plain"}


# ── trajectories ────────────────────────────────────────────────────────


class FakeEnv:
    def __init__(self):
        self.executed = []

    def execute(self, name, arguments):
        self.executed.append((name, dict(arguments)))
        return json.dumps({"ok": name})


class FakeK1:
    """Moves the file in turn 0, lists in turn 1, then stops each turn."""

    def __init__(self, fail=0):
        self.requests, self.fail = [], fail

    def send(self, request):
        self.requests.append(request)
        if self.fail:
            self.fail -= 1
            raise RuntimeError("api down")
        last = request.messages[-1]
        if isinstance(last["content"], list):  # tool results came back
            return ModelReply("done", "end_turn", Usage(1, 1),
                              raw_content=({"type": "text", "text": "done"},))
        name, args = (("mv", {"source": "report.txt", "destination": "archive"})
                      if "Move" in last["content"] else ("ls", {}))
        block = {"type": "tool_use", "id": f"t{len(self.requests)}", "name": name, "input": args}
        return ModelReply("", "tool_use", Usage(1, 1),
                          ({"id": block["id"], "name": name, "arguments": args},), (block,))


def _entries(data, tmp_path, side="test"):
    s = split.draw_split(split.structural_fields(data.root))
    return split.load_entries(data.root, s, side, lock=_lock(tmp_path), files=data.files)


def test_trajectory_logs_each_call_with_the_context_before_it(data, tmp_path):
    entry = next(e for e in _entries(data, tmp_path) if e.entry_id.startswith("multi_turn_base"))
    env = FakeEnv()
    run = trajectory.run_entry(entry, trajectory.AGENTS["K1"], FakeK1(), env, data.catalogue,
                               data.owner)
    assert [c["tool_name"] for c in run["calls"]] == ["mv", "ls"] and len(env.executed) == 2
    first, second = run["contexts"]
    assert all(m.get("role") != "tool" for m in first.transcript)
    assert second.user_turns == ("Move report.txt into archive.", "Now list the files.")
    assert any(m.get("role") == "tool" for m in second.transcript)
    lab = study.label_run(run, entry, data.catalogue)
    assert set(lab.values()) == {labels.GOLD}


def test_available_functions_honour_missed_and_excluded(data, tmp_path):
    entry = next(e for e in _entries(data, tmp_path) if "miss_func" in e.entry_id)
    names = lambda t: [d["name"] for d in trajectory.available_docs(entry, t, data.catalogue, data.owner)]  # noqa: E731
    assert "ls" not in names(0) and "ls" in names(1)
    from dataclasses import replace
    assert "cd" not in [d["name"] for d in trajectory.available_docs(
        replace(entry, excluded_functions=("cd",)), 1, data.catalogue, data.owner)]


def test_empty_turn_needs_bfcl_text(data, tmp_path):
    from dataclasses import replace
    entry = _entries(data, tmp_path)[0]
    empty = replace(entry, turns=[entry.turns[0], []])
    with pytest.raises(ValueError, match="empty"):
        trajectory.run_entry(empty, trajectory.AGENTS["K1"], FakeK1(), FakeEnv(), data.catalogue,
                             data.owner)
    run = trajectory.run_entry(empty, trajectory.AGENTS["K1"], FakeK1(), FakeEnv(), data.catalogue,
                               data.owner, empty_turn_text="Now list the files.")
    assert len(run["calls"]) == 2


def test_api_error_stops_the_entry_and_step_limit_is_kept(data, tmp_path):
    entry = _entries(data, tmp_path)[0]
    run = trajectory.run_entry(entry, trajectory.AGENTS["K1"], FakeK1(fail=4), FakeEnv(),
                               data.catalogue, data.owner)
    assert run["stopped_at_turn"] == 0 and run["turns_not_run"] == [0, 1]

    class Looper(FakeK1):
        def send(self, request):
            self.requests.append(request)
            block = {"type": "tool_use", "id": f"t{len(self.requests)}", "name": "ls", "input": {}}
            return ModelReply("", "tool_use", Usage(1, 1),
                              ({"id": block["id"], "name": "ls", "arguments": {}},), (block,))

    looper = Looper()
    run = trajectory.run_entry(entry, trajectory.AGENTS["K1"], looper, FakeEnv(), data.catalogue,
                               data.owner)
    assert run["step_limit_turns"] == [0, 1]
    assert len(looper.requests) == 2 * trajectory.MAX_STEPS_PER_TURN


def test_provider_messages(data):
    transcript = [{"role": "user", "content": "u"},
                  {"role": "assistant", "content": "", "tool_calls": [
                      {"id": "a", "type": "function", "function": {"name": "ls", "arguments": {}}},
                      {"id": "b", "type": "function", "function": {"name": "cd", "arguments": {"folder": "x"}}}]},
                  {"role": "tool", "tool_call_id": "a", "content": "1"},
                  {"role": "tool", "tool_call_id": "b", "content": "2"}]
    raw = {1: ({"type": "thinking", "thinking": "", "signature": "s"},)}
    k1 = trajectory.agent_request(trajectory.AGENTS["K1"], transcript, raw, DOCS["GorillaFileSystem"])
    assert k1.effort == "low" and k1.messages[1]["content"][0]["type"] == "thinking"
    assert [b["tool_use_id"] for b in k1.messages[2]["content"]] == ["a", "b"]
    k2 = trajectory.agent_request(trajectory.AGENTS["K2"], transcript, raw, DOCS["GorillaFileSystem"])
    assert k2.sampling == {"temperature": 0.0, "top_p": 1.0}
    assert json.loads(k2.messages[1]["tool_calls"][1]["function"]["arguments"]) == {"folder": "x"}


# ── end to end, gated ────────────────────────────────────────────────────


def test_judge_selection_keeps_every_non_gold_call():
    calls = {f"g{i}": labels.GOLD for i in range(10)} | {"w1": labels.WRONG_TOOL, "m": labels.MALFORMED}
    chosen, fraction = study.judge_selection(calls, capacity=6, seed=seal.SEED)
    assert {"w1", "m"} <= set(chosen) and len(chosen) == 6 and fraction == pytest.approx(0.4)
    assert study.judge_selection(calls, 100, seal.SEED)[1] == 1.0


def test_run_study_end_to_end_with_fakes(data, tmp_path):
    lock = _lock(tmp_path, judge_tau=40)
    judge = arms.LLMJudge(_Judge([_r('{"decision": "VERIFY", "risk": 30}')] * 200), "{proposed_call}")
    out = tmp_path / "raw.json"
    with pytest.raises(seal.RunRefused):
        study.run_study(None, data.root, client_for=lambda a: FakeK1(), env_for=lambda e: FakeEnv(),
                        arms=[], catalogue=data.catalogue, owner=data.owner, write_tools=WRITE,
                        out=out, files=data.files)
    body = study.run_study(lock, data.root, client_for=lambda a: FakeK1(),
                           env_for=lambda e: FakeEnv(),
                           arms=[arms.control, arms.allow, judge,
                                 arms.RemoraRouting(WRITE, data.owner)],
                           catalogue=data.catalogue, owner=data.owner, write_tools=WRITE, out=out,
                           empty_turn_text="Go on.", files=data.files)
    assert body["agents_run"] == ["K1", "K2"]  # no wrong calls, so K2 runs too
    row = body["decisions"][0]
    assert set(row["arms"]) == {"CONTROL", "ALLOW", "J", "J-tau", "R"}
    assert row["arms"]["J-tau"]["passed"] and not row["arms"]["J"]["passed"]
    assert all(r["entry_id"] in split.draw_split(split.structural_fields(data.root)).test
               for r in body["decisions"])
    with pytest.raises(seal.RunRefused, match="second run"):
        seal.open_locked_manifest(lock.path, tmp_path, ["h.txt"])
