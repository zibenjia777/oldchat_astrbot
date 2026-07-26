from astrbot.api.event import AstrMessageEvent


class OldChatMessageEvent(AstrMessageEvent):
    """OldChat 消息事件"""

    def __init__(self, message_str: str, platform_name: str, session_id: str,
                 message_obj, raw_event=None):
        super().__init__(message_str, platform_name, session_id, message_obj, raw_event)