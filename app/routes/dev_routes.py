"""
Developer routes for debugging and monitoring.
This file contains development-only routes that should NEVER be enabled in production.
"""

from flask import Blueprint, render_template, request, jsonify, g
from app import db
from app.models import User, Candidate, Vote
from app.security import get_client_ip, is_ip_allowed
import os
import platform
import psutil
import socket
from flask import current_app
from datetime import datetime
import subprocess

dev = Blueprint('dev', __name__, url_prefix='/dev')

@dev.route('/dashboard')
def dev_dashboard():
    """Developer dashboard - LOCAL DEVELOPMENT ONLY"""
    # Get real client IP (handle proxy/load balancer)
    client_ip = get_client_ip(request)
    
    # For development, also allow requests from nginx container network
    allowed_ips = ['127.0.0.1', '::1', '172.16.0.0/12']
    
    # Check if client IP is allowed (supports both individual IPs and CIDR subnets)
    if not is_ip_allowed(client_ip, allowed_ips):
        forwarded_header = request.headers.get('X-Forwarded-For', 'Not set')
        current_app.logger.warning(f"Dev dashboard access denied - Client IP: {client_ip}, Forwarded: {forwarded_header}, Allowed IPs: {allowed_ips}")
        return f"Access denied: Developer dashboard only available locally (client IP: {client_ip}, forwarded: {forwarded_header})", 403

    # Database contents
    users = User.query.all()
    candidates = Candidate.query.all()
    votes = Vote.query.all()

    # System information
    system_info = {
        'platform': platform.platform(),
        'python_version': platform.python_version(),
        'hostname': socket.gethostname(),
        'cpu_count': psutil.cpu_count(),
        'memory_total': f"{psutil.virtual_memory().total / (1024**3):.1f} GB",
        'memory_used': f"{psutil.virtual_memory().used / (1024**3):.1f} GB",
        'disk_free': f"{psutil.disk_usage('/').free / (1024**3):.1f} GB",
    }

    # App information
    app_info = {
        'flask_version': current_app.config.get('VERSION', 'Unknown'),
        'debug_mode': current_app.debug,
        'testing_mode': current_app.testing,
        'database_uri': current_app.config.get('SQLALCHEMY_DATABASE_URI', 'Not configured'),
        'secret_key_configured': bool(current_app.config.get('SECRET_KEY')),
    }

    # Read log files (last 50 lines each) - DEPRECATED: Now loaded via AJAX
    def read_last_lines(filepath, lines=50):
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.readlines()
                return ''.join(content[-lines:])
        except Exception as e:
            return f"Error reading file: {e}"

    # Web server logs (Flask logs) - DEPRECATED: Now loaded via AJAX
    log_file = os.path.join(current_app.instance_path, 'app.log')
    web_logs = read_last_lines(log_file)

    # WAF logs (nginx access/error logs) - DEPRECATED: Now loaded via AJAX
    # Note: nginx logs are in the nginx container. Use 'docker-compose logs waf' to view them
    nginx_access_log = "WAF access logs available via: docker-compose logs waf"
    nginx_error_log = "WAF error logs available via: docker-compose logs waf"

    # Client connection information
    client_info = {
        'remote_addr': request.remote_addr,
        'x_forwarded_for': request.headers.get('X-Forwarded-For', 'Not set'),
        'x_real_ip': request.headers.get('X-Real-IP', 'Not set'),
        'x_forwarded_proto': request.headers.get('X-Forwarded-Proto', 'Not set'),
        'user_agent': request.headers.get('User-Agent', 'Not set'),
        'host': request.headers.get('Host', 'Not set'),
        'referer': request.headers.get('Referer', 'Not set'),
    }

    # Database information
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', 'Not configured')
    db_binds = current_app.config.get('SQLALCHEMY_BINDS') or {}
    active_bind = getattr(g, '_active_bind', None) or 'default'
    debug_db_bind = bool(current_app.config.get('DEBUG_DB_BIND'))

    # Evaluate whether a true split is configured (different URLs)
    try:
        unique_uris = {db_uri}
        admin_uri = db_binds.get('admin')
        voters_uri = db_binds.get('voters')
        if admin_uri:
            unique_uris.add(admin_uri)
        if voters_uri:
            unique_uris.add(voters_uri)
        split_enabled = len(unique_uris) > 1
    except Exception:
        split_enabled = False

    db_info = {
        'uri': db_uri,
        'type': 'SQLite' if isinstance(db_uri, str) and db_uri.startswith('sqlite:///') else (
            'MySQL' if isinstance(db_uri, str) and 'mysql' in db_uri else (
            'PostgreSQL' if isinstance(db_uri, str) and 'postgresql' in db_uri else 'Unknown')
        ),
        'active_bind': active_bind,
        'debug_db_bind_header': debug_db_bind,
        'split_configured': split_enabled,
        'bind_admin': admin_uri or '(not set)',
        'bind_voters': voters_uri or '(not set)',
    }

    # For SQLite, add file information
    if isinstance(db_uri, str) and db_uri.startswith('sqlite:///'):
        db_path = db_uri.replace('sqlite:///', '')
        db_info.update({
            'path': db_path,
            'exists': os.path.exists(db_path),
            'size': f"{os.path.getsize(db_path) / 1024:.1f} KB" if os.path.exists(db_path) else "N/A",
            'modified': datetime.fromtimestamp(os.path.getmtime(db_path)).strftime('%Y-%m-%d %H:%M:%S') if os.path.exists(db_path) else "N/A"
        })
    else:
        # For other databases, show connection info
        db_info.update({
            'path': 'Remote database (MySQL/PostgreSQL)',
            'exists': 'Connected via network',
            'size': 'N/A (remote database)',
            'modified': 'N/A (remote database)'
        })

    return render_template('dev_dashboard.html',
                         users=users,
                         candidates=candidates,
                         votes=votes,
                         system_info=system_info,
                         app_info=app_info,
                         client_info=client_info,
                         db_info=db_info)


