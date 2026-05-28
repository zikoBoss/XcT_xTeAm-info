from flask import Flask, request, jsonify
from flask_cors import CORS
import urllib3
import requests
import concurrent.futures
import json
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from google.protobuf.json_format import ParseDict, MessageToDict

import MajorLogin_pb2
import data_pb2
import PlayerStats_pb2
import PlayerCSStats_pb2

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

RELEASEVERSION = "OB53"
MAIN_KEY = b'Yg&tc%DEuh6%Zc^8'
MAIN_IV = b'6oyZDr22E3ychjM%'

# الحساب الثابت لمنطقة الشرق الأوسط
ME_UID = "4812753412"
ME_PASSWORD = "492C6754CD1BB892C11548121956ADF254468453FA0A7A25FA6367F9DF926221"

app = Flask(__name__)
CORS(app)
app.config['JSON_SORT_KEYS'] = False
app.json.sort_keys = False

http_session = requests.Session()

def clean_stat_data(raw_data):
    if isinstance(raw_data, dict):
        cleaned = {}
        for k, v in raw_data.items():
            lower_k = str(k).lower()
            if lower_k in['accountid', 'matchmode', 'gamemode', 'gametype', 'account_id']:
                continue
            new_key = "".join([" " + c if c.isupper() else c for c in str(k)]).title().strip()
            cleaned[new_key] = clean_stat_data(v)
        return cleaned
    elif isinstance(raw_data, list):
        return[clean_stat_data(i) for i in raw_data]
    else:
        if isinstance(raw_data, float):
            return round(raw_data, 4)
        return raw_data

def encode_protobuf(data_dict, proto_obj):
    ParseDict(data_dict, proto_obj, ignore_unknown_fields=True)
    raw_bytes = proto_obj.SerializeToString()
    cipher = AES.new(MAIN_KEY, AES.MODE_CBC, MAIN_IV)
    return cipher.encrypt(pad(raw_bytes, AES.block_size))

def decode_protobuf(encrypted_bytes, proto_class):
    try:
        cipher = AES.new(MAIN_KEY, AES.MODE_CBC, MAIN_IV)
        decrypted = unpad(cipher.decrypt(encrypted_bytes), AES.block_size)
        proto_obj = proto_class()
        proto_obj.ParseFromString(decrypted)
        return MessageToDict(proto_obj, preserving_proto_field_name=True)
    except Exception:
        proto_obj = proto_class()
        proto_obj.ParseFromString(encrypted_bytes)
        return MessageToDict(proto_obj, preserving_proto_field_name=True)

def get_garena_token():
    """تسجيل الدخول كضيف باستخدام حساب ME الثابت"""
    url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    payload = {
        'uid': ME_UID,
        'password': ME_PASSWORD,
        'response_type': "token",
        'client_type': "2",
        'client_secret': "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        'client_id': "100067"
    }
    headers = {
        'User-Agent': "GarenaMSDK/4.0.19P9(A063 ;Android 13;en;IN;)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip"
    }
    try:
        response = http_session.post(url, data=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None

def get_major_login(logintoken, openid):
    encrypted_payload = encode_protobuf({
        "openid": openid,
        "logintoken": logintoken,
        "platform": "4",
    }, MajorLogin_pb2.request())

    # تأكد من أن هذا الرابط صحيح لإصدار OB53
    url = "https://loginbp.ggpolarbear.com/MajorLogin"  # قد تحتاج لتحديثه كما ناقشنا سابقاً
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 13; A063 Build/TKQ1.221220.001)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Expect': "100-continue",
        'Authorization': "Bearer",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': RELEASEVERSION,
        'Content-Type': "application/octet-stream"
    }
    try:
        response = http_session.post(url, data=encrypted_payload, headers=headers)
        return decode_protobuf(response.content, MajorLogin_pb2.response)
    except Exception:
        return False

