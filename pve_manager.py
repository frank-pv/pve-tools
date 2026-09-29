#!/usr/bin/env python3
"""Interactive Proxmox VE VM power manager."""

from __future__ import annotations

import json
import os
import select
import ssl
import sys
import termios
import tty
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


CONFIG_PATH = Path(__file__).with_name("config.env")


class PVEError(Exception):
    """Raised when a Proxmox API request cannot be completed."""


@dataclass(frozen=True)
class VirtualMachine:
    vmid: int
    name: str
    node: str
    status: str
    kind: str

    @property
    def label(self) -> str:
        state = "运行中" if self.status == "running" else "已停止"
        return f"{self.vmid:>6}  {self.name}  [{self.kind.upper()} / {state}]"


def load_config(path: Path = CONFIG_PATH) -> dict[str, str]:
    """Read simple KEY=VALUE settings from the adjacent config.env file."""
    if not path.is_file():
        raise PVEError(f"找不到配置文件：{path}\n请复制 config.env 模板并填写 PVE 连接信息。")

    config: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PVEError(f"{path.name} 第 {line_number} 行格式错误，应为 KEY=VALUE。")
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip().strip("\"'")

    required = ("PVE_HOST", "PVE_TOKEN_ID", "PVE_TOKEN_SECRET")
    missing = [key for key in required if not config.get(key) or "填写" in config[key]]
    if missing:
        raise PVEError(f"请在 {path.name} 中填写：{', '.join(missing)}")
    return config


class PVEClient:
    def __init__(self, config: dict[str, str]) -> None:
        self.base_url = config["PVE_HOST"].rstrip("/")
        self.token_id = config["PVE_TOKEN_ID"]
        self.token_secret = config["PVE_TOKEN_SECRET"]
        self.timeout = float(config.get("PVE_REQUEST_TIMEOUT", "15"))
        verify_tls = config.get("PVE_TLS_VERIFY", "true").lower() not in {
            "0", "false", "no", "off"
        }
        self.ssl_context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()

    def request(self, path: str, method: str = "GET") -> object:
        request = Request(
            f"{self.base_url}/api2/json{path}",
            headers={
                "Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}",
                "Accept": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout, context=self.ssl_context) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("message", detail)
            except (json.JSONDecodeError, AttributeError):
                pass
            raise PVEError(f"PVE API 返回 HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise PVEError(f"无法连接 PVE API：{error}") from error

        if not isinstance(payload, dict) or "data" not in payload:
            raise PVEError("PVE API 返回了无法识别的数据。")
        return payload["data"]

    def list_vms(self) -> list[VirtualMachine]:
        result = self.request("/cluster/resources?type=vm")
        if not isinstance(result, list):
            raise PVEError("PVE 返回的虚拟机列表格式无效。")

        machines = []
        for item in result:
            if not isinstance(item, dict) or item.get("type") not in {"qemu", "lxc"}:
                continue
            try:
                machines.append(
                    VirtualMachine(
                        vmid=int(item["vmid"]),
                        name=str(item.get("name") or f"VM {item['vmid']}"),
                        node=str(item["node"]),
                        status=str(item.get("status", "unknown")),
                        kind=str(item["type"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(machines, key=lambda machine: (machine.node, machine.vmid))

    def power_on(self, machine: VirtualMachine) -> object:
        return self._power_action(machine, "start")

    def shutdown(self, machine: VirtualMachine) -> object:
        return self._power_action(machine, "shutdown")

    def _power_action(self, machine: VirtualMachine, action: str) -> object:
        kind = "qemu" if machine.kind == "qemu" else "lxc"
        node = quote(machine.node, safe="")
        return self.request(f"/nodes/{node}/{kind}/{machine.vmid}/status/{action}", method="POST")


def _read_key(fd: int) -> str:
    first = os.read(fd, 1).decode("utf-8", errors="ignore")
    if first != "\x1b":
        return first
    if select.select([fd], [], [], 0.05)[0]:
        sequence = os.read(fd, 2).decode("utf-8", errors="ignore")
        return {"[A": "up", "[B": "down"}.get(sequence, "escape")
    return "escape"


def choose(title: str, options: list[str]) -> int:
    """Show a numbered, arrow-key navigable menu and return a zero-based choice."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise PVEError("交互菜单需要在终端中运行，请直接执行：python3 pve_manager.py")

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    selected = 0
    number_buffer = ""
    try:
        tty.setraw(fd)
        while True:
            sys.stdout.write("\x1b[2J\x1b[H")
            sys.stdout.write(f"{title}\n使用 ↑/↓ 或输入编号，回车确认\n\n")
            for index, option in enumerate(options):
                marker = ">" if index == selected else " "
                sys.stdout.write(f"{marker} {index + 1}. {option}\n")
            if number_buffer:
                sys.stdout.write(f"\n编号：{number_buffer}")
            sys.stdout.flush()

            key = _read_key(fd)
            if key == "\x03":
                raise KeyboardInterrupt
            if key == "up":
                selected = (selected - 1) % len(options)
                number_buffer = ""
            elif key == "down":
                selected = (selected + 1) % len(options)
                number_buffer = ""
            elif key in ("\r", "\n"):
                if number_buffer:
                    index = int(number_buffer) - 1
                    if 0 <= index < len(options):
                        return index
                else:
                    return selected
                number_buffer = ""
            elif key in ("\x7f", "\b"):
                number_buffer = number_buffer[:-1]
            elif key.isdigit():
                number_buffer += key
            elif key == "escape":
                number_buffer = ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def wait_for_enter(message: str = "按回车继续...") -> None:
    input(f"\n{message}")


def manage_vm(client: PVEClient, machine: VirtualMachine) -> None:
    while True:
        status_text = "运行中" if machine.status == "running" else "已停止"
        options = ["开机", "关机（优雅关闭）", "返回虚拟机列表"]
        choice = choose(
            f"虚拟机：{machine.name} (VMID {machine.vmid}, 节点 {machine.node}, {status_text})",
            options,
        )
        if choice == 2:
            return
        if choice == 1 and not confirm_shutdown(machine):
            continue

        try:
            task = client.power_on(machine) if choice == 0 else client.shutdown(machine)
            action = "开机" if choice == 0 else "关机"
            print(f"已提交{action}请求。任务：{task or 'PVE 已接受请求'}")
        except PVEError as error:
            print(f"操作失败：{error}")
        wait_for_enter()
        return


def confirm_shutdown(machine: VirtualMachine) -> bool:
    return choose(f"确认关闭虚拟机 {machine.name} (VMID {machine.vmid})？", ["确认关机", "取消"]) == 0


def run() -> None:
    client = PVEClient(load_config())
    while True:
        try:
            machines = client.list_vms()
        except PVEError as error:
            print(f"获取虚拟机列表失败：{error}")
            wait_for_enter("按回车重试...")
            continue

        if not machines:
            print("当前没有可管理的 QEMU 虚拟机或 LXC 容器。")
            wait_for_enter()
            return

        options = [machine.label for machine in machines] + ["刷新列表", "退出"]
        choice = choose("Proxmox VE 虚拟机管理", options)
        if choice == len(machines):
            continue
        if choice == len(machines) + 1:
            return
        manage_vm(client, machines[choice])


def main() -> int:
    try:
        run()
    except (PVEError, KeyboardInterrupt) as error:
        if isinstance(error, PVEError):
            print(f"错误：{error}", file=sys.stderr)
        else:
            print("\n已退出。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())