@dev.route('/logs')
def get_logs():
    """API endpoint to get logs via AJAX - LOCAL DEVELOPMENT ONLY"""
    # Get real client IP (handle proxy/load balancer)
    client_ip = get_client_ip(request)

    # For development, also allow requests from nginx container network
    allowed_ips = ['127.0.0.1', '::1', '172.16.0.0/12']

    # Check if client IP is allowed (supports both individual IPs and CIDR subnets)
    if not is_ip_allowed(client_ip, allowed_ips):
        return jsonify({'error': 'Access denied'}), 403

    # Read log files (last 100 lines each)
    def read_last_lines(filepath, lines=100):
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.readlines()
                return ''.join(content[-lines:])
        except Exception as e:
            return f"Error reading file: {e}"

    # Web server logs (Flask logs)
    log_file = os.path.join(current_app.instance_path, 'app.log')
    web_logs = read_last_lines(log_file)

    # WAF logs from Docker containers
    def get_docker_logs(container_name, tail=100):
        try:
            result = subprocess.run(
                ['docker-compose', 'logs', '--tail', str(tail), container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout
            else:
                return f"Error getting logs from {container_name}: {result.stderr}"
        except subprocess.TimeoutExpired:
            return f"Timeout getting logs from {container_name}"
        except FileNotFoundError:
            return f"docker-compose command not found. Make sure Docker is running."
        except Exception as e:
            return f"Error getting logs from {container_name}: {e}"

    nginx_access_log = get_docker_logs('waf')
    nginx_error_log = get_docker_logs('waf')  # Same container, but we can differentiate if needed

    return jsonify({
        'web_logs': web_logs,
        'nginx_access_log': nginx_access_log,
        'nginx_error_log': nginx_error_log
    })