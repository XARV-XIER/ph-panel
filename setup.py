#!/usr/bin/env python3
"""
VPS Panel Setup Script
Run this once to configure admin credentials and panel name.
"""

import os
import sys
import yaml
import bcrypt
import secrets
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.yaml"
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode(), salt).decode()


def generate_secret_key() -> str:
    return secrets.token_urlsafe(32)


def prompt_input(prompt: str, default: str = None, secret: bool = False) -> str:
    if secret:
        import getpass
        value = getpass.getpass(f"{prompt}: ")
    else:
        value = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return value or default


def main():
    print("=" * 50)
    print("  VPS Panel - Initial Setup")
    print("=" * 50)
    print()

    config = load_config()

    print("Admin Account Configuration")
    print("-" * 30)
    admin_user = prompt_input("Admin username", "admin")
    admin_pass = prompt_input("Admin password", secret=True)
    admin_pass_confirm = prompt_input("Confirm password", secret=True)

    if admin_pass != admin_pass_confirm:
        print("❌ Passwords do not match!")
        sys.exit(1)

    print()
    print("Panel Configuration")
    print("-" * 30)
    panel_name = prompt_input("Panel name (displayed in UI)", "VPS Panel")
    panel_domain = prompt_input("Panel domain (for SSH proxy)", "panel.example.com")

    print()
    print("SSH Proxy Configuration")
    print("-" * 30)
    ssh_proxy_enabled = prompt_input("Enable SSH domain proxy? (y/n)", "y").lower() == "y"
    ssh_port_start = int(prompt_input("SSH proxy port range start", "22000"))
    ssh_port_end = int(prompt_input("SSH proxy port range end", "22999"))

    print()
    print("Security Configuration")
    print("-" * 30)
    secret_key = generate_secret_key()
    print(f"Generated secret key: {secret_key}")
    print("⚠️  Save this key! It's used for session encryption.")

    # Update config
    config["app"]["name"] = panel_name
    config["app"]["secret_key"] = secret_key
    config["app"]["debug"] = False
    config["app"]["allow_registration"] = True

    config["ssh_proxy"]["enabled"] = ssh_proxy_enabled
    config["ssh_proxy"]["domain"] = panel_domain
    config["ssh_proxy"]["port_range_start"] = ssh_port_start
    config["ssh_proxy"]["port_range_end"] = ssh_port_end

    save_config(config)

    # Create admin user in database (will be created on first app run)
    admin_data = {
        "username": admin_user,
        "password_hash": hash_password(admin_pass),
        "is_admin": True,
        "created_at": __import__("datetime").datetime.utcnow().isoformat()
    }

    admin_file = DATA_DIR / "admin.yaml"
    with open(admin_file, "w") as f:
        yaml.dump(admin_data, f, default_flow_style=False)

    print()
    print("=" * 50)
    print("✅ Setup complete!")
    print(f"   Admin user: {admin_user}")
    print(f"   Panel name: {panel_name}")
    print(f"   Domain: {panel_domain}")
    print(f"   SSH proxy: {'Enabled' if ssh_proxy_enabled else 'Disabled'}")
    if ssh_proxy_enabled:
        print(f"   Port range: {ssh_port_start}-{ssh_port_end}")
    print()
    print("Next steps:")
    print("  1. Run: python -m app.main")
    print("  2. Access panel at http://localhost:5000")
    print("=" * 50)


if __name__ == "__main__":
    main()
