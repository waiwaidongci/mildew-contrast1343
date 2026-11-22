"""离线分包汇总：各库房只提交两组样本数、条件命中数和查重凭据。

巡检原表、巡检单号和架位留在库房本地。合并方只收到聚合计数与不可逆的
查重凭据（巡检单号的摘要），据此找出被两个库房重复提交的同一条巡检。
"""

import hashlib
import json
from itertools import combinations, product

from .analysis import condition_text, pattern_key, row_patterns, score_patterns
from .spec import SPEC

CONDITION_FIELDS = ("high_humidity", "vent_blocked", "maintenance_pending")
_VALUES = (False, True)
# 单项条件 6 个、来自不同字段的成对条件 12 个，与单批分析枚举的口径一致。
PATTERNS = tuple(
    ((field, value),) for field in CONDITION_FIELDS for value in _VALUES
) + tuple(
    tuple((field, value) for field, value in zip(pair, values))
    for pair in combinations(CONDITION_FIELDS, 2)
    for values in product(_VALUES, repeat=2)
)
PATTERN_KEYS = {pattern_key(pattern): pattern for pattern in PATTERNS}
PATTERN_COLUMNS = (
    ("pattern_id", "模式编号"), ("conditions", "伴随条件"), ("size", "条件数"),
    ("positive_count", "正组命中"), ("negative_count", "负组命中"),
    ("positive_support", "正组原始支持度"), ("negative_support", "负组原始支持度"),
    ("positive_smoothed", "正组平滑支持度"), ("negative_smoothed", "负组平滑支持度"),
    ("growth", "增长倍数"),
)
CREDENTIAL_SCHEME = {
    "algorithm": "sha256",
    "template": "inspection:{inspection_id_lowercase}",
    "help": "对巡检单号去除首尾空白并转小写后，加上前缀 inspection: 计算 SHA-256 小写十六进制摘要。",
}
MAX_ROWS = 5000


def pattern_label(pattern):
    return condition_text(pattern)


def credential_for(inspection_id):
    """把巡检单号转成可跨库房比对的查重凭据，原单号不进入汇总。"""
    return hashlib.sha256(f"inspection:{inspection_id.strip().casefold()}".encode()).hexdigest()


def clean_rooms(rooms):
    cleaned = []
    seen = set()
    for index, room in enumerate(rooms, start=1):
        if not isinstance(room, str) or not 1 <= len(room.strip()) <= 80:
            raise ValueError(f"第 {index} 个参与库房名称须为 1 至 80 个字符")
        room = room.strip()
        if room.casefold() in seen:
            raise ValueError(f"参与库房「{room}」重复")
        seen.add(room.casefold())
        cleaned.append(room)
    if not cleaned:
        raise ValueError("请至少选择一个参与库房")
    if len(cleaned) > 50:
        raise ValueError("一次合并最多容纳 50 个库房")
    return cleaned


def resolve_room(value, rooms):
    for room in rooms:
        if room.casefold() == value.strip().casefold():
            return room
    raise ValueError(f"库房「{value}」不在本次合并的参与库房内")


def _non_negative_int(value, label, limit=MAX_ROWS):
    if type(value) is not int or not 0 <= value <= limit:
        raise ValueError(f"{label}须为 0 至 {limit} 的整数")
    return value


def normalize_hits(raw):
    """校验六项条件的正负组命中数，返回可与原算法直接相加的计数。"""
    if not isinstance(raw, dict):
        raise ValueError("条件命中数须按模式编号逐项填写")
    unknown = [key for key in raw if key not in PATTERN_KEYS]
    if unknown:
        raise ValueError(f"存在不支持的条件组合：{'、'.join(sorted(unknown))}")
    missing = [key for key in PATTERN_KEYS if key not in raw]
    if missing:
        raise ValueError(f"缺少条件组合的命中数：{'、'.join(sorted(missing))}")
    hits = {}
    for key in PATTERN_KEYS:
        counts = raw[key]
        if not isinstance(counts, dict):
            raise ValueError(f"条件组合「{key}」的命中数格式有误")
        positive = _non_negative_int(counts.get("positive"), f"{key} 正组命中")
        negative = _non_negative_int(counts.get("negative"), f"{key} 负组命中")
        hits[key] = {"positive": positive, "negative": negative}
    return hits


def normalize_credentials(raw):
    if not isinstance(raw, (list, tuple)):
        raise ValueError("查重凭据须为巡检单号摘要列表")
    if len(raw) > MAX_ROWS:
        raise ValueError(f"单个包最多 {MAX_ROWS} 条查重凭据")
    credentials = []
    seen = set()
    for index, value in enumerate(raw, start=1):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
            raise ValueError(f"第 {index} 条查重凭据格式有误")
        value = value.strip().casefold()
        if any(character.isspace() for character in value):
            raise ValueError(f"第 {index} 条查重凭据不能包含空白")
        if value in seen:
            raise ValueError(f"第 {index} 条查重凭据在同一个包内重复，请先在库房本地去重")
        seen.add(value)
        credentials.append(value)
    return credentials


