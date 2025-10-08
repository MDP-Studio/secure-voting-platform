"""
Routes package for the application.
Contains various route blueprints.
"""

from . import main, dev_routes, health, candidates, registration

__all__ = ['main', 'dev_routes', 'health', 'candidates', 'registration']