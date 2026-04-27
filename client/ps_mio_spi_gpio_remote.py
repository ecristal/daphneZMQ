#!/usr/bin/env python3
"""
Laptop-side wrapper for the on-board PS MIO SPI GPIO smoketest helper.

This script syncs the board-local helper into the remote daphne-server checkout
and runs it via ssh + sudo.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shlex
import subprocess
import sys
from pathlib import Path


def local_board_script() -> Path:
    return Path(__file__).with_name("ps_mio_spi_gpio_board.py")


def remote_repo_expr(remote_repo: str) -> str:
    if remote_repo == "~":
        return "$HOME"
    if remote_repo.startswith("~/"):
        return "$HOME/" + remote_repo[2:]
    return shlex.quote(remote_repo)


def run(cmd: list[str]) -> int:
    proc = subprocess.run(cmd, check=False)
    return int(proc.returncode)


def sync_board_script(host: str, remote_repo: str) -> int:
    target = f"{host}:{remote_repo.rstrip('/')}/client/ps_mio_spi_gpio_board.py"
    return run(["scp", "-q", str(local_board_script()), target])


def remote_command(remote_repo: str, remote_args: list[str], sudo_password: str) -> str:
    helper = "client/ps_mio_spi_gpio_board.py"
    inner = " ".join(
        [
            "cd",
            remote_repo_expr(remote_repo),
            "&&",
            "python3",
            shlex.quote(helper),
            *[shlex.quote(arg) for arg in remote_args],
        ]
    )
    return " ".join(
        [
            "printf",
            "%s\\\\n",
            shlex.quote(sudo_password),
            "|",
            "sudo",
            "-S",
            "sh",
            "-lc",
            shlex.quote(inner),
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync and run the on-board PS MIO SPI GPIO helper over ssh."
    )
    parser.add_argument(
        "--host",
        default="daphne-13",
        help="SSH target alias. Default: daphne-13",
    )
    parser.add_argument(
        "--remote-repo",
        default="/home/petalinux/daphne-server",
        help="Remote daphne-server checkout. Default: /home/petalinux/daphne-server",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip scp of the board helper before execution.",
    )
    parser.add_argument(
        "--sudo-password",
        default=os.environ.get("DAPHNE_SUDO_PASSWORD"),
        help="Remote sudo password. If omitted, prompt interactively.",
    )
    parser.add_argument(
        "remote_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through to ps_mio_spi_gpio_board.py",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    remote_args = args.remote_args or ["status"]
    if remote_args and remote_args[0] == "--":
        remote_args = remote_args[1:]

    if not args.sudo_password:
        args.sudo_password = getpass.getpass("Remote sudo password: ")

    if not args.no_sync:
        rc = sync_board_script(args.host, args.remote_repo)
        if rc != 0:
            return rc

    cmd = [
        "ssh",
        "-o",
        "ClearAllForwardings=yes",
        args.host,
        remote_command(args.remote_repo, remote_args, args.sudo_password),
    ]
    return run(cmd)


if __name__ == "__main__":
    sys.exit(main())
