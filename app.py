from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

EXTERNAL_API_BASE = "https://mafuuuu-info-api.vercel.app"

@app.route('/info', methods=['GET'])
def proxy_info():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"error": "uid parameter is required"}), 400

    # استدعاء الـ API الخارجي مع نفس الـ uid
    external_url = f"{EXTERNAL_API_BASE}/mafu-info?uid={uid}"

    try:
        resp = requests.get(external_url, timeout=15)
        # إعادة نفس الاستجابة كما هي
        return resp.json(), resp.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Failed to fetch data", "details": str(e)}), 502