# 源清单与取舍

一共 24 路。每一路都实测过能出条目，且出的条目里「今天就能动手」的占多数。

## 保留的源

| # | 源 | 地址 | 抓法 | 实测条数/天 |
|---|---|---|---|---|
| 1 | linux.do 福利羊毛 | `linux.do/c/36.rss` | Discourse RSS，403 才过盾 | 25 |
| 2 | linux.do 资源荟萃 | `linux.do/c/14.rss` | 同上 | 20 |
| 3 | NodeSeek | `nodeseek.com/rss.xml` | RSS（交易帖占比高，靠噪音规则过滤） | 10~20 |
| 4 | V2EX 免费赠送 | `api/topics/show.json?node_name=free` | JSON API | 5~15 |
| 5 | V2EX 优惠信息 | `...node_name=deals` | JSON API | 5~15 |
| 6 | 小众软件 | `appinn.com/feed/` | RSS | 10 |
| 7 | 小众软件发现频道 | `meta.appinn.net/c/faxian/10.rss` | Discourse RSS | 25 |
| 8 | 少数派 | `sspai.com/feed` | RSS | 10 |
| 9 | 什么值得买 | `smzdm.com/rss/` | RSS（文章流，非好价流） | 10~20 |
| 10 | 量子位 | `qbitai.com/feed` | RSS | 10 |
| 11 | 吾爱破解 | `52pojie.cn` 全站 RSS | RSS，WAF 只放行朴素 UA | 20 |
| 12 | 其乐 Keylol | `keylol.com` 全站 RSS | RSS | 15~20 |
| 13 | GiveawayOfTheDay | `giveawayoftheday.com/feed/` | RSS | 10 |
| 14 | TickCoupon | `giveaway.tickcoupon.com/feed/` | RSS | 5 |
| 15 | SharewareOnSale | `sharewareonsale.com/feed/` | RSS，只留 100% off | 2 |
| 16 | 果核剥壳 | `ghxi.com/feed` | RSS | 10 |
| 17 | 异星软件空间 | `yxssp.com/feed` | RSS | 12~30 |
| 18 | itch.io | `itch.io/games/on-sale.xml` | RSS，只认 `100% Off` / `$0.00` | 11~36 |
| 19 | Reddit FreeGameFindings | `reddit.com/r/FreeGameFindings/hot.rss` | RSS（经常 429/404，允许失败） | 0~25 |
| 20 | Epic 限免 | `store-site-backend-static.ak.epicgames.com` | JSON API | 6~8 |
| 21 | OpenRouter 免费模型 | `openrouter.ai/api/v1/models` | JSON，只看 14 天内新增且价格为 0 | 0~17 |
| 22 | free-for-dev | `github.com/ripienaar/free-for-dev` | raw README + 二级标题分节 | 基线 1391 |
| 23 | awesome-selfhosted | `github.com/awesome-selfhosted/awesome-selfhosted` | 同上 | 基线 1270 |
| 24 | public-apis | `github.com/public-apis/public-apis` | 同上 | 基线 2571 |
| 25 | Telegram 话唠猫 | `t.me/s/zaihuapd` | 公开预览页 HTML | 17 |
| 26 | Telegram V2EX 频道 | `t.me/s/v2ex_channel` | 同上 | 20 |

> 表里 26 行是因为 linux.do / V2EX / Telegram 各算了两个频道，代码里是 24 个 `src` 分组。

## 舍掉的源，以及为什么

| 类别 | 源 | 原因 |
|---|---|---|
| VPS 促销（8 路） | LowEndTalk、老左笔记、VPS 侦探、VPSGO、VPS 嘉讯、搬瓦工中文站等 | 面向「正要买 VPS 的人」，一年用得上一次，放进日报就是每日噪音 |
| 实物样品（7 路） | 各类试用/众测站 | 需美国收货地址，无法落地 |
| 新闻资讯（8 路） | Solidot、IT 之家、Hacker News 等 | 已有单独的资讯日报，重复投递没有增量 |
| 需要登录态（4 路） | NGA 优惠区、微博、知乎、小红书 | 要 Cookie 或持久化浏览器 profile，不适合无头定时任务 |
| 反爬过不去 | DeepFlood | 本机 403，过盾后仍拿不到内容 |
| 信噪比太低 | NodeLoc | 闲聊比例过高，NodeSeek 已覆盖同类内容 |

## 判定一个源要不要留的三条标准

1. **能不能当天动手**：能领、能装、能注册，留下；只是「消息」「行情」的，交给资讯类日报。
2. **失败会不会污染整轮**：允许失败的源（Reddit）必须能把错误写进 `meta` 而不影响其他源。
3. **噪音率是否超过 40%**：超过就该考虑整源舍弃，而不是继续加正则——一个源每天 20 条里 12 条是求助帖，加规则的成本高于收益。
