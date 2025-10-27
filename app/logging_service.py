import os
import json
import hmac
import hashlib
import logging
import shutil
import stat
from datetime import datetime
from typing import Optional, Tuple, List


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
            self.last_hmac = None

        # Open file handle lazily (append per write to avoid long-held handles)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            payload = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'level': record.levelname,
                'logger': record.name,
                'message': msg,
                'pathname': getattr(record, 'pathname', None),
                'lineno': getattr(record, 'lineno', None),
            }
            # Allow extra structured data if provided
            extra = getattr(record, 'extra', None)
            if extra:
                payload['extra'] = extra

            # include previous hmac for chain
            payload['prev_hmac'] = self.last_hmac

            # canonical JSON: sort keys, separators compact
            canonical = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
            h = hmac.new(self.key, canonical, hashlib.sha256).hexdigest()
            payload['hmac'] = h

            line = json.dumps(payload, ensure_ascii=False) + '\n'

            # Append atomically
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    # Windows may not support fsync same way; ignore
                    pass

            # persist last_hmac to state file
            try:
                with open(self.state_path, 'w', encoding='utf-8') as sf:
                    sf.write(h)
            except Exception:
                pass

            self.last_hmac = h
        except Exception:
            # logging should not raise
            try:
                logging.getLogger(__name__).exception('Audit logging failed')
            except Exception:
                pass


def init_audit_logging(app) -> None:
    """Initialize audit logging using app config.

    Config keys:
      - AUDIT_LOG_PATH: file path for audit log (default: instance/audit.log)
      - AUDIT_HMAC_KEY: secret key for HMAC (must be set in env/config)
    """
    path = app.config.get('AUDIT_LOG_PATH') or os.path.join(app.instance_path, 'audit.log')
    key = app.config.get('AUDIT_HMAC_KEY') or os.environ.get('AUDIT_HMAC_KEY')
    if not key:
        app.logger.warning('AUDIT_HMAC_KEY not set; audit logs will not be HMAC protected.')
        key_bytes = b'dev-key'
    else:
        key_bytes = key.encode('utf-8')

    handler = HmacAuditHandler(path=path, key=key_bytes, level=logging.INFO)
    # Use a simple formatter (message already included); keep handler name
    handler.setFormatter(logging.Formatter('%(message)s'))
    handler.name = 'hmac_audit'

    root = logging.getLogger('')
    # Avoid duplicate handler addition
    if not any(getattr(h, 'name', None) == handler.name for h in root.handlers):
        root.addHandler(handler)

    # Also attach to the flask app logger
    if not any(getattr(h, 'name', None) == handler.name for h in app.logger.handlers):
        app.logger.addHandler(handler)


def seal_log(file_path: str) -> Optional[str]:
    """Make a sealed copy of the audit log and set it read-only.

    Returns the path of the sealed file or None on failure.
    """
    try:
        if not os.path.exists(file_path):
            return None
        ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
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
            pass

        return sealed
    except Exception:
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
        errors.append(f'file error: {e}')

    return (len(errors) == 0, errors)
