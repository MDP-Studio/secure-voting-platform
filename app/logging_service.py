import os
import json
import hmac
import hashlib
import logging
import shutil
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Tuple, List


AUDIT_HANDLER_NAME = 'hmac_audit'
AUDIT_LOGGER_NAME = 'securevote.audit'


def record_audit_event(
    *,
    actor_id,
    action: str,
    target_type: str,
    target_id,
    outcome: str = 'success',
) -> None:
    """Record a privacy-minimal structured security action.

    Callers must invoke this only after the related database commit succeeds.
    Identifiers are normalized to strings so every event remains JSON serializable.
    """
    event = {
        'actor': {
            'id': 'anonymous' if actor_id is None else str(actor_id),
        },
        'action': str(action),
        'target': {
            'type': str(target_type),
            'id': str(target_id),
        },
        'outcome': str(outcome),
    }
    logging.getLogger(AUDIT_LOGGER_NAME).info(
        'security_action',
        extra={'extra': event},
    )


@contextmanager
def _exclusive_file_lock(lock_file):
    """Apply an exclusive advisory lock on Unix and Windows."""
    if os.name == 'nt':
        import msvcrt

        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write('\0')
            lock_file.flush()

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


class HmacAuditHandler(logging.Handler):
    """A logging handler that appends HMAC-signed JSON lines to an audit log.

    Each line is a JSON object with fields:
      - timestamp (ISO)
      - level
      - logger
      - message
      - pathname, lineno
      - extra (optional)
      - prev_hmac (hex) - links to previous record to make a chain
      - hmac (hex) - HMAC-SHA256 over the canonical JSON payload + prev_hmac

    The handler keeps a small state file (same path + '.state') containing
    the last hmac so chains continue across restarts.
    """

    def __init__(self, path: str, key: bytes, level=logging.INFO):
        super().__init__(level=level)
        self.path = path
        self.key = key
        self.state_path = path + '.state'
        self.last_hmac = None
        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Load last hmac if available
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    self.last_hmac = f.read().strip() or None
        except Exception:
            logging.getLogger(__name__).debug("Handled exception in app/logging_service.py", exc_info=True)
            self.last_hmac = None

        # Open file handle lazily (append per write to avoid long-held handles)

    def emit(self, record: logging.LogRecord) -> None:
        """Write an HMAC-signed log entry with file locking.

        A lock file serializes writes across multiple Gunicorn workers
        so the HMAC chain remains linear and verifiable.
        """
        try:
            msg = self.format(record)
            payload = {
                'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                'level': record.levelname,
                'logger': record.name,
                'message': msg,
                'pathname': getattr(record, 'pathname', None),
                'lineno': getattr(record, 'lineno', None),
            }
            extra = getattr(record, 'extra', None)
            if extra:
                payload['extra'] = extra

            # Acquire exclusive lock to serialize across workers
            lock_path = self.path + '.lock'
            with open(lock_path, 'a+', encoding='utf-8') as lock_f:
                with _exclusive_file_lock(lock_f):
                    # Re-read last_hmac from state file because another worker
                    # may have updated it while this process waited for the lock.
                    try:
                        if os.path.exists(self.state_path):
                            with open(self.state_path, 'r', encoding='utf-8') as sf:
                                self.last_hmac = sf.read().strip() or None
                    except Exception:
                        logging.getLogger(__name__).debug("Handled exception in app/logging_service.py", exc_info=True)
                        pass

                    payload['prev_hmac'] = self.last_hmac

                    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
                    h = hmac.new(self.key, canonical, hashlib.sha256).hexdigest()
                    payload['hmac'] = h

                    line = json.dumps(payload, ensure_ascii=False) + '\n'

                    with open(self.path, 'a', encoding='utf-8') as f:
                        f.write(line)
                        f.flush()

                    # Persist last_hmac for next entry
                    self.last_hmac = h
                    try:
                        with open(self.state_path, 'w', encoding='utf-8') as sf:
                            sf.write(h)
                    except Exception:
                        logging.getLogger(__name__).debug("Handled exception in app/logging_service.py", exc_info=True)
                        pass

            self.last_hmac = h
        except Exception:
            logging.getLogger(__name__).debug("Handled exception in app/logging_service.py", exc_info=True)
            self.handleError(record)


