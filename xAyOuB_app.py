import asyncio
import time
import httpx
import json
import os
import sys
import threading
import re
import base64
import pickle
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS
from cachetools import TTLCache
from google.protobuf import json_format
from Crypto.Cipher import AES

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import xAyOuB_FreeFire_pb2 as xAyOuB_FreeFire_pb2
import xAyOuB_main_pb2 as xAyOuB_main_pb2
import xAyOuB_AccountPersonalShow_pb2 as xAyOuB_AccountPersonalShow_pb2

XAYOUB_KEY = base64.b64decode('WWcmdGMlREV1aDYlWmNeOA==')
XAYOUB_IV = base64.b64decode('Nm95WkRyMjJFM3ljaGpNJQ==')
XAYOUB_RELEASE_VERSION = "OB54"
XAYOUB_USER_AGENT = "UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"
XAYOUB_REGION = "ME"
XAYOUB_TOKEN_CACHE_FILE = "xAyOuB_token_cache.pkl"
XAYOUB_REQUEST_CACHE_FILE = "xAyOuB_request_cache.pkl"
XAYOUB_CACHE_TTL = 300

xAyOuB_app = Flask(__name__)
CORS(xAyOuB_app)
xAyOuB_cache = TTLCache(maxsize=200, ttl=XAYOUB_CACHE_TTL)
xAyOuB_token_manager = None
xAyOuB_request_cache = {}


def xAyOuB_load_request_cache():
    global xAyOuB_request_cache
    try:
        if os.path.exists(XAYOUB_REQUEST_CACHE_FILE):
            with open(XAYOUB_REQUEST_CACHE_FILE, "rb") as f:
                xAyOuB_request_cache = pickle.load(f)
                now = time.time()
                xAyOuB_request_cache = {
                    k: v for k, v in xAyOuB_request_cache.items()
                    if v.get("expires_at", 0) > now
                }
    except Exception:
        xAyOuB_request_cache = {}


def xAyOuB_save_request_cache():
    try:
        with open(XAYOUB_REQUEST_CACHE_FILE, "wb") as f:
            pickle.dump(xAyOuB_request_cache, f)
    except Exception:
        pass


def xAyOuB_get_cached_response(uid):
    if uid in xAyOuB_request_cache:
        cached = xAyOuB_request_cache[uid]
        if cached.get("expires_at", 0) > time.time():
            return cached.get("data")
        del xAyOuB_request_cache[uid]
        xAyOuB_save_request_cache()
    return None


def xAyOuB_cache_response(uid, data):
    xAyOuB_request_cache[uid] = {
        "data": data,
        "expires_at": time.time() + XAYOUB_CACHE_TTL,
        "cached_at": time.time(),
    }
    xAyOuB_save_request_cache()


