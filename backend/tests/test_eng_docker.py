"""① 실제 Docker daemon으로 풀이 격리·고아 컨테이너 회수를 확인합니다."""

import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from conftest import load
from test_eng_queue import clean_queue as clean_queue
from test_eng_resume import change
from test_eng_stdio import ARGS, connect_to, enqueue, rows
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.common.snapshot import merge_snapshot
from slotagent.engine import eng_docker
from slotagent.engine.loop import RunCancelled, ToolEnvironmentError
from slotagent.workers.eng_main import run_once


@pytest.fixture(scope="module")
def docker_cli():
    executable = shutil.which("docker")
    if executable is None:
        pytest.skip("Docker CLI가 없어 Docker 통합 검사를 건너뜁니다.")
    try:
        check = subprocess.run([executable, "info", "--format", "{{.OSType}}"], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("Docker daemon에 연결할 수 없어 Docker 통합 검사를 건너뜁니다.")
    if check.returncode != 0 or check.stdout.strip() != b"linux":
        pytest.skip("접근 가능한 Linux Docker daemon이 없어 Docker 통합 검사를 건너뜁니다.")
    return executable


def docker(cli, *args, **kwargs):
    return subprocess.run([cli, *args], capture_output=True, timeout=30, check=True, **kwargs).stdout.decode().strip()


@pytest.fixture(scope="module")
def docker_resources(docker_cli):
    scope = "eng-docker-test-" + uuid4().hex
    image, volume = scope + ":test", scope + "-data"
    recipe = (
        "FROM python:3.12-slim\nWORKDIR /app\nCOPY eng_stdio_server.py /app/server.py\n"
        f"LABEL io.slotagent.test-run={scope}\n"
        'USER 65534:65534\nENTRYPOINT ["python","-u","/app/server.py"]\n'
    ).encode()
    server = Path(__file__).with_name("eng_stdio_server.py").read_bytes()
    context = io.BytesIO()
    with tarfile.open(fileobj=context, mode="w") as archive:
        for name, data in [("Dockerfile", recipe), ("eng_stdio_server.py", server)]:
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    built, created = False, False
    try:
        subprocess.run(
            [docker_cli, "build", "-q", "-t", image, "-"],
            input=context.getvalue(),
            capture_output=True,
            timeout=180,
            check=True,
        )
        built = True
        docker(docker_cli, "volume", "create", volume)
        created = True
        docker(
            docker_cli,
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0",
            "--mount",
            f"type=volume,source={volume},target=/data",
            "--entrypoint",
            "python",
            image,
            "-c",
            "from pathlib import Path; p=Path('/data/check.txt'); p.write_text('frozen'); p.chmod(0o666)",
        )
        yield {"scope": scope, "image": image, "volume": volume, "cli": docker_cli}
    finally:
        # 이번 fixture가 만든 scope/tag/volume만 제거하며 전역 prune은 하지 않습니다.
        ids = docker(docker_cli, "ps", "-aq", "--filter", f"label=io.slotagent.scope={scope}").split()
        if ids:
            docker(docker_cli, "rm", "-f", *ids)
        if created:
            docker(docker_cli, "volume", "rm", volume)
        if built:
            docker(docker_cli, "image", "rm", image)


def snapshot():
    data = load("slot_and_candidates.json")
    return merge_snapshot(load("agent_version.json"), data["slot"], data["candidates"][0])


def config(resources, mode="ok", timeout_sec=5, image=None):
    tools = [{"name": t["name"], "inputSchema": t["parameters"]} for t in snapshot()["tools"] if t["access"] == "read"]
    server = eng_docker.DockerServer(
        image=image or resources["image"],
        arguments=(json.dumps({"tools": tools, "mode": mode}),),
        mounts=(eng_docker.ReadOnlyMount(resources["volume"], "/data", kind="volume"),),
    )
    return eng_docker.DockerStdioConfig(
        {"github": server}, scope=resources["scope"], docker=resources["cli"], timeout_sec=timeout_sec
    )


def execution(trial=1, attempt=1, job=1, lease=1):
    return {"trial_id": trial, "attempt": attempt, "job_id": job, "lease_attempt": lease}


def owned(resources):
    return docker(resources["cli"], "ps", "-aq", "--filter", f"label=io.slotagent.scope={resources['scope']}").split()


@pytest.fixture(autouse=True)
def clean_containers(request):
    yield
    if "docker_resources" in request.fixturenames:
        resources = request.getfixturevalue("docker_resources")
        ids = owned(resources)
        if ids:
            docker(resources["cli"], "rm", "-f", *ids)


@pytest.mark.parametrize("kind", ["missing_image", "bad_command", "bad_mount"])
def test_docker_start_failure(docker_resources, kind):
    setting = config(docker_resources, image="eng-no-such-image:" + uuid4().hex if kind == "missing_image" else None)
    if kind == "bad_command":
        setting = eng_docker.DockerStdioConfig(
            {"github": eng_docker.DockerServer(docker_resources["image"], entrypoint="/does-not-exist")},
            scope=docker_resources["scope"],
            docker=docker_resources["cli"],
        )
    if kind == "bad_mount":
        setting = eng_docker.DockerStdioConfig(
            {
                "github": eng_docker.DockerServer(
                    docker_resources["image"], mounts=(eng_docker.ReadOnlyMount("/eng/path/does-not-exist", "/data"),)
                )
            },
            scope=docker_resources["scope"],
            docker=docker_resources["cli"],
        )
    with pytest.raises(ToolEnvironmentError):
        with setting.open(snapshot(), execution=execution()):
            raise AssertionError("시작 실패 뒤 실행하면 안 됩니다.")
    assert owned(docker_resources) == []


def test_docker_initialize_timeout(docker_resources):
    with pytest.raises(ToolEnvironmentError):
        with config(docker_resources, "init_timeout", timeout_sec=0.5).open(snapshot(), execution=execution()):
            raise AssertionError("초기화 무응답을 통과하면 안 됩니다.")
    assert owned(docker_resources) == []


def test_docker_isolation(docker_resources, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "eng-parent-sentinel")
    monkeypatch.setenv("DATABASE_URL", "eng-parent-db-sentinel")
    with config(docker_resources, "isolation_probe").open(snapshot(), execution=execution()) as call:
        result = json.loads(call("list_issues", ARGS, 3))
        assert result["network_error"] == "ENETUNREACH"
        assert result["write_error"] == "EROFS" and result["data"] == "frozen"
        assert not result["has_parent_secrets"]
        ids = owned(docker_resources)
        assert len(ids) == 1
        info = json.loads(docker(docker_resources["cli"], "inspect", ids[0]))[0]
        host = info["HostConfig"]
        assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"] and host["Init"]
        assert host["Memory"] == 128 * 1024 * 1024 and host["NanoCpus"] == 1000000000 and host["PidsLimit"] == 64
        assert info["Config"]["User"] == "65534:65534"
        assert all(not m["RW"] for m in info["Mounts"] if m["Destination"] == "/data")
        assert not any("eng-parent-" in value for value in info["Config"]["Env"])
    assert owned(docker_resources) == []


def test_docker_retry_names_unique(docker_resources):
    setting = config(docker_resources)
    with setting.open(snapshot(), execution=execution()) as first:
        assert json.loads(first("list_issues", ARGS, 3))[0]["number"] == 145
        one = json.loads(docker(docker_resources["cli"], "inspect", owned(docker_resources)[0]))[0]
        with setting.open(snapshot(), execution=execution(attempt=2, lease=2)):
            containers = [
                json.loads(docker(docker_resources["cli"], "inspect", cid))[0] for cid in owned(docker_resources)
            ]
            assert len({c["Name"] for c in containers}) == 2
            assert {c["Config"]["Labels"]["io.slotagent.lease"] for c in containers} == {"1", "2"}
        assert len(owned(docker_resources)) == 1 and one["Name"]
    assert owned(docker_resources) == []


@pytest.mark.parametrize("kind", ["timeout", "cancel"])
def test_docker_call_abort(docker_resources, kind):
    cancelled = Event()
    with config(docker_resources, "call_timeout").open(
        snapshot(), execution=execution(), cancel_signals=(cancelled.is_set,)
    ) as call:
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(call, "list_issues", ARGS, 0.5 if kind == "timeout" else 5)
            if kind == "cancel":
                time.sleep(0.1)
                cancelled.set()
            with pytest.raises(ToolEnvironmentError if kind == "timeout" else RunCancelled):
                pending.result(timeout=10)
    assert owned(docker_resources) == []


def test_docker_worker_round_trip(experiment, engine_db, docker_resources):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    assert run_once(connect_to(engine_db), "docker", deps=dependencies(), stdio=config(docker_resources))
    assert rows(conn, "trials", ["status"], "id", trial) == [("finished",)]
    assert rows(conn, "jobs", ["status"], "id", job) == [("done",)]
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 2
    assert owned(docker_resources) == []


def test_docker_reclaim_preserves_other_lease(docker_resources):
    setting = config(docker_resources)
    with setting.open(snapshot(), execution=execution()):
        with setting.open(snapshot(), execution=execution(attempt=2, lease=2)) as current:
            setting.reclaim_expired([{"kind": "run_trial", "job_id": 1, "attempts": 1, "payload": {"trial_id": 1}}])
            assert len(owned(docker_resources)) == 1
            assert json.loads(current("list_issues", ARGS, 3))[0]["number"] == 145
    assert owned(docker_resources) == []


def test_docker_reclaim_sweeps_late_orphan(experiment, engine_db, docker_resources):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    setting = config(docker_resources)
    assert run_once(connect_to(engine_db), "first", deps=dependencies(), stdio=setting)
    # 종료한 job의 옛 Docker 생성 요청이 뒤늦게 반영된 상황을 재현합니다.
    with setting.open(snapshot(), execution=execution(trial=trial, job=job)):
        assert owned(docker_resources)
        assert not run_once(connect_to(engine_db), "sweeper", deps=dependencies(), stdio=setting)
        assert owned(docker_resources) == []
    assert rows(conn, "trials", ["status"], "id", trial) == [("finished",)]
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 2


def test_docker_reclaim_preserves_current_db_lease(experiment, docker_resources):
    conn, ids = experiment
    trial = ids["trials"][0]
    job_id = enqueue(conn, trial)
    job = queue.lease(conn, "active")
    change(conn, "trials", "id", trial, status="running")
    setting = config(docker_resources)
    with setting.open(snapshot(), execution=execution(trial=trial, job=job_id)) as call:
        setting.reclaim_expired([], conn=conn)
        assert len(owned(docker_resources)) == 1
        assert json.loads(call("list_issues", ARGS, 3))[0]["number"] == 145
    queue.fail(conn, job, retry=False, error="test_end")
    assert owned(docker_resources) == []


def test_docker_worker_kill_reclaim(experiment, engine_db, docker_resources, monkeypatch):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    tools = [{"name": t["name"], "inputSchema": t["parameters"]} for t in snapshot()["tools"] if t["access"] == "read"]
    code = (
        "import json,sys,time,psycopg; from slotagent.common import queue; "
        "from slotagent.engine.eng_docker import DockerServer,DockerStdioConfig; "
        "from slotagent.engine.worker import run_trial; from slotagent.engine.loop import Dependencies; "
        "from slotagent.common.llm import FakeModel,Reply,ToolCall; "
        "c=psycopg.connect(sys.argv[1],autocommit=True); j=queue.lease(c,'dead'); "
        "s=DockerStdioConfig({'github':DockerServer(sys.argv[2],arguments=(sys.argv[4],))},scope=sys.argv[3],docker=sys.argv[5]); "
        'm=FakeModel([Reply(tool_calls=(ToolCall(\'a\',\'list_issues\',\'{"owner":"acme","repo":"ops-service"}\'),))]); '
        "run_trial(c,j['payload']['trial_id'],deps=Dependencies(m,lambda *a:''),job=j,stdio=s)"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(eng_docker.__file__).resolve().parents[2])}
    worker = subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
            engine_db,
            docker_resources["image"],
            docker_resources["scope"],
            json.dumps({"tools": tools, "mode": "call_timeout"}),
            docker_resources["cli"],
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and worker.poll() is None:
            if owned(docker_resources) and rows(conn, "cost_ledger", ["id"], "ref_id", trial):
                break
            time.sleep(0.05)
        assert owned(docker_resources), "워커가 컨테이너를 시작하지 못했습니다."
        worker.kill()
        worker.wait(timeout=5)
        change(conn, "jobs", "id", job, lease_until="2000-01-01T00:00:00Z")
        lease = queue.lease

        def after_cleanup(*args, **kwargs):
            assert owned(docker_resources) == []
            assert rows(conn, "trials", ["status", "attempt"], "id", trial) == [("pending", 2)]
            assert rows(conn, "jobs", ["status"], "id", job) == [("queued",)]
            return lease(*args, **kwargs)

        monkeypatch.setattr(queue, "lease", after_cleanup)
        assert run_once(connect_to(engine_db), "replacement", deps=dependencies(), stdio=config(docker_resources))
        assert owned(docker_resources) == []
        assert rows(conn, "trials", ["status", "attempt"], "id", trial) == [("finished", 2)]
        assert rows(conn, "jobs", ["status"], "id", job) == [("done",)]
        assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 3
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=5)