def init_audit_logging(app) -> None:
    """Initialize audit logging using app config.

    Config keys:
      - AUDIT_LOG_PATH: file path for audit log (default: instance/audit.log)
      - AUDIT_HMAC_KEY: secret key for HMAC (must be set in env/config)
    """
    path = app.config.get('AUDIT_LOG_PATH') or os.path.join(app.instance_path, 'audit.log')
    key = app.config.get('AUDIT_HMAC_KEY') or os.environ.get('AUDIT_HMAC_KEY')
    if not key:
        if not app.config.get('TESTING'):
            raise RuntimeError('AUDIT_HMAC_KEY is required outside test mode')
        key_bytes = b'test-only-audit-hmac-key-32-bytes'
    else:
        key_bytes = key.encode('utf-8')

    handler = HmacAuditHandler(path=path, key=key_bytes, level=logging.INFO)
    # Use a simple formatter (message already included); keep handler name
    handler.setFormatter(logging.Formatter('%(message)s'))
    handler.name = AUDIT_HANDLER_NAME

    root = logging.getLogger('')
    audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)
    stale_handlers = set()
    for logger in (root, app.logger, audit_logger):
        for existing in list(logger.handlers):
            if getattr(existing, 'name', None) == AUDIT_HANDLER_NAME:
                logger.removeHandler(existing)
                stale_handlers.add(existing)
    for existing in stale_handlers:
        existing.close()

    # Only the dedicated structured-event logger enters the HMAC chain.
    # Operational request logs stay in the application log so IP/timing data
    # cannot silently turn the ballot audit trail into a correlation channel.
    audit_logger.addHandler(handler)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False


def seal_log(file_path: str) -> Optional[str]:
    """Make a sealed copy of the audit log and set it read-only.

    Returns the path of the sealed file or None on failure.
    """
    try:
        if not os.path.exists(file_path):
            return None
        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        dirname = os.path.dirname(file_path)
        base = os.path.basename(file_path)
        sealed = os.path.join(dirname, f"{base}.{ts}.sealed")
        shutil.copy2(file_path, sealed)

        # Set read-only depending on platform
        try:
            if os.name == 'nt':
                # Windows: remove write bits via chmod
                os.chmod(sealed, stat.S_IREAD)
            else:
                os.chmod(sealed, 0o444)
        except Exception:
            logging.getLogger(__name__).debug("Handled exception in app/logging_service.py", exc_info=True)
            pass

        return sealed
    except Exception:
        logging.getLogger(__name__).debug("Handled exception in app/logging_service.py", exc_info=True)
        return None


def verify_audit(file_path: str, key: bytes) -> Tuple[bool, List[str]]:
    """Verify the audit log chain. Returns (ok, errors).

    Expects JSON lines as written by HmacAuditHandler.
    """
    errors: List[str] = []
    last_hmac = None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for i, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    logging.getLogger(__name__).debug("Handled exception in app/logging_service.py", exc_info=True)
                    errors.append(f'line {i}: invalid json')
                    continue
                prev = obj.get('prev_hmac')
                if prev != last_hmac:
                    errors.append(f'line {i}: prev_hmac mismatch (expected {last_hmac} got {prev})')
                # recompute
                h = obj.get('hmac')
                obj_copy = dict(obj)
                obj_copy.pop('hmac', None)
                canonical = json.dumps(obj_copy, sort_keys=True, separators=(',', ':')).encode('utf-8')
                comp = hmac.new(key, canonical, hashlib.sha256).hexdigest()
                if comp != h:
                    errors.append(f'line {i}: hmac mismatch')
                last_hmac = h
    except Exception as e:
        logging.getLogger(__name__).debug("Handled exception in app/logging_service.py", exc_info=True)
        errors.append(f'file error: {e}')

    return (len(errors) == 0, errors)
