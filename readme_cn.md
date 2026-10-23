# DJMAX 成绩图生成器

本库使用 [V-ARCHIVE](https://v-archive.net/) 作为数据来源。

> **仓库形态**：本仓库现在只构建 Windows 单文件 exe（`app.py` + `build_exe.ps1`，产物在
> `dist-exe/`）。早期的脚本入口已移除，全部功能收进 exe 菜单；打包与使用见
> [README-EXE.md](README-EXE.md)。下面的 `generate.*` 库 API 仍然可用。

## Top 100 生成器

- `generate.generate_bests(username, bmode)`
    - 生成用户的 Top 100 成绩图。
    - `username`:用户的 V-ARCHIVE 账号用户名。
    - `bmode`:按键模式,可为 4、5、6、8 之一。

- `generate.generate_bests_theoretical(bmode)`
    - 生成当前版本的理论值(最大 DJ POWER)Top 100 成绩图。
    - `bmode`:按键模式,可为 4、5、6、8 之一。

## 成绩总览(Scorelist)生成器

- `generate.generate_scorelist(username, bmode, is_sc, level)`
    - 生成用户某个等级的成绩总览。
    - `username`:用户的 V-ARCHIVE 账号用户名。
    - `bmode`:按键模式,可为 4、5、6、8 之一。
    - `is_sc`:布尔值,表示 `level` 是否为 SC 等级。
    - `level`:要生成的等级,1-15。

- `generate.generate_scorelist_new(username, bmode, diff)`
    - 生成用户当前版本新曲的成绩总览。
    - `username`:用户的 V-ARCHIVE 账号用户名。
    - `bmode`:按键模式,可为 4、5、6、8 之一。
    - `diff`:难度,可为 NM、HD、MX、SC 之一。

- `generate.generate_scorelist_pack(username, bmode, diff, pack)`
    - 生成用户某个曲包的成绩总览。
    - `username`:用户的 V-ARCHIVE 账号用户名。
    - `bmode`:按键模式,可为 4、5、6、8 之一。
    - `diff`:难度,可为 NM、HD、MX、SC 之一。
    - `pack`:要生成的曲包,对应 V-ARCHIVE 的 `dlcCode`。
    - **注意:** 传入前请自行校验 `pack` 参数,完整的 DLC 列表可通过 `api_handler.fetch_dlc_list()` 获取。

- `generate.generate_scorelist_pp(username, bmode)`
    - 生成用户的 Perfect Play(PU 全连)成绩总览。
    - `username`:用户的 V-ARCHIVE 账号用户名。
    - `bmode`:按键模式,可为 4、5、6、8 之一。

## 本地记录库生成器

以下生成器产出与在线版相同的图,但成绩读取自 `records/` 下的本地记录库,而不是 V-ARCHIVE API,
因此重复运行不消耗任何请求。记录库分两层:`full_varecord.json` 保存原始 API 响应(每个按键
模式一条),`records_db.parquet` 是由它构建的合并、可直接渲染的形式 —— 手工维护的标签表
(`analyzer/djmax_songs_tags.csv`)在构建时就已经合并进去、`tags_score` 也已经算好,所以读取
它就是一次普通的 parquet 读取(`db_meta.json` 记录它属于哪个账号、由哪一版 schema 构建)。
`data_fetcher.ensure_db_available(username)` —— 每个本地生成器都会调用 —— 是唯一
联网步骤:记录库已能服务 `username` 时它什么都不做;只有歌曲库或标签表更新时它离线重建
parquet;否则才下载全部四个模式。读取与转换本身(`data_converter.load_records_db`、`fetch_bests`、
`fetch_scorelist*`)是纯本地文件操作,并且会拒绝属于其他账号的记录库,而不是默默使用它。
歌曲库、DLC 列表和 DJ POWER 换算系数来自缓存(`djmax_bests/cache`),`api_handler.remove_cache()`
随时可能清空它 —— 记录库在缓存之外,不受清空影响。

- `generate.generate_bests_local(username, bmode)`
- `generate.generate_scorelist_local(username, bmode, is_sc, level)`
- `generate.generate_scorelist_new_local(username, bmode, diff)`
- `generate.generate_scorelist_pack_local(username, bmode, diff, pack)`
- `generate.generate_scorelist_pp_local(username, bmode)`

参数与对应的在线版相同。

首次出图前,先在 exe 菜单 `[1] 刷新成绩` 填充一次记录库 —— 它使用 `data/account.txt` 里的
账号(首次运行会询问)。`records/` **不在仓库里**:它保存的是一个账号的成绩,所以每个副本都要
用自己的账号重新生成(目录在首次写入时创建)。`generate.generate_bests_theoretical` 没有本地
变体:它只需要歌曲库,`api_handler` 会从缓存的 `songs.json` 读取。

## 入口与菜单

仓库根目录只有 `app.py`（exe 入口）和构建脚本；早期的 `refresh.py`、`all.py`、`summary.py`、
`runrun.py`、`target.py`、`inspect_*.py`、`prefetch_covers.py` 已移除，对应功能全部收进
exe 菜单：

| 菜单 | 功能 | 备注 |
|---|---|---|
| [1] | 刷新成绩 | 成绩每次刷新；曲库/DLC/换算系数 7 天过期；首次下载曲绘 |
| [2] | 全部图片 | 4 模式 × 15 级 × SC/非SC + 新曲 + PP + 理论值 |
| [3] | 总结图 | `settings.ini` 的 `[summary]` |
| [4] | 游玩历史 | 可输入日期，默认最近一天 |
| [5] | 目标 DJPower | `[target]` 的 `floor_cap` / `balance_rounds` |
| [6] | 单图生成 | Top 100 / 等级 / 新曲 / 曲包 / PP / 标签 / 单曲轨迹 / 理论值 |
| [9] | 查询他人 | 只读内存，输出到 `output/inspect/<账号>/` |

刷新仍然是整体重写：`data_fetcher.fetch_all()` 一次性替换原始层，所以
`full_varecord.json` 只有一个写入者，绝不可能同时保存两个账号的条目。重建会把四个键全部
json 解析，任何一条缺失或为空都会失败 —— 这也是原始层整体替换、而不是逐模式改写的原因。
任何一条不可读、或无法确定所属账号的条目，都会让记录库无法被服务：`records_db.parquet`
拒绝由它重建(且 `db_meta.json` 保持原样)，因此下次本地运行会按自己被请求的账号重新抓取
全部四个模式。

### 游玩历史(`records/history/`)

V-ARCHIVE 只保留每张谱面当前的最好成绩,旧成绩被打破的那一刻就从 API 上消失了。
`analyzer/history.py` 把还能积累的都积累下来,每次刷新都会自动喂给它(`data_fetcher` 在重建
`records_db.parquet` 之前,把新抓取的状态并入历史):

- `play_events.parquet` —— 只追加的游玩事件日志,一次游玩一行。首次刷新把每条当前最好成绩
  按其各自的 `updatedAt`(存档的游玩时间戳)播种进去,所以历史从一开始就有真实深度;之后
  每次刷新把新的原始成绩与上一次快照做 diff,为每张分数上升或新出现的谱面追加一条事件。
  事件只在分数/最大连击变化时触发,所以游戏补丁重算 DJ POWER 不会伪造游玩记录。事件按账号
  键控 —— 切换主账号不会伪造事件。
- `snapshots/` —— 每次内容变化时归档的原始层(gzip,永久保留),事件日志万一损坏可以由它
  重新推导。
  
刷新越频繁,历史越细:两次刷新之间的游玩只会以最终最好成绩的形式幸存,所以玩完一局后记得刷新。
**删除 `records/history/` 会永久丢失所有被打破的旧成绩** —— API 无法重放它们。

读取端(供渲染器消费):

- `history.recent_plays(username, n=100)` —— 跨全部按键模式的最新事件,按时间倒序,每条带
  该谱面之前的最好成绩,以及相对它的分数/DJ POWER 增量。
- `history.chart_progression(username, songid, button, pattern)` —— 一张谱面的完整分数轨迹。
- `history.totals_over_time(username)` —— 每次游玩后该模式的总 DJ POWER,用与模式卡相同的
  top-70/30 + 换算系数公式(以及 10000 上限)从事件重放得出。
- `history.load_play_events(username)` —— 裸事件日志,供其他用途。

菜单 `[9] 查询他人成绩` 为另一个账号渲染同样的图(含跨 4 模式的 Top 100 / 最近 100 局):
成绩只保存在内存,不读也不写本地记录库。单个快照无法得知被打破的成绩,所以这类图只画结果
(没有分数/DJ POWER 增量)。输出:`output/inspect/<username>/`。

读取 API 也会与当前记录库对账:已在 `records/` 但尚未进日志的最好成绩(例如一次被中断的
刷新)仍然会显示,下一次刷新的快照 diff 会彻底补上缺口。如果你手里有更早的原始快照(例如
保存下来的 `full_varecord_<date>.json`),可以把它回填进日志:调用一次
`history.update_history(username, older_texts)` —— 播种会被去重键吸收,所以只补进该快照中
被打破的最好成绩(把 `records/history/snapshots/` 里最新的快照先挪开,调用完再用当前状态跑
一次 `update_history` 即可恢复快照时间线)。

> **注意**：`runrun.py` / `all.py` / `summary.py` / `target.py` 已从仓库移除，对应功能在
> exe 菜单 `[2]` / `[3]` / `[5]` / `[6]`；下面保留这些脚本的行为说明，作为渲染逻辑的参考。

`runrun.py`:单张图的草稿入口。编辑顶部变量(`bmode`、`levels`、`difficult`、`dlc`、
`tag_name`、`tag_level`),然后在 `main()` 里的 `await ...()` 行挑选任务 —— `best()`、
`theoretical()`、`level()`、`new()`、`perfect()`、`pack()` 或 `tag()`。渲染的是主账号
(refresh.py 里的 `username`)。

`tag()` 任务画出某账号对携带给定标签的歌曲的推歌进度,结果写入
`output/tag_<bmode>B/<tag_name>_<tag_level>.png`。参数:

- `username`:要查询的 V-ARCHIVE 账号(主账号,在 refresh.py 中设置)。
- `bmode`:按键模式,4、5、6、8 之一。
- `tag_name`:要查询的标签 —— `Jack`、`Longjack`、`Stream`(或 `FX`)、`Stair`、`Trill`、
  `Chord`、`Long`、`Side`、`Complex`、`SV`、`DoubleStairs`、`6B Stair`、`6B Basic`、`Read`
  或 `Spike`。
- `tag_level`:标签难度,`1`-`3`(标题中画作 I / II / III)。

`all.py`:一次性渲染一个账号的全部图(4 种按键模式 × 1-15 级 × SC 与非 SC,外加新曲、
Perfect Play、Top 100 与理论值 Top 100)。

`summary.py`:渲染总结(summary)图。

`target.py`:渲染目标 DJ POWER 计划图。它从本地记录库计算某个按键在 `target_total` 总值下的
预测 Top 100 —— 与该账号今天的 Top 100 布局相同,但需要打的谱面被标记出来:尚无成绩的谱面
金色边框 + NEW,需要提升的已有成绩青色边框 + UP。图片旁还可附带 .json 附档,记录计划
算出的一切(达到的总值、该准确率下的天花板、达到目标所需的最低准确率、每张谱面的明细),
包括刻意不画在图上的数字。用法:

```
python target.py                                  # 使用文件顶部设置的值
python target.py --bmode 4 --target 6400 --accuracy 99.5
python target.py --cap 6.0
```

各入口脚本(`runrun.py`、`all.py`、`summary.py`、`target.py`)完全从本地记录库渲染,不因成绩
消耗任何请求 —— 需要更新时先手动 `python refresh.py`。如果记录库所属账号与生成器被请求的
主账号不同,该生成器会一次性抓取全部四个模式(`data_fetcher.ensure_db_available`)并重建记录库,
所以切换主账号的代价要么是一次手动刷新,要么是下次渲染时的一次自动抓取。
由于 `AnalyzeUtil` 读取记录库,构建于其上的一切(`tag()`、目标计划、summary、`level()` /
`pack()` / `pp()` 使用的成绩总览渲染器)都只能看到该记录库持有的模式。记录库始终由刷新流程
整体写入,所以它的四条记录属于同一个账号;残留的他人账号记录库会被拒绝,而不是
被合并。
输出保存在 `output/` 下,目标目录按需创建。

# 构建 exe

见 [README-EXE.md](README-EXE.md):

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Zip
```

产物是 `dist-exe\DJMAX-Bests\`(exe + `settings.ini` + `使用说明.txt` + 空 `data/`)和
`dist-exe\DJMAX-Bests.zip`。分发给别人时不要带 `records/`(个人成绩)。

# 常见问题(Troubleshooting)

- DJ POWER / 段位定数不对、缺少新曲,或其他任何东西看起来过期了
    - 歌曲库(`songs.json`)、DLC 列表和换算系数(`maxpower_*.txt`)在 `refresh.py` 时按文件
      时间检查:缺失或超过 `settings.ini` 的 `[refresh] max_age_days`(默认 7 天)才重新下载,
      成绩则每次都刷新。所以游戏更新后最多一周会自动跟上;想立刻更新,把 `max_age_days` 改成
      `0` 再刷新一次,或删除 `djmax_bests/cache` 里对应的文件。
      `api_handler.remove_cache()` 会清空整个缓存(maxpower、`songs.json`、`dlcs.json`),
      下次运行重新下载。`records/` 里的记录库在缓存之外,清空缓存不影响它;单独删除
      `records/records_db.parquet` 也是安全的 —— 下次运行会离线重建它。

- 图上显示的是另一个账号的数据
    - 记录库属于某一个账号,`db_meta.json` 记录了是哪个。本地生成器被请求另一个账号时会拒绝
      这份记录,并按被请求的账号重新抓取全部四个模式;直接读取会报
      `records_db holds 'SomeoneElse' account, not 'You'`。运行一次 `python refresh.py` 即可为
      你正在使用的账号整体重写记录库(username 在 refresh.py 中设置)。
      `api_handler.remove_cache()` 清空整个缓存。

- `records_db holds no account, not 'You'` / `records_db cannot be rebuilt`
    - `records/records_db.parquet` 是原始成绩的派生、可直接渲染的形式。它缺失、由旧版本代码
      构建、或比其来源(`full_varecord.json`、`songs.json`、`analyzer/djmax_songs_tags.csv`)旧时
      会被离线重建 —— 不涉及任何请求。这个报错说明原始层也缺条目,没有东西可重建:运行一次
      `python refresh.py` 即可。
