"""Exercises the real asyncssh transport against in-process SSH servers (no network access).

Servers mimic PSU logins: a keyboard-interactive password round followed by a Duo round.
The client must answer the password itself and forward the Duo prompt, on either hop.
"""

import asyncio
import shlex
from contextlib import asynccontextmanager
from dataclasses import replace

import asyncssh
import pytest
from pydantic import SecretStr

from hpc.backend import AuthFailed
from hpc.config import load_hpc_settings
from hpc.models import ConnectRequest
from hpc.slurm import SlurmBackend
from hpc.ssh_client import AsyncSSHBackend, SessionManager
from hpc.store import InMemoryStore
from hpc.workstation import WorkstationBackend

PASSWORD = ("", "", "", [("Password: ", False)])
DUO = ("Duo two-factor login", "Choose an option", "", [("Passcode or option (1-1): ", True)])


class FakeLogin(asyncssh.SSHServer):
    """Password + Duo via keyboard-interactive. Also allows TCP forwarding (jump host)."""

    password = "s3cret"

    def __init__(self):
        self.gave_up = False

    def begin_auth(self, username: str) -> bool:
        return True

    def kbdint_auth_supported(self) -> bool:
        return True

    def get_kbdint_challenge(self, username, lang, submethods):
        return False if self.gave_up else PASSWORD  # like sshd's MaxAuthTries

    def validate_kbdint_response(self, username, responses):
        if responses == [self.password]:
            return DUO
        if responses == ["1"]:
            return True
        self.gave_up = responses == ["give-up"]
        return False if self.gave_up else PASSWORD

    def connection_requested(self, dest_host, dest_port, orig_host, orig_port):
        return True


async def handle_process(process: asyncssh.SSHServerProcess) -> None:
    argv = shlex.split(process.command)
    assert argv[:2] == ["bash", "-lc"], argv  # backend always uses a login shell
    process.stdout.write(f"ran: {argv[2]}\n")
    process.exit(0)


async def start_server(root, factory=FakeLogin):
    root.mkdir(exist_ok=True)
    server = await asyncssh.listen(
        "127.0.0.1", 0, server_factory=factory,
        server_host_keys=[asyncssh.generate_private_key("ssh-ed25519")],
        process_factory=handle_process,
        sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(root).encode()),
    )
    return server, server.sockets[0].getsockname()[1]


def manager_for(compute_cls):
    settings = replace(load_hpc_settings(), mock=False, strict_host_keys=False,
                       connect_timeout=10, auth_timeout=10, base_dir="/data/pre")
    return SessionManager(AsyncSSHBackend(settings), compute_cls(settings), InMemoryStore(), settings)


@asynccontextmanager
async def login_node(tmp_path):
    server, port = await start_server(tmp_path / "fs")
    manager = manager_for(SlurmBackend)
    try:
        yield manager, ConnectRequest(host="127.0.0.1", port=port, jump_host="", username="abc123",
                                      password="s3cret")
    finally:
        await manager.close_all()
        server.close()
        await server.wait_closed()


def test_password_then_duo_then_exec_and_sftp(tmp_path):
    async def run():
        async with login_node(tmp_path) as (manager, req):
            first = await manager.connect(req)
            assert first.status == "awaiting_2fa" and first.hop == "127.0.0.1"
            assert [p.prompt for p in first.prompts] == ["Passcode or option (1-1): "]
            assert "Duo" in first.instructions
            assert (await manager.respond(first.session_id, ["1"])).status == "connected"

            record, conn = await manager.connection(first.session_id)
            assert record.base_dir == "/pre-projects"
            assert (await conn.run("squeue -u abc123", 5)).stdout == "ran: squeue -u abc123\n"
            chunks = [c async for c in conn.stream("echo hi", 5)]
            assert chunks == [("output", "ran: echo hi\n"), ("exit", 0)]

            job_dir = f"{record.base_dir}/demo/jobs/j1"
            await conn.makedirs(job_dir)
            await conn.write_file(f"{job_dir}/slurm-1.out", b"epoch 1\nepoch 2\n")
            assert await conn.read_file(f"{job_dir}/slurm-1.out", 1000) == b"epoch 1\nepoch 2\n"
            assert await conn.read_from(f"{job_dir}/slurm-1.out", 8) == b"epoch 2\n"
            assert await conn.read_from(f"{job_dir}/missing.out", 0) == b""
            assert [f.name for f in await conn.listdir(job_dir)] == ["slurm-1.out"]

            await manager.disconnect(first.session_id)
            assert not conn.is_alive()

    asyncio.run(run())


def test_wrong_password_is_reprompted_not_resent(tmp_path):
    async def run():
        async with login_node(tmp_path) as (manager, req):
            first = await manager.connect(req.model_copy(update={"password": SecretStr("typo")}))
            assert [(p.prompt, p.echo) for p in first.prompts] == [("Password: ", False)]
            second = await manager.respond(first.session_id, ["s3cret"])
            assert [p.prompt for p in second.prompts] == ["Passcode or option (1-1): "]
            assert (await manager.respond(first.session_id, ["1"])).status == "connected"

            other = await manager.connect(req.model_copy(update={"password": SecretStr("typo")}))
            with pytest.raises(AuthFailed, match="target 127.0.0.1"):
                await manager.respond(other.session_id, ["give-up"])
            assert (await manager.status(other.session_id)).status == "failed"

    asyncio.run(run())


def test_two_hop_connect_through_jump_host(tmp_path):
    """jump host (localhost) -> tunnel -> workstation (127.0.0.1); Duo on both hops."""

    async def run():
        jump, jump_port = await start_server(tmp_path / "jump")
        target, target_port = await start_server(tmp_path / "target")
        manager = manager_for(WorkstationBackend)
        req = ConnectRequest(host="127.0.0.1", port=target_port, jump_host="localhost", jump_port=jump_port,
                             username="abc123", password="s3cret")
        try:
            first = await manager.connect(req)
            assert first.status == "awaiting_2fa" and first.hop == "localhost"
            second = await manager.respond(first.session_id, ["1"])
            assert second.status == "awaiting_2fa" and second.hop == "127.0.0.1"
            done = await manager.respond(first.session_id, ["1"])
            assert done.status == "connected"

            record, conn = await manager.connection(first.session_id)
            assert record.base_dir == "/data/pre/abc123" and record.jump_host == "localhost"
            assert (tmp_path / "target" / "data" / "pre" / "abc123").is_dir()  # created on the target
            assert not (tmp_path / "jump" / "data").exists()
            assert (await conn.run("nvidia-smi", 5)).stdout == "ran: nvidia-smi\n"
            await manager.disconnect(first.session_id)
            assert not conn.is_alive()

            # Failure on the second hop names it.
            class OtherPassword(FakeLogin):
                password = "different"

            target2, port2 = await start_server(tmp_path / "t2", OtherPassword)
            try:
                bad = await manager.connect(req.model_copy(update={"port": port2}))
                await manager.respond(bad.session_id, ["1"])  # jump hop Duo OK
                with pytest.raises(AuthFailed, match=r"target 127\.0\.0\.1 \(via localhost\)"):
                    await manager.respond(bad.session_id, ["give-up"])  # target re-asked for password
            finally:
                target2.close()
        finally:
            await manager.close_all()
            for s in (jump, target):
                s.close()
                await s.wait_closed()

    asyncio.run(run())
