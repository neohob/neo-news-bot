#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""neo-news-bot · 精简移植版（源清单与抓法照搬 freebie-radar，只裁剪源和出口）

与上游（ZiChuanLan/freebie-radar）的对应关系：
- 源清单：来自 upstream/src/server/collectors/index.ts 的 SEEDS（111 条内置源），
  这里只保留对自建/开发者有用的子集，并按上游的采集器种类照抄抓取方式：
    linuxdo     → Discourse RSS /c/<slug>/<id>.rss，直连 403 才切 FlareSolverr；429 视为限流跳过本轮
    rss         → 通用 RSS/Atom，带 includeCategories / titleKeywords / only100Off 等过滤
    github      → api.github.com/repos/<repo>/contents/README.md (accept: raw)，按二级标题分节定类
    openrouter  → /api/v1/models，只取 created 在 14 天内且 prompt+completion 价格为 0 的模型
    telegram    → t.me/s/<channel> 公开预览页 HTML 解析（tgme_widget_message_wrap）
    epic        → store-site-backend-static freeGamesPromotions
- 算法：移植他的 enrich 规则
    noise.ts   NOISE_TITLE 干扰标题黑名单
    obtain.ts  guessObtain 六级判定（free/conditional/trial/lottery/promo/paid），顺序与上游一致
    codes.ts   邀请码/兑换码/激活码抽取
    score.ts   五维加权：获取确定性 .3 / 质量 .35 / 时效 .15 / 源可信 .1 / 可验证 .1 + 乘性惩罚

用法：
  python3 collect.py           # 采集并写 candidates.json
  python3 collect.py --show    # 采集并打印候选
