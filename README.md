# neo-news-bot

把 [ZiChuanLan/freebie-radar](https://github.com/ZiChuanLan/freebie-radar) 的**采集源与判定算法**移植成一个「无界面、无常驻服务、每天跑一次」的命令行情报雷达：抓取 24 路源，过滤噪音，五维打分，输出一份可直接投递的候选清单。

它只做两件事：**抓 + 筛**。抓完写 `candidates.json`，由你自己（或一个 AI agent）压成日报。没有 Web UI、没有数据库、没有队列、没有账号体系，只有 Python 标准库。

```
24 路源 ──► 噪音过滤 ──► 跨源去重 ──► 五维打分 ──► obtain 分级 ──► 邀请码抽取 ──► candidates.json
```

## 为什么是「精简版」

上游是一个完整的自托管聚合站：React 前端、SQLite/PostgreSQL、管理面板、27 类分频道目录、多路由推送、AI 语义定级，内置 111 条源。功能很全，但要的是「每天一条推送」的话，那套运行时是纯负担。

所以这里只搬走两样东西，其余全部留在上游：

- **源清单与抓法**：`src/server/collectors/` 里每种采集器怎么写请求（Discourse RSS、GitHub raw 清单、OpenRouter 免费模型、Telegram 公开预览页、Epic 免费游戏接口……）
- **判定算法**：`src/server/enrich/` 里的五处规则（噪音黑名单、六级获取方式判定、兑换码正则、五维加权、引流话术惩罚）

换来的是：单文件 639 行、零第三方依赖、一次跑完 2 分钟、状态只有三个 JSON。

## 快速开始

```bash
git clone https://github.com/neohob/neo-news-bot.git
cd neo-news-bot

python3 collect.py --show     # 跑一轮，打印候选
python3 collect.py            # 跑一轮，写 candidates.json（供后续加工）
python3 collect.py --stats    # 每源「抓到 / 噪音砍掉 / 进候选」+ 合计，诊断用
```

首次运行会把清单型源（GitHub 的 free-for-dev 等）的当前内容记成基线（`baseline.json`），之后只报增量。`seen.json` 记 45 天内报过的条目，跨天去重。

输出样例（`candidates.json` 里的一条）：

```json
{
  "src": "appinn发现",
  "title": "Krss：单二进制 + SQLite 的自托管 RSS 阅读器，能装插件、接 MCP",
  "url": "https://meta.appinn.net/t/topic/96655",
  "score": 87.4,
  "obtain": "free",
  "codes": [],
  "tags": ["开发", "软件"],
  "extra": ""
}
```

## 可选依赖：FlareSolverr

`linux.do` 有 Cloudflare 反爬，直连 403。想过盾就得起一个 [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)：

```bash
docker run -d --name flaresolverr --restart unless-stopped \
  -p 8191:8191 -e LOG_LEVEL=info --shm-size=1g flaresolverr/flaresolverr:latest
```

然后 `export FLARESOLVERR=http://127.0.0.1:8191/v1`（默认值就是它）。没起也能跑，`linux.do` 那两路会在 `meta` 里显示失败，其余 22 路不受影响。

## 24 路源

| 类别 | 源 | 抓法 |
|---|---|---|
| 社区福利 | linux.do 福利羊毛 `c/36`、资源荟萃 `c/14` | Discourse RSS，403 才过盾，429 直接跳过本轮 |
| 社区交易/讨论 | NodeSeek、V2EX（`free` + `deals`）、其乐 Keylol | RSS / JSON API |
| 软件限免 | 小众软件 + 发现频道、少数派、吾爱破解、果核剥壳、异星软件空间、TickCoupon、GiveawayOfTheDay、SharewareOnSale、itch.io | RSS，各自带 `titleKeywords` / `only100Off` 之类的过滤 |
| 游戏 | Epic 每周限免 | `store-site-backend-static` 的 `freeGamesPromotions` 接口 |
| AI | OpenRouter 免费模型、量子位 | `/api/v1/models`（只取 14 天内新增且价格为 0）、RSS |
| 清单 | `ripienaar/free-for-dev`、`awesome-selfhosted`、`public-apis` | `api.github.com/.../contents/README.md` + `Accept: application/vnd.github.raw`，按二级标题分节 |
| 频道 | Telegram `zaihuapd`、`v2ex_channel` | `t.me/s/<channel>` 公开预览页 HTML 解析 |
| 行情 | 什么值得买 | RSS |

取舍原则写在 [`docs/sources.md`](docs/sources.md)：只要能落地成「今天就能动手」的，不要面向「要买 VPS 的人」的促销站、不要需要美国收货地址的实物样品、不要和已有资讯日报重复的新闻流。

## 算法

**噪音**（`NOISE_TITLE` / `NOISE_EXTRA` / `CHAT_NOISE`）：求助、水帖、二手收售、抽奖、破解版、银行卡话费、影视盗版、餐饮优惠。社区源额外过滤问句标题和「有佬吗 / 求推荐 / 怎么弄」这类闲聊——实测 linux.do 25 条里能砍掉 6~8 条纯聊天。

**获取方式分级**（照抄上游 `obtain.ts`，顺序不能换）：

```
抽奖 lottery → 软广/招商 promo → 试用 trial → 有条件 conditional → 免费 free
```

「免费体验我们的服务」要判 promo 而不是 free，否则软广会顶到榜首。判成 `free` 但正文里没有任何免费/促销信号词的，单独归 `info`（资讯或工具，不是白嫖）。

**五维加权**（照抄上游 `score.ts`）：

```
score = 获取确定性 .30 + 质量 .35 + 时效 .15 + 源可信 .10 + 可验证 .10
引流话术（加微信/扫码进群/评论区扣1）×0.6    标题过短 ×0.72
```

**兑换码抽取**（照抄上游 `codes.ts`）：`邀请码/兑换码/激活码:` 之后的值、`CODE-XXXX` 形态、12 位以上含数字的裸串。要挡住月份词（`Code November`）和 `PUSH/MAIN/README`。

**去重**：跨源标题归一化（去标点、转小写、取前 40 字）后同 key 只留高分。

## 把候选变成日报

`candidates.json` 只是原料。真正决定「读起来像不像一份报纸」的是下游的编版规则，这里给了一份可直接用的版式与 agent 提示词：[`docs/digest-format.md`](docs/digest-format.md)。

实测产出（24 路源，一天）：

```
抓 235 条 → 噪音砍 40 → 跨源去重后 195 → 候选池 110 → 日报 88 条（头条 5 / 专题 1 / 要闻 16 / 快讯 63）
```

日报控制在 8000~10000 字符，Discord 会自动拆成 5~6 条消息。

## 已知限制

- **Reddit 按 IP 限速**，`/r/.../.rss` 经常 429 或 404，脚本会跳过本轮并在 `meta` 里标出来，不阻塞其他源。
- **什么值得买 RSS 拿不到「好价」流**，只有文章流，硬件史低类信息目前是缺口。
- **需要登录态的源没接**：小红书、知乎、NGA 优惠区、微博，都要 Cookie 或持久化浏览器 profile。
- **不走代理就无法访问的源**：不要指望换出口能解 Cloudflare，出口是境外 VPS 也一样 403。
- **不要把它当无监督的准确源**：摘要层是 LLM 写的，额度、截止日、价格这类数字必须回链核实。

## 致谢

本项目的源清单、采集器写法和判定算法全部来自 **[ZiChuanLan/freebie-radar](https://github.com/ZiChuanLan/freebie-radar)**（MIT License）。上游是一个功能完整得多的工作：111 条内置源、12 类采集器、AI 语义定级、Web 管理面板、多路由推送。如果你想要的是一个自托管站点而不是一条命令行，直接去用上游。

具体借用了哪些文件、改了什么，见 [`NOTICE.md`](NOTICE.md)。

## License

MIT。见 [LICENSE](LICENSE)。
