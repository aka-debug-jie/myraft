"""Real-process election smoke test. Build raft-node.exe first; stdlib only."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / ("raft-node.exe" if os.name == "nt" else "raft-node")
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _stop_process(processes, node_id):
    process = processes[node_id]
    process.kill()
    process.wait(timeout=5)
    processes.pop(node_id)


def _cleanup_processes(processes):
    failures = []
    for node_id, process in list(processes.items()):
        try:
            if process.poll() is None:
                process.kill()
        except Exception as exc:
            failures.append((node_id, exc))
        try:
            process.wait(timeout=5)
        except Exception as exc:
            failures.append((node_id, exc))
    if failures:
        details = "; ".join(f"node {node_id}: {error}" for node_id, error in failures)
        raise RuntimeError(f"failed to clean up smoke-test processes: {details}") from failures[0][1]


def _finalize_result(folder, result, processes, outputs, sockets):
    was_pass = result["result"] == "PASS"
    failures = []
    try:
        _cleanup_processes(processes)
    except Exception as exc:
        failures.append(f"process cleanup: {exc}")
    for resource in [*outputs, *sockets]:
        try:
            resource.close()
        except Exception as exc:
            failures.append(f"resource close: {exc}")
    if failures:
        if was_pass:
            result["result"] = "FAIL"
        result["cleanup_error"] = "; ".join(failures)
    (folder / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if failures and was_pass:
        raise RuntimeError(result["cleanup_error"])


def scenario(count):
    folder = ROOT / ".test-output" / f"smoke-{count}-{time.time_ns()}"
    folder.mkdir(parents=True)
    sockets = []
    processes = {}
    outputs = []
    result = {"nodes": count, "result": "FAIL"}
    try:
        for _ in range(count):
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            sockets.append(s)
        config = {"cluster_id": uuid.uuid4().hex,
                  "nodes": [{"id": i + 1, "addr": f"127.0.0.1:{s.getsockname()[1]}"}
                            for i, s in enumerate(sockets)]}
        config_path = folder / "nodes.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        for s in sockets:
            s.close()

        def start(node_id):
            out = (folder / f"process-{node_id}.log").open("ab")
            outputs.append(out)
            processes[node_id] = subprocess.Popen(
                [str(EXE), "-id", str(node_id), "-config", str(config_path),
                 "-data-dir", str(folder / "data"), "-log-dir", str(folder / "logs")],
                cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, creationflags=FLAGS)

        def stop(node_id):
            _stop_process(processes, node_id)

        def status(node_id):
            p = processes[node_id]
            if p.poll() is not None:
                raise RuntimeError(f"node {node_id} exited: see {folder}")
            r = subprocess.run([str(EXE), "-id", str(node_id), "-config", str(config_path), "-status"],
                               capture_output=True, text=True, timeout=3, creationflags=FLAGS)
            if r.returncode:
                raise RuntimeError(r.stderr)
            result = json.loads(r.stdout)
            assert not result.get("error"), result
            return result

        def converged(timeout=15):
            deadline = time.monotonic() + timeout
            last = []
            while time.monotonic() < deadline:
                try:
                    last = [status(i) for i in processes]
                    leaders = [s for s in last if s["state"] == "Leader"]
                    if len(leaders) == 1:
                        leader = leaders[0]
                        if all(s["term"] == leader["term"] and s["leader_id"] == leader["id"] for s in last):
                            return leader
                except (RuntimeError, subprocess.TimeoutExpired):
                    pass
                time.sleep(0.1)
            raise AssertionError(f"no converged leader: {last}; logs: {folder}")

        for i in range(1, count + 1):
            start(i)
        first = converged()
        print(f"{count} nodes: initial leader {first['id']}, term {first['term']}", flush=True)
        time.sleep(3)
        stable = converged()
        assert (stable["id"], stable["term"]) == (first["id"], first["term"]), "unstable healthy leader"
        begin = time.monotonic()
        stop(first["id"])
        second = converged()
        elapsed = time.monotonic() - begin
        assert second["id"] != first["id"] and second["term"] > first["term"]
        print(f"{count} nodes: killed leader; new leader {second['id']} after {elapsed:.3f}s (polling observation)", flush=True)
        start(first["id"])
        joined = converged()
        assert joined["id"] == second["id"], "rejoining node disrupted leader"
        survivor = first["id"]
        initial_term = status(survivor)["term"]
        for i in list(processes):
            if i != survivor:
                stop(i)
        deadline = time.monotonic() + 15
        minority = status(survivor)
        while minority["term"] <= initial_term and time.monotonic() < deadline:
            assert minority["state"] != "Leader", "minority elected a leader"
            time.sleep(0.2)
            minority = status(survivor)
        assert minority["state"] != "Leader" and minority["term"] > initial_term
        result = {"nodes": count, "initial_leader": first, "replacement_leader": second,
                  "observed_failover_seconds": elapsed, "restart_joined": True,
                  "minority_rejected": True, "result": "PASS"}
    except KeyboardInterrupt as exc:
        result["result"] = "INTERRUPTED"
        result["error"] = str(exc) or "KeyboardInterrupt"
        raise
    except Exception as exc:
        result["result"] = "FAIL"
        result["error"] = str(exc)
        raise
    finally:
        _finalize_result(folder, result, processes, outputs, sockets)
    print(f"{count} nodes: PASS restart and minority checks; evidence: {folder}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", nargs="+", type=int, default=[3, 11])
    args = parser.parse_args()
    if any(n < 3 for n in args.nodes):
        parser.error("failover scenarios require at least 3 nodes")
    for count in args.nodes:
        scenario(count)
