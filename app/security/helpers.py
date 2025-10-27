"""
Security helper functions for IP validation and client IP detection.
"""

import ipaddress
import os
import socket


def get_allowed_dev_subnets():
    """
    Returns a list of allowed IPs and subnets for development routes.
    This can include localhost and common Docker subnets.
    """

    DEFAULT = "127.0.0.1,192.168.1.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

    # get from flask config ALLOWED_IPS
    allowed_ips_env = os.environ.get("ALLOWED_IPS", DEFAULT)
    allowed_ips = [ip.strip() for ip in allowed_ips_env.split(",") if ip.strip()]

    return allowed_ips


def get_client_ip(request):
    """
    Get the real client IP address, accounting for proxy headers.

    Checks headers in order of preference:
    1. X-Real-IP (set by some proxies/load balancers)
    2. X-Forwarded-For (comma-separated list, takes first IP)
    3. request.remote_addr (direct connection)

    Returns the IP address as a string.
    """
    # Check X-Real-IP first (preferred by some proxies)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Check X-Forwarded-For (most common)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first IP in the chain (original client)
        return forwarded.split(",")[0].strip()

    # Fallback to direct remote address
    return request.remote_addr


def is_ip_allowed(client_ip, allowed_list):
    """
    Check if a client IP is allowed based on a list that can contain individual IPs and CIDR subnets.

    Args:
        client_ip (str): The client IP address to check
        allowed_list (list): List of allowed entries (IPs or CIDR subnets like '192.168.1.0/24')

    Returns:
        bool: True if the IP is allowed, False otherwise
    """
    if not client_ip:
        return False
    
    if not allowed_list:
        allowed_list = get_allowed_dev_subnets()

    for allowed in allowed_list:
        if "/" in allowed:
            # Handle CIDR subnet
            try:
                network = ipaddress.ip_network(allowed, strict=False)
                if ipaddress.ip_address(client_ip) in network:
                    return True
            except (ipaddress.AddressValueError, ValueError):
                # Invalid subnet format, skip
                continue
        elif allowed == client_ip:
            # Exact IP match
            return True

    return False


def resolve_container_ip(hostname, logger=None):
    """
    Example helper for dynamically resolving container IPs using Docker DNS.

    This is useful when you need to allow access from specific containers
    but don't want to hardcode IPs. Note: This may not be necessary if you're
    already allowing entire subnets (e.g., '172.16.0.0/12' for Docker networks).

    Args:
        hostname (str): The container hostname/service name
        logger: Optional logger for warning messages

    Returns:
        str or None: The resolved IP address, or None if resolution fails
    """
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror as e:
        if logger:
            logger.warning(f"Could not resolve '{hostname}' hostname: {e}")
        return None