def test_docker_reclaim_failure_blocks_requeue(experiment):
    conn, ids = experiment
    trial = ids["trials"][0]
    job_id = enqueue(conn, trial)
    job = queue.lease(conn, "dead")
    change(conn, "trials", "id", trial, status="running")
    change(conn, "jobs", "id", job_id, lease_until="2000-01-01T00:00:00Z")

    def unavailable(jobs):
        assert jobs[0]["job_id"] == job["job_id"]
        raise ToolEnvironmentError()

    with pytest.raises(ToolEnvironmentError):
        queue.reclaim(conn, cleanup_expired=unavailable)
    assert rows(conn, "jobs", ["status"], "id", job_id) == [("leased",)]
    assert rows(conn, "trials", ["status"], "id", trial) == [("running",)]
    assert queue.reclaim(conn) == 1


def test_docker_secret_environment_rejected():
    with pytest.raises(ValueError):
        eng_docker.DockerServer("test", environment={"OPENAI_API_KEY": "eng-sentinel"})


def test_docker_environment_snapshot():
    values = {"TZ": "UTC"}
    server = eng_docker.DockerServer("test", environment=values)
    values["OPENAI_API_KEY"] = "eng-sentinel"
    assert dict(server.environment) == {"TZ": "UTC"}
    with pytest.raises(TypeError):
        server.environment["DATABASE_URL"] = "eng-sentinel"