class xAyOuB_TokenManager:
    def __init__(self):
        self.tokens = {}
        self.lock = asyncio.Lock()
        self.xAyOuB_load_tokens()

    def xAyOuB_load_tokens(self):
        try:
            if os.path.exists(XAYOUB_TOKEN_CACHE_FILE):
                with open(XAYOUB_TOKEN_CACHE_FILE, "rb") as f:
                    saved = pickle.load(f)
                    now = time.time()
                    for r, info in saved.items():
                        if info.get("expires_at", 0) > now:
                            self.tokens[r] = info
        except Exception:
            pass

    def xAyOuB_save_tokens(self):
        try:
            with open(XAYOUB_TOKEN_CACHE_FILE, "wb") as f:
                pickle.dump(dict(self.tokens), f)
        except Exception:
            pass

    async def xAyOuB_get_token(self):
        async with self.lock:
            info = self.tokens.get(XAYOUB_REGION)
            if info and info.get("expires_at", 0) > time.time():
                return info
            new_token = await self.xAyOuB_generate_token()
            if new_token:
                self.tokens[XAYOUB_REGION] = new_token
                self.xAyOuB_save_tokens()
                return new_token
            return None

    async def xAyOuB_generate_token(self):
        attempts = max(1, xAyOuB_account_pool.xAyOuB_count())
        for _ in range(attempts):
            try:
                account = xAyOuB_account_pool.xAyOuB_current()
                if not account:
                    return None

                token_val, open_id = await xAyOuB_get_access_token(
                    xAyOuB_get_account_credentials(account)
                )
                if not token_val or not open_id:
                    xAyOuB_account_pool.xAyOuB_next()
                    continue

                body = json.dumps({
                    "open_id": open_id,
                    "open_id_type": "4",
                    "login_token": token_val,
                    "orign_platform_type": "4",
                })

                proto_bytes = await xAyOuB_json_to_proto(body, xAyOuB_FreeFire_pb2.LoginReq())
                payload = xAyOuB_aes_cbc_encrypt(XAYOUB_KEY, XAYOUB_IV, proto_bytes)

                url = "https://loginbp.ggpolarbear.com/MajorLogin"
                headers = {
                    "User-Agent": XAYOUB_USER_AGENT,
                    "Connection": "Keep-Alive",
                    "Accept-Encoding": "deflate, gzip",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "*/*",
                    "X-Unity-Version": "2022.3.47f1",
                    "X-GA": "v1 1",
                    "ReleaseVersion": XAYOUB_RELEASE_VERSION,
                }

                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, data=payload, headers=headers)
                    if resp.status_code != 200:
                        xAyOuB_account_pool.xAyOuB_next()
                        continue
                    login_res = xAyOuB_FreeFire_pb2.LoginRes()
                    login_res.ParseFromString(resp.content)
                    msg = json.loads(json_format.MessageToJson(login_res))
                    token_str = msg.get("token", "0")
                    if not token_str or token_str == "0":
                        xAyOuB_account_pool.xAyOuB_next()
                        continue
                    return {
                        "token": f"Bearer {token_str}",
                        "region": msg.get("lockRegion", "0"),
                        "server_url": msg.get("serverUrl", "0"),
                        "account_uid": account[0],
                        "expires_at": time.time() + 25200,
                    }
            except Exception:
                xAyOuB_account_pool.xAyOuB_next()
                continue
        return None

    async def xAyOuB_refresh_token(self):
        xAyOuB_account_pool.xAyOuB_next()
        info = await self.xAyOuB_generate_token()
        if info:
            self.tokens[XAYOUB_REGION] = info
            self.xAyOuB_save_tokens()
        return info

    async def xAyOuB_rotate_account(self):
        """Switch to the next guest account and generate a fresh token with it."""
        async with self.lock:
            xAyOuB_account_pool.xAyOuB_next()
            info = await self.xAyOuB_generate_token()
            if info:
                self.tokens[XAYOUB_REGION] = info
                self.xAyOuB_save_tokens()
            return info

    async def xAyOuB_auto_refresh_loop(self):
        while True:
            await asyncio.sleep(6 * 60 * 60)
            await self.xAyOuB_refresh_token()


def xAyOuB_pad(text: bytes) -> bytes:
    n = AES.block_size - (len(text) % AES.block_size)
    return text + bytes([n] * n)


def xAyOuB_aes_cbc_encrypt(key, iv, plaintext):
    return AES.new(key, AES.MODE_CBC, iv).encrypt(xAyOuB_pad(plaintext))


async def xAyOuB_json_to_proto(json_data, proto_message):
    json_format.ParseDict(json.loads(json_data), proto_message)
    return proto_message.SerializeToString()


XAYOUB_ACCOUNTS_FILE = os.path.join(CURRENT_DIR, "acc.txt")


class xAyOuB_AccountPool:
    """Loads guest accounts from acc.txt (uid:password per line) and rotates
    to the next account immediately when the current one stops working."""

    def __init__(self, path):
        self.path = path
        self.accounts = []
        self.index = 0
        self.lock = threading.Lock()
        self.xAyOuB_load()

    def xAyOuB_load(self):
        accounts = []
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if ":" in line:
                            uid, pwd = line.split(":", 1)
                            uid, pwd = uid.strip(), pwd.strip()
                            if uid and pwd:
                                accounts.append((uid, pwd))
        except Exception:
            pass
        with self.lock:
            self.accounts = accounts
            if self.index >= len(accounts):
                self.index = 0

    def xAyOuB_current(self):
        with self.lock:
            if not self.accounts:
                return None
            return self.accounts[self.index]

    def xAyOuB_next(self):
        with self.lock:
            if not self.accounts:
                return None
            self.index = (self.index + 1) % len(self.accounts)
            return self.accounts[self.index]

    def xAyOuB_count(self):
        with self.lock:
            return len(self.accounts)

    def xAyOuB_current_uid(self):
        acc = self.xAyOuB_current()
        return acc[0] if acc else None


