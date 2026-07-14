from flask import Blueprint, jsonify, request, render_template_string, current_app
from flask_login import login_required, current_user
from app import db
from app.logging_service import record_audit_event
from app.models import Election, ResultSigningPublicKey, SignedElectionResult
from app.security import signing_service
from app.services.results_service import ResultsUnavailableError, get_vote_tallies
from datetime import datetime, timezone
from functools import wraps
import json
import threading
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

results = Blueprint('results', __name__)
_result_signing_lock = threading.Lock()


def _serialize_result_signing(function):
    """Serialize rare manager signing operations within one app process."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with _result_signing_lock:
            return function(*args, **kwargs)

    return wrapped

@results.route('/results/sign', methods=['POST'])
@login_required
@_serialize_result_signing
def sign_election_results():
    """
    ADMIN-ONLY ENDPOINT.
    Signs the final election results and stores the signature.
    """
    # Enforce manager role (admin-equivalent) for signing
    if not getattr(current_user, "is_manager", False):
        return jsonify({"error": "Forbidden"}), 403

    body = request.get_json(silent=True) or {}
    election_id = body.get("election_id") or request.form.get("election_id")
    try:
        election_id = int(election_id)
    except (TypeError, ValueError):
        current_app.logger.debug("Rejected non-integer election_id for signing")
        return jsonify({"error": "A valid election_id is required."}), 400

    election = (
        db.session.query(Election)
        .filter(Election.id == election_id)
        .with_for_update()
        .first()
    )
    if not election:
        return jsonify({"error": "Election not found."}), 404
    if election.status != "closed":
        db.session.rollback()
        return jsonify({"error": "Only closed election results can be signed."}), 409

    # A closed election has one canonical signed projection. Holding the
    # election row lock serializes signers on databases that support FOR UPDATE;
    # the unique election_id constraint remains the final cross-process guard.
    if SignedElectionResult.query.filter_by(election_id=election.id).first():
        db.session.rollback()
        return jsonify({"error": "Election results have already been signed."}), 409

    try:
        tallies = get_vote_tallies(election.id)
    except ResultsUnavailableError:
        db.session.rollback()
        current_app.logger.error(
            "Refused to sign unavailable tallies for election %s",
            election.id,
            exc_info=True,
        )
        return jsonify({"error": "Authoritative election results are unavailable."}), 503

    signed_at = datetime.now(timezone.utc)
    election_results = {
        "election_id": election.id,
        "election_name": election.name,
        "signed_at": signed_at.isoformat(),
        "results": tallies,
        "total_votes": sum(item["votes"] for item in tallies),
    }

    # Convert results dictionary to a consistent JSON string (bytes)
    results_json = json.dumps(election_results, sort_keys=True, separators=(',', ':')).encode('utf-8')

    try:
        signed = signing_service.sign_data(results_json)
    except signing_service.SigningUnavailableError:
        db.session.rollback()
        current_app.logger.error(
            "Refused to sign election %s because its signing backend is unavailable.",
            election.id,
            exc_info=True,
        )
        return jsonify({"error": "The result-signing service is unavailable."}), 503

    if signed.signer_backend == signing_service.LOCAL_RSA_BACKEND:
        try:
            signing_service.validate_local_public_key(
                signed.public_key_pem,
                signed.signing_key_id,
            )
        except signing_service.SignatureMetadataError:
            db.session.rollback()
            current_app.logger.error(
                "Refused to archive invalid local signing-key provenance.",
                exc_info=True,
            )
            return jsonify({"error": "The result-signing key is invalid."}), 503

        archived_key = db.session.get(
            ResultSigningPublicKey,
            signed.signing_key_id,
        )
        if archived_key is None:
            try:
                with db.session.begin_nested():
                    db.session.add(
                        ResultSigningPublicKey(
                            key_id=signed.signing_key_id,
                            algorithm=signed.signature_algorithm,
                            public_key_pem=signed.public_key_pem,
                        )
                    )
                    db.session.flush()
            except IntegrityError:
                current_app.logger.info(
                    "Result-signing public key was archived concurrently."
                )
                archived_key = db.session.get(
                    ResultSigningPublicKey,
                    signed.signing_key_id,
                )
        if archived_key is not None and (
            archived_key.algorithm != signed.signature_algorithm
            or archived_key.public_key_pem != signed.public_key_pem
        ):
            db.session.rollback()
            current_app.logger.error(
                "Local signing-key archive fingerprint collision detected."
            )
            return jsonify({"error": "The result-signing key archive is invalid."}), 503

    stored = SignedElectionResult(
        election_id=election.id,
        payload=results_json.decode("utf-8"),
        signature=signed.signature,
        signed_at=signed_at.replace(tzinfo=None),
        signed_by=current_user.id,
        signer_backend=signed.signer_backend,
        signature_algorithm=signed.signature_algorithm,
        signing_key_id=signed.signing_key_id,
        signing_key_version=signed.signing_key_version,
    )
    db.session.add(stored)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning(
            "Rejected a concurrent repeat signing for election %s.",
            election.id,
        )
        return jsonify({"error": "Election results have already been signed."}), 409
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.error(
            "Could not persist the signed results for election %s.",
            election.id,
            exc_info=True,
        )
        return jsonify({"error": "Signed results could not be persisted."}), 503

    record_audit_event(
        actor_id=current_user.id,
        action='result.sign',
        target_type='election_result',
        target_id=election.id,
    )
    return jsonify({
        "status": "success",
        "election_id": election.id,
        "message": "Results have been digitally signed and persisted.",
    })


@results.route('/results/latest', methods=['GET'])
def get_latest_results():
    """
    PUBLIC ENDPOINT.
    Provides the latest signed election results for download.
    """
    election_id = request.args.get("election_id")
    query = SignedElectionResult.query
    if election_id is not None:
        try:
            query = query.filter_by(election_id=int(election_id))
        except (TypeError, ValueError):
            current_app.logger.debug("Rejected non-integer election_id for results")
            return jsonify({"error": "Invalid election_id."}), 400
    stored = query.order_by(SignedElectionResult.signed_at.desc()).first()
    if not stored:
        return jsonify({"error": "Results have not been signed yet."}), 404

    archived_key = (
        db.session.get(ResultSigningPublicKey, stored.signing_key_id)
        if stored.signer_backend == signing_service.LOCAL_RSA_BACKEND
        else None
    )
    if stored.signer_backend == signing_service.LOCAL_RSA_BACKEND:
        try:
            if archived_key is None:
                raise signing_service.SignatureMetadataError(
                    "The archived local result-signing key is missing."
                )
            if archived_key.algorithm != stored.signature_algorithm:
                raise signing_service.SignatureMetadataError(
                    "The archived local result-signing algorithm does not match."
                )
            signing_service.validate_local_public_key(
                archived_key.public_key_pem,
                stored.signing_key_id,
            )
        except signing_service.SignatureMetadataError:
            current_app.logger.error(
                "The local signing provenance for election %s is unavailable.",
                stored.election_id,
                exc_info=True,
            )
            return jsonify({"error": "Result signing provenance is unavailable."}), 503

    return jsonify({
        "data": json.loads(stored.payload),
        "signature": stored.signature,
        "signer_backend": stored.signer_backend,
        "signature_algorithm": stored.signature_algorithm,
        "signing_key_id": stored.signing_key_id,
        "signing_key_version": stored.signing_key_version,
        "public_key_pem": archived_key.public_key_pem if archived_key else None,
    })


@results.route('/results/verify', methods=['POST'])
def verify_election_results():
    """
    PUBLIC ENDPOINT.
    Allows anyone to submit data and a signature to verify its authenticity.
    """
    body = request.get_json(silent=True) or {}
    data = body.get('data')
    signature = body.get('signature')

    if not isinstance(data, dict) or not isinstance(signature, str) or not signature:
        return jsonify({"error": "Missing 'data' or 'signature' in request."}), 400

    # Convert incoming data to the same consistent format before verification
    data_bytes = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    try:
        election_id = data["election_id"]
        if isinstance(election_id, bool):
            raise ValueError
        election_id = int(election_id)
    except (TypeError, ValueError):
        current_app.logger.debug("Rejected invalid election_id for verification")
        return jsonify({"error": "Signed result data has an invalid election_id."}), 400
    except KeyError:
        current_app.logger.debug("Signed result data omitted election_id")
        return jsonify({"error": "Signed result data has no election_id."}), 400

    stored = SignedElectionResult.query.filter_by(election_id=election_id).first()
    if stored is None:
        return jsonify({"error": "No signed result exists for this election."}), 404

    # Verification is for the immutable official projection, not an arbitrary
    # payload signed by any key the process happens to have access to.
    if stored.payload != data_bytes.decode("utf-8") or stored.signature != signature:
        return jsonify({
            "status": "Verification complete",
            "is_valid": False,
        })

    try:
        archived_key = (
            db.session.get(ResultSigningPublicKey, stored.signing_key_id)
            if stored.signer_backend == signing_service.LOCAL_RSA_BACKEND
            else None
        )
        is_valid = signing_service.verify_signature(
            data_bytes,
            signature,
            signer_backend=stored.signer_backend,
            signature_algorithm=stored.signature_algorithm,
            signing_key_id=stored.signing_key_id,
            signing_key_version=stored.signing_key_version,
            public_key_pem=(
                archived_key.public_key_pem if archived_key is not None else None
            ),
        )
    except (
        signing_service.SignatureMetadataError,
        signing_service.SigningUnavailableError,
    ):
        current_app.logger.error(
            "Could not verify the persisted result for election %s.",
            election_id,
            exc_info=True,
        )
        return jsonify({"error": "Result verification is unavailable."}), 503
    
    return jsonify({
        "status": "Verification complete",
        "is_valid": is_valid
    })


# Add this new route to the bottom of your app/results.py file

@results.route('/results/test-panel')
@login_required
def results_test_panel():
    """
    Renders a complete test page for signing, fetching, and verifying results.
    Manager-only access.
    """
    if not getattr(current_user, "is_manager", False):
        return "Forbidden", 403

    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Results Test Panel</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 2em; line-height: 1.6; }
            .panel { border: 1px solid #ccc; border-radius: 8px; padding: 1.5em; margin-bottom: 2em; }
            h1, h2 { border-bottom: 2px solid #eee; padding-bottom: 10px; }
            button { font-size: 1em; padding: 10px 15px; cursor: pointer; border-radius: 5px; border: 1px solid #777; }
            pre { background-color: #f4f4f4; padding: 1em; border-radius: 5px; white-space: pre-wrap; word-wrap: break-word; }
        </style>
    </head>
    <body>
        <h1>Non-Repudiation Test Panel 🧪</h1>

        <div class="panel">
            <h2>Step 1: Sign Election Results (Admin Action)</h2>
            <p>Click the button to call the <code>POST /results/sign</code> endpoint.</p>
            <button id="signBtn">Sign Results</button>
            <pre id="signResponse">Awaiting action...</pre>
        </div>

        <div class="panel">
            <h2>Step 2: View Latest Signed Results (Public Action)</h2>
            <p>Click to fetch data from the <code>GET /results/latest</code> endpoint. You can copy this data for the verification step.</p>
            <button id="viewBtn">View Latest Results</button>
            <pre id="viewResponse">Awaiting action...</pre>
        </div>

        <div class="panel">
            <h2>Step 3: Verify Results (Public Action)</h2>
            <p>Paste the data and signature from Step 2 into a verification tool or use this form to call <code>POST /results/verify</code>.</p>
            <form id="verifyForm">
                <textarea id="verifyData" rows="10" style="width: 100%;" placeholder="Paste the 'data' JSON object here..."></textarea><br><br>
                <input type="text" id="verifySig" style="width: 100%;" placeholder="Paste the 'signature' string here..."><br><br>
                <button type="submit">Verify Signature</button>
            </form>
            <pre id="verifyResponse">Awaiting action...</pre>
        </div>

        <script>
            // Helper function to handle fetch requests
            async function postData(url = '', data = {}) {
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': '{{ csrf_token() }}'
                    },
                    body: JSON.stringify(data)
                });
                return response.json();
            }

            // --- Event Listeners ---

            // Step 1: Sign
            document.getElementById('signBtn').addEventListener('click', async () => {
                const responseArea = document.getElementById('signResponse');
                responseArea.textContent = 'Signing...';
                const result = await postData("{{ url_for('results.sign_election_results') }}");
                responseArea.textContent = JSON.stringify(result, null, 2);
            });

            // Step 2: View
            document.getElementById('viewBtn').addEventListener('click', async () => {
                const responseArea = document.getElementById('viewResponse');
                responseArea.textContent = 'Fetching...';
                const response = await fetch("{{ url_for('results.get_latest_results') }}");
                const result = await response.json();
                responseArea.textContent = JSON.stringify(result, null, 2);
            });

            // Step 3: Verify
            document.getElementById('verifyForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const responseArea = document.getElementById('verifyResponse');
                responseArea.textContent = 'Verifying...';

                try {
                    const dataToVerify = JSON.parse(document.getElementById('verifyData').value);
                    const signatureToVerify = document.getElementById('verifySig').value;

                    const result = await postData("{{ url_for('results.verify_election_results') }}", {
                        data: dataToVerify,
                        signature: signatureToVerify
                    });
                    responseArea.textContent = JSON.stringify(result, null, 2);
                } catch (error) {
                    responseArea.textContent = 'Error: Invalid JSON in the data field. Please paste the full JSON object.';
                }
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)
