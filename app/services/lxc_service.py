"""
VPS Panel - LXC Container Management Service
"""

import subprocess
import os
import yaml
import secrets
import string
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from app.config import get_config
from app.models import VPSInstance, OSTemplate, SSHProxyPort, AuditLog


class LXCService:
    def __init__(self):
        self.config = get_config()
        self.lxc_config = self.config.get("lxc", {})
        self.storage_pool = self.lxc_config.get("storage_pool", "default")
        self.network_bridge = self.lxc_config.get("network_bridge", "lxcbr0")
        self.templates_path = Path(self.lxc_config.get("templates_path", "lxc_templates"))
        self.templates_path.mkdir(parents=True, exist_ok=True)

    def _run_cmd(self, cmd: List[str], check: bool = True) -> Tuple[int, str, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)

    def container_exists(self, name: str) -> bool:
        code, _, _ = self._run_cmd(["lxc", "info", name], check=False)
        return code == 0

    def create_container(self, vps: Dict) -> bool:
        name = vps["hostname"]
        os_template = vps["os_template"]
        cpu = vps["cpu_cores"]
        memory = vps["memory_mb"]
        disk = vps["disk_gb"]

        # Check if template exists locally, if not download
        if not self._template_exists_locally(os_template):
            if not self._download_template(os_template):
                return False

        # Create container from template
        code, out, err = self._run_cmd([
            "lxc", "copy", f"{os_template}", name
        ])
        if code != 0:
            return False

        # Configure resources
        self._run_cmd(["lxc", "config", "set", name, "limits.cpu", str(cpu)])
        self._run_cmd(["lxc", "config", "set", name, "limits.memory", f"{memory}M"])
        self._run_cmd(["lxc", "config", "set", name, "limits.disk", f"{disk}GB"])

        # Network config
        self._run_cmd(["lxc", "config", "device", "add", name, "eth0", "nic",
                       "nictype=bridged", f"parent={self.network_bridge}"])

        # Start container
        code, _, _ = self._run_cmd(["lxc", "start", name])
        if code != 0:
            return False

        # Wait for network
        import time
        time.sleep(3)

        # Set root password
        root_pass = self._generate_password()
        self._run_cmd(["lxc", "exec", name, "--", "bash", "-c",
                       f"echo 'root:{root_pass}' | chpasswd"])

        # Enable SSH
        self._run_cmd(["lxc", "exec", name, "--", "systemctl", "enable", "ssh"])
        self._run_cmd(["lxc", "exec", name, "--", "systemctl", "start", "ssh"])

        # Get IP address
        ipv4 = self._get_container_ip(name)

        # Update VPS record
        VPSInstance.update(vps["id"],
            ipv4_address=ipv4,
            root_password=root_pass,
            status="running"
        )

        return True

    def _template_exists_locally(self, template: str) -> bool:
        code, _, _ = self._run_cmd(["lxc", "image", "info", template], check=False)
        return code == 0

    def _download_template(self, template: str) -> bool:
        # Map template names to LXC image aliases
        image_map = {
            "ubuntu-22.04": "ubuntu:22.04",
            "ubuntu-24.04": "ubuntu:24.04",
            "debian-12": "debian:12",
            "debian-11": "debian:11",
            "alpine-3.19": "alpine:3.19",
            "centos-9": "centos:9",
            "rocky-9": "rockylinux:9",
            "alma-9": "almalinux:9",
            "fedora-39": "fedora:39",
            "arch-latest": "archlinux:latest",
        }
        alias = image_map.get(template)
        if not alias:
            return False

        code, _, _ = self._run_cmd(["lxc", "image", "copy", alias, "local:", "--alias", template])
        return code == 0

    def _get_container_ip(self, name: str) -> Optional[str]:
        code, out, _ = self._run_cmd(["lxc", "list", name, "-c", "4", "--format", "csv"], check=False)
        if code == 0 and out.strip():
            ips = out.strip().split()
            for ip in ips:
                if not ip.startswith("fd") and ":" not in ip:  # IPv4, not IPv6 ULA
                    return ip
        return None

    def _generate_password(self, length: int = 16) -> str:
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def start_container(self, name: str) -> bool:
        code, _, _ = self._run_cmd(["lxc", "start", name])
        if code == 0:
            VPSInstance.update_by_hostname(name, status="running")
        return code == 0

    def stop_container(self, name: str, force: bool = False) -> bool:
        cmd = ["lxc", "stop", name]
        if force:
            cmd.append("--force")
        code, _, _ = self._run_cmd(cmd)
        if code == 0:
            VPSInstance.update_by_hostname(name, status="stopped")
        return code == 0

    def restart_container(self, name: str) -> bool:
        code, _, _ = self._run_cmd(["lxc", "restart", name])
        if code == 0:
            VPSInstance.update_by_hostname(name, status="running")
        return code == 0

    def delete_container(self, name: str) -> bool:
        # Stop first if running
        self.stop_container(name, force=True)
        code, _, _ = self._run_cmd(["lxc", "delete", name])
        return code == 0

    def execute_command(self, name: str, command: List[str]) -> Tuple[int, str, str]:
        return self._run_cmd(["lxc", "exec", name, "--"] + command)

    def get_container_info(self, name: str) -> Dict:
        code, out, _ = self._run_cmd(["lxc", "info", name, "--format", "yaml"], check=False)
        if code == 0:
            return yaml.safe_load(out)
        return {}

    def list_containers(self) -> List[Dict]:
        code, out, _ = self._run_cmd(["lxc", "list", "--format", "yaml"], check=False)
        if code == 0:
            return yaml.safe_load(out) or []
        return []

    def resize_disk(self, name: str, size_gb: int) -> bool:
        code, _, _ = self._run_cmd(["lxc", "config", "device", "override", name, "root", "size", f"{size_gb}GB"])
        return code == 0

    def set_resource_limits(self, name: str, cpu: int = None, memory_mb: int = None) -> bool:
        if cpu:
            self._run_cmd(["lxc", "config", "set", name, "limits.cpu", str(cpu)])
        if memory_mb:
            self._run_cmd(["lxc", "config", "set", name, "limits.memory", f"{memory_mb}M"])
        return True

    def snapshot_create(self, name: str, snapshot_name: str) -> bool:
        code, _, _ = self._run_cmd(["lxc", "snapshot", name, snapshot_name])
        return code == 0

    def snapshot_restore(self, name: str, snapshot_name: str) -> bool:
        code, _, _ = self._run_cmd(["lxc", "restore", name, snapshot_name])
        return code == 0

    def snapshot_list(self, name: str) -> List[Dict]:
        code, out, _ = self._run_cmd(["lxc", "info", name, "--format", "yaml"], check=False)
        if code == 0:
            data = yaml.safe_load(out)
            return data.get("snapshots", [])
        return []

    def get_usage_stats(self, name: str) -> Dict:
        code, out, _ = self._run_cmd(["lxc", "info", name, "--format", "yaml"], check=False)
        if code == 0:
            data = yaml.safe_load(out)
            return {
                "cpu": data.get("cpu", {}),
                "memory": data.get("memory", {}),
                "network": data.get("network", {}),
            }
        return {}


