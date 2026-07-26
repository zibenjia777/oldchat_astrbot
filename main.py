import json
from typing import Optional
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot import logger

from .oldchat_platform_adapter import OldChatPlatformAdapter


@register(
    name="astrbot_plugin_oldchat",
    display_name="OldChat 旗舰适配器",
    version="5.2.0",
    author="AstrBot Community"
)
class OldChatPlugin(Star):

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

    async def initialize(self):
        logger.info("OldChat 旗舰适配器 v5.2.0 已加载")

    # ---------- 辅助方法：获取适配器实例 ----------
    def _get_adapter(self) -> Optional[OldChatPlatformAdapter]:
        """从当前上下文中获取 OldChat 平台适配器"""
        if not hasattr(self.context, 'platform_adapters'):
            return None
        for adapter in self.context.platform_adapters:
            if isinstance(adapter, OldChatPlatformAdapter):
                return adapter
        return None

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        adapter = self._get_adapter()
        if not adapter or not adapter.client:
            return False
        sender_uid = event.get_sender_id()
        return sender_uid in adapter._admin_uids

    def _get_client(self):
        adapter = self._get_adapter()
        if not adapter:
            return None
        return adapter.client

    # ========== 基础命令 ==========

    @filter.command("oldchat")
    async def oldchat_status(self, event: AstrMessageEvent):
        adapter = self._get_adapter()
        if not adapter or not adapter.client:
            yield event.result().plain_message("❌ 适配器未运行")
            return
        c = adapter.client
        unread = await c.get_unread_count()
        yield event.result().plain_message(
            f"""📡 OldChat 状态
━━━━━━━━━━━━━━━━━━━
👤 UID: {c.user_uid}
🌐 服务器: {c.base_url}{c.api_prefix}
🔗 WebSocket: {'✅ 在线' if c._ws else '❌ 断开'}
👥 好友缓存: {len(c.friend_cache)} 人
📚 群组缓存: {len(c.group_member_cache)} 个
📩 未读消息: 私聊 {unread.get('direct_total', 0)} | 群聊 {unread.get('group_total', 0)}
👑 管理员: {list(adapter._admin_uids)}"""
        )

    # ========== 红包命令 ==========

    @filter.command("oldchat redpacket send")
    async def oldchat_redpacket_send(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 只有管理员可以发红包")
            return
        args = event.message_str.strip().split()
        if len(args) < 5:
            yield event.result().plain_message(
                "用法: /oldchat redpacket send <目标ID> <金额> <份数> [标题]"
            )
            return
        target = args[3]
        try:
            amount = int(args[4])
            count = int(args[5])
        except ValueError:
            yield event.result().plain_message("❌ 金额和份数必须为数字")
            return
        title = " ".join(args[6:]) if len(args) > 6 else self.config.get("redpacket_default_title", "恭喜发财")

        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return

        is_group = target.startswith("GRP-") or target.startswith("grp-")
        try:
            if is_group:
                res = await c.send_redpacket(group_id=target, total_amount=amount,
                                             total_count=count, title=title)
            else:
                res = await c.send_redpacket(to_uid=target, total_amount=amount,
                                             total_count=count, title=title)
            if "id" in res:
                yield event.result().plain_message(
                    f"✅ 红包已发送！\n消息ID: {res['id']}\n金额: {amount} 金币, 份数: {count}\n标题: {title}"
                )
            else:
                yield event.result().plain_message(f"❌ 发送失败: {res}")
        except Exception as e:
            yield event.result().plain_message(f"❌ 错误: {str(e)}")

    @filter.command("oldchat redpacket info")
    async def oldchat_redpacket_info(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 4:
            yield event.result().plain_message("用法: /oldchat redpacket info <红包ID>")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        try:
            detail = await c.get_redpacket_detail(args[3])
            if "packet_id" in detail:
                msg = f"""📦 红包详情
ID: {detail['packet_id']}
标题: {detail.get('title', '')}
总额: {detail.get('total_amount', 0)} 金币
已领: {detail.get('claimed_count', 0)}/{detail.get('total_count', 0)} 人
状态: {'已领完' if detail.get('status') == 'done' else '进行中'}
领取记录:"""
                for c in detail.get('claims', [])[:5]:
                    msg += f"\n  {c.get('display_name')} 领了 {c.get('amount')} 金币"
                yield event.result().plain_message(msg)
            else:
                yield event.result().plain_message(f"❌ 未找到红包")
        except Exception as e:
            yield event.result().plain_message(f"❌ 查询失败: {str(e)}")

    # ========== 阅后即焚 ==========

    @filter.command("oldchat burn")
    async def oldchat_burn(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 3:
            yield event.result().plain_message("用法: /oldchat burn <消息ID>")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        try:
            res = await c.open_burn_message(args[2])
            yield event.result().plain_message(f"✅ 阅后即焚已开启: {'成功' if res else '失败'}")
        except Exception as e:
            yield event.result().plain_message(f"❌ 错误: {str(e)}")

    @filter.command("oldchat burn send")
    async def oldchat_burn_send(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 5:
            yield event.result().plain_message(
                "用法: /oldchat burn send <目标ID> <秒数(5/10/20/30/60/300)> <消息内容>"
            )
            return
        target = args[3]
        try:
            seconds = int(args[4])
            if seconds not in [5, 10, 20, 30, 60, 300]:
                yield event.result().plain_message("❌ 秒数必须是 5/10/20/30/60/300 之一")
                return
        except ValueError:
            yield event.result().plain_message("❌ 秒数必须为数字")
            return
        text = " ".join(args[5:]) if len(args) > 5 else "阅后即焚消息"

        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return

        is_group = target.startswith("GRP-") or target.startswith("grp-")
        try:
            if is_group:
                res = await c.send_group_message(group_id=target, text=text, burn_seconds=seconds)
            else:
                res = await c.send_direct_message(to_uid=target, text=text, burn_seconds=seconds)
            if "id" in res:
                yield event.result().plain_message(f"✅ 阅后即焚消息已发送 ({seconds}s)\n消息ID: {res['id']}")
            else:
                yield event.result().plain_message(f"❌ 发送失败: {res}")
        except Exception as e:
            yield event.result().plain_message(f"❌ 错误: {str(e)}")

    # ========== 朋友圈 ==========

    @filter.command("oldchat moment")
    async def oldchat_moment(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 3:
            yield event.result().plain_message("用法: /oldchat moment <内容> [图片URL]")
            return
        body = args[2]
        img_url = args[3] if len(args) > 3 else ""

        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        try:
            res = await c.publish_moment(body=body, image_url=img_url)
            if "id" in res:
                yield event.result().plain_message(f"✅ 朋友圈已发布\nID: {res['id']}")
            else:
                yield event.result().plain_message(f"❌ 发布失败: {res}")
        except Exception as e:
            yield event.result().plain_message(f"❌ 错误: {str(e)}")

    @filter.command("oldchat moment list")
    async def oldchat_moment_list(self, event: AstrMessageEvent):
        args = event.message_str.strip().split()
        limit = int(args[3]) if len(args) > 3 else 10
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        try:
            res = await c.get_moments(limit=limit)
            moments = res.get("moments", [])
            if not moments:
                yield event.result().plain_message("📭 暂无朋友圈")
                return
            msg = "📋 朋友圈:\n"
            for m in moments[:10]:
                msg += f"  {m.get('from_name')}: {m.get('body', '')[:30]}"
                if m.get('liked'):
                    msg += " ❤️"
                msg += "\n"
            yield event.result().plain_message(msg)
        except Exception as e:
            yield event.result().plain_message(f"❌ 错误: {str(e)}")

    # ========== 签到 ==========

    @filter.command("oldchat checkin")
    async def oldchat_checkin(self, event: AstrMessageEvent):
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        try:
            res = await c.checkin()
            if res.get("code") == 200:
                wall = await c.get_checkin_wall()
                count = wall.get("checkin_count", 0)
                yield event.result().plain_message(f"✅ 签到成功！累计签到 {count} 天 🎉")
            elif res.get("error") == "already_checked_in":
                wall = await c.get_checkin_wall()
                count = wall.get("checkin_count", 0)
                yield event.result().plain_message(f"⏰ 今日已签到！累计签到 {count} 天")
            else:
                yield event.result().plain_message(f"❌ 签到失败: {res}")
        except Exception as e:
            yield event.result().plain_message(f"❌ 错误: {str(e)}")

    # ========== 群管理 ==========

    @filter.command("oldchat groups")
    async def oldchat_list_groups(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        groups = await c.get_groups()
        if not groups:
            yield event.result().plain_message("没有群组")
            return
        msg = "📋 群组列表:\n"
        for g in groups[:15]:
            role = {0: "成员", 1: "管理员", 2: "群主"}.get(g.get("role", 0), "未知")
            msg += f"  {g.get('name')} ({g.get('id')}) [{role}]\n"
        yield event.result().plain_message(msg)

    @filter.command("oldchat members")
    async def oldchat_list_members(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 3:
            yield event.result().plain_message("用法: /oldchat members <群组ID>")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        members = await c.get_group_members(args[2])
        if not members:
            yield event.result().plain_message("没有成员")
            return
        msg = "👥 群成员:\n"
        for m in members[:20]:
            role = {0: "成员", 1: "管理员", 2: "群主"}.get(m.get("role", 0), "未知")
            msg += f"  {m.get('display_name') or m.get('username')} ({m.get('uid')}) [{role}]\n"
        yield event.result().plain_message(msg)

    @filter.command("oldchat kick")
    async def oldchat_kick(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 4:
            yield event.result().plain_message("用法: /oldchat kick <群组ID> <用户UID>")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        res = await c.kick_member(args[2], args[3])
        yield event.result().plain_message(f"✅ 踢出{'成功' if res else '失败'}")

    @filter.command("oldchat setadmin")
    async def oldchat_setadmin(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 5:
            yield event.result().plain_message("用法: /oldchat setadmin <群组ID> <用户UID> <true/false>")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        flag = args[4].lower() == "true"
        res = await c.set_group_admin(args[2], args[3], flag)
        yield event.result().plain_message(f"✅ 设置管理员{'成功' if res else '失败'}")

    @filter.command("oldchat transfer")
    async def oldchat_transfer(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 4:
            yield event.result().plain_message("用法: /oldchat transfer <群组ID> <新群主UID>")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        res = await c.transfer_group_owner(args[2], args[3])
        yield event.result().plain_message(f"✅ 转让{'成功' if res else '失败'}")

    @filter.command("oldchat mute")
    async def oldchat_mute(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 4:
            yield event.result().plain_message("用法: /oldchat mute <群组ID> <true/false>")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        flag = args[3].lower() == "true"
        res = await c.set_group_mute(args[2], flag)
        yield event.result().plain_message(f"✅ 全员禁言{'已开启' if flag else '已关闭'}")

    @filter.command("oldchat groupname")
    async def oldchat_groupname(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 4:
            yield event.result().plain_message("用法: /oldchat groupname <群组ID> <新名称>")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        name = " ".join(args[3:])
        res = await c.set_group_name(args[2], name)
        yield event.result().plain_message(f"✅ 修改群名{'成功' if res else '失败'}")

    @filter.command("oldchat announcement")
    async def oldchat_announcement(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 4:
            yield event.result().plain_message("用法: /oldchat announcement <群组ID> <公告内容>")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        content = " ".join(args[3:])
        res = await c.set_group_announcement(args[2], content)
        yield event.result().plain_message(f"✅ 发布公告{'成功' if res else '失败'}")

    # ========== 查询命令 ==========

    @filter.command("oldchat user")
    async def oldchat_user_info(self, event: AstrMessageEvent):
        args = event.message_str.strip().split()
        if len(args) < 3:
            yield event.result().plain_message("用法: /oldchat user <UID>")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        try:
            info = await c.get_user_profile(args[2])
            if "uid" in info:
                yield event.result().plain_message(
                    f"""👤 用户信息
UID: {info.get('uid')}
昵称: {info.get('display_name') or info.get('username')}
头衔: {info.get('user_title', '无')}
在线: {'在线' if info.get('is_online') else '离线'}"""
                )
            else:
                yield event.result().plain_message("❌ 未找到该用户")
        except Exception as e:
            yield event.result().plain_message(f"❌ 查询失败: {str(e)}")

    @filter.command("oldchat unread")
    async def oldchat_unread(self, event: AstrMessageEvent):
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        unread = await c.get_unread_count()
        yield event.result().plain_message(
            f"📩 未读消息:\n私聊: {unread.get('direct_total', 0)} 条\n群聊: {unread.get('group_total', 0)} 条"
        )

    @filter.command("oldchat me")
    async def oldchat_me(self, event: AstrMessageEvent):
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        try:
            info = await c.get_me()
            yield event.result().plain_message(
                f"""👤 我的信息
UID: {info.get('uid')}
用户名: {info.get('username')}
昵称: {info.get('display_name')}
头衔: {info.get('user_title', '无')}
签名: {info.get('signature', '无')}
金币: {info.get('coin_balance', 0)}
声望: {info.get('reputation_score', 0)}"""
            )
        except Exception as e:
            yield event.result().plain_message(f"❌ 查询失败: {str(e)}")

    # ========== 举报 ==========

    @filter.command("oldchat report")
    async def oldchat_report(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        args = event.message_str.strip().split()
        if len(args) < 3:
            yield event.result().plain_message("用法: /oldchat report <目标UID> [原因]")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        target = args[2]
        reason = " ".join(args[3:]) if len(args) > 3 else "机器人举报"
        try:
            res = await c.report_user(target, reason)
            if res.get("success"):
                yield event.result().plain_message(f"✅ 举报已提交，已进入公堂审理")
            else:
                yield event.result().plain_message(f"❌ 举报失败: {res}")
        except Exception as e:
            yield event.result().plain_message(f"❌ 错误: {str(e)}")

    # ========== 通知 ==========

    @filter.command("oldchat notices")
    async def oldchat_notices(self, event: AstrMessageEvent):
        args = event.message_str.strip().split()
        limit = int(args[2]) if len(args) > 2 else 10
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        try:
            res = await c.get_notifications(limit=limit)
            notices = res.get("notifications", [])
            if not notices:
                yield event.result().plain_message("📭 暂无系统通知")
                return
            msg = "📢 系统通知:\n"
            for n in notices[:10]:
                msg += f"  {n.get('body', '')[:50]}\n"
            yield event.result().plain_message(msg)
        except Exception as e:
            yield event.result().plain_message(f"❌ 错误: {str(e)}")

    # ========== 缓存管理 ==========

    @filter.command("oldchat cache")
    async def oldchat_refresh_cache(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.result().plain_message("❌ 权限不足")
            return
        c = self._get_client()
        if not c:
            yield event.result().plain_message("❌ 客户端未就绪")
            return
        await c.refresh_cache()
        yield event.result().plain_message(
            f"✅ 缓存已刷新\n好友: {len(c.friend_cache)} 人\n群组: {len(c.group_member_cache)} 个"
        )