@pytest.mark.parametrize("memory,cpus,pids", [(128, 1, 64), (256, 0.5, 32)])
def test_linux_docker_argv_without_docker(monkeypatch, memory, cpus, pids):
    def forbidden(*args, **kwargs):
        raise AssertionError("argv 단위 검사는 Docker나 외부 프로세스를 실행하면 안 됩니다.")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    image = "sha256:" + "a" * 64
    server = eng_docker.DockerServer(
        "practice:fixed",
        arguments=("server-config-json",),
        mounts=(eng_docker.ReadOnlyMount("/srv/slotagent/frozen data", "/data"),),
        memory_mb=memory,
        cpus=cpus,
        pids_limit=pids,
    )
    argv = eng_docker.docker_run_argv("/usr/bin/docker", server, image, "unit-scope", execution(), "unit-container")
    assert argv[:5] == ["/usr/bin/docker", "run", "-i", "--rm", "--pull=never"]
    for flag in ("--init", "--read-only"):
        assert argv.count(flag) == 1
    for flag, expected in {
        "--network": "none",
        "--user": "65534:65534",
        "--cap-drop": "ALL",
        "--security-opt": "no-new-privileges",
        "--memory": f"{memory}m",
        "--memory-swap": f"{memory}m",
        "--cpus": str(cpus),
        "--pids-limit": str(pids),
        "--mount": "type=bind,source=/srv/slotagent/frozen data,target=/data,readonly",
    }.items():
        assert argv.count(flag) == 1 and argv[argv.index(flag) + 1] == expected
    assert argv[-2:] == [image, "server-config-json"]


