import asyncio
import base64
import hashlib
import hmac
import json
import secrets
from typing import Optional, Dict, Any, Callable, List
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
import aiohttp
import websockets


class OldChatClient:
    """OldChat 完整 SDK - 支持自定义服务器地址和 API 路径前缀"""

    def __init__(self, base_url: str, api_prefix: str = "/v1", ws_url: str = None):
        """
        :param base_url: 服务器基础地址，如 http://60.205.94.101:8080
        :param api_prefix: API 路径前缀，如 /v1，若根目录则填 "" 或 "/"
        :param ws_url: WebSocket 地址，若不提供则根据 base_url 自动转换
        """
        self.base_url = base_url.rstrip("/")
        self.api_prefix = api_prefix.rstrip("/") if api_prefix else ""

        if ws_url:
            self.ws_url = ws_url
        else:
            # 自动转换：http->ws, https->wss，直接拼接到根路径 /ws
            if self.base_url.startswith("https://"):
                self.ws_url = self.base_url.replace("https://", "wss://") + "/ws"
            else:
                self.ws_url = self.base_url.replace("http://", "ws://") + "/ws"

        self._session = None
        self._ws = None

        # 认证
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.user_uid: Optional[str] = None
        self.user_id: Optional[str] = None

        # 加密
        self.session_id: Optional[str] = None
        self.enc_key: Optional[bytes] = None
        self.mac_key: Optional[bytes] = None
        self._private_key: Optional[ec.EllipticCurvePrivateKey] = None

        # 缓存
        self.friend_cache: Dict[str, str] = {}
        self.friend_remark_cache: Dict[str, str] = {}
        self.group_cache: Dict[str, str] = {}
        self.group_member_cache: Dict[str, Dict[str, str]] = {}

        # 状态
        self._running = False
        self._ws_task: Optional[asyncio.Task] = None
        self._reconnect_delay = 1

        # 回调
        self.on_direct_message: Optional[Callable] = None
        self.on_group_message: Optional[Callable] = None
        self.on_recall: Optional[Callable] = None

    # ========== 工具方法：构建完整 URL ==========

    def _build_url(self, path: str) -> str:
        """拼接 base_url + api_prefix + path"""
        # 确保 path 以 / 开头
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{self.api_prefix}{path}"

    # ========== 加密握手 ==========

    async def handshake(self) -> bool:
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        pub_bytes = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        client_pub = base64.b64encode(pub_bytes).decode()

        url = self._build_url("/auth/handshake")
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json={"client_pub": client_pub}) as resp:
                data = await resp.json()

        if "session_id" not in data:
            return False
        self.session_id = data["session_id"]
        server_pub = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), base64.b64decode(data["server_pub"])
        )
        shared = self._private_key.exchange(ec.ECDH(), server_pub)
        self.enc_key = hashlib.sha256(shared + b"enc").digest()
        self.mac_key = hashlib.sha256(shared + b"mac").digest()
        return True

    # ========== 登录与认证 ==========

    async def login(self, username: str, password: str, device_id: str = "astrbot") -> bool:
        url = self._build_url("/auth/login")
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json={
                "identifier": username,
                "password": password,
                "device_id": device_id,
                "platform": "astrbot",
                "app_version": "5.2.0"
            }) as resp:
                data = await resp.json()
        if "access_token" not in data:
            return False
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        user = data.get("user", {})
        self.user_uid = user.get("uid")
        self.user_id = user.get("id")
        return True

    async def refresh_auth(self) -> bool:
        if not self.refresh_token:
            return False
        url = self._build_url("/auth/refresh")
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json={"refresh_token": self.refresh_token}) as resp:
                data = await resp.json()
        if "access_token" in data:
            self.access_token = data["access_token"]
            self.refresh_token = data.get("refresh_token", self.refresh_token)
            return True
        return False

    # ========== 加密 HTTP 请求 ==========

    async def _request(self, method: str, path: str, data: Optional[Dict] = None,
                       retry_auth: bool = True) -> Dict:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "X-Enc": "1",
            "X-Session": self.session_id,
            "Content-Type": "application/json"
        }
        body = None
        if data:
            plain = json.dumps(data).encode()
            iv = secrets.token_bytes(16)
            cipher = Cipher(algorithms.AES(self.enc_key), modes.CBC(iv))
            padder = PKCS7(128).padder()
            padded = padder.update(plain) + padder.finalize()
            ctext = cipher.encryptor().update(padded) + cipher.encryptor().finalize()
            mac = hmac.new(self.mac_key, iv + ctext, hashlib.sha256).digest()
            body = json.dumps({
                "iv": base64.b64encode(iv).decode(),
                "data": base64.b64encode(ctext).decode(),
                "mac": base64.b64encode(mac).decode()
            })

        url = self._build_url(path)
        async with aiohttp.ClientSession() as sess:
            async with sess.request(method, url, headers=headers, data=body) as resp:
                if resp.status == 401 and retry_auth:
                    if await self.refresh_auth():
                        return await self._request(method, path, data, retry_auth=False)
                    return {"error": "auth_failed"}
                raw = await resp.text()
                try:
                    obj = json.loads(raw)
                    if "iv" in obj and "data" in obj and "mac" in obj:
                        return self._decrypt(obj)
                    return obj
                except:
                    return {"error": raw}

    def _decrypt(self, encrypted: Dict) -> Dict:
        iv = base64.b64decode(encrypted["iv"])
        ctext = base64.b64decode(encrypted["data"])
        mac = base64.b64decode(encrypted["mac"])
        if not hmac.compare_digest(hmac.new(self.mac_key, iv + ctext, hashlib.sha256).digest(), mac):
            raise ValueError("HMAC mismatch")
        cipher = Cipher(algorithms.AES(self.enc_key), modes.CBC(iv))
        padded = cipher.decryptor().update(ctext) + cipher.decryptor().finalize()
        unpadder = PKCS7(128).unpadder()
        return json.loads(unpadder.update(padded) + unpadder.finalize())

    # ========== 媒体上传 ==========

    async def upload_media(self, file_data: bytes, filename: str, content_type: str,
                           thumb_data: Optional[bytes] = None) -> Dict:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        form = aiohttp.FormData()
        form.add_field("file", file_data, filename=filename, content_type=content_type)
        if thumb_data:
            form.add_field("thumb", thumb_data, filename="thumb.jpg", content_type="image/jpeg")

        url = self._build_url("/media")
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, headers=headers, data=form) as resp:
                return await resp.json()

    async def upload_file(self, file_data: bytes, filename: str) -> Dict:
        return await self.upload_media(file_data, filename, "application/octet-stream")

    # ========== 消息发送 ==========

    async def send_direct_message(self, to_uid: str, text: str,
                                  media_url: str = None, msg_type: str = "text",
                                  quote_msg_id: str = None,
                                  burn_seconds: int = 0) -> Dict:
        payload = {"to_uid": to_uid, "msg_type": msg_type, "body": text or ""}
        if media_url:
            payload["media_url"] = media_url
        if quote_msg_id:
            payload["quote_message_id"] = quote_msg_id
        if burn_seconds > 0:
            payload["burn_after_seconds"] = burn_seconds
        return await self._request("POST", "/direct/send", payload)

    async def send_group_message(self, group_id: str, text: str,
                                 media_url: str = None, msg_type: str = "text",
                                 quote_msg_id: str = None,
                                 burn_seconds: int = 0) -> Dict:
        payload = {"group_id": group_id, "msg_type": msg_type, "body": text or ""}
        if media_url:
            payload["media_url"] = media_url
        if quote_msg_id:
            payload["quote_message_id"] = quote_msg_id
        if burn_seconds > 0:
            payload["burn_after_seconds"] = burn_seconds
        return await self._request("POST", "/groups/message/send", payload)

    async def recall_message(self, msg_id: str, is_group: bool = False) -> bool:
        path = f"/groups/messages/{msg_id}" if is_group else f"/direct/messages/{msg_id}"
        res = await self._request("DELETE", path)
        return res.get("ok", False)

    async def mark_read(self, chat_id: str, is_group: bool = False) -> bool:
        path = "/groups/read" if is_group else "/direct/read"
        key = "group_id" if is_group else "with_uid"
        res = await self._request("POST", path, {key: chat_id})
        return res.get("ok", False)

    async def open_burn_message(self, message_id: str) -> bool:
        res = await self._request("POST", "/direct/burn/open", {"message_id": message_id})
        return res.get("ok", False)

    # ========== 红包 ==========

    async def send_redpacket(self, to_uid: str = None, group_id: str = None,
                             total_amount: int = 100, total_count: int = 5,
                             title: str = "恭喜发财，大吉大利",
                             cover_url: str = None) -> Dict:
        payload = {"title": title, "total_amount": total_amount, "total_count": total_count}
        if cover_url:
            payload["cover_url"] = cover_url
        if group_id:
            payload["group_id"] = group_id
        elif to_uid:
            payload["to_uid"] = to_uid
        else:
            raise ValueError("必须指定 to_uid 或 group_id")
        return await self._request("POST", "/redpackets/send", payload)

    async def claim_redpacket(self, packet_id: str) -> Dict:
        return await self._request("POST", "/redpackets/claim", {"packet_id": packet_id})

    async def get_redpacket_detail(self, packet_id: str) -> Dict:
        return await self._request("GET", f"/redpackets/{packet_id}")

    # ========== 好友管理 ==========

    async def get_friends(self) -> List[Dict]:
        res = await self._request("GET", "/friends")
        return res.get("friends", [])

    async def get_friend_requests(self) -> List[Dict]:
        res = await self._request("GET", "/friends/requests")
        return res.get("requests", [])

    async def send_friend_request(self, to_uid: str) -> Dict:
        return await self._request("POST", "/friends/request", {"to_uid": to_uid})

    async def respond_friend_request(self, request_id: str, accept: bool) -> Dict:
        return await self._request("POST", "/friends/respond",
                                   {"request_id": request_id, "accept": accept})

    async def delete_friend(self, friend_uid: str) -> bool:
        res = await self._request("DELETE", f"/friends/{friend_uid}")
        return res.get("ok", False)

    async def set_friend_remark(self, friend_uid: str, remark: str) -> bool:
        res = await self._request("POST", "/friends/remark",
                                  {"friend_uid": friend_uid, "remark": remark})
        return res.get("ok", False)

    # ========== 群组管理 ==========

    async def get_groups(self) -> List[Dict]:
        res = await self._request("GET", "/groups/list")
        return res.get("groups", [])

    async def create_group(self, name: str, member_uids: List[str]) -> Dict:
        return await self._request("POST", "/groups/create",
                                   {"name": name, "member_uids": member_uids})

    async def join_group(self, group_id: str) -> Dict:
        return await self._request("POST", "/groups/join", {"group_id": group_id})

    async def leave_group(self, group_id: str) -> bool:
        res = await self._request("POST", "/groups/leave", {"group_id": group_id})
        return res.get("ok", False)

    async def dissolve_group(self, group_id: str) -> bool:
        res = await self._request("POST", "/groups/dissolve", {"group_id": group_id})
        return res.get("ok", False)

    async def kick_member(self, group_id: str, user_uid: str) -> bool:
        res = await self._request("POST", "/groups/kick",
                                  {"group_id": group_id, "user_uid": user_uid})
        return res.get("ok", False)

    async def set_group_admin(self, group_id: str, user_uid: str, is_admin: bool) -> bool:
        res = await self._request("POST", "/groups/admin",
                                  {"group_id": group_id, "user_uid": user_uid, "admin": is_admin})
        return res.get("ok", False)

    async def transfer_group_owner(self, group_id: str, new_owner_uid: str) -> bool:
        res = await self._request("POST", "/groups/transfer",
                                  {"group_id": group_id, "new_owner_uid": new_owner_uid})
        return res.get("ok", False)

    async def get_group_members(self, group_id: str) -> List[Dict]:
        res = await self._request("GET", f"/groups/members?group_id={group_id}")
        return res.get("members", [])

    async def get_group_requests(self, group_id: str) -> List[Dict]:
        res = await self._request("GET", f"/groups/requests?group_id={group_id}")
        return res.get("requests", [])

    async def approve_group_request(self, group_id: str, request_id: str, approve: bool = True) -> bool:
        res = await self._request("POST", "/groups/approve",
                                  {"group_id": group_id, "request_id": request_id, "approve": approve})
        return res.get("ok", False)

    async def set_group_name(self, group_id: str, name: str) -> bool:
        res = await self._request("POST", "/groups/name", {"group_id": group_id, "name": name})
        return res.get("ok", False)

    async def set_group_announcement(self, group_id: str, announcement: str, mode: int = 0) -> bool:
        res = await self._request("POST", "/groups/announcement",
                                  {"group_id": group_id, "announcement": announcement, "announcement_mode": mode})
        return res.get("ok", False)

    async def set_group_avatar(self, group_id: str, avatar_url: str) -> bool:
        res = await self._request("POST", "/groups/avatar",
                                  {"group_id": group_id, "avatar_url": avatar_url})
        return res.get("ok", False)

    async def set_group_mute(self, group_id: str, global_mute: bool) -> bool:
        res = await self._request("POST", "/groups/mute",
                                  {"group_id": group_id, "global_mute": global_mute})
        return res.get("ok", False)

    # ========== 朋友圈 ==========

    async def get_moments(self, limit: int = 20, offset: int = 0) -> Dict:
        return await self._request("GET", f"/moments/v2?limit={limit}&offset={offset}")

    async def get_user_moments(self, uid: str, limit: int = 20) -> Dict:
        return await self._request("GET", f"/moments/user?uid={uid}&limit={limit}")

    async def publish_moment(self, body: str = "", image_url: str = "") -> Dict:
        return await self._request("POST", "/moments", {"body": body, "image_url": image_url})

    async def delete_moment(self, moment_id: str) -> bool:
        res = await self._request("POST", "/moments/delete", {"moment_id": moment_id})
        return res.get("ok", False)

    async def like_moment(self, moment_id: str) -> bool:
        res = await self._request("POST", "/moments/like", {"moment_id": moment_id})
        return res.get("ok", False)

    async def unlike_moment(self, moment_id: str) -> bool:
        res = await self._request("POST", "/moments/unlike", {"moment_id": moment_id})
        return res.get("ok", False)

    async def comment_moment(self, moment_id: str, body: str) -> Dict:
        return await self._request("POST", "/moments/comment", {"moment_id": moment_id, "body": body})

    async def get_moment_comments(self, moment_id: str, limit: int = 50) -> Dict:
        return await self._request("GET", f"/moments/comments?moment_id={moment_id}&limit={limit}")

    # ========== 签到 ==========

    async def checkin(self) -> Dict:
        return await self._request("POST", "/me/checkin", {})

    async def get_checkin_wall(self) -> Dict:
        return await self._request("GET", "/me/checkin/wall")

    async def post_checkin_message(self, content_text: str = "", image_url: str = "", thumb_url: str = "") -> Dict:
        return await self._request("POST", "/me/checkin/wall",
                                   {"content_text": content_text, "image_url": image_url, "thumb_url": thumb_url})

    async def like_checkin_post(self, post_id: str) -> Dict:
        return await self._request("POST", "/me/checkin/wall/like", {"post_id": post_id})

    async def unlike_checkin_post(self, post_id: str) -> Dict:
        return await self._request("POST", "/me/checkin/wall/unlike", {"post_id": post_id})

    async def comment_checkin_post(self, post_id: str, body: str) -> Dict:
        return await self._request("POST", "/me/checkin/wall/comment", {"post_id": post_id, "body": body})

    async def get_checkin_comments(self, post_id: str, limit: int = 50) -> Dict:
        return await self._request("GET", f"/me/checkin/wall/comments?post_id={post_id}&limit={limit}")

    # ========== 音乐广场 ==========

    async def get_music_plaza(self, limit: int = 50, offset: int = 0, sort: str = "latest", q: str = "") -> Dict:
        params = f"limit={limit}&offset={offset}&sort={sort}"
        if q:
            params += f"&q={q}"
        return await self._request("GET", f"/music/plaza?{params}")

    async def get_music_ranking(self, limit: int = 10) -> Dict:
        return await self._request("GET", f"/music/plaza/ranking?limit={limit}")

    async def like_music(self, item_id: str) -> bool:
        res = await self._request("POST", "/music/plaza/like", {"item_id": item_id})
        return res.get("ok", False)

    async def unlike_music(self, item_id: str) -> bool:
        res = await self._request("POST", "/music/plaza/unlike", {"item_id": item_id})
        return res.get("ok", False)

    async def comment_music(self, item_id: str, body: str) -> Dict:
        return await self._request("POST", "/music/plaza/comment", {"item_id": item_id, "body": body})

    async def get_music_comments(self, item_id: str, limit: int = 50) -> Dict:
        return await self._request("GET", f"/music/plaza/comments?item_id={item_id}&limit={limit}")

    async def report_music_play(self, item_id: str) -> bool:
        res = await self._request("POST", "/music/plaza/play", {"item_id": item_id})
        return res.get("ok", False)

    # ========== 表情包 ==========

    async def get_emoji_plaza(self, limit: int = 50, offset: int = 0, q: str = "") -> Dict:
        params = f"limit={limit}&offset={offset}"
        if q:
            params += f"&q={q}"
        return await self._request("GET", f"/emoji/plaza?{params}")

    async def save_emoji(self, item_id: str) -> Dict:
        return await self._request("POST", "/emoji/plaza/save", {"item_id": item_id})

    # ========== 公堂 ==========

    async def get_court_cases(self, status: str = "all", limit: int = 20, before: int = 0) -> Dict:
        return await self._request("GET", f"/public-court/cases?status={status}&limit={limit}&before={before}")

    async def get_court_case_detail(self, case_id: str) -> Dict:
        return await self._request("GET", f"/public-court/cases/{case_id}")

    async def vote_court_case(self, case_id: str, vote: str, reason: str = "") -> bool:
        res = await self._request("POST", f"/public-court/cases/{case_id}/vote",
                                  {"vote": vote, "reason": reason})
        return res.get("ok", False)

    async def submit_court_statement(self, case_id: str, reason: str = "", evidence: str = "") -> bool:
        res = await self._request("POST", f"/public-court/cases/{case_id}/statement",
                                  {"reason": reason, "evidence": evidence})
        return res.get("ok", False)

    # ========== 举报 ==========

    async def report_user(self, target_uid: str, reason: str = "") -> Dict:
        return await self._request("POST", "/reports/user", {"target_uid": target_uid, "reason": reason})

    # ========== 通知 ==========

    async def get_notifications(self, limit: int = 100) -> Dict:
        return await self._request("GET", f"/notifications?limit={limit}")

    # ========== 未读消息 ==========

    async def get_unread_count(self) -> Dict:
        direct = await self._request("GET", "/direct/unread")
        group = await self._request("GET", "/groups/unread")
        return {
            "direct_total": len(direct.get("messages", [])),
            "group_total": len(group.get("messages", []))
        }

    # ========== 用户资料 ==========

    async def get_me(self) -> Dict:
        return await self._request("GET", "/me")

    async def get_user_profile(self, uid: str) -> Dict:
        return await self._request("GET", f"/users/profile?uid={uid}")

    async def update_profile(self, display_name: str = None, signature: str = None,
                             avatar_url: str = None, cover_url: str = None) -> bool:
        payload = {}
        if display_name is not None:
            payload["display_name"] = display_name
        if signature is not None:
            payload["signature"] = signature
        if avatar_url is not None:
            payload["avatar_url"] = avatar_url
        if cover_url is not None:
            payload["cover_url"] = cover_url
        res = await self._request("POST", "/me/profile", payload)
        return res.get("ok", False)

    # ========== 缓存管理 ==========

    async def refresh_cache(self):
        try:
            friends = await self.get_friends()
            for f in friends:
                uid = f.get("uid")
                if uid:
                    self.friend_cache[uid] = f.get("display_name") or f.get("username") or uid
                    if f.get("remark_name"):
                        self.friend_remark_cache[uid] = f["remark_name"]
        except:
            pass

        try:
            groups = await self.get_groups()
            for g in groups:
                gid = g.get("id")
                if gid:
                    self.group_cache[gid] = g.get("name", gid)
                    members = await self.get_group_members(gid)
                    self.group_member_cache[gid] = {}
                    for m in members:
                        uid = m.get("uid")
                        if uid:
                            self.group_member_cache[gid][uid] = m.get("display_name") or m.get("username") or uid
        except:
            pass

    def get_user_name(self, uid: str, group_id: Optional[str] = None) -> str:
        if group_id and group_id in self.group_member_cache:
            if uid in self.group_member_cache[group_id]:
                return self.group_member_cache[group_id][uid]
        if uid in self.friend_remark_cache:
            return self.friend_remark_cache[uid]
        if uid in self.friend_cache:
            return self.friend_cache[uid]
        return uid

    # ========== WebSocket ==========

    async def _websocket_loop(self):
        while self._running:
            try:
                url = f"{self.ws_url}?token={self.access_token}"
                if self.session_id:
                    url += f"&sid={self.session_id}"

                async with websockets.connect(url, close_timeout=5) as ws:
                    self._ws = ws
                    self._reconnect_delay = 1
                    print(f"[OldChat] WebSocket 已连接 ({self.ws_url})")
                    await self.refresh_cache()

                    async for raw in ws:
                        await self._handle_ws_message(raw)

            except websockets.ConnectionClosed:
                print(f"[OldChat] WS 断开，{self._reconnect_delay}s 后重连...")
            except Exception as e:
                print(f"[OldChat] WS 错误: {e}")

            if not self._running:
                break
            await asyncio.sleep(min(self._reconnect_delay, 60))
            self._reconnect_delay *= 2

    async def _handle_ws_message(self, raw: str):
        try:
            data = json.loads(raw)
            t = data.get("type")
            d = data.get("data", {})

            if t == "direct_message":
                if self.on_direct_message:
                    await self.on_direct_message(d)
            elif t == "group_message":
                if self.on_group_message:
                    await self.on_group_message(d)
            elif t in ("direct_recall", "group_recall"):
                if self.on_recall:
                    await self.on_recall(d)
        except Exception as e:
            print(f"[OldChat] 消息解析失败: {e}")

    async def start_websocket(self, on_direct=None, on_group=None, on_recall=None):
        self._running = True
        self.on_direct_message = on_direct
        self.on_group_message = on_group
        self.on_recall = on_recall
        self._ws_task = asyncio.create_task(self._websocket_loop())

    def stop(self):
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()