# SSH Proxy Service
class SSHProxyService:
    def __init__(self):
        self.config = get_config()
        self.ssh_config = self.config.get("ssh_proxy", {})
        self.enabled = self.ssh_config.get("enabled", True)
        self.domain = self.ssh_config.get("domain", "")
        self.port_start = self.ssh_config.get("port_range_start", 22000)
        self.port_end = self.ssh_config.get("port_range_end", 22999)

    def setup_proxy_for_vps(self, vps_id: int) -> Optional[int]:
        if not self.enabled:
            return None
        port = SSHProxyPort.allocate(vps_id, self.port_start, self.port_end)
        if port:
            vps = VPSInstance.get_by_id(vps_id)
            if vps and vps.get("ipv4_address"):
                self._add_iptables_rule(port, vps["ipv4_address"])
        return port

    def _add_iptables_rule(self, external_port: int, internal_ip: str):
        # DNAT rule for SSH proxy
        subprocess.run([
            "iptables", "-t", "nat", "-A", "PREROUTING",
            "-p", "tcp", "--dport", str(external_port),
            "-j", "DNAT", "--to-destination", f"{internal_ip}:22"
        ], check=False)
        subprocess.run([
            "iptables", "-t", "nat", "-A", "POSTROUTING",
            "-p", "tcp", "-d", internal_ip, "--dport", "22",
            "-j", "MASQUERADE"
        ], check=False)

    def remove_proxy_for_vps(self, vps_id: int):
        ports = SSHProxyPort.get_by_vps(vps_id)
        for port_info in ports:
            self._remove_iptables_rule(port_info["external_port"])
        SSHProxyPort.release(vps_id)

    def _remove_iptables_rule(self, external_port: int):
        subprocess.run([
            "iptables", "-t", "nat", "-D", "PREROUTING",
            "-p", "tcp", "--dport", str(external_port),
            "-j", "DNAT", "--to-destination"
        ], check=False)

    def get_ssh_command(self, vps: Dict) -> Dict:
        ports = SSHProxyPort.get_by_vps(vps["id"])
        if not ports:
            return {"command": None, "port": None, "password": vps.get("root_password")}

        port = ports[0]["external_port"]
        domain = self.domain or "yourdomain.com"
        password = vps.get("root_password", "")

        return {
            "command": f"ssh root@{domain} -p {port}",
            "port": port,
            "domain": domain,
            "password": password,
            "sshx_url": f"https://{domain}/sshx/{vps['id']}" if self.ssh_config.get("sshx_enabled") else None
        }