def test_bind_requires_allowed_roots(tmp_path):
    source = tmp_path / "data"
    source.mkdir()
    with pytest.raises(ValueError):
        eng_docker.validate_bind_source(str(source), ())


@pytest.mark.parametrize("source", ["/", "C:/", "c:\\", "/var/run", "/run", "C:/VaR/RuN", "c:\\RuN"])
def test_bind_control_roots_rejected(tmp_path, source):
    with pytest.raises(ValueError):
        eng_docker.ReadOnlyMount(source, "/data")
    with pytest.raises(ValueError):
        eng_docker.DockerServer("test", allowed_data_roots=(source,))


@pytest.mark.parametrize("kind", ["file", "directory", "root"])
def test_bind_allowed_descendant(tmp_path, kind):
    root = tmp_path / "approved"
    root.mkdir()
    source = root if kind == "root" else root / "frozen data"
    if kind == "file":
        source.write_text("frozen", encoding="utf-8")
    elif kind == "directory":
        source.mkdir()
    assert eng_docker.validate_bind_source(str(source), (str(root),)) == str(source.resolve())


def test_bind_sibling_prefix_rejected(tmp_path):
    root, sibling = tmp_path / "data", tmp_path / "data2"
    root.mkdir()
    sibling.mkdir()
    with pytest.raises(ValueError):
        eng_docker.validate_bind_source(str(sibling), (str(root),))


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_bind_parent_traversal_rejected(tmp_path, separator):
    root = tmp_path / "data"
    root.mkdir()
    source = str(root) + separator + ".." + separator + "data"
    with pytest.raises(ValueError):
        eng_docker.ReadOnlyMount(source, "/data")
    with pytest.raises(ValueError):
        eng_docker.validate_bind_source(source, (str(root),))


