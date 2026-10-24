# DJMAX 成绩图生成器

本库使用 [V-ARCHIVE](https://v-archive.net/) 作为数据来源，把 DJMAX RESPECT V 的成绩渲染成图片。

> Windows 单文件 exe 的安装、菜单和配置说明见 [README-EXE.md](README-EXE.md)。
> 本文介绍各个生图模块的调用方式。英文版见 [README.md](README.md)。

## 环境

- Python 3.10+（仓库的 `.venv` 使用 CPython 3.14.6）；
- 依赖见 `requirements.txt`：

```powershell
uv venv .venv --python 3.14
uv pip install -r requirements.txt
```

所有生成函数都是 `async`，返回 `PIL.Image.Image`，由调用方决定保存路径。

## 字体

- 图里的主体字体（`Respect_bd.ttf` / `Respect_rg.ttf` / `Respect_lt.ttf`）随仓库打包，不用装；
- 只有技能雷达 `tools.plot_tags_score_radar()` 单独指定了 **Sarasa Mono HC SemiBold**，
  这个字体**不随仓库 / exe 分发**，需要自己装：
  - 打开 [be5invis/Sarasa-Gothic](https://github.com/be5invis/Sarasa-Gothic) 的 Release，
    下载 `SarasaMonoHC-TTF-<版本>.7z`（当前版本是 `SarasaMonoHC-TTF-1.0.42.7z`，约 64 MB）；
  - 解压后右键 `SarasaMonoHC-SemiBold.ttf` → “安装”（或“为所有用户安装”），重启程序；
- 用到雷达的图：`summary_generate.generate_summary()` 的总结图、以及
  `song_history_generate.generate_song_history()` / `generate_song_history_snapshot()` 的单曲轨迹图；
- matplotlib 里的字族名把字重也算了进去，所以代码里写的是 `Sarasa Mono HC SemiBold`；
- 没装不会报错，但每次渲染都会刷一串 `findfont: Generic family 'sans-serif' not found ...`，
  雷达标签回退到 DejaVu Sans，字宽和换行跟设计稿不一致；
- 装完字体画面没变，就删掉字体缓存再跑：源码是仓库根的 `.matplotlib/`，exe 是 `data/.matplotlib/`。

确认字体是否已注册（能列出 `Sarasa Mono HC SemiBold` 就说明装好了）：

```powershell
python -c "import matplotlib.font_manager as fm; print([f.name for f in fm.fontManager.ttflist if 'Sarasa Mono HC' in f.name])"
```

---

## Top 100 生成器

- `generate.generate_bests(username, bmode)`
    - 在线生成某个账号的 Top 100 成绩图。
    - `username`：V-ARCHIVE 账号名（区分大小写）。
    - `bmode`：按键模式，4 / 5 / 6 / 8。
    - 直接请求 V-ARCHIVE 的 `djpower` 榜单（70 Basic + 30 New）。

- `generate.generate_bests_theoretical(bmode)`
    - 生成当前版本的理论值（最大 DJ POWER）Top 100。
    - `bmode`：按键模式，4 / 5 / 6 / 8。
    - 只依赖歌曲库 `songs.json`，不需要账号成绩；标题显示 `Max DJPower`。

## 成绩总览（Scorelist）生成器

- `generate.generate_scorelist(username, bmode, is_sc, level)`
    - 生成某个等级的完整成绩总览。
    - `username`：V-ARCHIVE 账号名。
    - `bmode`：按键模式，4 / 5 / 6 / 8。
    - `is_sc`：`True` 表示该等级是 SC 等级。
    - `level`：等级 1–15。

- `generate.generate_scorelist_new(username, bmode, diff)`
    - 生成当前版本新曲的成绩总览。
    - `diff`：`NM` / `HD` / `MX` / `SC`。

- `generate.generate_scorelist_pack(username, bmode, diff, pack)`
    - 生成某个曲包的成绩总览。
    - `pack`：V-ARCHIVE 的 `dlcCode`（如 `DNF`、`VE`、`PLI4`）。
    - 传入前请自行校验 `pack`；完整列表可用 `api_handler.fetch_dlc_list()` 获取。

- `generate.generate_scorelist_pp(username, bmode)`
    - 生成 Perfect Play（100%）成绩总览。
    - `bmode`：按键模式，4 / 5 / 6 / 8。

## 本地记录库生成器

以下函数与上面的在线版产出一致，但成绩读取自本地记录库 `records/records_db.parquet`，
重复运行不消耗任何请求。渲染前会先调用 `data_fetcher.ensure_db_available(username)`：
记录库已能服务该账号时什么都不做；只有歌曲库或标签表更新时离线重建 parquet；否则才下载
全部四个模式。读取端会拒绝属于其他账号的记录库。

- `generate.generate_bests_local(username, bmode)`
- `generate.generate_scorelist_local(username, bmode, is_sc, level)`
- `generate.generate_scorelist_new_local(username, bmode, diff)`
- `generate.generate_scorelist_pack_local(username, bmode, diff, pack)`
- `generate.generate_scorelist_pp_local(username, bmode)`
- `generate.generate_all_local(username)`
    - 一次性渲染全部单图：4 模式 × 15 级 × SC/非 SC、新曲、Perfect Play、Top 100、
      理论值 Top 100，写入 `<项目>/output/`，返回 `None`。
    - 输出命名与 exe 的 `[2] 生成全部图片` 一致。

参数与对应的在线版相同。

记录库分两层：`records/full_varecord.json` 保存四个按键模式的原始 API 响应，
`records/records_db.parquet` 是合并了歌曲库、标签表和 `max_djpower` 的派生层；
`records/db_meta.json` 记录所属账号与构建版本。`records/` 不在仓库里，首次使用需要
`refresh_records(username)` 或 `ensure_db_available(username)` 联网生成。

## 总结图生成器

- `summary_generate.generate_summary(username, nickname=None, photo=None, prefer_button=[4, 5, 6, 8], info='')`
    - 生成 2200px 宽的总结长图和 4 张模式卡。
    - `username`：记录库所属账号（也显示在封面上）。
    - `nickname`：非空时覆盖显示名。
    - `photo`：头像曲绘的 songid；`None` 或越界时随机。
    - `prefer_button`：要高亮的按键模式列表。
    - `info`：签名栏文字。
    - 返回 `(summary, modecards)`，其中 `modecards` 是 `{4: Image, 5: Image, 6: Image, 8: Image}`。
    - 图右侧的技能雷达由 matplotlib 绘制，字体要求见上文“字体”一节（Sarasa Mono HC SemiBold）。

- `tag_scorelist_generate.tag_scorelist(username, bmode, tag, level)`
    - 生成某个标签的推歌进度图（同步函数，返回 `Image`）。
    - `tag`：`Jack`、`Longjack`、`Stream`（或 `FX`）、`Stair`、`Trill`、`Chord`、`Long`、
      `Side`、`Complex`、`SV`、`DoubleStairs`、`6B Stair`、`6B Basic`、`Read`、`Spike`。
    - `level`：标签难度 1–3（标题画作 I / II / III）。

上面两个函数基于 `AnalyzeUtil` 读取本地记录库；查看他人账号时先用
`AnalyzeUtil.use_varecords(...)` 注入其成绩（见“数据层”）。

## 游玩历史生成器

- `history_generate.generate_history(username, recent100=True, date=None, target_date=None)`
    - 从本地游玩事件日志渲染历史图。
    - `recent100=True`：最近 100 局；`False`：`date` 指定的那一天。
    - `date=None` 表示“最近有记录的一天”；也可以传 `datetime.date` 回溯指定日期。
    - `target_date` 传一个列表时，会把实际绘制的那一天追加进去，方便命名输出文件。
    - 每行带该谱面之前的最好成绩和分数 / DJ POWER 增量；模式块带每日总值变化。

- `history_generate.generate_history_snapshot(username, texts, recent100=True)`
    - 从一份 `{bmode: 原始响应文本}` 快照直接渲染（查询他人用，不读本地记录库）。
    - 单个快照无法知道被打破的旧成绩，所以只画结果，没有增量。

读取端（供自定义渲染使用）：

- `history.replay_view(username)` —— 返回 `(events, totals)`：事件行（含该谱面之前的最好成绩与
  增量）和每次游玩后的模式总值，历史图读取的就是它。
- `history.chart_progression(username, songid, button, pattern)` —— 一张谱面的完整成绩轨迹。
- `history.load_play_events(username=None)` —— 裸事件日志。
- `history.update_history(username, texts)` / `history.verify_history()` —— 写入与自检。

## 单曲成绩轨迹生成器

- `song_history_generate.generate_song_history(username, songid, button, pattern)`
    - 渲染一张谱面的完整成绩轨迹（本地记录库）；右上角的雷达同样需要 Sarasa Mono HC SemiBold。
    - `songid`：歌曲 ID；`button`：4 / 5 / 6 / 8；`pattern`：`NM` / `HD` / `MX` / `SC`。

- `song_history_generate.generate_song_history_snapshot(username, texts, songid, button, pattern)`
    - 同上，但数据来自 `{bmode: 原始响应文本}` 快照（查询他人用）。

## 目标 DJPower 生成器

- `target_plan.build_plan(bmode, target_total, accuracy, floor_cap=None, *, username='Max DJPower', analyzer=None, balance=True, balance_rounds=7)`
    - 计算“达到目标总分要打哪些谱面”，返回 `TargetPlan`。
    - `bmode`：按键模式，4 / 5 / 6 / 8。
    - `target_total`：目标总分。
    - `accuracy`：预计准确率（百分比数值，如 `99.2`）。
    - `floor_cap`：可选难度上限（floor 单位，如 `6.0`）；`None` = 不限制。
    - `username`：计划所属账号（写进输出文件名/图内）。
    - `analyzer`：`RecordAnalyzer`；`None` 时自动从记录库读取。
    - `balance` / `balance_rounds`：是否搜索 basic/new 配额比例，以及尝试轮数。
    - 计划包含 `reachable`、`achieved_total`、`current_total`、`min_accuracy`、`tasks`、
      `basic` / `new` 等内容，`plan.describe()` 返回可读摘要。

- `target_generate.generate_target_image(plan)`
    - 把 `TargetPlan` 渲染成 Top 100 布局：金色 `NEW` = 新打，青色 `UP` = 提升；
      顶部画目标、实际达到值、当前值和最低准确率。

## 数据层

- `data_fetcher.ensure_db_available(username)`
    - 让 `records_db.parquet` 能服务 `username`：已可用则零请求；只有歌曲库或标签表变新时
      离线重建；否则下载四个模式并重建。

- `data_fetcher.refresh_records(username)`
    - 强制重新下载四个模式并重建记录库（exe 的 `[1]` 走的就是它）。

- `data_converter.load_records_db()`
    - 读取 `records_db.parquet`，返回带 `tags` / `tags_score` 的 DataFrame；过期会先离线重建。

- `data_analyzer.AnalyzeUtil`
    - `spawn_analyzer(bmode)`：单个按键模式的只读分析器。
    - `spawn_analyzer_full()`：跨四个模式的分析器。
    - `use_varecords({bmode: 原始响应文本})`：注入他人成绩，后续渲染不读本地记录库；
      查询他人结束后应重置（`AnalyzeUtil.merged_df = None` 或重新构造）。

## 示例

```python
import asyncio

from djmax_bests import api_handler, generate
from djmax_bests.generators.summary_generator import summary_generate


async def main():
    # 离线：使用本地记录库（必要时自动刷新）
    bests = await generate.generate_bests_local("YourName", 6)
    bests.save("best_6B.png")

    # 理论值：只需要歌曲库
    theoretical = await generate.generate_bests_theoretical(4)
    theoretical.save("theoretical_4B.png")

    # 总结图
    summary, modecards = summary_generate.generate_summary("YourName", info="steam xxxx")
    summary.save("summary.png")

    await api_handler.aclose()


asyncio.run(main())
```

## 构建

exe 的打包流程见 [README-EXE.md](README-EXE.md) 的“构建”一节。

## 许可

MIT License，见 [LICENSE](LICENSE)。数据与曲绘版权归 DJMAX / NEOWIZ 及 V-ARCHIVE 所有。
