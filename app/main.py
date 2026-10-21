"""
VPS Panel - Main Flask Application
"""

import os
import sys
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from werkzeug.security import check_password_hash

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import get_config
from app.models import (
    User, VPSInstance, OSTemplate, SSHProxyPort, Theme, AuditLog, init_db
)
from app.services.lxc_service import VPSProvisioner

config = get_config()
app_config = config["app"]

app = Flask(__name__,
            template_folder=str(BASE_DIR / "app/templates"),
            static_folder=str(BASE_DIR / "app/static"))
app.secret_key = app_config["secret_key"]
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 3600 * config["security"]["session_timeout_hours"]


# Helper functions
def get_current_user():
    if "user_id" not in session:
        return None
    return User.get_by_id(session["user_id"])


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_user():
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or not user.get("is_admin"):
            flash("Admin access required", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def inject_globals():
    user = get_current_user()
    themes = Theme.get_all()
    current_theme = user.get("theme", "dark") if user else "dark"
    theme_data = Theme.get_css_variables(current_theme)
    panel_name = config["app"]["name"]
    return dict(
        current_user=user,
        themes=themes,
        current_theme=current_theme,
        theme_vars=theme_data,
        panel_name=panel_name
    )

app.context_processor(inject_globals)


# Routes
@app.route("/")
def index():
    user = get_current_user()
    if user:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.get_by_username(username)
        if user and User.verify_password(user, password):
            session["user_id"] = user["id"]
            User.update_last_login(user["id"])
            AuditLog.log(user["id"], "login", "auth", None, f"User {username} logged in", request.remote_addr)
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
        else:
            AuditLog.log(None, "login_failed", "auth", None, f"Failed login for {username}", request.remote_addr)
            flash("Invalid credentials", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    user = get_current_user()
    if user:
        AuditLog.log(user["id"], "logout", "auth", None, f"User {user['username']} logged out", request.remote_addr)
    session.clear()
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    config = get_config()
    if not config.get("app", {}).get("allow_registration", True):
        flash("Registration is disabled", "danger")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        
        if not username or not password:
            flash("All fields required", "danger")
        elif password != password_confirm:
            flash("Passwords do not match", "danger")
        elif User.get_by_username(username):
            flash("Username already exists", "danger")
        else:
            User.create(username, password, is_admin=False)
            flash("Account created. Please login.", "success")
            return redirect(url_for("login"))
    
    return render_template("register.html")


@app.route("/admin/vps/assign", methods=["POST"])
@login_required
@admin_required
def admin_assign_vps():
    user_id = request.form.get("user_id", type=int)
    vps_id = request.form.get("vps_id", type=int)
    
    if not user_id or not vps_id:
        flash("User and VPS required", "danger")
        return redirect(url_for("admin_dashboard"))
    
    vps = VPSInstance.get_by_id(vps_id)
    if not vps:
        flash("VPS not found", "danger")
        return redirect(url_for("admin_dashboard"))
    
    VPSInstance.update(vps_id, user_id=user_id)
    AuditLog.log(get_current_user()["id"], "vps_assign", "vps", vps_id, f"Assigned VPS {vps['name']} to user {user_id}", request.remote_addr)
    flash("VPS assigned", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    vps_list = VPSInstance.get_by_user(user["id"])
    return render_template("dashboard.html", vps_list=vps_list)


@app.route("/vps/create", methods=["GET", "POST"])
@login_required
def create_vps():
    user = get_current_user()
    templates = OSTemplate.get_all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        hostname = request.form.get("hostname", "").strip().lower()
        os_template = request.form.get("os_template", "")
        cpu = int(request.form.get("cpu", 1))
        memory = int(request.form.get("memory", 512))
        disk = int(request.form.get("disk", 5))

        if not name or not hostname or not os_template:
            flash("All fields are required", "danger")
            return render_template("create_vps.html", templates=templates)

        # Check hostname uniqueness
        existing = VPSInstance.get_by_id(0)  # dummy
        with app.app_context():
            from app.models import get_db
            with get_db() as conn:
                row = conn.execute("SELECT id FROM vps_instances WHERE hostname = ?", (hostname,)).fetchone()
                if row:
                    flash("Hostname already in use", "danger")
                    return render_template("create_vps.html", templates=templates)

        provisioner = VPSProvisioner()
        result = provisioner.provision(user["id"], name, hostname, os_template, cpu, memory, disk)

        if result["success"]:
            flash(f"VPS '{name}' is being provisioned", "success")
            return redirect(url_for("vps_detail", vps_id=result["vps"]["id"]))
        else:
            flash(result["error"], "danger")

    return render_template("create_vps.html", templates=templates)


@app.route("/vps/<int:vps_id>")
@login_required
def vps_detail(vps_id):
    user = get_current_user()
    vps = VPSInstance.get_by_id(vps_id)

    if not vps or vps["user_id"] != user["id"]:
        flash("VPS not found", "danger")
        return redirect(url_for("dashboard"))

    provisioner = VPSProvisioner()
    ssh_info = provisioner.ssh_proxy.get_ssh_command(vps)
    snapshots = provisioner.lxc.snapshot_list(vps["hostname"])
    usage = provisioner.lxc.get_usage_stats(vps["hostname"])

    return render_template("vps_detail.html", vps=vps, ssh_info=ssh_info, snapshots=snapshots, usage=usage)


@app.route("/vps/<int:vps_id>/action", methods=["POST"])
@login_required
def vps_action(vps_id):
    user = get_current_user()
    action = request.form.get("action")
    provisioner = VPSProvisioner()

    result = provisioner.power_action(user["id"], vps_id, action)
    if result["success"]:
        flash(f"VPS {action} initiated", "success")
    else:
        flash(result["error"], "danger")

    return redirect(url_for("vps_detail", vps_id=vps_id))


@app.route("/vps/<int:vps_id>/reinstall", methods=["POST"])
@login_required
def vps_reinstall(vps_id):
    user = get_current_user()
    os_template = request.form.get("os_template")
    provisioner = VPSProvisioner()

    result = provisioner.reinstall(user["id"], vps_id, os_template)
    if result["success"]:
        flash("VPS reinstallation started", "success")
    else:
        flash(result["error"], "danger")

    return redirect(url_for("vps_detail", vps_id=vps_id))


@app.route("/vps/<int:vps_id>/resize", methods=["POST"])
@login_required
def vps_resize(vps_id):
    user = get_current_user()
    cpu = request.form.get("cpu", type=int)
    memory = request.form.get("memory", type=int)
    disk = request.form.get("disk", type=int)
    provisioner = VPSProvisioner()

    result = provisioner.resize(user["id"], vps_id, cpu, memory, disk)
    if result["success"]:
        flash("VPS resize initiated", "success")
    else:
        flash(result["error"], "danger")

    return redirect(url_for("vps_detail", vps_id=vps_id))


@app.route("/vps/<int:vps_id>/snapshot", methods=["POST"])
@login_required
def vps_snapshot(vps_id):
    user = get_current_user()
    vps = VPSInstance.get_by_id(vps_id)

    if not vps or vps["user_id"] != user["id"]:
        return jsonify({"success": False, "error": "Not found"}), 404

    snapshot_name = request.form.get("name", f"snapshot-{vps_id}")
    provisioner = VPSProvisioner()
    success = provisioner.lxc.snapshot_create(vps["hostname"], snapshot_name)

    if success:
        AuditLog.log(user["id"], "snapshot_create", "vps", vps_id, f"Created snapshot {snapshot_name}", request.remote_addr)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Failed to create snapshot"}), 500


@app.route("/vps/<int:vps_id>/snapshot/<snapshot_name>/restore", methods=["POST"])
@login_required
def vps_snapshot_restore(vps_id, snapshot_name):
    user = get_current_user()
    vps = VPSInstance.get_by_id(vps_id)

    if not vps or vps["user_id"] != user["id"]:
        return jsonify({"success": False, "error": "Not found"}), 404

    provisioner = VPSProvisioner()
    success = provisioner.lxc.snapshot_restore(vps["hostname"], snapshot_name)

    if success:
        AuditLog.log(user["id"], "snapshot_restore", "vps", vps_id, f"Restored snapshot {snapshot_name}", request.remote_addr)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Failed to restore snapshot"}), 500


@app.route("/vps/<int:vps_id>/console")
@login_required
def vps_console(vps_id):
    user = get_current_user()
    vps = VPSInstance.get_by_id(vps_id)

    if not vps or vps["user_id"] != user["id"]:
        flash("VPS not found", "danger")
        return redirect(url_for("dashboard"))

    provisioner = VPSProvisioner()
    ssh_info = provisioner.ssh_proxy.get_ssh_command(vps)

    return render_template("console.html", vps=vps, ssh_info=ssh_info)


# Admin Routes
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    users = User.list_all()
    all_vps = VPSInstance.get_all()
    templates = OSTemplate.get_all(active_only=False)
    recent_logs = AuditLog.get_recent(50)
    return render_template("admin/dashboard.html", users=users, all_vps=all_vps, templates=templates, logs=recent_logs)


@app.route("/admin/themes", methods=["GET", "POST"])
@login_required
@admin_required
def admin_themes():
    if request.method == "POST":
        theme_name = request.form.get("theme")
        user = get_current_user()
        User.update_theme(user["id"], theme_name)
        flash("Theme updated", "success")
        return redirect(url_for("admin_themes"))

    themes = Theme.get_all()
    return render_template("admin/themes.html", themes=themes)


@app.route("/admin/templates", methods=["GET", "POST"])
@login_required
@admin_required
def admin_templates():
    if request.method == "POST":
        name = request.form.get("name")
        display_name = request.form.get("display_name")
        description = request.form.get("description")
        architecture = request.form.get("architecture", "amd64")
        template_url = request.form.get("template_url", "")

        OSTemplate.create(name, display_name, description, architecture, template_url)
        flash("Template added", "success")
        return redirect(url_for("admin_templates"))

    templates = OSTemplate.get_all(active_only=False)
    return render_template("admin/templates.html", templates=templates)


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    users = User.list_all()
    return render_template("admin/users.html", users=users)


@app.route("/admin/logs")
@login_required
@admin_required
def admin_logs():
    logs = AuditLog.get_recent(200)
    return render_template("admin/logs.html", logs=logs)


# API Routes for AJAX
@app.route("/api/vps/<int:vps_id>/stats")
@login_required
def api_vps_stats(vps_id):
    user = get_current_user()
    vps = VPSInstance.get_by_id(vps_id)

    if not vps or vps["user_id"] != user["id"]:
        return jsonify({"error": "Not found"}), 404

    provisioner = VPSProvisioner()
    usage = provisioner.lxc.get_usage_stats(vps["hostname"])
    return jsonify(usage)


@app.route("/api/theme", methods=["POST"])
@login_required
def api_set_theme():
    user = get_current_user()
    theme = request.json.get("theme")
    if theme:
        User.update_theme(user["id"], theme)
        return jsonify({"success": True, "theme": theme})
    return jsonify({"success": False}), 400


# Static file serving for SSHX
@app.route("/sshx/<int:vps_id>")
@login_required
def sshx_terminal(vps_id):
    user = get_current_user()
    vps = VPSInstance.get_by_id(vps_id)

    if not vps or vps["user_id"] != user["id"]:
        flash("VPS not found", "danger")
        return redirect(url_for("dashboard"))

    return render_template("sshx.html", vps=vps)


# Health check
@app.route("/health")
def health():
    return jsonify({"status": "ok", "panel": config["app"]["name"]})


if __name__ == "__main__":
    init_db()
    app.run(host=app_config["host"], port=app_config["port"], debug=app_config["debug"])
