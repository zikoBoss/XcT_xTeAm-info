from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

EXTERNAL_API_BASE = "https://mafuuuu-info-api.vercel.app"

@app.route('/mafu-info', methods=['GET'])
def proxy_mafu_info():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"error": "uid parameter is required"}), 400

    # بناء الرابط الخارجي
    external_url = f"{EXTERNAL_API_BASE}/mafu-info?uid={uid}"

    try:
        # طلب البيانات من API الخارجي
        resp = requests.get(external_url, timeout=15)

        # إعادة نفس الـ JSON ونفس Status Code
        return resp.json(), resp.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Failed to fetch data", "details": str(e)}), 502

# مطلوب لـ Vercel
app = app