def make_directory_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # Windows 일반 사용자도 만들 수 있는 junction으로 실제 reparse 경로를 검증합니다.
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            timeout=5,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


@pytest.mark.parametrize("kind", ["source", "parent", "root"])
def test_bind_links_rejected(tmp_path, kind):
    root, outside = tmp_path / "data", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    if kind == "root":
        alias = tmp_path / "root-alias"
        make_directory_link(alias, root)
        source, roots = alias, (str(alias),)
    else:
        alias = root / "alias"
        make_directory_link(alias, outside)
        if kind == "parent":
            (outside / "child").mkdir()
            source = alias / "child"
        else:
            source = alias
        roots = (str(root),)
    with pytest.raises(ValueError):
        eng_docker.validate_bind_source(str(source), roots)


def test_bind_reparse_flag_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace

    root = tmp_path / "data"
    root.mkdir()
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        if path == root:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError):
        eng_docker.validate_bind_source(str(root), (str(root),))


@pytest.mark.parametrize("kind", ["missing", "foreign", "unc", "device", "drive_relative", "permission"])
def test_bind_uncheckable_paths_rejected(tmp_path, monkeypatch, kind):
    root = tmp_path / "data"
    root.mkdir()
    source = {
        "missing": str(root / "missing"),
        "foreign": "/srv/data" if os.name == "nt" else "C:/Data",
        "unc": "\\\\server\\share\\data",
        "device": "\\\\?\\C:\\Data",
        "drive_relative": "C:data",
        "permission": str(root),
    }[kind]
    if kind == "permission":

        def denied(*args, **kwargs):
            raise PermissionError("검증 불가")

        monkeypatch.setattr(Path, "lstat", denied)
    with pytest.raises(ValueError):
        eng_docker.validate_bind_source(source, (str(root),))


@pytest.mark.skipif(os.name != "nt", reason="Windows 대소문자·역슬래시의 실제 파일 시스템 검사")
@pytest.mark.parametrize("kind", ["case_and_slash", "sibling_case"])
def test_bind_windows_path_forms(tmp_path, kind):
    root = tmp_path / "DaTa"
    root.mkdir()
    if kind == "case_and_slash":
        child = root / "FrOzEn"
        child.mkdir()
        assert eng_docker.validate_bind_source(str(child).upper().replace("\\", "/"), (str(root).lower(),)) == str(
            child.resolve()
        )
    else:
        sibling = tmp_path / "DaTa2"
        sibling.mkdir()
        with pytest.raises(ValueError):
            eng_docker.validate_bind_source(str(sibling).upper(), (str(root).lower(),))


