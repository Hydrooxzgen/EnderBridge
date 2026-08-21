"""QQ 消息检测 Mod 模块

消息发送前的安全检测:字节数限制 + 敏感词过滤。

注:没有与 profanity-guard/sensitive-word-tool 直接等价的 Python 库,
这里用内置的精简敏感词表实现同等接口。
"""
import re

# 精简版中英文敏感词表(可自行扩充)
_EN_WORDS = [
    "fuck", "shit", "bitch", "asshole", "dick", "pussy", "cunt",
    "nigger", "faggot", "retard", "bastard", "whore", "slut", "porn",
]
_ZH_WORDS = [
    "傻逼", "煞笔", "妈的", "操你", "去死", "贱人", "婊子", "妓女",
    "色情", "赌博", "毒品", "诈骗",
]


class Detector:
    """消息检测器(静态方法)"""

    word_tool = None
    max_bytes = 1024
    _profanity_check = None

    _en_re = re.compile("|".join(re.escape(w) for w in _EN_WORDS), re.IGNORECASE)
    _zh_re = re.compile("|".join(re.escape(w) for w in _ZH_WORDS))

    @staticmethod
    def detect(raw_text):
        """检测文本是否可发送

        返回 {"passed": bool, "reason": str|None, "raw": str|None}
        """
        if not raw_text or not isinstance(raw_text, str):
            return {"passed": True, "reason": None}

        if len(raw_text.encode("utf-8")) > Detector.max_bytes:
            return {"passed": False, "reason": "文本超过字节限制", "raw": raw_text}

        # 英文敏感词检查(容错:词表为空时跳过)
        try:
            if Detector._en_re.search(raw_text):
                return {"passed": False, "reason": "多语言敏感词命中", "raw": raw_text}
        except Exception:
            pass

        # 中文敏感词检查
        try:
            if Detector._zh_re.search(raw_text):
                return {"passed": False, "reason": "中文敏感词命中", "raw": raw_text}
        except Exception:
            pass

        return {"passed": True, "reason": None, "raw": raw_text}