xAyOuB_account_pool = xAyOuB_AccountPool(XAYOUB_ACCOUNTS_FILE)

# Vercel runs this Flask app as a serverless function, so initialize
# request-safe in-memory state when the module is imported.
if xAyOuB_token_manager is None:
    xAyOuB_token_manager = xAyOuB_TokenManager()
    xAyOuB_load_request_cache()


def xAyOuB_get_account_credentials(account=None) -> str:
    if account is None:
        account = xAyOuB_account_pool.xAyOuB_current()
    if not account:
        return ""
    uid, pwd = account
    return f"uid={uid}&password={pwd}"


async def xAyOuB_get_access_token(account: str):
    url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    payload = (
        account
        + "&response_type=token&client_type=2"
        + "&client_secret=2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
        + "&client_id=100067"
    )
    headers = {
        "User-Agent": XAYOUB_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    for _ in range(3):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, data=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("access_token"), data.get("open_id")
                await asyncio.sleep(2)
        except Exception:
            await asyncio.sleep(2)
    return None, None


async def xAyOuB_get_account_information(uid):
    max_tries = max(1, xAyOuB_account_pool.xAyOuB_count())
    for _ in range(max_tries):
        try:
            token_info = await xAyOuB_token_manager.xAyOuB_get_token()
            if not token_info:
                return None

            token = token_info["token"]
            server_url = token_info["server_url"]
            payload = await xAyOuB_json_to_proto(
                json.dumps({"a": uid, "b": "7"}),
                xAyOuB_main_pb2.GetPlayerPersonalShow(),
            )
            data_enc = xAyOuB_aes_cbc_encrypt(XAYOUB_KEY, XAYOUB_IV, payload)
            headers = {
                "User-Agent": XAYOUB_USER_AGENT,
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip",
                "Content-Type": "application/octet-stream",
                "Expect": "100-continue",
                "Authorization": token,
                "X-Unity-Version": "2022.3.47f1",
                "X-GA": "v1 1",
                "ReleaseVersion": XAYOUB_RELEASE_VERSION,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    server_url + "/GetPlayerPersonalShow",
                    data=data_enc,
                    headers=headers,
                )
                if resp.status_code != 200:
                    if not await xAyOuB_token_manager.xAyOuB_rotate_account():
                        return None
                    continue
                account_info = xAyOuB_AccountPersonalShow_pb2.AccountPersonalShowInfo()
                account_info.ParseFromString(resp.content)
                return json.loads(json_format.MessageToJson(account_info))
        except Exception:
            if not await xAyOuB_token_manager.xAyOuB_rotate_account():
                return None
            continue
    return None


def xAyOuB_fmt_time(ts):
    if ts and str(ts) != "0":
        try:
            return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts)
    return "0"


def xAyOuB_time_ago(ts):
    if not ts or str(ts) == "0":
        return "Unknown"
    try:
        then = datetime.fromtimestamp(int(ts))
        delta = datetime.now() - then
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds} seconds ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minutes ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} hours ago"
        days = hours // 24
        if days < 30:
            return f"{days} days ago"
        months = days // 30
        if months < 12:
            return f"{months} months ago"
        years = days // 365
        return f"{years} years ago"
    except Exception:
        return "Unknown"


def xAyOuB_account_age(create_ts):
    if not create_ts or str(create_ts) == "0":
        return "Unknown"
    try:
        created = datetime.fromtimestamp(int(create_ts))
        delta = datetime.now() - created
        days = delta.days
        years = days // 365
        months = (days % 365) // 30
        remaining_days = (days % 365) % 30
        return f"{years} years, {months} months, {remaining_days} days"
    except Exception:
        return "Unknown"


