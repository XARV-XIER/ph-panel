# VPS Panel

A modern, self-hosted VPS management panel built with Flask, LXC containers, and Tailwind CSS. Features multi-OS support, SSH domain proxy, web terminal (SSHX), theme system, and admin panel.

## Features

- **LXC Container Management**: Full lifecycle (create, start, stop, restart, delete, reinstall, resize)
- **Multi-OS Support**: Ubuntu, Debian, Alpine, CentOS, Rocky, AlmaLinux, Fedora, Arch
- **SSH Domain Proxy**: `ssh root@yourdomain.com -p PORT` with automatic port allocation
- **SSHX Web Terminal**: Collaborative browser-based terminal with file transfer
- **Theme System**: 5 built-in themes (Dark, Light, Ocean, Forest, Sunset) + custom themes
- **Admin Panel**: User management, OS templates, audit logs, theme configuration
- **Snapshots**: Create/restore container snapshots
- **Resource Monitoring**: CPU, memory, network usage stats
- **Secure Authentication**: bcrypt password hashing, session management

## Quick Start

### Prerequisites

- Linux host with LXC/LXD installed and configured
- Python 3.10+
- Root/sudo access for container operations

### Installation

```bash
# Clone or navigate to the panel directory
cd vps_panel

# Install Python dependencies
pip install -r requirements.txt

# Run initial setup (creates admin user, configures panel)
python setup.py

# Start the panel
python -m app.main
```

### Setup Wizard

The `setup.py` script will prompt for:
- Admin username/password
- Panel display name
- Domain for SSH proxy (e.g., `panel.example.com`)
- SSH proxy port range (default: 22000-22999)

## Architecture

```
vps_panel/
├── app/
│   ├── main.py              # Flask application
│   ├── config.py            # Configuration loader
│   ├── models/__init__.py   # Database models (SQLite)
│   ├── services/
│   │   └── lxc_service.py   # LXC + SSH proxy services
│   ├── templates/           # Jinja2 templates
│   └── static/              # CSS/JS assets
├── config.yaml              # Main configuration
├── setup.py                 # Initial setup wizard
├── requirements.txt         # Python dependencies
└── run.py                   # Entry point
```

## Configuration

Edit `config.yaml` to customize:

```yaml
app:
  name: "VPS Panel"
  secret_key: "your-secret-key"
  host: "0.0.0.0"
  port: 8080

database:
  type: "sqlite"
  path: "data/panel.db"

lxc:
  storage_pool: "default"
  network_bridge: "lxcbr0"
  templates_path: "lxc_templates"

ssh_proxy:
  enabled: true
  domain: "panel.example.com"
  port_range_start: 22000
  port_range_end: 22999
  sshx_enabled: true
```

## SSH Domain Proxy

The panel automatically allocates a unique port (22000-22999) for each VPS and configures iptables DNAT rules. Users connect via:

```bash
ssh root@panel.example.com -p 22001
```

Password is displayed in the VPS detail page.

## SSHX Web Terminal

Access via `/sshx/<vps_id>` - provides a full terminal in browser with:
- Real-time collaboration
- Clipboard synchronization
- File upload/download
- Multiple panes/tabs

## Themes

Built-in themes (in `config.yaml` and database):
- **Dark** (default) - Slate gray
- **Light** - Clean white
- **Ocean** - Blue tones
- **Forest** - Green tones
- **Sunset** - Pink/purple tones

Admins can add custom themes via Admin → Themes with custom CSS variables.

## Admin Features

Access `/admin` with admin account:
- **Dashboard**: System overview, recent activity
- **Users**: Manage users, promote to admin
- **OS Templates**: Add/edit/disable container templates
- **Themes**: Switch themes, create custom themes
- **Audit Logs**: Filterable security/activity logs

## Development

```bash
# Run in debug mode
export FLASK_DEBUG=1
python -m app.main
```

## Production Deployment

1. Use a reverse proxy (nginx/Caddy) with SSL
2. Set `debug: false` in config.yaml
3. Use a strong `secret_key`
4. Configure firewall for panel port (8080) and SSH proxy range (22000-22999)
5. Run as systemd service:

```ini
[Unit]
Description=VPS Panel
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vps_panel
ExecStart=/opt/vps_panel/venv/bin/python -m app.main
Restart=always

[Install]
WantedBy=multi-user.target
```

## Security Notes

- Run on a trusted network or behind VPN
- SSH proxy exposes container SSH on domain ports
- Change default password immediately after setup
- Keep LXC/LXD and host kernel updated
- Audit logs track all admin actions

## License

MIT License - Feel free to modify and distribute.