def normalize_package(body, params, rooms):
    """把提交的包整理成可入账的载荷，并校验与本次合并的参数口径一致。"""
    if not isinstance(body, dict):
        raise ValueError("分包内容格式有误")
    room = resolve_room(str(body.get("room", "")), rooms)
    version = body.get("version")
    if type(version) is not int or version < 1:
        raise ValueError("包版本须为不小于 1 的整数")
    reference = str(body.get("reference", "")).strip()
    if not 1 <= len(reference) <= 120:
        raise ValueError("包编号须为 1 至 120 个字符")
    positive = _non_negative_int(body.get("positive_count"), "见霉斑样本数")
    negative = _non_negative_int(body.get("negative_count"), "未见霉斑样本数")
    total = positive + negative
    if total < 1:
        raise ValueError("请至少提交一条巡检的计数")
    hits = normalize_hits(body.get("pattern_hits"))
    for key, counts in hits.items():
        if counts["positive"] > positive or counts["negative"] > negative:
            raise ValueError(f"条件组合「{key}」的命中数超过对应分组的样本数")
    credentials = normalize_credentials(body.get("credentials"))
    if len(credentials) != total:
        raise ValueError(f"查重凭据 {len(credentials)} 条与两组样本数合计 {total} 条不一致")
    echoed = body.get("params")
    if echoed is not None:
        if not isinstance(echoed, dict):
            raise ValueError("包内参数格式有误")
        mismatch = []
        for field in SPEC["params"]:
            key = field["key"]
            if key not in echoed:
                continue
            expected, actual = params[key], echoed[key]
            try:
                same = (
                    int(actual) == int(expected) if field["type"] == "int" else float(actual) == float(expected)
                )
            except (TypeError, ValueError):
                same = False
            if not same:
                mismatch.append(key)
        if mismatch:
            raise ValueError("分包参数与本次合并冻结的筛查参数不一致，请按同一口径重新计算")
    return {
        "room": room, "version": version, "reference": reference,
        "positive_count": positive, "negative_count": negative,
        "pattern_hits": hits, "credentials": credentials,
    }


def package_checksum(package):
    """同一包重试时以内容摘要识别，不重复入账。"""
    material = {
        "room": package["room"], "version": package["version"], "reference": package["reference"],
        "positive_count": package["positive_count"], "negative_count": package["negative_count"],
        "pattern_hits": package["pattern_hits"], "credentials": sorted(package["credentials"]),
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def build_package(rows, room, params, reference, version=1):
    """在库房本地从巡检明细生成一个只含计数与凭据的包。"""
    threshold = params["humidity_threshold"]
    hits = {key: {"positive": 0, "negative": 0} for key in PATTERN_KEYS}
    credentials = []
    positive = negative = 0
    for row in rows:
        observed = bool(row["mildew_observed"])
        group = "positive" if observed else "negative"
        if observed:
            positive += 1
        else:
            negative += 1
        for pattern in row_patterns(row, threshold):
            hits[pattern_key(pattern)][group] += 1
        credentials.append(credential_for(row["inspection_id"]))
    return {
        "room": room, "version": version, "reference": reference,
        "positive_count": positive, "negative_count": negative,
        "pattern_hits": hits, "credentials": credentials,
    }


def aggregate(packages):
    """把各库房最新包的样本数与条件命中数逐项相加。"""
    positives = negatives = 0
    hits = {key: {"positive": 0, "negative": 0} for key in PATTERN_KEYS}
    for package in packages:
        positives += package["positive_count"]
        negatives += package["negative_count"]
        for key, counts in package["pattern_hits"].items():
            hits[key]["positive"] += counts["positive"]
            hits[key]["negative"] += counts["negative"]
    return {"positive_count": positives, "negative_count": negatives, "pattern_hits": hits}


def rank_patterns(totals, params):
    """按原筛查规则为合并后的计数重新排名。"""
    positives, negatives = totals["positive_count"], totals["negative_count"]
    if not positives or not negatives:
        return []
    counts = {
        PATTERN_KEYS[key]: {True: value["positive"], False: value["negative"]}
        for key, value in totals["pattern_hits"].items()
    }
    ranked = []
    for rank, score in enumerate(score_patterns(counts, positives, negatives, params), start=1):
        pattern, growth, positive, negative, positive_smoothed, negative_smoothed = score
        ranked.append({
            "pattern_id": f"P{rank:02d}",
            "conditions": pattern_label(pattern),
            "size": len(pattern),
            "positive_count": positive,
            "negative_count": negative,
            "positive_support": positive / positives,
            "negative_support": negative / negatives,
            "positive_smoothed": float(positive_smoothed),
            "negative_smoothed": float(negative_smoothed),
            "growth": float(growth),
        })
    return ranked


def find_conflicts(packages):
    """返回被两个及以上库房提交的同一巡检凭据，只暴露数量与涉及库房。"""
    owners = {}
    for package in packages:
        for credential in package["credentials"]:
            owners.setdefault(credential, set()).add(package["room"])
    duplicated = {credential: sorted(rooms) for credential, rooms in owners.items() if len(rooms) > 1}
    involved = sorted({room for rooms in duplicated.values() for room in rooms})
    return {
        "credential_count": len(duplicated),
        "rooms": involved,
        "digests": sorted(duplicated),
    }


def derive_state(rooms, latest_packages):
    """由各库房已入账包推导核对状态：冲突优先，其次等齐库房，齐备后待确认发布。"""
    accepted = [package for package in latest_packages if package["state"] == "accepted"]
    conflicts = find_conflicts(accepted)
    accepted_rooms = {package["room"] for package in accepted}
    missing = [room for room in rooms if room not in accepted_rooms]
    if conflicts["credential_count"]:
        state = "conflict"
    elif missing:
        state = "awaiting"
    else:
        state = "ready"
    return state, missing, conflicts, accepted