def xAyOuB_format_response(data):
    if not data:
        return {"error": "No data"}

    basic = data.get("basicInfo", {})
    clan = data.get("clanBasicInfo", {})
    captain = data.get("captainBasicInfo", {})
    profile = data.get("profileInfo", {})
    pet = data.get("petInfo", {})
    social = data.get("socialInfo", {})
    credit_score = data.get("creditScoreInfo", {})
    diamond_cost = data.get("diamondCostRes", {})
    equipped_ach = data.get("equippedAch", {})

    create_at = basic.get("createAt", "0")
    last_login = basic.get("lastLoginAt", "0")

    equipped_weapons = basic.get("weaponSkinShows", []) or []
    equipped_outfit = profile.get("clothes", []) or []
    equipped_skills = profile.get("equipedSkills", []) or []
    pve_primary_weapon = profile.get("pvePrimaryWeapon", []) or []
    game_bag_show = basic.get("gameBagShow", []) or []
    selected_item_slots = basic.get("selectedItemSlots", []) or []

    pet_actions = pet.get("actions", []) or []
    pet_skills = pet.get("skills", []) or []

    response = {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "region_used": XAYOUB_REGION,
        "credit": "xAyOuB",
        "AccountInfo": {
            "AccountName": basic.get("nickname", "Unknown"),
            "AccountUID": str(basic.get("accountId", "0")),
            "AccountRegion": basic.get("region", "Unknown"),
            "AccountLevel": str(basic.get("level", "0")),
            "AccountEXP": str(basic.get("exp", "0")),
            "AccountLikes": str(basic.get("liked", "0")),
            "AccountType": str(basic.get("accountType", "0")),
            "AccountAvatarId": str(basic.get("headPic", "0")),
            "AccountBannerId": str(basic.get("bannerId", "0")),
            "AccountBPID": str(basic.get("badgeId", "0")),
            "AccountBPBadges": str(basic.get("badgeCnt", "0")),
            "AccountSeasonId": str(basic.get("seasonId", "0")),
            "AccountCreateTime": xAyOuB_fmt_time(create_at),
            "AccountCreateTimestamp": str(create_at),
            "AccountAge": xAyOuB_account_age(create_at),
            "AccountLastLogin": xAyOuB_fmt_time(last_login),
            "AccountLastLoginAgo": xAyOuB_time_ago(last_login),
            "AccountLastLoginTimestamp": str(last_login),
            "AccountReturnAt": xAyOuB_fmt_time(basic.get("returnAt", "0")),
            "Title": str(basic.get("title", "0")),
            "PinId": str(basic.get("pinId", "0")),
            "ReleaseVersion": basic.get("releaseVersion", XAYOUB_RELEASE_VERSION),
            "HasElitePass": str(basic.get("hasElitePass", "0")),
            "IsDeleted": str(basic.get("isDeleted", "0")),
            "IsBanned": str(basic.get("isBanned", "0")),
            "BanReason": basic.get("banReason", ""),
            "PreVeteranType": str(basic.get("preVeteranType", "0")),
            "VeteranLeaveDaysTag": str(basic.get("veteranLeaveDaysTag", "0")),
            "VeteranExpireTime": xAyOuB_fmt_time(basic.get("veteranExpireTime", "0")),
        },
        "RankInfo": {
            "BrRank": str(basic.get("rank", "0")),
            "BrRankPoint": str(basic.get("rankingPoints", "0")),
            "BrMaxRank": str(basic.get("maxRank", "0")),
            "BrPeakRankPos": str(basic.get("peakRankPos", "0")),
            "ShowBrRank": str(basic.get("showBrRank", "0")),
            "CsRank": str(basic.get("csRank", "0")),
            "CsRankPoint": str(basic.get("csRankingPoints", "0")),
            "CsMaxRank": str(basic.get("csMaxRank", "0")),
            "CsPeakRankPos": str(basic.get("csPeakRankPos", "0")),
            "ShowCsRank": str(basic.get("showCsRank", "0")),
            "MaxRankingPoints": str(basic.get("maxRankingPoints", "0")),
            "PeriodicRank": str(basic.get("periodicRank", "0")),
            "PeriodicRankPoints": str(basic.get("periodicRankingPoints", "0")),
            "IsCsRankingBan": str(basic.get("isCsRankingBan", "0")),
        },
        "AccountProfileInfo": {
            "AvatarId": str(profile.get("avatarId", "0")),
            "SkinColor": str(profile.get("skinColor", "0")),
            "EquippedOutfit": equipped_outfit,
            "EquippedOutfitCount": len(equipped_outfit),
            "EquippedSkills": equipped_skills,
            "EquippedSkillsCount": len(equipped_skills),
            "PvePrimaryWeapon": pve_primary_weapon,
            "IsSelected": str(profile.get("isSelected", "0")),
            "IsSelectedAwaken": str(profile.get("isSelectedAwaken", "0")),
            "EndTime": xAyOuB_fmt_time(profile.get("endTime", "0")),
            "UnlockType": str(profile.get("unlockType", "0")),
            "UnlockTime": xAyOuB_fmt_time(profile.get("unlockTime", "0")),
            "IsMarkedStar": str(profile.get("isMarkedStar", "0")),
            "ClothesTailorEffects": profile.get("clothesTailorEffects", []) or [],
        },
        "EquippedWeapons": {
            "WeaponSkins": equipped_weapons,
            "WeaponCount": len(equipped_weapons),
        },
        "SelectedItems": {
            "GameBagShow": game_bag_show,
            "GameBagCount": len(game_bag_show),
            "SelectedItemSlots": selected_item_slots,
            "SelectedItemSlotsCount": len(selected_item_slots),
        },
        "PetInfo": {
            "PetId": str(pet.get("id", "0")),
            "PetName": pet.get("name", "None"),
            "PetLevel": str(pet.get("level", "0")),
            "PetExp": str(pet.get("exp", "0")),
            "PetSkinId": str(pet.get("skinId", "0")),
            "PetIsSelected": str(pet.get("isSelected", "0")),
            "PetSelectedSkillId": str(pet.get("selectedSkillId", "0")),
            "PetIsMarkedStar": str(pet.get("isMarkedStar", "0")),
            "PetEndTime": xAyOuB_fmt_time(pet.get("endTime", "0")),
            "PetActions": pet_actions,
            "PetActionsCount": len(pet_actions),
            "PetSkills": pet_skills,
        },
        "GuildInfo": {
            "GuildName": clan.get("clanName", "No Guild"),
            "GuildID": str(clan.get("clanId", "0")),
            "GuildLevel": str(clan.get("clanLevel", "0")),
            "GuildCapacity": str(clan.get("capacity", "0")),
            "GuildMember": str(clan.get("memberNum", "0")),
            "GuildOwner": str(clan.get("captainId", "0")),
            "HonorPoint": str(clan.get("honorPoint", "0")),
            "ClanBadgeId": str(basic.get("clanBadgeId", "0")),
            "ClanFrameId": str(basic.get("clanFrameId", "0")),
            "UseCustomClanBadge": str(basic.get("useCustomClanBadge", "0")),
            "MembershipState": str(basic.get("membershipState", "0")),
        },
        "GuildOwnerInfo": {
            "OwnerName": captain.get("nickname", "Unknown"),
            "OwnerUID": str(captain.get("accountId", "0")),
            "OwnerLevel": str(captain.get("level", "0")),
            "OwnerEXP": str(captain.get("exp", "0")),
            "OwnerLikes": str(captain.get("liked", "0")),
            "OwnerRegion": captain.get("region", "Unknown"),
            "OwnerBrRank": str(captain.get("rank", "0")),
            "OwnerBrRankPoints": str(captain.get("rankingPoints", "0")),
            "OwnerCsRank": str(captain.get("csRank", "0")),
            "OwnerCsRankPoints": str(captain.get("csRankingPoints", "0")),
            "OwnerLastLogin": xAyOuB_fmt_time(captain.get("lastLoginAt", "0")),
            "OwnerLastLoginAgo": xAyOuB_time_ago(captain.get("lastLoginAt", "0")),
            "OwnerCreateTime": xAyOuB_fmt_time(captain.get("createAt", "0")),
            "OwnerAccountAge": xAyOuB_account_age(captain.get("createAt", "0")),
            "OwnerTitle": str(captain.get("title", "0")),
            "OwnerBadgeId": str(captain.get("badgeId", "0")),
            "OwnerBadgeCount": str(captain.get("badgeCnt", "0")),
            "OwnerReleaseVersion": captain.get("releaseVersion", ""),
        },
        "SocialInfo": {
            "AccountId": str(social.get("accountId", "0")),
            "Gender": str(social.get("gender", "0")),
            "Language": str(social.get("language", "0")),
            "TimeOnline": str(social.get("timeOnline", "0")),
            "TimeActive": str(social.get("timeActive", "0")),
            "BattleTag": str(social.get("battleTag", "0")),
            "BattleTagCount": str(social.get("battleTagCount", "0")),
            "SocialTag": str(social.get("socialTag", "0")),
            "ModePrefer": str(social.get("modePrefer", "0")),
            "Signature": social.get("signature", ""),
            "RankShow": str(social.get("rankShow", "0")),
            "SignatureBanExpireTime": xAyOuB_fmt_time(social.get("signatureBanExpireTime", "0")),
            "LeaderboardTitles": social.get("leaderboardTitles", []) or [],
        },
        "CreditScoreInfo": {
            "CreditScore": str(credit_score.get("creditScore", "0")),
            "IsInit": str(credit_score.get("isInit", "0")),
            "RewardState": str(credit_score.get("rewardState", "0")),
            "PeriodicSummaryLikeCnt": str(credit_score.get("periodicSummaryLikeCnt", "0")),
            "PeriodicSummaryIllegalCnt": str(credit_score.get("periodicSummaryIllegalCnt", "0")),
            "WeeklyMatchCnt": str(credit_score.get("weeklyMatchCnt", "0")),
            "PeriodicSummaryStartTime": xAyOuB_fmt_time(credit_score.get("periodicSummaryStartTime", "0")),
            "PeriodicSummaryEndTime": xAyOuB_fmt_time(credit_score.get("periodicSummaryEndTime", "0")),
        },
        "DiamondInfo": {
            "DiamondCost": str(diamond_cost.get("diamondCost", "0")),
        },
        "EquippedAchievement": {
            "AchievementId": str(equipped_ach.get("achId", "0")),
            "AchievementLevel": str(equipped_ach.get("level", "0")),
        },
        "ChampionshipInfo": {
            "TeamName": basic.get("championshipTeamName", ""),
            "TeamId": str(basic.get("championshipTeamId", "0")),
            "TeamMemberNum": str(basic.get("championshipTeamMemberNum", "0")),
        },
        "HistoryEpInfo": data.get("historyEpInfo", {}),
        "NewsInfo": data.get("news", {}),
    }
    return response


