from __future__ import annotations

from typing import Literal

ExpressionLabel = Literal["开心", "委屈", "生气", "震惊", "困", "不确定"]


CAPTIONS_FALLBACK: dict[ExpressionLabel, list[str]] = {
    "开心": [
        "嘿嘿，开心！",
        "今天也太快乐了",
        "好耶！",
        "我超满意",
        "快乐加载中",
        "笑到停不下来",
        "安排！",
        "这也太好玩了",
        "我可以！",
        "心情：晴天",
        "开心到转圈圈",
        "这波稳了",
    ],
    "委屈": [
        "我哪有嘛",
        "我只是小小委屈一下",
        "不要凶我嘛",
        "我先抿嘴",
        "我真的没有",
        "就一点点难过",
        "我先躲一会儿",
        "我需要安慰",
        "我不服，但我忍",
        "我好委屈",
        "眼泪在眼眶打转",
        "你说呢？",
    ],
    "生气": [
        "我生气了！",
        "哼！",
        "别惹我",
        "我现在很严肃",
        "不许这样",
        "气鼓鼓",
        "我不理你了",
        "这事儿我记下了",
        "我拒绝",
        "你给我解释清楚",
        "我在发火边缘",
        "哼唧……",
    ],
    "震惊": [
        "啊？还有这事？",
        "我听到了什么",
        "等等，我没听错吧",
        "这合理吗？",
        "震惊到失语",
        "我脑子嗡的一下",
        "我人都傻了",
        "让我缓一缓",
        "你再说一遍？",
        "这个我真没想到",
        "眼睛都瞪圆了",
        "离谱！",
    ],
    "困": [
        "我困了",
        "我先眯一会儿",
        "电量不足",
        "我需要睡觉觉",
        "我已经开始打哈欠",
        "眼皮打架中",
        "能不能先让我睡会",
        "我真的要睡了",
        "困到灵魂出走",
        "今天的我：想睡",
        "晚安模式开启",
        "让我安静一下",
    ],
    "不确定": [
        "收到",
        "嗯嗯",
        "好吧",
        "行",
        "我先这样",
        "我看看",
        "等等我",
        "让我想想",
        "我不说话",
        "我先沉默",
        "先这样吧",
        "我在呢",
    ],
}

MOUTH_CLOSEUP_CAPTIONS: list[str] = [
    "口水上线",
    "我先尝一口",
    "馋到不行",
    "嗯…好香",
    "别拍了别拍了",
    "我在认真品",
    "等我一口",
    "这一口很关键",
    "先别催我",
    "我先含会儿",
    "给我留点面子",
    "我就看看不说话",
]


def get_fallback_captions(label: ExpressionLabel, n: int = 5) -> list[str]:
    pool = CAPTIONS_FALLBACK.get(label) or CAPTIONS_FALLBACK["不确定"]
    if n <= 0:
        return []
    out: list[str] = []
    for i in range(n):
        out.append(pool[i % len(pool)])
    return out


def get_mouth_closeup_captions(n: int = 5) -> list[str]:
    if n <= 0:
        return []
    out: list[str] = []
    for i in range(n):
        out.append(MOUTH_CLOSEUP_CAPTIONS[i % len(MOUTH_CLOSEUP_CAPTIONS)])
    return out
