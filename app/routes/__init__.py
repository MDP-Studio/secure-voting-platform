"""
Routes package for the application.
Contains various route blueprints.
"""

from . import main, dev_routes, health, candidates, registration, password

__all__ = ['main', 'dev_routes', 'health', 'candidates', 'registration', 'password']
from . import admin_users, main, dev_routes, health, candidates, registration

__all__ = ['main', 'dev_routes', 'health', 'candidates', 'registration', 'admin_users']
