#!/usr/bin/env python3
"""
生成广东电信 IPTV 播放列表和 XMLTV 节目表。
只输出 rtp2httpd RTP→HTTP 播放列表（gdctiptv4.m3u）。

特性：
  - 置顶频道：广东珠江、岭南戏曲、大湾区卫视、广东卫视、广东4K、CCTV-11
  - 智能分组：央视、广东、卫视、少儿、CGTN、超清4K、其他
  - 置顶是复制一份，原分组保留（如 CCTV-11 同时在置顶和央视）
  - 模糊匹配："广东4K" 能匹配 "广东4K超高清" 等，排除 "广东卫视4K"
  - 外部源保持原样，不参与分组
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import gzip
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


# =========================
# 用户配置
# =========================

USER_ID = ""
PASSWORD = ""
MAC = ""

IMEI = ""
ADDRESS = ""

SOURCE_ADDRESS: str | None = None

EDS_URL = "http://eds.iptv.gd.cn:8082/EDS/jsp/AuthenticationURL"
HTTP_TIMEOUT = 10
EPG_WORKERS = 16

EPG_DAYS_BEFORE = 7
EPG_DAYS_AFTER = 2

OUTPUT_RTP2HTTPD_RTP_M3U = "gdctiptv4.m3u"
OUTPUT_XMLTV = "gdctepg.xml"
OUTPUT_XMLTV_GZ = "gdctepg.xml.gz"
M3U_XMLTV_URL = "/epg.xml"

GENERATE_XMLTV_GZ = True

RTP2HTTPD_RTP_BASE_URL = "http://192.168.1.189:4022"
DEFAULT_FCC_SERVER = "183.59.156.166:8027"
USE_DEFAULT_FCC_FOR_MISSING_CHANNELS = True
RTP2HTTPD_FCC_TYPE = "telecom"
INCLUDE_FEC_IN_RTP_URLS = True
RTP2HTTPD_CATCHUP_SEEK_MODE = ""
RTP2HTTPD_CATCHUP_SEEK_OFFSET = ""

ADD_FCC_TO_EXTINF_ATTRIBUTES = False

CAPTURE_FALLBACK_JSON = "exports/pcap1_channels.json"

FILL_EMPTY_EPG_FROM_SAME_MULTICAST = True

FILL_EMPTY_EPG_FROM_CHANNEL_ALIAS = True
EPG_ALIAS_SUFFIXES = ["时移专用"]
EPG_ALIAS_RULES = {
    "CCTV1-1M开机标清": ["CCTV-1综合"],
}
NO_EPG_FALLBACK_CHANNEL_NAMES = {"CCTV4K-25P", "CCTV4K-50P"}

FILL_EMPTY_EPG_WITH_PLACEHOLDER = True
PLACEHOLDER_EPG_TITLE = "暂无节目表"
PLACEHOLDER_EPG_DESC = "运营商接口未提供该频道节目表"
PLACEHOLDER_EPG_INTERVAL_HOURS = 6

INCLUDE_CATCHUP = True
PLAYSEEK_TEMPLATE = "${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}"

GROUP_ORDER = [
    "置顶",
    "央视",
    "广东",
    "卫视",
    "少儿",
    "CGTN",
    "超清4K",
    "其他",
]

MERGE_EXTERNAL_M3U = True
EXTERNAL_M3U_URL = "https://github.nezha.loc.cc/taoiptv.m3u"
EXTERNAL_M3U_CACHE = "exports/external_hkat_cache.m3u"
EXTERNAL_GROUP_TITLES = {"iptv源": "iptv源", "网络源": "网络源"}
EXTERNAL_M3U_TIMEOUT = 15
EXTERNAL_GROUP_MIN_MATCH = 3


# =========================
# 置顶频道（模糊匹配）
# =========================

def match_top_channel(name: str) -> int:
    """返回置顶优先级，越小越靠前。0 表示不置顶。"""
    n = name
    nl = n.casefold()

    if "广东珠江" in n:
        return 1
    if "岭南戏曲" in n:
        return 2
    if "大湾区" in n:
        return 3
    if "广东卫视" in n:
        return 4
    # 广东4K：含"广东"和"4k"，但排除"卫视"
    if "广东" in n and "4k" in nl and "卫视" not in n:
        return 5
    # CCTV-11（后面不能跟数字）
    if re.search(r"cctv[\s\-_]*11(?!\d)", nl):
        return 6
    return 0


# =========================
# 智能分组
# =========================

CCTV_SPECIAL_KEYWORDS = [
    "风云音乐", "风云足球", "风云剧场", "风云",
    "第一剧场", "怀旧剧场", "世界地理", "女性时尚",
    "兵器科技", "电视指南", "央视精品", "央视台球",
    "高尔夫网球", "CCTV4K", "cctv4k",
    "CCTV4欧洲", "CCTV4美洲", "cctv4欧洲", "cctv4美洲",
]

GUANGDONG_LOCAL_KEYWORDS = [
    "云浮", "肇庆", "汕头", "潮州", "梅州", "河源",
    "揭阳", "清远", "茂名", "阳江", "湛江", "中山",
    "珠海", "江门", "佛山", "东莞", "韶关", "惠州",
    "广州", "深圳",
]

GUANGDONG_KEYWORDS = [
    "广东", "珠江", "岭南", "大湾区", "嘉佳卡通", "南方",
]

KIDS_KEYWORDS = [
    "少儿", "卡通", "KAKU", "kaku",
]


def group_title(name: str) -> str:
    n = name
    nl = n.casefold()

    if "cgtn" in nl:
        return "CGTN"

    if any(k in n or k.casefold() in nl for k in CCTV_SPECIAL_KEYWORDS):
        if "广东" not in n:
            return "央视"

    m = re.search(r"cctv[\s\-_]*(\d+)", nl)
    if m:
        try:
            num = int(m.group(1))
            if 1 <= num <= 17:
                return "央视"
        except ValueError:
            pass
    if "央视" in n and "风云" not in n and "特色" not in n:
        return "央视"

    if any(k in n or k.casefold() in nl for k in KIDS_KEYWORDS):
        return "少儿"

    if any(k in n for k in GUANGDONG_LOCAL_KEYWORDS) or any(k in n for k in GUANGDONG_KEYWORDS):
        return "广东"

    if "卫视" in n:
        return "卫视"

    if "4k" in nl or "超高清" in n or "超清" in n:
        return "超清4K"

    return "其他"


# =========================
# DES / 3DES ECB 实现
# =========================

IP = [
    58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4,
    62, 54, 46, 38, 30, 22, 14, 6, 64, 56, 48, 40, 32, 24, 16, 8,
    57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3,
    61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7,
]
FP = [
    40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31,
    38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29,
    36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27,
    34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25,
]
E = [
    32, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9,
    8, 9, 10, 11, 12, 13, 12, 13, 14, 15, 16, 17,
    16, 17, 18, 19, 20, 21, 20, 21, 22, 23, 24, 25,
    24, 25, 26, 27, 28, 29, 28, 29, 30, 31, 32, 1,
]
P = [
    16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10,
    2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25,
]
PC1 = [
    57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18,
    10, 2, 59, 51, 43, 35, 27, 19, 11, 3, 60, 52, 44, 36,
    63, 55, 47, 39, 31, 23, 15, 7, 62, 54, 46, 38, 30, 22,
    14, 6, 61, 53, 45, 37, 29, 21, 13, 5, 28, 20, 12, 4,
]
PC2 = [
    14, 17, 11, 24, 1, 5, 3, 28, 15, 6, 21, 10,
    23, 19, 12, 4, 26, 8, 16, 7, 27, 20, 13, 2,
    41, 52, 31, 37, 47, 55, 30, 40, 51, 45, 33, 48,
    44, 49, 39, 56, 34, 53, 46, 42, 50, 36, 29, 32,
]
SHIFTS = [1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1]
S_BOXES = [
    [[14,4,13,1,2,15,11,8,3,10,6,12,5,9,0,7],[0,15,7,4,14,2,13,1,10,6,12,11,9,5,3,8],[4,1,14,8,13,6,2,11,15,12,9,7,3,10,5,0],[15,12,8,2,4,9,1,7,5,11,3,14,10,0,6,13]],
    [[15,1,8,14,6,11,3,4,9,7,2,13,12,0,5,10],[3,13,4,7,15,2,8,14,12,0,1,10,6,9,11,5],[0,14,7,11,10,4,13,1,5,8,12,6,9,3,2,15],[13,8,10,1,3,15,4,2,11,6,7,12,0,5,14,9]],
    [[10,0,9,14,6,3,15,5,1,13,12,7,11,4,2,8],[13,7,0,9,3,4,6,10,2,8,5,14,12,11,15,1],[13,6,4,9,8,15,3,0,11,1,2,12,5,10,14,7],[1,10,13,0,6,9,8,7,4,15,14,3,11,5,2,12]],
    [[7,13,14,3,0,6,9,10,1,2,8,5,11,12,4,15],[13,8,11,5,6,15,0,3,4,7,2,12,1,10,14,9],[10,6,9,0,12,11,7,13,15,1,3,14,5,2,8,4],[3,15,0,6,10,1,13,8,9,4,5,11,12,7,2,14]],
    [[2,12,4,1,7,10,11,6,8,5,3,15,13,0,14,9],[14,11,2,12,4,7,13,1,5,0,15,10,3,9,8,6],[4,2,1,11,10,13,7,8,15,9,12,5,6,3,0,14],[11,8,12,7,1,14,2,13,6,15,0,9,10,4,5,3]],
    [[12,1,10,15,9,2,6,8,0,13,3,4,14,7,5,11],[10,15,4,2,7,12,9,5,6,1,13,14,0,11,3,8],[9,14,15,5,2,8,12,3,7,0,4,10,1,13,11,6],[4,3,2,12,9,5,15,10,11,14,1,7,6,0,8,13]],
    [[4,11,2,14,15,0,8,13,3,12,9,7,5,10,6,1],[13,0,11,7,4,9,1,10,14,3,5,12,2,15,8,6],[1,4,11,13,12,3,7,14,10,15,6,8,0,5,9,2],[6,11,13,8,1,4,10,7,9,5,0,15,14,2,3,12]],
    [[13,2,8,4,6,15,11,1,10,9,3,14,5,0,12,7],[1,15,13,8,10,3,7,4,12,5,6,11,0,14,9,2],[7,11,4,1,9,12,14,2,0,6,10,13,15,3,5,8],[2,1,14,7,4,10,8,13,15,12,9,0,3,5,6,11]],
]


def _permute(value: int, table: list[int], in_bits: int) -> int:
    out = 0
    for pos in table:
        out = (out << 1) | ((value >> (in_bits - pos)) & 1)
    return out


def _rotl28(value: int, bits: int) -> int:
    return ((value << bits) & 0x0FFFFFFF) | (value >> (28 - bits))


def _des_subkeys(key8: bytes) -> list[int]:
    key = int.from_bytes(key8, "big")
    key56 = _permute(key, PC1, 64)
    c = (key56 >> 28) & 0x0FFFFFFF
    d = key56 & 0x0FFFFFFF
    subkeys = []
    for shift in SHIFTS:
        c = _rotl28(c, shift)
        d = _rotl28(d, shift)
        subkeys.append(_permute((c << 28) | d, PC2, 56))
    return subkeys


def _des_f(r: int, subkey: int) -> int:
    x = _permute(r, E, 32) ^ subkey
    out = 0
    for i in range(8):
        chunk = (x >> (42 - 6 * i)) & 0x3F
        row = ((chunk & 0x20) >> 4) | (chunk & 0x01)
        col = (chunk >> 1) & 0x0F
        out = (out << 4) | S_BOXES[i][row][col]
    return _permute(out, P, 32)


def _des_crypt_block(block8: bytes, subkeys: list[int]) -> bytes:
    block = int.from_bytes(block8, "big")
    block = _permute(block, IP, 64)
    l = (block >> 32) & 0xFFFFFFFF
    r = block & 0xFFFFFFFF
    for subkey in subkeys:
        l, r = r, l ^ _des_f(r, subkey)
    out = _permute((r << 32) | l, FP, 64)
    return out.to_bytes(8, "big")


def _des_encrypt_block(block8: bytes, key8: bytes) -> bytes:
    return _des_crypt_block(block8, _des_subkeys(key8))


def _des_decrypt_block(block8: bytes, key8: bytes) -> bytes:
    return _des_crypt_block(block8, list(reversed(_des_subkeys(key8))))


def _pkcs7_pad(data: bytes, block_size: int = 8) -> bytes:
    pad = block_size - (len(data) % block_size)
    return data + bytes([pad]) * pad


def tdes_ede3_ecb_encrypt_pkcs7(data: bytes, key_material: bytes) -> bytes:
    if len(key_material) < 24:
        raise ValueError("3DES key material must be at least 24 bytes")
    key = key_material[:24]
    k1, k2, k3 = key[:8], key[8:16], key[16:24]
    out = bytearray()
    padded = _pkcs7_pad(data)
    for i in range(0, len(padded), 8):
        block = padded[i:i + 8]
        block = _des_encrypt_block(block, k1)
        block = _des_decrypt_block(block, k2)
        block = _des_encrypt_block(block, k3)
        out.extend(block)
    return bytes(out)


# =========================
# HTTP 工具
# =========================


class SourceAddressHTTPConnection(urllib.request.http.client.HTTPConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if SOURCE_ADDRESS:
            kwargs["source_address"] = (SOURCE_ADDRESS, 0)
        super().__init__(*args, **kwargs)


class SourceAddressHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request):
        return self.do_open(SourceAddressHTTPConnection, req)


def build_opener() -> urllib.request.OpenerDirector:
    cookie_jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        SourceAddressHTTPHandler(),
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )


def make_url(base: str, params: dict[str, str] | list[tuple[str, str]] | None = None) -> str:
    if not params:
        return base
    return base + "?" + urllib.parse.urlencode(params)


def http_get(opener: urllib.request.OpenerDirector, url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "gdctiptv.py/1.0", "Accept": "*/*"})
    try:
        with opener.open(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} for {url}: {body[:300]}") from e


def http_get_text(opener: urllib.request.OpenerDirector, url: str) -> str:
    return http_get(opener, url).decode("utf-8", errors="replace")


def http_get_json(opener: urllib.request.OpenerDirector, url: str) -> Any:
    return json.loads(http_get_text(opener, url))


# =========================
# 数据结构
# =========================


@dataclass
class Program:
    start: int
    stop: int
    title: str
    desc: str


@dataclass
class Channel:
    id: str
    name: str
    rtsp: str
    igmp: str = ""
    time_shift_url: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    epg: list[Program] = field(default_factory=list)


@dataclass
class ExternalChannel:
    title: str
    url: str
    group: str
    attrs: dict[str, str] = field(default_factory=dict)
    extra_lines: list[str] = field(default_factory=list)


# =========================
# IPTV 认证
# =========================


def get_base_url(opener: urllib.request.OpenerDirector) -> str:
    params = {"Action": "Login", "return_type": "1", "UserID": USER_ID}
    data = http_get_json(opener, make_url(EDS_URL, params))
    epgurl = data["epgurl"]
    parsed = urllib.parse.urlparse(epgurl)
    if not parsed.scheme or not parsed.hostname:
        raise RuntimeError(f"无效的 epgurl：{epgurl}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    base_url = f"{parsed.scheme}://{parsed.hostname}:{port}"
    print(f"EPG 基础地址：{base_url}")
    return base_url


def build_authinfo(token: str) -> str:
    md5_hex = hashlib.md5(PASSWORD.encode("utf-8")).hexdigest().upper()
    plain = f"{random.randrange(0, 10000000)}${token}${USER_ID}${IMEI}${ADDRESS}${MAC}$$CTC"
    encrypted = tdes_ede3_ecb_encrypt_pkcs7(plain.encode("utf-8"), md5_hex.encode("ascii"))
    return encrypted.hex().upper()


def login(opener: urllib.request.OpenerDirector) -> str:
    base_url = get_base_url(opener)
    authorize_url = make_url(
        f"{base_url}/EPG/oauth/v2/authorize",
        {"response_type": "EncryToken", "client_id": "smcphone", "userid": USER_ID},
    )
    token = http_get_json(opener, authorize_url)["EncryToken"]
    print("已获取 EncryToken")

    token_url = make_url(
        f"{base_url}/EPG/oauth/v2/token",
        [
            ("client_id", "smcphone"), ("DeviceType", "deviceType"),
            ("UserID", USER_ID), ("DeviceVersion", "deviceVersion"),
            ("userdomain", "2"), ("datadomain", "3"), ("accountType", "1"),
            ("authinfo", build_authinfo(token)), ("grant_type", "EncryToken"),
        ],
    )
    http_get(opener, token_url)
    print("EPG 登录成功")
    return base_url


# =========================
# 频道解析
# =========================


def parse_channel_config(config: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in config.split('",'):
        if '="' not in part:
            continue
        key, value = part.split('="', 1)
        if value.endswith('"'):
            value = value[:-1]
        fields[key.strip()] = value.strip()
    return fields


def first_prefixed(value: str, prefix: str) -> str:
    for item in value.split("|"):
        item = item.strip()
        if item.lower().startswith(prefix):
            return item
    return ""


def get_channels(opener: urllib.request.OpenerDirector, base_url: str) -> list[Channel]:
    url = f"{base_url}/EPG/jsp/getchannellistHWCTC.jsp"
    text = http_get_text(opener, url)
    configs = re.findall(r"Authentication\.CTCSetConfig\('Channel','(.+?)'\)", text, re.S)
    channels: list[Channel] = []
    for config in configs:
        fields = parse_channel_config(config)
        channel_id = fields.get("ChannelID", "")
        name = fields.get("ChannelName", "")
        channel_url = fields.get("ChannelURL", "")
        if not channel_id or not name or not channel_url:
            continue
        rtsp = first_prefixed(channel_url, "rtsp://").replace("zoneoffset=0", "zoneoffset=480")
        igmp = first_prefixed(channel_url, "igmp://")
        if not rtsp:
            continue
        channels.append(Channel(
            id=channel_id, name=name, rtsp=rtsp, igmp=igmp,
            time_shift_url=fields.get("TimeShiftURL", "").replace("zoneoffset=0", "zoneoffset=480"),
            fields=fields,
        ))
    print(f"已获取 {len(channels)} 个频道")
    return channels


def apply_capture_fallback(channels: list[Channel], cwd: Path) -> None:
    if not CAPTURE_FALLBACK_JSON:
        return
    path = Path(CAPTURE_FALLBACK_JSON)
    if not path.is_absolute():
        path = cwd / path
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"警告：读取抓包兜底文件失败 {path}: {e}")
        return
    fallback: dict[str, dict[str, str]] = {}
    for item in data:
        channel_id = str(item.get("ChannelID", ""))
        if not channel_id:
            continue
        fallback[channel_id] = {str(k): str(v) for k, v in item.items() if v is not None}
        igmp = str(item.get("igmp_url", ""))
        if not igmp:
            igmp = first_prefixed(str(item.get("ChannelURL", "")), "igmp://")
        if igmp:
            fallback[channel_id]["igmp_url"] = igmp
    filled_igmp = 0
    filled_fcc = 0
    for channel in channels:
        item = fallback.get(channel.id)
        if not item:
            continue
        if not channel.igmp and item.get("igmp_url"):
            channel.igmp = item["igmp_url"]
            filled_igmp += 1
        for key in ("FCCEnable", "ChannelFCCIP", "ChannelFCCPort", "ChannelFECPort"):
            value = item.get(key, "")
            if not value:
                continue
            current = channel.fields.get(key, "")
            if key in ("ChannelFCCIP", "ChannelFCCPort") and not current:
                channel.fields[key] = value
                filled_fcc += 1
            elif key == "FCCEnable" and item.get("ChannelFCCIP") and item.get("ChannelFCCPort"):
                channel.fields[key] = value
            elif key == "ChannelFECPort" and (not current or current == "0"):
                channel.fields[key] = value
    if filled_igmp:
        print(f"已从 {path} 补充 {filled_igmp} 个组播地址")
    if filled_fcc:
        print(f"已从 {path} 补充 FCC 字段")


def normalize_channel_name(name: str) -> str:
    name = re.sub(r"[\s\-＋+_/·.（）()【】\[\]]+", "", name)
    name = name.casefold()
    for suffix in ["高清", "超清", "标清", "4k", "测试", "hd"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def build_igmp_from_external_m3u(ext_channels: list[ExternalChannel]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for ch in ext_channels:
        url = ch.url.strip()
        if not url.lower().startswith("rtp://"):
            continue
        key = normalize_channel_name(ch.title)
        if key and key not in mapping:
            mapping[key] = url
    return mapping


def apply_igmp_from_external(channels: list[Channel], mapping: dict[str, str]) -> None:
    filled_exact = 0
    filled_prefix = 0
    for channel in channels:
        if channel.igmp:
            continue
        key = normalize_channel_name(channel.name)
        if not key:
            continue
        igmp = mapping.get(key)
        if igmp:
            channel.igmp = igmp
            filled_exact += 1
            continue
        best_key = ""
        best_url = ""
        for map_key, map_url in mapping.items():
            if len(map_key) < 4:
                continue
            if key.startswith(map_key) and len(map_key) > len(best_key):
                best_key = map_key
                best_url = map_url
        if best_url:
            channel.igmp = best_url
            filled_prefix += 1
    total = filled_exact + filled_prefix
    if total:
        print(f"已从外部 M3U 补充 {total} 个组播地址（精确 {filled_exact}，前缀 {filled_prefix}）")


# =========================
# EPG
# =========================


def fetch_playbill(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    channel: Channel,
    begin_ms: int,
    end_ms: int,
) -> Channel:
    url = make_url(
        f"{base_url}/EPG/jsp/iptvsnmv3/en/play/ajax/_ajax_getPlaybillList.jsp",
        {"channelId": channel.id, "begin": str(begin_ms), "end": str(end_ms)},
    )
    try:
        data = http_get_json(opener, url)
        for bill in data.get("playbillLites", []):
            name = str(bill.get("name", ""))
            start = int(bill.get("startTime", 0))
            stop = int(bill.get("endTime", 0))
            if name and start and stop:
                channel.epg.append(Program(start=start, stop=stop, title=name, desc=name))
    except Exception as e:
        print(f"警告：获取节目表失败 {channel.id} {channel.name}: {e}")
    return channel


def fetch_all_epg(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    channels: list[Channel],
) -> None:
    now_ms = int(time.time() * 1000)
    begin_ms = now_ms - EPG_DAYS_BEFORE * 86400000
    end_ms = now_ms + EPG_DAYS_AFTER * 86400000
    total_programs = 0
    done = 0
    with ThreadPoolExecutor(max_workers=EPG_WORKERS) as pool:
        futures = [pool.submit(fetch_playbill, opener, base_url, c, begin_ms, end_ms) for c in channels]
        for future in as_completed(futures):
            channel = future.result()
            done += 1
            total_programs += len(channel.epg)
            if done % 20 == 0 or done == len(channels):
                print(f"节目表进度：{done}/{len(channels)}，节目数={total_programs}")
    print(f"已获取 {total_programs} 条节目")


def multicast_epg_key(channel: Channel) -> str:
    if not channel.igmp:
        return ""
    parsed = urllib.parse.urlparse(channel.igmp)
    if parsed.hostname:
        port = parsed.port or ""
        return f"{parsed.hostname}:{port}" if port else parsed.hostname
    return channel.igmp.strip()


def clone_epg(programs: list[Program]) -> list[Program]:
    return [Program(start=p.start, stop=p.stop, title=p.title, desc=p.desc) for p in programs]


def copy_epg(channel: Channel, source: Channel) -> int:
    channel.epg = clone_epg(source.epg)
    return len(channel.epg)


def fill_empty_epg_from_same_multicast(channels: list[Channel]) -> None:
    if not FILL_EMPTY_EPG_FROM_SAME_MULTICAST:
        return
    source_by_multicast: dict[str, Channel] = {}
    for channel in channels:
        key = multicast_epg_key(channel)
        if key and channel.epg and key not in source_by_multicast:
            source_by_multicast[key] = channel
    filled = 0
    added = 0
    for channel in channels:
        if channel.epg:
            continue
        if is_no_epg_fallback_channel(channel):
            continue
        source = source_by_multicast.get(multicast_epg_key(channel))
        if not source:
            continue
        copied = copy_epg(channel, source)
        filled += 1
        added += copied
        print(f"节目表同组播兜底：{channel.id} {channel.name} <- {source.id} {source.name}（{copied} 条节目）")
    if filled:
        print(f"已通过同组播源补充 {filled} 个频道节目表，新增 {added} 条节目")


def epg_name_key(name: str) -> str:
    return re.sub(r"[\s\-＋+_/]+", "", name).casefold()


def is_no_epg_fallback_channel(channel: Channel) -> bool:
    return epg_name_key(channel.name) in {epg_name_key(n) for n in NO_EPG_FALLBACK_CHANNEL_NAMES}


def epg_alias_candidates(name: str) -> list[str]:
    candidates = list(EPG_ALIAS_RULES.get(name, []))
    for suffix in EPG_ALIAS_SUFFIXES:
        if name.endswith(suffix):
            candidates.append(name[: -len(suffix)].strip())
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = epg_name_key(candidate)
        if candidate and key not in seen:
            result.append(candidate)
            seen.add(key)
    return result


def fill_empty_epg_from_channel_alias(channels: list[Channel]) -> None:
    if not FILL_EMPTY_EPG_FROM_CHANNEL_ALIAS:
        return
    source_by_name: dict[str, Channel] = {}
    for channel in channels:
        key = epg_name_key(channel.name)
        if key and channel.epg and key not in source_by_name:
            source_by_name[key] = channel
    filled = 0
    added = 0
    for channel in channels:
        if channel.epg:
            continue
        if is_no_epg_fallback_channel(channel):
            continue
        for candidate in epg_alias_candidates(channel.name):
            source = source_by_name.get(epg_name_key(candidate))
            if not source:
                continue
            copied = copy_epg(channel, source)
            filled += 1
            added += copied
            print(f"节目表别名兜底：{channel.id} {channel.name} <- {source.id} {source.name}（{copied} 条节目）")
            break
    if filled:
        print(f"已通过别名补充 {filled} 个频道节目表，新增 {added} 条节目")


def datetime_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def fill_empty_epg_with_placeholder(channels: list[Channel]) -> None:
    if not FILL_EMPTY_EPG_WITH_PLACEHOLDER:
        return
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    start = (now - timedelta(days=EPG_DAYS_BEFORE)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (now + timedelta(days=EPG_DAYS_AFTER + 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    step = timedelta(hours=max(1, int(PLACEHOLDER_EPG_INTERVAL_HOURS)))
    filled = 0
    added = 0
    for channel in channels:
        if channel.epg:
            continue
        cursor = start
        while cursor < end:
            stop = min(cursor + step, end)
            channel.epg.append(Program(
                start=datetime_ms(cursor), stop=datetime_ms(stop),
                title=PLACEHOLDER_EPG_TITLE, desc=PLACEHOLDER_EPG_DESC,
            ))
            cursor = stop
        filled += 1
        added += len(channel.epg)
        print(f"节目表占位：{channel.id} {channel.name}（{len(channel.epg)} 条节目）")
    if filled:
        print(f"已为 {filled} 个频道填充占位节目表，新增 {added} 条节目")


# =========================
# 排序
# =========================


def natural_sort_key(text: str) -> list[tuple[int, int | str]]:
    parts = re.findall(r"\d+|\D+", text)
    key: list[tuple[int, int | str]] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            normalized = re.sub(r"[\s\-＋+_/]+", "", part).casefold()
            if normalized:
                key.append((1, normalized))
    return key


def channel_sort_key(channel: Channel) -> tuple:
    group = group_title(channel.name)
    group_index = GROUP_ORDER.index(group) if group in GROUP_ORDER else len(GROUP_ORDER)
    top_order = match_top_channel(channel.name)
    channel_id = int(channel.id) if channel.id.isdigit() else channel.id
    return (group_index, top_order, natural_sort_key(channel.name), channel_id)


def sort_channels(channels: list[Channel]) -> list[Channel]:
    return sorted(channels, key=channel_sort_key)


# =========================
# 外部 M3U 处理
# =========================


def valid_m3u_content(text: str) -> bool:
    return bool(text and ("#EXTM3U" in text or "#EXTINF" in text))


def download_text(url: str, timeout: int = HTTP_TIMEOUT) -> str:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def load_external_m3u_text() -> tuple[str, str]:
    cache_path = Path(EXTERNAL_M3U_CACHE)
    try:
        text = download_text(EXTERNAL_M3U_URL, EXTERNAL_M3U_TIMEOUT)
        if valid_m3u_content(text):
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
            print(f"已从网络获取外部 M3U：{EXTERNAL_M3U_URL}")
            return text, "network"
    except Exception as e:
        print(f"警告：获取外部 M3U 失败：{e}")
    if cache_path.exists():
        text = cache_path.read_text(encoding="utf-8", errors="replace")
        if valid_m3u_content(text):
            print(f"使用缓存的外部 M3U：{cache_path}")
            return text, "cache"
    return "", "none"


def normalize_external_group(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text.lower()))


def shared_group_fragment(source: str, target: str) -> bool:
    source_norm = normalize_external_group(source)
    target_norm = normalize_external_group(target)
    if not source_norm or not target_norm:
        return False
    if source_norm == target_norm or source_norm in target_norm or target_norm in source_norm:
        return True
    shorter, longer = (source_norm, target_norm) if len(source_norm) <= len(target_norm) else (target_norm, source_norm)
    if len(shorter) < EXTERNAL_GROUP_MIN_MATCH:
        return False
    return any(shorter[i:i + EXTERNAL_GROUP_MIN_MATCH] in longer for i in range(len(shorter) - EXTERNAL_GROUP_MIN_MATCH + 1))


def external_target_group(source_group: str) -> str:
    for key, target in EXTERNAL_GROUP_TITLES.items():
        if key in source_group or shared_group_fragment(source_group, key):
            return target
    return ""


def normalize_external_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme or parsed.netloc:
        return parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower()).geturl()
    return url.strip()


def parse_external_m3u(text: str) -> list[ExternalChannel]:
    channels: list[ExternalChannel] = []
    seen_urls: set[str] = set()
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attrs = {k: v for k, v in re.findall(r'(\S+?)="([^"]*)"', line)}
            current = {
                "title": line.split(",", 1)[-1].strip() if "," in line else "",
                "attrs": attrs,
                "extra_lines": [],
            }
        elif line.startswith("#") and current is not None:
            current["extra_lines"].append(line)
        elif current is not None:
            source_group = current["attrs"].get("group-title", "")
            target_group = external_target_group(source_group)
            norm_url = normalize_external_url(line)
            if target_group and norm_url not in seen_urls:
                seen_urls.add(norm_url)
                attrs = dict(current["attrs"])
                attrs["group-title"] = target_group
                title = current["title"] or attrs.get("tvg-name", "") or attrs.get("tvg-id", "")
                channels.append(ExternalChannel(
                    title=title, url=line, group=target_group,
                    attrs=attrs, extra_lines=list(current["extra_lines"]),
                ))
            current = None
    return channels


def load_external_channels() -> list[ExternalChannel]:
    if not MERGE_EXTERNAL_M3U or not EXTERNAL_M3U_URL or not EXTERNAL_GROUP_TITLES:
        return []
    text, source = load_external_m3u_text()
    if not text:
        return []
    channels = parse_external_m3u(text)
    source_label = {"network": "网络", "cache": "缓存", "none": "无"}.get(source, source)
    print(f"已提取 {len(channels)} 个外部频道，来源={source_label}")
    return channels


def attr_escape(value: Any) -> str:
    return escape(str(value), {'"': "&quot;"})


def external_m3u_lines(channel: ExternalChannel) -> list[str]:
    attrs = dict(channel.attrs)
    attrs["group-title"] = channel.group
    attrs.setdefault("tvg-name", channel.title)
    attrs.setdefault("tvg-id", channel.title)
    parts = ["#EXTINF:-1"]
    for key, value in attrs.items():
        safe_value = attr_escape(str(value).replace(",", "&comma;"))
        parts.append(f'{key}="{safe_value}"')
    safe_url = channel.url.replace(",", "%2C")
    return [" ".join(parts) + f",{channel.title}", *channel.extra_lines, safe_url]


# =========================
# 地址构造
# =========================


def parse_igmp(igmp: str) -> tuple[str, str, str]:
    parsed = urllib.parse.urlparse(igmp)
    host = parsed.hostname or ""
    port = str(parsed.port or "")
    addr = f"{host}:{port}" if port else host
    return host, port, addr


def append_query(url: str, params: list[tuple[str, str]]) -> str:
    params = [(k, v) for k, v in params if v]
    if not params:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + urllib.parse.urlencode(params, safe=":,$(){}")


def fcc_server(channel: Channel) -> str:
    ip = channel.fields.get("ChannelFCCIP", "")
    port = channel.fields.get("ChannelFCCPort", "")
    if ip and port:
        return f"{ip}:{port}"
    if USE_DEFAULT_FCC_FOR_MISSING_CHANNELS:
        return DEFAULT_FCC_SERVER
    return ""


def fec_port(channel: Channel) -> str:
    port = channel.fields.get("ChannelFECPort", "")
    return port if port and port != "0" else ""


def fcc_query_params(channel: Channel, include_fec: bool = False) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = []
    fcc = fcc_server(channel)
    if fcc:
        params.append(("fcc", fcc))
        if RTP2HTTPD_FCC_TYPE:
            params.append(("fcc-type", RTP2HTTPD_FCC_TYPE))
    if include_fec:
        fec = fec_port(channel)
        if fec:
            params.append(("fec", fec))
    return params


def rtsp_to_http_url(
    rtsp_url: str,
    base_url: str,
    channel: Channel,
    extra_params: list[tuple[str, str]] | None = None,
) -> str:
    parsed = urllib.parse.urlparse(rtsp_url)
    if parsed.scheme != "rtsp" or not parsed.hostname:
        return rtsp_url
    port = parsed.port or 554
    path = parsed.path or "/"
    if port == 554:
        url = f"{base_url.rstrip('/')}/rtsp/{parsed.hostname}{path}"
    else:
        url = f"{base_url.rstrip('/')}/rtsp/{parsed.hostname}:{port}{path}"
    if parsed.query:
        url = f"{url}?{parsed.query}"
    params: list[tuple[str, str]] = []
    if extra_params:
        params.extend(extra_params)
    return append_query(url, params)


def proxied_multicast_url(
    channel: Channel,
    base_url: str,
    path: str = "rtp",
    include_fcc: bool = True,
    include_fec: bool = True,
) -> str:
    if not channel.igmp:
        return ""
    host, port, addr = parse_igmp(channel.igmp)
    if not host or not port:
        return ""
    url = f"{base_url.rstrip('/')}/{path.strip('/')}/{addr}"
    if include_fcc:
        url = append_query(url, fcc_query_params(channel, include_fec=include_fec))
    return url


def rtp2httpd_rtp_url(channel: Channel) -> str:
    return proxied_multicast_url(
        channel, RTP2HTTPD_RTP_BASE_URL, "rtp",
        include_fcc=True, include_fec=INCLUDE_FEC_IN_RTP_URLS,
    )


def playlist_url(channel: Channel, mode: str) -> str:
    if mode == "rtp2httpd_rtp":
        return rtp2httpd_rtp_url(channel)
    raise ValueError(f"未知播放列表模式：{mode}")


def catchup_url(channel: Channel, mode: str) -> str:
    if not channel.time_shift_url:
        return ""
    params = [("playseek", PLAYSEEK_TEMPLATE)]
    if RTP2HTTPD_CATCHUP_SEEK_MODE:
        params.append(("r2h-seek-mode", RTP2HTTPD_CATCHUP_SEEK_MODE))
    if RTP2HTTPD_CATCHUP_SEEK_OFFSET:
        params.append(("r2h-seek-offset", RTP2HTTPD_CATCHUP_SEEK_OFFSET))
    if mode == "rtp2httpd_rtp":
        return rtsp_to_http_url(channel.time_shift_url, RTP2HTTPD_RTP_BASE_URL, channel, params)
    raise ValueError(f"未知播放列表模式：{mode}")


def extinf_line(channel: Channel, mode: str, group_override: str | None = None) -> str:
    group = group_override if group_override is not None else group_title(channel.name)
    attrs = [
        "#EXTINF:-1",
        f'tvg-id="{channel.id}"',
        f'tvg-name="{channel.name}"',
        f'tvg-chno="{channel.id}"',
        f'group-title="{group}"',
    ]
    if ADD_FCC_TO_EXTINF_ATTRIBUTES and fcc_server(channel):
        attrs.insert(4, f'fcc="{fcc_server(channel)}"')
        if RTP2HTTPD_FCC_TYPE:
            attrs.insert(5, f'fcc-type="{RTP2HTTPD_FCC_TYPE}"')
        if fec_port(channel):
            attrs.insert(6, f'fec="{fec_port(channel)}"')
    if INCLUDE_CATCHUP and channel.time_shift_url:
        catchup_source = catchup_url(channel, mode).replace(",", "%2C")
        attrs.insert(4, 'catchup="default"')
        attrs.insert(5, f'catchup-source="{catchup_source}"')
    return " ".join(attrs) + f",{channel.name}"


def write_m3u(path: Path, channels: list[Channel], mode: str, external_channels: list[ExternalChannel]) -> None:
    lines = [f'#EXTM3U x-tvg-url="{M3U_XMLTV_URL}"']

    # 1) 先输出置顶副本（复制一份，不删除原分组）
    top_channels = [c for c in channels if match_top_channel(c.name) > 0]
    top_channels.sort(key=lambda c: (match_top_channel(c.name), natural_sort_key(c.name)))
    for channel in top_channels:
        url = playlist_url(channel, mode)
        if not url:
            continue
        url = url.replace(",", "%2C")
        lines.append(extinf_line(channel, mode, group_override="置顶"))
        lines.append(url)

    # 2) 再输出全部频道（原分组，包含置顶频道本身）
    for channel in channels:
        url = playlist_url(channel, mode)
        if not url:
            continue
        url = url.replace(",", "%2C")
        lines.append(extinf_line(channel, mode))
        lines.append(url)

    # 3) 外部频道原样追加
    for channel in external_channels:
        lines.extend(external_m3u_lines(channel))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {path}（{sum(1 for line in lines if line.startswith('#EXTINF'))} 个频道）")


def xmltv_time(ms: int) -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(ms / 1000, tz=tz).strftime("%Y%m%d%H%M%S +0800")


def write_xmltv(path: Path, channels: list[Channel]) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<tv generator-info-name="gdctiptv.py" source-info-name="gdctiptv.py">\n')
        for channel in channels:
            f.write(f'  <channel id="{escape(channel.id)}">')
            f.write(f"<display-name>{escape(channel.name)}</display-name>")
            f.write("</channel>\n")
        for channel in channels:
            for program in channel.epg:
                f.write(
                    f'  <programme start="{xmltv_time(program.start)}" '
                    f'stop="{xmltv_time(program.stop)}" '
                    f'channel="{escape(channel.id)}">'
                )
                f.write(f'<title lang="chi">{escape(program.title)}</title>')
                if program.desc:
                    f.write(f"<desc>{escape(program.desc)}</desc>")
                f.write("</programme>\n")
        f.write("</tv>\n")
    count = sum(len(c.epg) for c in channels)
    print(f"已写入 {path}（{len(channels)} 个频道，{count} 条节目）")


def write_gzip_from_file(source_path: Path, gzip_path: Path) -> None:
    with source_path.open("rb") as src, gzip.open(gzip_path, "wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
    print(f"已写入 {gzip_path}")


def self_test_des() -> None:
    key = bytes.fromhex("133457799BBCDFF1")
    plain = bytes.fromhex("0123456789ABCDEF")
    expected = "85E813540F0AB405"
    got = _des_encrypt_block(plain, key).hex().upper()
    if got != expected:
        raise RuntimeError(f"DES 自检失败：实际 {got}，期望 {expected}")


def validate_config() -> None:
    required = [("USER_ID", USER_ID), ("PASSWORD", PASSWORD), ("MAC", MAC)]
    missing = [n for n, v in required if not v.strip()]
    if missing:
        raise RuntimeError("缺少广东电信配置：" + ", ".join(missing))


def main() -> int:
    self_test_des()
    validate_config()
    out_dir = Path.cwd()
    print(f"输出目录：{out_dir}")
    opener = build_opener()
    base_url = login(opener)
    channels = get_channels(opener, base_url)
    if not channels:
        raise RuntimeError("未解析到频道")
    apply_capture_fallback(channels, out_dir)

    external_channels = load_external_channels()
    if external_channels:
        igmp_map = build_igmp_from_external_m3u(external_channels)
        apply_igmp_from_external(channels, igmp_map)

    channels = sort_channels(channels)
    fetch_all_epg(opener, base_url, channels)
    fill_empty_epg_from_same_multicast(channels)
    fill_empty_epg_from_channel_alias(channels)
    fill_empty_epg_with_placeholder(channels)

    write_m3u(out_dir / OUTPUT_RTP2HTTPD_RTP_M3U, channels, "rtp2httpd_rtp", external_channels)

    xmltv_path = out_dir / OUTPUT_XMLTV
    write_xmltv(xmltv_path, channels)
    if GENERATE_XMLTV_GZ:
        write_gzip_from_file(xmltv_path, out_dir / OUTPUT_XMLTV_GZ)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)