@xAyOuB_app.route("/")
def xAyOuB_home():
    return jsonify({
        "status": "online",
        "service": "xAyOuB Player Info API",
        "version": "3.0",
        "release": XAYOUB_RELEASE_VERSION,
        "region": XAYOUB_REGION,
        "credit": "xAyOuB",
        "features": {
            "me_region_only": True,
            "response_caching": True,
            "token_auto_refresh": True,
            "extended_info": True,
        },
        "endpoints": {
            "/get": {
                "method": "GET",
                "params": {"uid": "required - Free Fire UID"},
                "example": "/get?uid=123456789",
            },
            "/status": "GET - Token status",
            "/refresh": "GET - Force refresh token",
            "/stats": "GET - API statistics",
            "/clear_cache": "GET - Clear response cache",
        },
    })


@xAyOuB_app.route("/get")
def xAyOuB_get_account_info():
    uid = request.args.get("uid")
    if not uid:
        return jsonify({
            "error": "UID required",
            "message": "Please provide a Free Fire UID",
            "credit": "xAyOuB",
            "example": "/get?uid=123456789",
        }), 400

    if not re.match(r"^\d{5,15}$", uid):
        return jsonify({
            "error": "Invalid UID",
            "message": "UID must be 5-15 digits only",
            "credit": "xAyOuB",
        }), 400

    cached_data = xAyOuB_get_cached_response(uid)
    if cached_data:
        cached_data["from_cache"] = True
        return jsonify(cached_data)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    data = loop.run_until_complete(xAyOuB_get_account_information(uid))
    loop.close()

    if data:
        response = xAyOuB_format_response(data)
        response["from_cache"] = False
        xAyOuB_cache_response(uid, response)
        return jsonify(response)

    return jsonify({
        "error": "Player not found",
        "message": "Could not fetch player info from ME region",
        "credit": "xAyOuB",
    }), 404