def fetch_profile(serverurl, authorization, uid):
    # ... (نفس الكود السابق دون تغيير)
    url = f"{serverurl}/GetPlayerPersonalShow"
    try:
        request_proto = data_pb2.request()
        data_dict = {
            "accountId": int(uid),
            "callSignSrc": 7,
            "needGalleryInfo": False,
        }
        encrypted_payload = encode_protobuf(data_dict, request_proto)

        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 13; A063 Build/TKQ1.221220.001)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Expect': "100-continue",
            'Authorization': f"Bearer {authorization}",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': RELEASEVERSION,
            'Content-Type': "application/octet-stream"
        }
        
        response = http_session.post(url, data=encrypted_payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        try:
            cipher = AES.new(MAIN_KEY, AES.MODE_CBC, MAIN_IV)
            decrypted = unpad(cipher.decrypt(response.content), AES.block_size)
            response_obj = data_pb2.AccountPersonalShowInfo()
            response_obj.ParseFromString(decrypted)
        except Exception:
            response_obj = data_pb2.AccountPersonalShowInfo()
            response_obj.ParseFromString(response.content)

        result_dict = MessageToDict(response_obj, preserving_proto_field_name=True)
        basic_info = result_dict.get("basic_info", {})

        return {
            "nickname": basic_info.get("nickname", "Unknown"),
            "uid": str(basic_info.get("account_id", uid)),
            "likes": basic_info.get("liked", 0),
            "exp": basic_info.get("exp", 0),
            "level": basic_info.get("level", 0)
        }

    except Exception as e:
        return {
            "nickname": "Error",
            "uid": str(uid),
            "likes": 0,
            "exp": 0,
            "level": 0
        }

def get_player_stats(authorization, serverurl, mode, uid, match_type="CAREER"):
    # ... (نفس الكود السابق دون تغيير)
    try:
        uid = int(uid)
        mode = mode.lower()
        match_type = match_type.upper()
        
        if mode == "br":
            type_mapping = {"CAREER": 0, "NORMAL": 1, "RANKED": 2}
            url = f"{serverurl}/GetPlayerStats"
            proto_module = PlayerStats_pb2
            payload_data = {"accountid": uid, "matchmode": type_mapping.get(match_type, 0)}
        else:
            type_mapping = {"CAREER": 0, "NORMAL": 1, "RANKED": 6}
            url = f"{serverurl}/GetPlayerTCStats"
            proto_module = PlayerCSStats_pb2
            payload_data = {"accountid": uid, "gamemode": 15, "matchmode": type_mapping.get(match_type, 0)}
        
        request_proto = proto_module.request()
        encrypted_payload = encode_protobuf(payload_data, request_proto)
        
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 13; A063 Build/TKQ1.221220.001)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Expect': "100-continue",
            'Authorization': f"Bearer {authorization}",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': RELEASEVERSION,
            'Content-Type': "application/octet-stream"
        }
        
        response = http_session.post(url, data=encrypted_payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        response_obj = proto_module.response()
        response_obj.ParseFromString(response.content)
        return MessageToDict(response_obj, preserving_proto_field_name=True)
        
    except Exception:
        return {}

def fetch_stat_safe(token, url, uid, mode, mtype):
    try:
        return get_player_stats(token, url, mode, uid, mtype)
    except:
        return {}

@app.route('/stats', methods=['GET'])
def get_player_info_flexible():
    try:
        uid = request.args.get('uid')
        raw_mode = request.args.get('mode')
        raw_type = request.args.get('type')

        # معالجة الفلاتر كما هي
        req_mode = None
        if raw_mode:
            m = raw_mode.strip().lower()
            if m in ['br', 'battle royale']: 
                req_mode = 'br'
            elif m in ['cs', 'clash squad']: 
                req_mode = 'cs'
            else: 
                req_mode = m

        req_type = None
        if raw_type:
            t = raw_type.strip().lower()
            if t in ['casual', 'normal']: 
                req_type = 'NORMAL'
            elif t in ['ranked', 'rank']: 
                req_type = 'RANKED'
            elif t in['career', 'lifetime']: 
                req_type = 'CAREER'
            else: 
                req_type = t.upper()

        if not uid: 
            return jsonify({"success": False, "error": "Missing UID"}), 400

        # ✅ لا نستخدم السيرفر من الطلب، نستخدم ME فقط
        g_token = get_garena_token()
        if not g_token or 'access_token' not in g_token:
            return jsonify({"success": False, "error": "Garena Auth Failed"}), 401
            
        major_login = get_major_login(g_token["access_token"], g_token["open_id"])
        if not major_login or 'token' not in major_login:
            return jsonify({"success": False, "error": "Game Login Failed"}), 401

        game_token = major_login["token"]
        server_url = major_login["serverUrl"]

        # ... باقي الكود لجلب الإحصائيات والبروفايل كما هو، مع استخدام uid المُدخل
        # (نفس الكود الذي كان موجوداً، لا تغيير فيه)
        all_stats_tasks =[
            ("br_career", "br", "CAREER"),
            ("br_ranked", "br", "RANKED"),
            ("br_casual", "br", "NORMAL"),
            ("cs_career", "cs", "CAREER"),
            ("cs_ranked", "cs", "RANKED"),
            ("cs_casual", "cs", "NORMAL"),
        ]

        stats_to_run = {}
        for key, task_mode, task_type in all_stats_tasks:
            if req_mode and task_mode != req_mode: continue
            if req_type and task_type != req_type: continue
            stats_to_run[key] = (task_mode, task_type)

        results = {}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(stats_to_run) + 2) as executor:
            future_profile = executor.submit(fetch_profile, server_url, game_token, uid)
            
            future_stats = {
                executor.submit(fetch_stat_safe, game_token, server_url, uid, m, t): key 
                for key, (m, t) in stats_to_run.items()
            }
            
            for future in concurrent.futures.as_completed(future_stats):
                key = future_stats[future]
                results[key] = future.result()
            
            profile_result = future_profile.result()

        stats_output = {}

        if "br_ranked" in results: stats_output["BR Ranked"] = clean_stat_data(results["br_ranked"])
        if "br_casual" in results: stats_output["BR Casual"] = clean_stat_data(results["br_casual"])
        if "br_career" in results: stats_output["BR Career"] = clean_stat_data(results["br_career"])
        if "cs_ranked" in results: stats_output["CS Ranked"] = clean_stat_data(results["cs_ranked"])
        if "cs_casual" in results: stats_output["CS Casual"] = clean_stat_data(results["cs_casual"])
        if "cs_career" in results: stats_output["CS Career"] = clean_stat_data(results["cs_career"])

        def recursive_sort(obj):
            if isinstance(obj, dict):
                return {k: recursive_sort(v) for k, v in sorted(obj.items())}
            elif isinstance(obj, list):
                return [recursive_sort(item) for item in obj]
            return obj

        stats_output = recursive_sort(stats_output)

        return jsonify({
            "server": "ME",  # للإشارة فقط
            "filters_applied": {
                "mode": req_mode.upper() if req_mode else "ALL MODES",
                "type": req_type if req_type else "ALL TYPES"
            },
            "profile": profile_result,
            "stats": stats_output,
            "success": True
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": "Internal Server Error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)