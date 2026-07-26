import asyncio
import os
import aiofiles
import aiohttp
from typing import Optional
from astrbot.api.platform import (
    Platform, AstrBotMessage, PlatformMetadata,
    MessageType, register_platform_adapter
)
from astrbot.api.message_components import Plain, Image, At, Reply, File
from astrbot.core.platform.message_session import MessageSession
from astrbot import logger

from .oldchat_client import OldChatClient


@register_platform_adapter(
    "oldchat",
    "OldChat 旗舰适配器",
    default_config_tmpl={
        "server_base_url": "http://60.205.94.101:8080",
        "api_path_prefix": "/v1",
        "username": "", "password": "", "device_id": "astrbot_ultimate",
        "admin_users": "", "group_whitelist": "", "user_whitelist": "",
        "redpacket_enabled": True, "redpacket_default_amount": 100,
        "redpacket_default_count": 5, "redpacket_default_title": "恭喜发财，大吉大利",
        "redpacket_auto_claim": False,
        "burn_enabled": True, "burn_default_seconds": 10,
        "auto_accept_friend": False, "auto_join_group": False,
        "reply_with_mention": True, "auto_checkin": False,
        "ws_reconnect_max_delay": 60, "cache_refresh_interval": 1800
    }
)
class OldChatPlatformAdapter(Platform):

    def __init__(self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue):
        super().__init__(event_queue)
        self.config = platform_config
        self.settings = platform_settings
        self.client: Optional[OldChatClient] = None
        self._running = False
        self._admin_uids = set()
        self._group_whitelist = set()
        self._user_whitelist = set()
        self._cache_task = None
        self._checkin_task = None

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata("oldchat", "OldChat 旗舰适配器")

    async def run(self):
        # 读取服务器配置
        base_url = self.config.get("server_base_url", "http://60.205.94.101:8080")
        api_prefix = self.config.get("api_path_prefix", "/v1")
        # 如果用户填了 "/"，也标准化为 ""
        if api_prefix == "/":
            api_prefix = ""

        self._admin_uids = set([x.strip() for x in self.config.get("admin_users", "").split(",") if x.strip()])
        self._group_whitelist = set([x.strip() for x in self.config.get("group_whitelist", "").split(",") if x.strip()])
        self._user_whitelist = set([x.strip() for x in self.config.get("user_whitelist", "").split(",") if x.strip()])

        username = self.config.get("username")
        password = self.config.get("password")
        if not username or not password:
            logger.error("OldChat: 用户名或密码未配置")
            return

        # 初始化客户端（传入自定义配置）
        self.client = OldChatClient(base_url=base_url, api_prefix=api_prefix)
        self._running = True

        if not await self.client.handshake():
            logger.error(f"OldChat: ECDH 握手失败 (服务器: {base_url}{api_prefix})")
            return
        if not await self.client.login(username, password, self.config.get("device_id")):
            logger.error("OldChat: 登录失败")
            return

        logger.info(f"OldChat: 登录成功 | UID={self.client.user_uid} | 管理员: {self._admin_uids}")
        logger.info(f"OldChat: 服务器地址: {base_url} | API 前缀: {api_prefix}")

        await self.client.start_websocket(
            on_direct=self._on_direct_message,
            on_group=self._on_group_message,
            on_recall=self._on_recall_message
        )

        self._cache_task = asyncio.create_task(self._cache_refresh_loop())
        if self.config.get("auto_checkin", False):
            self._checkin_task = asyncio.create_task(self._auto_checkin_loop())

    # ========== 权限校验 ==========

    def _is_admin(self, uid: str) -> bool:
        return uid in self._admin_uids

    def _check_permission(self, session: MessageSession) -> bool:
        if session.type == "friend":
            if self._user_whitelist and session.session_id not in self._user_whitelist:
                return False
        elif session.type == "group":
            if self._group_whitelist and session.session_id not in self._group_whitelist:
                return False
        return True

    # ========== 消息接收 ==========

    async def _on_direct_message(self, data: dict):
        msg_type = data.get("msg_type", "text")
        if msg_type == "red_packet" and self.config.get("redpacket_auto_claim", False):
            await self._handle_redpacket(data)

        abm = self._build_base_message(data, MessageType.FRIEND_MESSAGE)
        await self.handle_msg(abm)

    async def _on_group_message(self, data: dict):
        msg_type = data.get("msg_type", "text")
        if msg_type == "red_packet" and self.config.get("redpacket_auto_claim", False):
            await self._handle_redpacket(data)

        abm = self._build_base_message(data, MessageType.GROUP_MESSAGE)
        await self.handle_msg(abm)

    async def _on_recall_message(self, data: dict):
        logger.info(f"OldChat: 消息被撤回 {data}")

    def _build_base_message(self, data: dict, msg_type: MessageType) -> AstrBotMessage:
        abm = AstrBotMessage()
        abm.type = msg_type
        abm.self_id = self.client.user_uid
        abm.sender_id = data.get("from_uid")
        abm.message_id = data.get("id")
        abm.timestamp = data.get("created_at", 0)
        if msg_type == MessageType.GROUP_MESSAGE:
            abm.group_id = data.get("group_id")
            abm.session_id = data.get("group_id")
        else:
            abm.session_id = data.get("from_uid")
        abm.message_chain = self._build_message_chain(data)
        return abm

    def _build_message_chain(self, data: dict) -> list:
        msg_type = data.get("msg_type", "text")
        body = data.get("body", "")
        media = data.get("media_url")
        burn_seconds = data.get("burn_after_seconds", 0)

        components = []
        if burn_seconds > 0:
            components.append(Plain(text=f"🔥[阅后即焚 {burn_seconds}s] "))

        if msg_type == "text":
            components.append(Plain(text=body))
        elif msg_type == "image":
            if body:
                components.append(Plain(text=body))
            if media:
                components.append(Image(url=media))
        elif msg_type == "voice":
            components.append(Plain(text=f"[语音] {body}"))
        elif msg_type == "video":
            components.append(Plain(text=f"[视频] {body}"))
        elif msg_type == "file":
            components.append(Plain(text=f"[文件] {body}"))
        elif msg_type == "red_packet":
            components.append(Plain(text=f"🧧[红包] {body or '恭喜发财'}"))
        else:
            components.append(Plain(text=f"[{msg_type}] {body}"))
        return components

    async def _handle_redpacket(self, data: dict):
        try:
            body = data.get("body", "")
            import json
            info = json.loads(body) if body else {}
            packet_id = info.get("packet_id")
            if packet_id:
                res = await self.client.claim_redpacket(packet_id)
                logger.info(f"OldChat: 自动领取红包 {packet_id} -> {res}")
        except Exception as e:
            logger.error(f"OldChat: 自动领取红包失败 {e}")

    # ========== 消息发送 ==========

    async def send_by_session(self, session: MessageSession, message_chain):
        if not self.client or not self._check_permission(session):
            return

        text_parts = []
        media_data = None
        file_data = None
        quote_id = None
        at_uids = []
        burn_seconds = self.config.get("burn_default_seconds", 0)

        for comp in message_chain:
            if isinstance(comp, Plain):
                text_parts.append(comp.text)
            elif isinstance(comp, At):
                at_uids.append(comp.qq)
            elif isinstance(comp, Reply):
                quote_id = comp.id
            elif isinstance(comp, Image):
                media_data = comp
            elif isinstance(comp, File):
                file_data = comp

        if at_uids and self.config.get("reply_with_mention", True):
            group_id = session.session_id if session.type == "group" else None
            for uid in at_uids:
                name = self.client.get_user_name(uid, group_id)
                text_parts.insert(0, f"@{name} ")

        final_text = "".join(text_parts).strip()
        if not final_text and not media_data and not file_data:
            final_text = " "

        msg_type = "text"
        media_url = None

        # 文件上传
        if file_data:
            try:
                file_bytes = await self._resolve_file_content(file_data)
                if file_bytes:
                    upload_res = await self.client.upload_file(file_bytes, file_data.name or "file.bin")
                    if "url" in upload_res:
                        media_url = upload_res["url"]
                        msg_type = "file"
            except Exception as e:
                logger.error(f"OldChat: 文件上传失败 {e}")
                return

        # 图片上传
        elif media_data:
            try:
                img_bytes, content_type, filename = await self._resolve_image_content(media_data)
                if img_bytes:
                    upload_res = await self.client.upload_media(img_bytes, filename, content_type)
                    if "url" in upload_res:
                        media_url = upload_res["url"]
                        msg_type = "image"
            except Exception as e:
                logger.error(f"OldChat: 图片上传失败 {e}")
                return

        # 发送
        try:
            if self.config.get("burn_enabled", True) and burn_seconds > 0:
                burn_seconds = burn_seconds if burn_seconds in [5, 10, 20, 30, 60, 300] else 10
            else:
                burn_seconds = 0

            if session.type == "friend":
                await self.client.send_direct_message(
                    to_uid=session.session_id,
                    text=final_text,
                    media_url=media_url,
                    msg_type=msg_type,
                    quote_msg_id=quote_id,
                    burn_seconds=burn_seconds
                )
            else:
                await self.client.send_group_message(
                    group_id=session.session_id,
                    text=final_text,
                    media_url=media_url,
                    msg_type=msg_type,
                    quote_msg_id=quote_id,
                    burn_seconds=burn_seconds
                )
        except Exception as e:
            logger.error(f"OldChat: 发送失败 {e}")

    async def _resolve_file_content(self, file_comp) -> Optional[bytes]:
        if hasattr(file_comp, 'path') and file_comp.path:
            if os.path.exists(file_comp.path):
                async with aiofiles.open(file_comp.path, "rb") as f:
                    return await f.read()
            elif file_comp.path.startswith("http"):
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(file_comp.path) as resp:
                        return await resp.read()
        elif hasattr(file_comp, 'url') and file_comp.url:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(file_comp.url) as resp:
                    return await resp.read()
        return None

    async def _resolve_image_content(self, img_comp) -> tuple:
        filename = "image.jpg"
        content_type = "image/jpeg"
        data = None
        if hasattr(img_comp, 'path') and img_comp.path:
            if os.path.exists(img_comp.path):
                async with aiofiles.open(img_comp.path, "rb") as f:
                    data = await f.read()
                filename = os.path.basename(img_comp.path)
        elif hasattr(img_comp, 'url') and img_comp.url:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(img_comp.url) as resp:
                    data = await resp.read()
                    content_type = resp.headers.get("Content-Type", "image/jpeg")
        return data, content_type, filename

    # ========== 自动任务 ==========

    async def _cache_refresh_loop(self):
        interval = self.config.get("cache_refresh_interval", 1800)
        while self._running:
            await asyncio.sleep(interval)
            try:
                await self.client.refresh_cache()
                logger.info("OldChat: 缓存已自动刷新")
            except Exception as e:
                logger.error(f"OldChat: 缓存刷新失败 {e}")

    async def _auto_checkin_loop(self):
        while self._running:
            try:
                res = await self.client.checkin()
                if res.get("code") == 200:
                    logger.info("OldChat: 自动签到成功")
                elif res.get("error") == "already_checked_in":
                    pass
                else:
                    logger.warning(f"OldChat: 自动签到结果: {res}")
            except Exception as e:
                logger.error(f"OldChat: 自动签到失败 {e}")
            await asyncio.sleep(86400)

    async def shutdown(self):
        self._running = False
        if self._cache_task:
            self._cache_task.cancel()
        if self._checkin_task:
            self._checkin_task.cancel()
        if self.client:
            self.client.stop()
        logger.info("OldChat: 适配器已关闭")