@xAyOuB_app.route("/status")
def xAyOuB_token_status():
    status = {}
    for region, info in xAyOuB_token_manager.tokens.items():
        expires_in = info["expires_at"] - time.time()
        status[region] = {
            "has_token": True,
            "expires_in": f"{expires_in / 3600:.1f} hours",
            "is_valid": expires_in > 0,
            "server_url": info["server_url"][:50] + "...",
        }
    return jsonify({
        "credit": "xAyOuB",
        "region": XAYOUB_REGION,
        "total_tokens": len(xAyOuB_token_manager.tokens),
        "cached_requests": len(xAyOuB_request_cache),
        "accounts_loaded": xAyOuB_account_pool.xAyOuB_count(),
        "active_account_uid": xAyOuB_account_pool.xAyOuB_current_uid(),
        "tokens": status,
    })


@xAyOuB_app.route("/refresh")
def xAyOuB_refresh_tokens():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(xAyOuB_token_manager.xAyOuB_refresh_token())
    loop.close()
    return jsonify({
        "status": "refreshed",
        "region": XAYOUB_REGION,
        "count": len(xAyOuB_token_manager.tokens),
        "credit": "xAyOuB",
    })


@xAyOuB_app.route("/stats")
def xAyOuB_api_stats():
    return jsonify({
        "credit": "xAyOuB",
        "timestamp": datetime.now().isoformat(),
        "stats": {
            "cached_responses": len(xAyOuB_request_cache),
            "active_tokens": len(xAyOuB_token_manager.tokens) if xAyOuB_token_manager else 0,
            "region": XAYOUB_REGION,
        },
    })