def test_bind_rechecked_before_start(tmp_path, monkeypatch):
    root, source, outside = tmp_path / "data", tmp_path / "data" / "frozen", tmp_path / "outside"
    root.mkdir()
    source.mkdir()
    outside.mkdir()

    class Control:
        executable = "docker"
        environment = {}

        def image_id(self, image):
            return "sha256:" + "a" * 64

        def bind_paths_visible(self):
            return True

    server = eng_docker.DockerServer(
        "test", mounts=(eng_docker.ReadOnlyMount(str(source), "/data"),), allowed_data_roots=(str(root),)
    )
    definitions = [t for t in snapshot()["tools"] if t["access"] == "read"]
    client = eng_docker.DockerStdioTools(
        Control(), server, definitions, scope="unit", execution=execution(), timeout_sec=1, cancel_signals=()
    )
    source.rmdir()
    make_directory_link(source, outside)

    def forbidden(*args, **kwargs):
        raise AssertionError("링크로 바뀐 원본으로 Docker를 실행하면 안 됩니다.")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with pytest.raises(ToolEnvironmentError):
        client.start()
    assert client.state == "closed" and client.process is None
    client.close()


@pytest.mark.parametrize("endpoint", ["ssh://host", "tcp://host:2376"])
def test_bind_remote_daemon_rejected(endpoint):
    control = eng_docker.DockerControl("docker")
    control.environment["DOCKER_HOST"] = endpoint
    assert not control.bind_paths_visible()


@pytest.mark.parametrize("kind", ["empty_roots", "invisible_host"])
def test_bind_invalid_config_never_launches(tmp_path, monkeypatch, kind):
    root = tmp_path / "data"
    root.mkdir()

    class Control:
        def bind_paths_visible(self):
            return False

        def image_id(self, image):
            raise AssertionError("거절한 설정은 이미지 검사까지 진행하면 안 됩니다.")

    def forbidden(*args, **kwargs):
        raise AssertionError("거절한 bind 설정으로 프로세스를 실행하면 안 됩니다.")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    server = eng_docker.DockerServer(
        "test",
        mounts=(eng_docker.ReadOnlyMount(str(root), "/data"),),
        allowed_data_roots=() if kind == "empty_roots" else (str(root),),
    )
    with pytest.raises(ToolEnvironmentError):
        eng_docker.DockerStdioTools(
            Control(), server, [], scope="unit", execution=execution(), timeout_sec=1, cancel_signals=()
        )


@pytest.mark.parametrize("endpoint", ["local", "remote_context"])
def test_bind_daemon_context_checked(monkeypatch, endpoint):
    control = eng_docker.DockerControl("docker")
    control.environment.pop("DOCKER_HOST", None)
    control.environment["DOCKER_CONTEXT"] = "explicit"
    local = "npipe:////./pipe/dockerDesktopLinuxEngine" if os.name == "nt" else "unix:///var/run/docker.sock"
    expected = local if endpoint == "local" else "ssh://remote"
    monkeypatch.setattr(control, "run", lambda *args: subprocess.CompletedProcess(args, 0, expected.encode()))
    monkeypatch.setattr(Path, "exists", lambda path: False)
    assert control.bind_paths_visible() == (endpoint == "local")


def test_bind_container_worker_path_space(monkeypatch):
    control = eng_docker.DockerControl("docker")
    local = "npipe:////./pipe/dockerDesktopLinuxEngine" if os.name == "nt" else "unix:///var/run/docker.sock"
    control.environment["DOCKER_HOST"] = local
    control.environment.pop("DOCKER_CONTEXT", None)
    monkeypatch.setattr(Path, "exists", lambda path: str(path) == "/.dockerenv")
    assert control.bind_paths_visible() == (os.name == "nt")


def test_docker_bind_allowed_root(docker_resources, tmp_path):
    root, source = tmp_path / "approved", tmp_path / "approved" / "frozen"
    source.mkdir(parents=True)
    (source / "check.txt").write_text("frozen", encoding="utf-8")
    original = config(docker_resources, "isolation_probe").servers["github"]
    server = eng_docker.DockerServer(
        docker_resources["image"],
        arguments=original.arguments,
        mounts=(eng_docker.ReadOnlyMount(str(source), "/data"),),
        allowed_data_roots=(str(root),),
    )
    setting = eng_docker.DockerStdioConfig(
        {"github": server}, scope=docker_resources["scope"], docker=docker_resources["cli"]
    )
    with setting.open(snapshot(), execution=execution()) as call:
        result = json.loads(call("list_issues", ARGS, 3))
        assert result["data"] == "frozen" and result["write_error"] == "EROFS"
    assert owned(docker_resources) == []