"""
import json, os, re, sys, time, hashlib, gzip, html, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(BASE, "seen.json")
BASELINE = os.path.join(BASE, "baseline.json")
OUT = os.path.join(BASE, "candidates.json")
CAP_TOTAL = int(os.environ.get("CAP_TOTAL", "110"))
FLARE = os.environ.get("FLARESOLVERR", "http://127.0.0.1:8191/v1")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

# ============ 规则层：照抄 upstream/src/server/enrich ============

# noise.ts —— 社区求助/水帖/小版本更新，不作为福利收录
NOISE_TITLE = re.compile(
    r"^(怎样|怎么|如何|哪里|哪个|为什么|为何)|请问|有没有|求推荐|求一个|哪里(有|能)|值得买吗|怎么样\?|不够用|用完了"
    r"|失效了|吐槽|踩坑|后悔|失望|谁有|求个|求购|哪有|哪里有|多少钱|求助|求带|大佬|老哥|有人吗|有人知道|怎么弄"
    r"|能白嫖吗|免费更新|内容更新|版本更新|免费升级|更新公告|更新补丁|补丁说明|patch\s*notes|free\s+update", re.I)

# 与自建/开发者无关的羊毛噪音（上游没有，这里加：银行卡/话费/影视/实物样品）
PY_FREE = ("linux.do", "tg", "nodeseek", "keylol")  # 需要额外闲聊过滤的社区源前缀
COMMUNITY = {"52pojie", "nodeloc", "yxssp"}
# 社区源里的闲聊/求助/二手/破解帖：问句、"有佬吗"、"求推荐"、收售、解锁会员版
CHAT_NOISE = re.compile(r"有佬|大佬|求助|问一下|想问|请问|有没有人|哪家|求推荐|怎么弄|能开吗|会不会|拉闸|"
                        r"兄弟们|家人们|萌新|水一贴|[（(【\[]\s*[\d\s]*\s*(收|出|售)\s*[）)】\]]|出闲置|闲置出|收个|收一|补一人|"
                        r"解锁会员|破解|修改版|去广告版|完美解锁|直装解锁|"
                        r"求几本|求三本|求购|帮忙下载|请帮忙|带价来|代充|收币|收个号|求全套|求课程|"
                        r"有无.*渠道|汇丰|信用卡|理财|基金|被动收入|财务自由|月入过万|教你月入")
NOISE_EXTRA = re.compile(r"话费|立减金|信用卡|银行|影视|连续剧|4k|电影下载|网盘资源|资源合集|奶茶|外卖"
                         r"|收一个|收一台|出一台|出一个|收个|出个|求购|转让|明盘|收\\s*\\d+|出\\s*\\d+|【出】|【收】|【售】|【求】"
                         r"|请教|想问|请问下|有没有人|怎么选|哪个好|值不值|已出|已收|结帖"
                         r"|女友|伴侣|私密|成人|擦边|酒馆|华莱士|麦当劳|肯德基|瑞幸|蜜雪", re.I)

# obtain.ts —— 顺序有意为之：抽奖 > 推广 > 试用 > 有条件 > free
def guess_obtain(text):
    if re.search(r"抽奖|抽\s*\d+\s*(份|个|名|位)|抽取|随机送|开奖|中奖|摇号|锦鲤|抽名额", text):
        return "lottery"
    if re.search(r"招募|代理|加盟|官方旗舰|我们的服务|软广|推广位|商务合作|招商|诚招|带货", text):
        return "promo"
    if re.search(r"试用|免费体验\s*\d+\s*天|首月免费|体验期|试用期|7\s*天免费|30\s*天免费|free\s+trial", text, re.I):
        return "trial"
    if re.search(r"回帖|盖楼|转发|关注.*领取|邀请|拉新|实名|绑卡|下单|首单|充值|发帖|评论.*领取|签到.*领|分享.*得", text):
        return "conditional"
    return "free"


# codes.ts —— 可直接使用的凭据
CODE_EXPLICIT = re.compile(r"(?:邀请码|兑换码|激活码|优惠码|注册码|礼品码|口令|code|invite\s*code)[\s:：是]{0,4}([A-Za-z0-9][A-Za-z0-9_\-]{3,39})", re.I)
CODE_DASHED = re.compile(r"\b([A-Z0-9]{4}(?:-[A-Z0-9]{4}){2,5})\b")
CODE_LONG = re.compile(r"\b([A-Z0-9]{10,40})\b")
CODE_STOP = {"FREE", "WINNER", "HTTP", "HTTPS", "HTML", "NULL", "TRUE", "FALSE", "LOGIN", "REGISTER",
             "STEAM", "EPIC", "GAMES", "GIVEAWAY", "BONUS", "COUPON", "WELCOME", "SUPPORT", "ACCOUNT",
             "DOWNLOAD", "PASSWORD", "USERNAME", "VERIFY", "PLEASE", "THANKS", "UPDATE", "VERSION",
             "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
             "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER", "PUSH", "MAIN", "README"}


def extract_codes(text, limit=6):
    out = []
    for rx in (CODE_EXPLICIT, CODE_DASHED, CODE_LONG):
        for m in rx.finditer(text):
            c = m.group(1).strip().rstrip(".,;:)]}\"'")
            if not (4 <= len(c) <= 40) or c.upper() in CODE_STOP:
                continue
            if rx is CODE_LONG and not (len(c) >= 12 and re.search(r"\\d", c)):
                continue
            if re.match(r"^(https?|www|linux|topic|app|store|game)", c, re.I) or not re.search(r"[A-Za-z]", c):
                continue
            if c not in out:
                out.append(c)
    return out[:limit]


# noise.ts 的信号词
DEAL_HINT = re.compile(r"免费|领取|报名领|领积分|领额度|赠送|白嫖|白送|白给|零元|0\.01|试用|体验金|兑换|激活码"
                       r"|注册送|限时|开放注册|额度|代金券|算力券|抵扣券|学生包|公测|内测|礼包|优惠券|包邮"
                       r"|:free\b|giveaway|coupon|free|credits|tokens", re.I)
PROMO_HINT = re.compile(r"黑五|black\s*friday|cyber\s*monday|双十一|双11|618|周年庆|特价|特惠|促销|折扣|史低"
                        r"|最低价|优惠码|promo\s*code|年付|折上折|%off|clearance|flash\s*sale", re.I)
OPENSOURCE_HINT = re.compile(r"开源|open\s*source|github\.com|gitlab\.com|self-?host(?:ed)?|自托管|自建服务"
                             r"|mit\s*协议|apache\s*协议|gpl|开源项目|开源工具", re.I)
URGENT = re.compile(r"先到先得|手慢无|名额有限|限量\s*\d|还剩\s*\d|仅剩|库存告急|cdk|cdkey|兑换码|激活码|邀请码"
                    r"|免费领|白嫖|送码|限时免费|限免", re.I)
PENALTY_DRAIN = re.compile(r"加微|私信|评论区|扣\s*1|vx[:：]|微信[:：]|扫码进群", re.I)

# 兴趣标签（参与打分，也给二手审 agent 做提示；按需自己改）
KW = {
    "AI":   ["ai", "llm", "gpt", "claude", "gemini", "大模型", "模型", "token", "额度", "openrouter",
             "推理", "agent", "mcp", "embedding", "公益站", "算力", "生图", "语音"],
    "开发": ["docker", "nas", "unraid", "vps", "服务器", "域名", "cloudflare", "自建", "开源", "github",
             "对象存储", "cdn", "部署", "数据库", "self-host", "自托管"],
    "软件": ["限免", "正版", "激活", "license", "终身", "免费下载", "mac", "windows", "ios", "安卓",
             "工具", "插件", "脚本", "黑五", "giveaway"],
    "硬件": ["硬盘", "ssd", "固态", "内存", "显卡", "迷你主机", "软路由", "群晖", "显示器", "机械键盘"],
    "家庭": ["亲子", "儿童", "少儿", "博物馆", "科技馆", "图书馆", "夏令营", "研学"],
    "素材": ["字体", "图库", "素材", "音效", "bgm", "免费商用", "可商用", "icon", "模板", "课件",
             "教程", "课程", "电子书", "古籍"],
}

# 源可信度（score.ts 的 trust 维，上游按历史留存率算，这里给静态先验）
TRUST = {
    "linux.do福利": 92, "linux.do资源": 80, "nodeseek": 85, "nodeloc": 78, "v2ex免费": 88, "v2ex优惠": 82,
    "appinn": 90, "appinn发现": 85, "sspai": 78, "openrouter": 95, "github清单": 95,
    "giveawayoftheday": 88, "tickcoupon": 85, "sharewareonsale": 82, "ghxi": 70, "yxssp": 68,
    "epic": 100, "itch": 80, "reddit喜加一": 85, "tg": 70, "52pojie": 72,
}

# ============ 采集层 ============

class RateLimited(Exception):
    pass


def http_get(url, timeout=25, simple_ua=False, extra_headers=None):
    headers = {"User-Agent": "Mozilla/5.0 Chrome/126.0"} if simple_ua else dict(UA)
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return r.status, raw
    except urllib.error.HTTPError as e:
        if e.code == 429:            # 上游口径：429 是限流不是拦截，本轮跳过，不回落过盾
            raise RateLimited("HTTP 429")
        return e.code, b""


def decode(raw):
    head = raw[:220].decode("ascii", "ignore").lower()
    enc = "utf-8"
    m = re.search(r'encoding="([\w-]+)"', head)
    if m:
        enc = m.group(1)
    try:
        return raw.decode(enc, "ignore")
    except LookupError:
        return raw.decode("gb18030", "ignore")


# ---- FlareSolverr：session 复用 cookie（上游 flaresolverr.ts 同款策略）----
_FLARE_SESS = "radar-lite"
_flare_up = False


def flare_post(payload, timeout=240):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(FLARE, data=body, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def flare_ensure():
    global _flare_up
    if _flare_up:
        return
    try:
        flare_post({"cmd": "sessions.create", "session": _FLARE_SESS})
    except Exception:
        pass
    _flare_up = True


def flare_release():
    global _flare_up
    if not _flare_up:
        return
    try:
        flare_post({"cmd": "sessions.destroy", "session": _FLARE_SESS})
    except Exception:
        pass
    _flare_up = False


def flare_get(url):
    flare_ensure()
    r = flare_post({"cmd": "request.get", "url": url, "session": _FLARE_SESS, "maxTimeout": 120000})
    if r.get("status") != "ok":
        raise RuntimeError(r.get("message", "flare failed"))
    sol = r["solution"]
    if sol.get("status") == 429:
        raise RateLimited("flare 429")
    if sol.get("status") != 200:
        raise RuntimeError("flare HTTP %s" % sol.get("status"))
    body = sol.get("response", "")
    # 浏览器会把 RSS/JSON 包进 <pre> 并转义实体，剥壳后还原
    m = re.search(r"<pre[^>]*>([\s\S]*?)</pre>", body, re.I)
    if m:
        body = html.unescape(m.group(1))
    elif body.lstrip().startswith("<!DOCTYPE") or body.lstrip().startswith("<html"):
        # 人机校验页，不是目标内容
        raise RuntimeError("拿到人机校验页")
    return body


def rss_items(xml_text):
    """通用 RSS/Atom 解析，兼容 gbk 声明、CDATA、media:* 与 Atom link 数组"""
    out = []
    xml_text = re.sub(r"^\s*<\?xml[^>]*\?>", "", xml_text, count=1)
    xml_text = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-f]+);)", "&amp;", xml_text)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for node in root.iter():
        if node.tag.split("}")[-1].lower() not in ("item", "entry"):
            continue
        d, cats, ts = {}, [], ""
        for ch in node:
            k = ch.tag.split("}")[-1].lower()
            if k == "category":
                cats.append((ch.get("term") or "".join(ch.itertext()) or "").strip().lower())
            if k == "link":
                href = ch.get("href")
                if href and (ch.get("rel") in (None, "alternate")):
                    d.setdefault("link", href)
                elif ch.text:
                    d.setdefault("link", ch.text.strip())
            elif k in ("title", "summary", "description", "content", "encoded"):
                d.setdefault(k, "".join(ch.itertext()).strip())
            elif k in ("pubdate", "published", "updated", "date"):
                ts = ts or (ch.text or "").strip()
        title = re.sub(r"\s+", " ", html.unescape(d.get("title", ""))).strip()
        link = (d.get("link") or "").strip()
        desc = html.unescape(d.get("description") or d.get("summary") or d.get("content") or "")
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip()[:400]
        if title:
            out.append({"title": title, "url": link, "ts": ts, "extra": desc, "cats": cats})
    return out


# ---- 源清单：照 SEEDS 裁剪 ----
RSS_FEEDS = [
    # AI / 开发者 / 中文福利社区
    ("nodeseek", "NodeSeek", "https://rss.nodeseek.com/", 30, {"includeCategories": ["info", "promotion", "trade"]}),
    ("appinn发现", "小众软件发现频道", "https://meta.appinn.net/c/faxian/10.rss", 25, {}),
    ("appinn", "小众软件", "https://www.appinn.com/feed/", 12, {}),
    ("sspai", "少数派", "https://sspai.com/feed", 10, {}),
    ("smzdm", "什么值得买", "https://www.smzdm.com/rss/", 10, {}),
    ("qbitai", "量子位", "https://www.qbitai.com/feed", 10, {}),
    ("52pojie", "吾爱破解", "https://www.52pojie.cn/forum.php?mod=rss", 20, {"simpleUA": True}),
    # 正版软件限免
    ("giveawayoftheday", "GiveawayOfTheDay", "https://www.giveawayoftheday.com/feed/", 15, {}),
    ("tickcoupon", "TickCoupon 终身限免", "https://giveaway.tickcoupon.com/feed/", 10, {}),
    ("sharewareonsale", "SharewareOnSale", "https://sharewareonsale.com/feed", 15,
     {"titleKeywords": ["100% discount", "free", "giveaway"]}),
    ("ghxi", "果核剥壳", "https://www.ghxi.com/feed", 12, {}),
    ("yxssp", "异星软件空间", "https://www.yxssp.com/feed", 12, {}),
    # 游戏限免（孩子/自己都能玩）
    ("itch", "itch.io 100% off", "https://itch.io/games/on-sale.xml", 20, {"only100Off": True}),
    ("reddit喜加一", "Reddit FreeGameFindings", "https://www.reddit.com/r/FreeGameFindings/hot.rss", 25, {}),
    ("keylol", "其乐 Keylol", "https://keylol.com/forum.php?mod=rss", 15, {"simpleUA": True}),
]

GITHUB_REPOS = [
    ("ripienaar/free-for-dev", "免费服务", ["开发", "AI"]),
    ("awesome-selfhosted/awesome-selfhosted", "自托管项目", ["开发"]),
    ("public-apis/public-apis", "免费公开 API", ["开发", "AI"]),
]

TELEGRAM = ["zaihuapd", "v2ex_channel"]

SECTION_RULES = [
    (re.compile(r"generative ai|apis, data, and ml|ai|llm|chatbot|image|video|audio|writing|agent", re.I), "ai"),
    (re.compile(r"domain|dns|web hosting", re.I), "domain"),
    (re.compile(r"education", re.I), "edu"),
    (re.compile(r"source code|artifact|code generation|code quality|ci and cd|testing|issue|low-code"
                r"|forms|cms|translation|monitoring|log management|messaging|security|authentication"
                r"|tunneling|font|email|search|design|analytics", re.I), "software"),
    (re.compile(r"cloud|paas|baas|iaas|cdn|storage|managed data", re.I), "cloud"),
]


def tags_of(text):
    low = text.lower()
    return [c for c, kws in KW.items() if any(k in low for k in kws)]


def parse_ts(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})", s)
    if m:
        return datetime(*[int(x) for x in m.groups()], tzinfo=timezone.utc)
    return None


def key(src, s):
    return hashlib.sha1((src + "|" + s).encode()).hexdigest()[:16]


def _obtain_of(text):
    """先按上游六级判定；判成 free 但正文没有任何福利/促销信号的，是资讯或工具，不是白嫖。"""
    o = guess_obtain(text)
    if o == "free" and not (DEAL_HINT.search(text) or PROMO_HINT.search(text)):
        return "info"
    return o


def score_item(it):
    """移植 score.ts 的五维加权"""
    text = it["title"] + " " + it["extra"]
    obtain = OBTAIN_SCORE.get(it["obtain"], 55)
    # quality：没有 AI 二审时用信号密度当代理
    q = 30
    if DEAL_HINT.search(text):
        q += 30
    if PROMO_HINT.search(text):
        q += 15
    if OPENSOURCE_HINT.search(text):
        q += 15
    if re.search(r"\d", text):
        q += 10
    if it["tags"]:
        q += 10
    q = min(q, 100)
    fresh = 50
    if it.get("dt"):
        age_h = max(0.0, (datetime.now(timezone.utc) - it["dt"]).total_seconds() / 3600)
        fresh = max(0, 100 - age_h / (14 * 24) * 100)
    trust = TRUST.get(it["src"], 65)
    proof = 0
    if it["codes"]:
        proof += 45
    if re.search(r"限量|限时|仅剩|名额|截止|有效至", text):
        proof += 30
    if re.search(r"\d+\s*(份|个|名|位|台|天|元|刀|token|积分|额度)", text, re.I):
        proof += 25
    proof = min(proof, 100)
    total = 0.3 * obtain + 0.35 * q + 0.15 * fresh + 0.1 * trust + 0.1 * proof
    if PENALTY_DRAIN.search(text):
        total *= 0.6
    if len(it["title"]) < 6:
        total *= 0.72
    return round(total, 1)


OBTAIN_SCORE = {"free": 100, "conditional": 72, "info": 40, "trial": 35, "lottery": 22, "promo": 6, "paid": 30}


def main():
    seen = json.load(open(SEEN)) if os.path.exists(SEEN) else {}
    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    first_run = not base
    items, meta, errors = [], {}, []

    STAT = {}


    def stat(src, key):
        STAT.setdefault(src, {"raw": 0, "noise": 0, "dup": 0, "kept": 0})[key] += 1

    def add(src, title, url, ts="", extra="", tags=None, fixed_obtain=None):
        if not title or not url:
            return None
        stat(src, "raw")
        if NOISE_TITLE.search(title) or NOISE_EXTRA.search(title + " " + extra):
            stat(src, "noise")
            return None
        if src.startswith(PY_FREE) or src in COMMUNITY:
            if CHAT_NOISE.search(title) or title.rstrip().endswith(("？", "?")):
                stat(src, "noise")
                return None
        text = title + " " + extra
        items.append({
            "id": key(src, url), "src": src, "title": title.strip(), "url": url.strip(),
            "ts": ts, "extra": extra.strip()[:300],
            "tags": tags if tags is not None else tags_of(text),
            "obtain": fixed_obtain or _obtain_of(text),
            "codes": extract_codes(text),
            "dt": parse_ts(ts),
        })

    # ---------- 1) linux.do（RSS + FlareSolverr，429 跳过） ----------
    for src, slug, cid, cap, need in (
            ("linux.do福利", "welfare", 36, 25, None),
            ("linux.do资源", "resource", 14, 20, ["电子书", "古籍", "课程", "教材", "字体", "软件", "工具",
                                                 "模板", "AI", "教程", "课件", "开源"])):
        url = "https://linux.do/c/%s/%d.rss" % (slug, cid)
        try:
            body = None
            try:
                st, raw = http_get(url)
                if st == 200 and b"<rss" in raw[:2000]:
                    body = decode(raw)
                    meta[src] = "直连"
            except RateLimited:
                body = None
            if body is None:
                body = flare_get(url)
                meta[src] = "FlareSolverr"
            its = rss_items(body)[:cap]
            meta[src] = "%s · %d 条" % (meta.get(src, ""), len(its))
            for it in its:
                if need and not any(k.lower() in it["title"].lower() for k in need):
                    continue
                add(src, it["title"], it["url"], it["ts"], it["extra"])
        except Exception as e:
            meta[src] = "ERR %s" % str(e)[:70]
            errors.append(src)

    # ---------- 2) 通用 RSS 源 ----------
    for src, name, url, cap, opt in RSS_FEEDS:
        try:
            st, raw = http_get(url, simple_ua=opt.get("simpleUA", False))
            if st != 200:
                raise RuntimeError("HTTP %s" % st)
            its = rss_items(decode(raw))
            keep = []
            for it in its:
                if opt.get("includeCategories") and not (set(it["cats"]) & set(opt["includeCategories"])):
                    continue
                if opt.get("titleKeywords") and not any(k.lower() in it["title"].lower()
                                                        for k in opt["titleKeywords"]):
                    continue
                if opt.get("only100Off"):
                    blob = (it["title"] + it["extra"]).lower()
                    if not re.search(r"100%\s*off|\$0(\.00)?\b", blob):
                        continue
                keep.append(it)
            meta[src] = "%d/%d 条" % (len(keep[:cap]), len(its))
            for it in keep[:cap]:
                add(src, it["title"], it["url"], it["ts"], it["extra"])
        except RateLimited:
            meta[src] = "429 限流，本轮跳过"
        except Exception as e:
            meta[src] = "ERR %s" % str(e)[:70]
            errors.append(src)

    # ---------- 3) Epic 本周限免 ----------
    try:
        st, raw = http_get("https://store-site-backend-static.ak.epicgames.com/"
                          "freeGamesPromotions?locale=zh-CN&country=CN&allowCountries=CN")
        e = json.loads(decode(raw))
        promos = [x for x in e["data"]["Catalog"]["searchStore"]["elements"] if x.get("promotions")]
        meta["epic"] = len(promos)
        for x in promos:
            price = ((x.get("price") or {}).get("totalPrice") or {}).get("fmtPrice", {}).get("originalPrice", "")
            slug = ""
            for m in (x.get("offerMappings") or []) + (x.get("catalogNs", {}).get("mappings") or []):
                slug = slug or m.get("pageSlug") or ""
            url = "https://store.epicgames.com/zh-CN/p/" + slug if slug else "https://store.epicgames.com/zh-CN/free-games"
            add("epic", "Epic 限免：%s（原价 %s）" % (x.get("title", ""), price), url, "",
                "本周限免，领了永久保留", tags=["游戏"], fixed_obtain="free")
    except Exception as e:
        meta["epic"] = "ERR %s" % str(e)[:70]
        errors.append("epic")

    # ---------- 4) OpenRouter：14 天内新增且价格为 0 ----------
    try:
        st, raw = http_get("https://openrouter.ai/api/v1/models", timeout=45)
        d = json.loads(decode(raw))
        cutoff = time.time() - 14 * 86400
        rows = []
        for m in d.get("data", []):
            mid = m.get("id", "")
            pr = m.get("pricing") or {}
            is_free = mid.endswith(":free") or (float(pr.get("prompt", 1) or 1) == 0.0 and
                                                float(pr.get("completion", 1) or 1) == 0.0)
            if not is_free:
                continue
            created = m.get("created") or 0
            rows.append((mid, created, m))
        cur = {key("openrouter", r[0]) for r in rows}
        known = set(base.get("openrouter", []))
        base["openrouter"] = sorted(cur)
        recent = [r for r in rows if not r[1] or r[1] >= cutoff]
        meta["openrouter"] = "%d 个免费（14 天内 %d，新增 %d）" % (len(rows), len(recent), len(cur - known))
        if not first_run:
            for mid, created, m in recent:
                if key("openrouter", mid) in known:
                    continue
                add("openrouter", "OpenRouter 新免费模型：%s" % (m.get("name") or mid),
                    "https://openrouter.ai/" + mid,
                    datetime.fromtimestamp(created, timezone.utc).isoformat() if created else "",
                    "%sK 上下文 · %s" % (round((m.get("context_length") or 0) / 1000),
                                        (m.get("description") or "")[:150]),
                    tags=["AI"], fixed_obtain="free")
    except Exception as e:
        meta["openrouter"] = "ERR %s" % str(e)[:70]
        errors.append("openrouter")

    # ---------- 5) GitHub 清单（API + 分节映射分类） ----------
    for repo, label, tg in GITHUB_REPOS:
        src = "github清单"
        try:
            st, raw = http_get("https://api.github.com/repos/%s/contents/README.md" % repo, timeout=40,
                               extra_headers={"Accept": "application/vnd.github.raw"})
            txt = decode(raw)
            section, rows = "", []
            for line in txt.splitlines():
                h = re.match(r"^#{2,3}\s+(.+)$", line)
                if h:
                    section = h.group(1).strip()
                    continue
                m = re.match(r"^\s*[-*+]\s+\[(.+?)\]\((https?://[^)\s]+)\)\s*[--—:]?\s*(.*)$", line) \
                    or re.match(r"^\|\s*\[(.+?)\]\((https?://[^)\s]+)\)\s*\|\s*([^|]*)", line)
                if not m:
                    continue
                rows.append((m.group(2).strip(), m.group(1).strip(), m.group(3).strip(), section))
            cur = {key(src + ":" + repo, r[0]) for r in rows}
            known = set(base.get(src + ":" + repo, []))
            base[src + ":" + repo] = sorted(cur)
            meta["github:" + repo.split("/")[0]] = "%d 条（新增 %d）" % (len(cur), len(cur - known))
            if first_run:
                continue
            for url, title, desc, section in rows:
                if key(src + ":" + repo, url) in known:
                    continue
                cat = "cloud"
                for rx, c in SECTION_RULES:
                    if rx.search(section):
                        cat = c
                        break
                add(src, "%s：%s" % (label, title), url, "", (desc + " · " + section).strip(" ·"),
                    tags=tg, fixed_obtain="free")
        except Exception as e:
            meta["github:" + repo.split("/")[0]] = "ERR %s" % str(e)[:60]

    # ---------- 6) Telegram 频道（t.me/s 直连解析） ----------
    for ch in TELEGRAM:
        try:
            st, raw = http_get("https://t.me/s/" + ch, timeout=20)
            if st != 200:
                raise RuntimeError("HTTP %s" % st)
            page = decode(raw)
            n = 0
            for block in page.split('class="tgme_widget_message_wrap')[1:]:
                idm = re.search(r'data-post="([^"/]+)/(\d+)"', block)
                txt = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>', block)
                tm = re.search(r'<time[^>]*datetime="([^"]+)"', block)
                if not (idm and txt):
                    continue
                body = re.sub(r"<br\s*/?>", "\n", txt.group(1))
                body = re.sub(r"<[^>]+>", " ", body)
                body = re.sub(r"\s+", " ", html.unescape(body)).strip()
                if not body:
                    continue
                first = body.split("\n")[0][:180]
                add("tg", first, "https://t.me/s/%s/%s" % (ch, idm.group(2)),
                    tm.group(1) if tm else "", body[:300])
                n += 1
            meta["tg:" + ch] = n
        except Exception as e:
            meta["tg:" + ch] = "ERR %s" % str(e)[:60]

    flare_release()

    # ---------- 去重 + 打分 ----------
    fresh, ids, titles = [], set(), {}
    for it in items:
        if it["id"] in seen or it["id"] in ids:
            continue
        ids.add(it["id"])
        stat(it["src"], "kept")
        it["score"] = score_item(it)
        norm = re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", it["title"].lower())[:40]
        if norm and norm in titles:          # 同一条内容被多源转发，只留分高的
            prev = titles[norm]
            if it["score"] > prev["score"]:
                fresh[fresh.index(prev)] = it
                titles[norm] = it
            continue
        titles[norm] = it
        fresh.append(it)
    fresh.sort(key=lambda x: -x["score"])
    capped, per = [], {}
    for it in fresh:
        per[it["src"]] = per.get(it["src"], 0) + 1
        if per[it["src"]] <= (16 if it["src"].startswith("linux.do") else 12):
            capped.append(it)
    fresh = capped[:CAP_TOTAL]

    now = int(time.time())
    for it in items:
        seen[it["id"]] = now
    json.dump({k: v for k, v in seen.items() if v > now - 45 * 86400}, open(SEEN, "w"))
    json.dump(base, open(BASELINE, "w"))

    for it in fresh:
        it.pop("dt", None)
    json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "meta": meta, "errors": errors,
               "count": len(fresh), "items": fresh}, open(OUT, "w"), ensure_ascii=False, indent=1)

    print("源状态：", json.dumps(meta, ensure_ascii=False))
    if "--stats" in sys.argv:
        print("%-16s %6s %6s %6s" % ("源", "抓到", "噪音砍", "成候选"))
        for src, v in sorted(STAT.items(), key=lambda x: -x[1]["raw"]):
            print("%-16s %6d %6d %6d" % (src, v["raw"], v["noise"], v["kept"]))
        print("合计：抓到 %d，噪音砍掉 %d，去重后进候选 %d，最终输出 %d" % (
            sum(v["raw"] for v in STAT.values()), sum(v["noise"] for v in STAT.values()),
            sum(v["kept"] for v in STAT.values()), len(fresh)))
    print("新候选 %d 条 → %s%s" % (len(fresh), OUT,
          "（首次运行：已建基线，明日开始产出）" if first_run else ""))
    if "--show" in sys.argv:
        for it in fresh:
            print("[%5.1f|%s|%s] %s | %s%s" % (it["score"], it["src"], it["obtain"],
                                               it["title"][:64], it["url"][:52],
                                               (" 码:" + ",".join(it["codes"])) if it["codes"] else ""))


if __name__ == "__main__":
    main()
