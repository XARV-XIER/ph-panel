"""
VPS Panel - Database Models
"""

import sqlite3
import json
import bcrypt
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from app.config import get_db_path


DB_PATH = get_db_path()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin BOOLEAN DEFAULT 0,
                theme TEXT DEFAULT 'dark',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS vps_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                hostname TEXT UNIQUE NOT NULL,
                os_template TEXT NOT NULL,
                cpu_cores INTEGER DEFAULT 1,
                memory_mb INTEGER DEFAULT 512,
                disk_gb INTEGER DEFAULT 5,
                ipv4_address TEXT,
                ipv6_address TEXT,
                ssh_port INTEGER,
                status TEXT DEFAULT 'creating',
                root_password TEXT,
                lxc_config TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            );

            CREATE TABLE IF NOT EXISTS os_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                description TEXT,
                architecture TEXT DEFAULT 'amd64',
                template_url TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ssh_proxy_ports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vps_id INTEGER NOT NULL,
                external_port INTEGER UNIQUE NOT NULL,
                internal_port INTEGER DEFAULT 22,
                domain TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vps_id) REFERENCES vps_instances (id)
            );

            CREATE TABLE IF NOT EXISTS themes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                css_variables TEXT NOT NULL,
                is_default BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id INTEGER,
                details TEXT,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            );

            CREATE INDEX IF NOT EXISTS idx_vps_user ON vps_instances(user_id);
            CREATE INDEX IF NOT EXISTS idx_vps_status ON vps_instances(status);
            CREATE INDEX IF NOT EXISTS idx_ssh_proxy_vps ON ssh_proxy_ports(vps_id);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);
        """)
        conn.commit()

        # Insert default OS templates
        default_templates = [
            ("ubuntu-22.04", "Ubuntu 22.04 LTS", "Long-term support release", "amd64", ""),
            ("ubuntu-24.04", "Ubuntu 24.04 LTS", "Latest long-term support", "amd64", ""),
            ("debian-12", "Debian 12 (Bookworm)", "Stable and reliable", "amd64", ""),
            ("debian-11", "Debian 11 (Bullseye)", "Previous stable release", "amd64", ""),
            ("alpine-3.19", "Alpine Linux 3.19", "Lightweight and secure", "amd64", ""),
            ("centos-9", "CentOS Stream 9", "Enterprise-grade", "amd64", ""),
            ("rocky-9", "Rocky Linux 9", "RHEL-compatible", "amd64", ""),
            ("alma-9", "AlmaLinux 9", "RHEL-compatible", "amd64", ""),
            ("fedora-39", "Fedora 39", "Cutting-edge features", "amd64", ""),
            ("arch-latest", "Arch Linux", "Rolling release, DIY", "amd64", ""),
        ]

        for tpl in default_templates:
            conn.execute("""
                INSERT OR IGNORE INTO os_templates (name, display_name, description, architecture, template_url)
                VALUES (?, ?, ?, ?, ?)
            """, tpl)

        # Insert default themes
        default_themes = [
            ("dark", "Dark", '{"--bg-primary": "#0f172a", "--bg-secondary": "#1e293b", "--bg-tertiary": "#334155", "--text-primary": "#f1f5f9", "--text-secondary": "#94a3b8", "--accent": "#3b82f6", "--accent-hover": "#2563eb", "--border": "#334155", "--success": "#22c55e", "--warning": "#f59e0b", "--danger": "#ef4444", "--card-shadow": "0 4px 6px -1px rgba(0,0,0,0.3)"}', 1),
            ("light", "Light", '{"--bg-primary": "#ffffff", "--bg-secondary": "#f8fafc", "--bg-tertiary": "#f1f5f9", "--text-primary": "#0f172a", "--text-secondary": "#475569", "--accent": "#3b82f6", "--accent-hover": "#2563eb", "--border": "#e2e8f0", "--success": "#16a34a", "--warning": "#d97706", "--danger": "#dc2626", "--card-shadow": "0 4px 6px -1px rgba(0,0,0,0.1)"}', 0),
            ("ocean", "Ocean", '{"--bg-primary": "#0c1e35", "--bg-secondary": "#142d4a", "--bg-tertiary": "#1e3d5f", "--text-primary": "#e0f2fe", "--text-secondary": "#7dd3fc", "--accent": "#0ea5e9", "--accent-hover": "#0284c7", "--border": "#1e3d5f", "--success": "#10b981", "--warning": "#f59e0b", "--danger": "#ef4444", "--card-shadow": "0 4px 6px -1px rgba(0,0,0,0.4)"}', 0),
            ("forest", "Forest", '{"--bg-primary": "#0c2e1a", "--bg-secondary": "#144d2e", "--bg-tertiary": "#1a5c3a", "--text-primary": "#dcfce7", "--text-secondary": "#86efac", "--accent": "#22c55e", "--accent-hover": "#16a34a", "--border": "#1a5c3a", "--success": "#10b981", "--warning": "#f59e0b", "--danger": "#ef4444", "--card-shadow": "0 4px 6px -1px rgba(0,0,0,0.4)"}', 0),
            ("sunset", "Sunset", '{"--bg-primary": "#2e1020", "--bg-secondary": "#4c1d3e", "--bg-tertiary": "#6b2d54", "--text-primary": "#ffe4e6", "--text-secondary": "#fda4af", "--accent": "#ec4899", "--accent-hover": "#db2777", "--border": "#6b2d54", "--success": "#10b981", "--warning": "#f59e0b", "--danger": "#ef4444", "--card-shadow": "0 4px 6px -1px rgba(0,0,0,0.4)"}', 0),
        ]

        for theme in default_themes:
            conn.execute("""
                INSERT OR IGNORE INTO themes (name, display_name, css_variables, is_default)
                VALUES (?, ?, ?, ?)
            """, theme)

        conn.commit()


# User Model
class User:
    @staticmethod
    def create(username: str, password: str, is_admin: bool = False, theme: str = "dark") -> int:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO users (username, password_hash, is_admin, theme)
                VALUES (?, ?, ?, ?)
            """, (username, password_hash, is_admin, theme))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(user_id: int) -> Optional[Dict]:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_username(username: str) -> Optional[Dict]:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def verify_password(user: Dict, password: str) -> bool:
        return bcrypt.checkpw(password.encode(), user["password_hash"].encode())

    @staticmethod
    def update_theme(user_id: int, theme: str):
        with get_db() as conn:
            conn.execute("UPDATE users SET theme = ? WHERE id = ?", (theme, user_id))
            conn.commit()

    @staticmethod
    def update_last_login(user_id: int):
        with get_db() as conn:
            conn.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
            conn.commit()

    @staticmethod
    def list_all() -> List[Dict]:
        with get_db() as conn:
            rows = conn.execute("SELECT id, username, is_admin, theme, created_at, last_login FROM users").fetchall()
            return [dict(r) for r in rows]


