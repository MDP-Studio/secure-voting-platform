from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify(message="Hello from voting_web")

@app.route("/healthz")
def healthz():
    return jsonify(status="ok")
