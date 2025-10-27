"""Generate test audit log entries and verify HMAC chain.

This script writes to `instance/audit_test.log` using the HmacAuditHandler
with a test key (b'test-key'), then runs verify_audit against it and prints
results.
"""
import logging
import os
from app.logging_service import HmacAuditHandler, verify_audit

os.makedirs('instance', exist_ok=True)
path = os.path.join('instance', 'audit_test.log')
key = b'test-key'

# Create handler and logger
handler = HmacAuditHandler(path=path, key=key, level=logging.INFO)
handler.setFormatter(logging.Formatter('%(message)s'))
handler.name = 'hmac_test'

logger = logging.getLogger('generate_test_log')
logger.setLevel(logging.INFO)
# Avoid duplicate handlers
if not any(getattr(h, 'name', None) == handler.name for h in logger.handlers):
    logger.addHandler(handler)

logger.info('Test audit entry 1: user=test action=login_attempt')
logger.info('Test audit entry 2: user=test action=registration')

print('Wrote test entries to', path)

ok, errors = verify_audit(path, key)
print('Verification OK?', ok)
if errors:
    print('Errors:')
    for e in errors:
        print(' -', e)
else:
    print('No verification errors')