# VPS Instance Model
class VPSInstance:
    @staticmethod
    def create(user_id: int, name: str, hostname: str, os_template: str,
               cpu_cores: int = 1, memory_mb: int = 512, disk_gb: int = 5) -> int:
        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO vps_instances (user_id, name, hostname, os_template, cpu_cores, memory_mb, disk_gb, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'creating')
            """, (user_id, name, hostname, os_template, cpu_cores, memory_mb, disk_gb))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(vps_id: int) -> Optional[Dict]:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM vps_instances WHERE id = ?", (vps_id,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_user(user_id: int) -> List[Dict]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM vps_instances WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_all() -> List[Dict]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM vps_instances ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def update(vps_id: int, **kwargs):
        allowed = {"name", "cpu_cores", "memory_mb", "disk_gb", "ipv4_address", "ipv6_address",
                   "ssh_port", "status", "root_password", "lxc_config"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        fields["updated_at"] = datetime.utcnow().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        with get_db() as conn:
            conn.execute(f"UPDATE vps_instances SET {set_clause} WHERE id = ?",
                        list(fields.values()) + [vps_id])
            conn.commit()

    @staticmethod
    def delete(vps_id: int):
        with get_db() as conn:
            conn.execute("DELETE FROM vps_instances WHERE id = ?", (vps_id,))
            conn.execute("DELETE FROM ssh_proxy_ports WHERE vps_id = ?", (vps_id,))
            conn.commit()


# OS Template Model
class OSTemplate:
    @staticmethod
    def get_all(active_only: bool = True) -> List[Dict]:
        with get_db() as conn:
            query = "SELECT * FROM os_templates"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY display_name"
            rows = conn.execute(query).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_by_name(name: str) -> Optional[Dict]:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM os_templates WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def create(name: str, display_name: str, description: str, architecture: str = "amd64", template_url: str = "") -> int:
        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO os_templates (name, display_name, description, architecture, template_url)
                VALUES (?, ?, ?, ?, ?)
            """, (name, display_name, description, architecture, template_url))
            conn.commit()
            return cursor.lastrowid


# SSH Proxy Port Model
class SSHProxyPort:
    @staticmethod
    def allocate(vps_id: int, port_range_start: int, port_range_end: int) -> Optional[int]:
        with get_db() as conn:
            used = set(r[0] for r in conn.execute("SELECT external_port FROM ssh_proxy_ports WHERE is_active = 1").fetchall())
            for port in range(port_range_start, port_range_end + 1):
                if port not in used:
                    conn.execute("""
                        INSERT INTO ssh_proxy_ports (vps_id, external_port, internal_port)
                        VALUES (?, ?, 22)
                    """, (vps_id, port))
                    conn.commit()
                    return port
            return None

    @staticmethod
    def get_by_vps(vps_id: int) -> List[Dict]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM ssh_proxy_ports WHERE vps_id = ? AND is_active = 1", (vps_id,)).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def release(vps_id: int):
        with get_db() as conn:
            conn.execute("UPDATE ssh_proxy_ports SET is_active = 0 WHERE vps_id = ?", (vps_id,))
            conn.commit()

    @staticmethod
    def get_by_port(port: int) -> Optional[Dict]:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM ssh_proxy_ports WHERE external_port = ? AND is_active = 1", (port,)).fetchone()
            return dict(row) if row else None


# Theme Model
class Theme:
    @staticmethod
    def get_all() -> List[Dict]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM themes ORDER BY is_default DESC, display_name").fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_by_name(name: str) -> Optional[Dict]:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM themes WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_css_variables(name: str) -> Dict:
        theme = Theme.get_by_name(name)
        if theme:
            return json.loads(theme["css_variables"])
        return {}


# Audit Log Model
class AuditLog:
    @staticmethod
    def log(user_id: Optional[int], action: str, resource_type: str = None,
            resource_id: int = None, details: str = None, ip_address: str = None):
        with get_db() as conn:
            conn.execute("""
                INSERT INTO audit_logs (user_id, action, resource_type, resource_id, details, ip_address)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, action, resource_type, resource_id, details, ip_address))
            conn.commit()

    @staticmethod
    def get_recent(limit: int = 100) -> List[Dict]:
        with get_db() as conn:
            rows = conn.execute("""
                SELECT al.*, u.username
                FROM audit_logs al
                LEFT JOIN users u ON al.user_id = u.id
                ORDER BY al.created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]


# Initialize on import
init_db()