# VPS Provisioning Service
class VPSProvisioner:
    def __init__(self):
        self.lxc = LXCService()
        self.ssh_proxy = SSHProxyService()

    def provision(self, user_id: int, name: str, hostname: str, os_template: str,
                  cpu: int = 1, memory_mb: int = 512, disk_gb: int = 5) -> Dict:
        # Validate
        template = OSTemplate.get_by_name(os_template)
        if not template:
            return {"success": False, "error": "Invalid OS template"}

        # Create VPS record
        vps_id = VPSInstance.create(user_id, name, hostname, os_template, cpu, memory_mb, disk_gb)

        # Provision container (async in production)
        success = self.lxc.create_container(VPSInstance.get_by_id(vps_id))

        if success:
            vps = VPSInstance.get_by_id(vps_id)
            ssh_port = self.ssh_proxy.setup_proxy_for_vps(vps_id)

            AuditLog.log(user_id, "vps_create", "vps", vps_id, f"Created VPS {name}", None)

            return {
                "success": True,
                "vps": vps,
                "ssh_port": ssh_port,
                "ssh_info": self.ssh_proxy.get_ssh_command(vps)
            }
        else:
            VPSInstance.delete(vps_id)
            return {"success": False, "error": "Failed to create container"}

    def terminate(self, user_id: int, vps_id: int) -> Dict:
        vps = VPSInstance.get_by_id(vps_id)
        if not vps:
            return {"success": False, "error": "VPS not found"}

        if vps["user_id"] != user_id:
            return {"success": False, "error": "Unauthorized"}

        self.ssh_proxy.remove_proxy_for_vps(vps_id)
        self.lxc.delete_container(vps["hostname"])
        VPSInstance.delete(vps_id)

        AuditLog.log(user_id, "vps_delete", "vps", vps_id, f"Deleted VPS {vps['name']}", None)

        return {"success": True}

    def power_action(self, user_id: int, vps_id: int, action: str) -> Dict:
        vps = VPSInstance.get_by_id(vps_id)
        if not vps or vps["user_id"] != user_id:
            return {"success": False, "error": "VPS not found"}

        actions = {
            "start": self.lxc.start_container,
            "stop": lambda n: self.lxc.stop_container(n, force=False),
            "force_stop": lambda n: self.lxc.stop_container(n, force=True),
            "restart": self.lxc.restart_container,
        }

        if action not in actions:
            return {"success": False, "error": "Invalid action"}

        success = actions[action](vps["hostname"])
        new_status = "running" if action in ["start", "restart"] else "stopped"
        VPSInstance.update(vps_id, status=new_status)

        AuditLog.log(user_id, f"vps_{action}", "vps", vps_id, f"{action} VPS {vps['name']}", None)

        return {"success": success}

    def reinstall(self, user_id: int, vps_id: int, os_template: str) -> Dict:
        vps = VPSInstance.get_by_id(vps_id)
        if not vps or vps["user_id"] != user_id:
            return {"success": False, "error": "VPS not found"}

        template = OSTemplate.get_by_name(os_template)
        if not template:
            return {"success": False, "error": "Invalid OS template"}

        # Delete old container
        self.lxc.delete_container(vps["hostname"])

        # Update OS template
        VPSInstance.update(vps_id, os_template=os_template, status="reinstalling")

        # Create new container
        success = self.lxc.create_container(VPSInstance.get_by_id(vps_id))

        if success:
            vps = VPSInstance.get_by_id(vps_id)
            AuditLog.log(user_id, "vps_reinstall", "vps", vps_id, f"Reinstalled VPS {vps['name']} with {os_template}", None)
            return {"success": True, "vps": vps}
        else:
            VPSInstance.update(vps_id, status="error")
            return {"success": False, "error": "Failed to reinstall"}

    def resize(self, user_id: int, vps_id: int, cpu: int = None, memory_mb: int = None, disk_gb: int = None) -> Dict:
        vps = VPSInstance.get_by_id(vps_id)
        if not vps or vps["user_id"] != user_id:
            return {"success": False, "error": "VPS not found"}

        if disk_gb:
            self.lxc.resize_disk(vps["hostname"], disk_gb)
            VPSInstance.update(vps_id, disk_gb=disk_gb)

        if cpu or memory_mb:
            self.lxc.set_resource_limits(vps["hostname"], cpu, memory_mb)
            if cpu:
                VPSInstance.update(vps_id, cpu_cores=cpu)
            if memory_mb:
                VPSInstance.update(vps_id, memory_mb=memory_mb)

        AuditLog.log(user_id, "vps_resize", "vps", vps_id, f"Resized VPS {vps['name']}", None)
        return {"success": True}


# Monkey patch for update_by_hostname
def _update_by_hostname(hostname: str, **kwargs):
    with get_db() as conn:
        row = conn.execute("SELECT id FROM vps_instances WHERE hostname = ?", (hostname,)).fetchone()
        if row:
            VPSInstance.update(row["id"], **kwargs)

VPSInstance.update_by_hostname = staticmethod(_update_by_hostname)

from app.config import get_db_path
import sqlite3
from contextlib import contextmanager

@contextmanager
def get_db():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()