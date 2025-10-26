from flask import Blueprint, jsonify, request, render_template_string, current_app
from flask_login import login_required, current_user
from app.security import signing_service
import json

results = Blueprint('results', __name__)

# --- Mock Data Store ---
# In a real app, this would come from your database.
ELECTION_RESULTS = {
    "election_id": "FED2025",
    "results": {
        "PartyA": 5000000,
        "PartyB": 4500000,
        "PartyC": 1500000
    }
}
SIGNED_RESULTS = {
    "data": None,
    "signature": None
}

@results.route('/results/sign', methods=['POST'])
@login_required
def sign_election_results():
    """
    ADMIN-ONLY ENDPOINT.
    Signs the final election results and stores the signature.
    """
    # Enforce manager role (admin-equivalent) for signing
    if not getattr(current_user, "is_manager", False):
        return jsonify({"error": "Forbidden"}), 403

    # Convert results dictionary to a consistent JSON string (bytes)
    results_json = json.dumps(ELECTION_RESULTS, sort_keys=True, separators=(',', ':')).encode('utf-8')
    
    # Use the service to sign the data
    signature = signing_service.sign_data(results_json)
    
    # Store the signed data and signature (hex-encoded for easy transport)
    SIGNED_RESULTS['data'] = ELECTION_RESULTS
    SIGNED_RESULTS['signature'] = signature.hex()
    
    return jsonify({"status": "success", "message": "Results have been digitally signed."})


@results.route('/results/latest', methods=['GET'])
def get_latest_results():
    """
    PUBLIC ENDPOINT.
    Provides the latest signed election results for download.
    """
    if not SIGNED_RESULTS.get('signature'):
        return jsonify({"error": "Results have not been signed yet."}), 404
        
    return jsonify(SIGNED_RESULTS)


@results.route('/results/verify', methods=['POST'])
def verify_election_results():
    """
    PUBLIC ENDPOINT.
    Allows anyone to submit data and a signature to verify its authenticity.
    """
    data = request.json.get('data')
    signature_hex = request.json.get('signature')

    if not all([data, signature_hex]):
        return jsonify({"error": "Missing 'data' or 'signature' in request."}), 400

    # Convert incoming data to the same consistent format before verification
    data_bytes = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    signature_bytes = bytes.fromhex(signature_hex)
    
    is_valid = signing_service.verify_signature(data_bytes, signature_bytes)
    
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
    """
    # In a real app, you would add a robust admin check here.
    # if not current_user.is_admin:
    #     return "Forbidden", 403

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
                    headers: {'Content-Type': 'application/json'},
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