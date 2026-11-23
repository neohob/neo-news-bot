# NOTICE · 来源与借用说明

本项目是 **[ZiChuanLan/freebie-radar](https://github.com/ZiChuanLan/freebie-radar)** 的精简移植版（derivative work）。

移植部分的上游版权：`Copyright (c) 2026 ZiChuanLan (https://github.com/ZiChuanLan/freebie-radar)`。
上游以 **MIT License** 发布，原始许可证全文：

```
MIT License

Copyright (c) 2026 ZiChuanLan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 具体借用了什么

| 上游路径 | 借用的内容 | 本项目的对应实现 |
|---|---|---|
| `src/server/collectors/index.ts` | `SEEDS` 源清单：每条源的名称、URL、启停状态、采集器类型、过滤参数 | `collect.py` 的 `RSS_FEEDS` / `LINUXDO` / `TELEGRAM` 常量（只保留 24 路，见 `docs/sources.md`） |
| `src/server/collectors/linuxdo.ts` | 走 Discourse 的 `/c/<slug>/<id>.rss`，被 Cloudflare 拦时切 FlareSolverr | `fetch_linuxdo()` |
| `src/server/collectors/github.ts` | 用 `contents/README.md` + `Accept: application/vnd.github.raw` 拿清单，按二级标题分节 | `fetch_github_list()` |
| `src/server/collectors/openrouter.ts` | 只收 `created` 在 14 天内、且 prompt/completion 价格为 0 的模型 | `fetch_openrouter()` |
| `src/server/collectors/telegram.ts` | 解析 `t.me/s/<channel>` 的 `tgme_widget_message_wrap` 结构 | `fetch_telegram()` |
| `src/server/collectors/rss.ts` | `includeCategories` / `titleKeywords` / `only100Off` 三种过滤语义 | `RSS_FEEDS` 的 `opt` 字典 |
| `src/server/collectors/flaresolverr.ts` | `sessions.create` → 带 session 请求 → `sessions.destroy` 复用 cookie 的用法 | `flare_get()` |
| `src/server/enrich/noise.ts` | `NOISE_TITLE` 干扰标题黑名单 | `NOISE_TITLE` |
| `src/server/enrich/obtain.ts` | `guessObtain` 六级判定及其**判定顺序** | `guess_obtain()` |
| `src/server/enrich/codes.ts` | 三类兑换码抽取正则与停用词 | `extract_codes()` |
| `src/server/enrich/score.ts` | 五维加权公式与乘性惩罚 | `score_item()` |

## 本项目改动

- **语言与运行时**：TypeScript / Node.js（≥22.5）→ 单文件 Python 3（仅标准库）
- **剥离**：React 前端、管理面板、SQLite/PostgreSQL、任务队列、多路由推送、AI 语义定级、27 类分频道目录
- **裁剪源**：111 条 → 24 条，只保留能落地成「今天就能动手」的（舍掉的见 `docs/sources.md`）
- **状态**：上游数据库 → 三个 JSON（`seen.json` 45 天去重、`baseline.json` 清单基线、`candidates.json` 输出）
- **新增**：
  - `CHAT_NOISE`：社区源的闲聊/求助/二手/破解版过滤，以及问句标题过滤（上游只有通用黑名单）
  - `obtain=info` 档：判成 free 但没有任何免费信号的条目，避免资讯/工具冒充白嫖抢榜首
  - `--stats`：每源「抓到 / 噪音砍掉 / 进候选」三列，用来定位「日报内容太少」到底是源不够还是筛选太狠
- **未包含**：需要登录态的采集器（`cookie` / `nga` / `weibo` / `bili` 的 wbi 签名）、`cctv` / `bsky` / `cheapshark` / `gamerpower` / `steam` / `gog` 采集器

上游的 Web UI、AI 定级、推送编排仍然值得一看，如果你想自托管一个站点而不是跑一条命令，请直接使用上游仓库。