@xAyOuB_app.route("/clear_cache")
def xAyOuB_clear_cache():
    global xAyOuB_request_cache
    xAyOuB_request_cache = {}
    xAyOuB_save_request_cache()
    return jsonify({
        "status": "Cache cleared",
        "credit": "xAyOuB",
    })


def xAyOuB_start_background_tasks():
    global xAyOuB_token_manager
    xAyOuB_token_manager = xAyOuB_TokenManager()
    xAyOuB_load_request_cache()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(xAyOuB_token_manager.xAyOuB_get_token())
    except Exception:
        pass
    loop.run_forever()


if __name__ == "__main__":
    print("=" * 55)
    print("xAyOuB Player Info API v3.0")
    print("=" * 55)
    print(f"Region: {XAYOUB_REGION}")
    print(f"Release: {XAYOUB_RELEASE_VERSION}")
    print("=" * 55)

    xAyOuB_bg = threading.Thread(target=xAyOuB_start_background_tasks, daemon=True)
    xAyOuB_bg.start()

    print(f"Guest accounts loaded from acc.txt: {xAyOuB_account_pool.xAyOuB_count()}")
    print("Initializing token for ME region...")
    time.sleep(10)

    if xAyOuB_token_manager and XAYOUB_REGION in xAyOuB_token_manager.tokens:
        print(f"Token cached for {XAYOUB_REGION}")
    else:
        print(f"Warning: no token yet for {XAYOUB_REGION}")

    print("=" * 55)
    print("API running on port 5000")
    print("Endpoints:")
    print("   GET /get?uid=UID  - Get player info (ME region)")
    print("   GET /status       - Token status")
    print("   GET /refresh      - Force refresh token")
    print("   GET /stats        - API statistics")
    print("   GET /clear_cache  - Clear response cache")
    print("=" * 55)

    xAyOuB_app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
