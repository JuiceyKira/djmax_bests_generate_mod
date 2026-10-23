# 单文件 exe 版（免安装，根目录只有 5 项）

`DJMAX-Bests.exe` 里打包了 **CPython 3.14.6、全部依赖和渲染素材**（真实曲绘不打包，只带占位图）。
目标电脑上看不到 Python、没有 `runtime/`、没有 `.py` 文件，双击即用。

```
DJMAX-Bests/
├── DJMAX-Bests.exe      ← 唯一入口（118 MB）
├── settings.ini         ← 总结图 / 目标规划的默认参数（记事本编辑）
├── 使用说明.txt
├── data/                ← 首次运行自动生成
│   ├── account.txt
│   ├── cache/           歌曲库、换算系数
│   ├── covers/          曲绘（exe 只带占位图，首次刷新时下载）
│   └── records/         成绩记录库（刷新后生成）
└── output/              ← 生成的图片（与 data 同级）
```

首次启动只释放一张占位曲绘；真正的封面在第一次 `[1] 刷新成绩` 时下载（约 800 多张、1 分钟），
之后每次刷新只补新曲。这样 exe 里不带 13 MB 曲绘。

## 使用

1. 解压到任意**可写**目录（不要放 `C:\Program Files`）；
2. 双击 `DJMAX-Bests.exe`，首次输入 V-ARCHIVE 账号；
3. 选 `[1] 刷新成绩`（刷新 / 查询他人需要联网，出图完全离线）；
4. 之后 `[2]`～`[9]` 出图，结果在 `output/`。

`[1]` 的更新策略：成绩每次都刷新；`songs.json` / `dlcs.json` / `maxpower_*.txt` 只在
**超过 7 天**时重新下载（`settings.ini` 的 `[refresh] max_age_days` 可改，`0` = 每次都更新）。

## 设置文件 settings.ini

放在 exe 旁边，首次运行前就已生成（打包时预置）；用记事本改完保存即生效，**不需要重启**。

```ini
[summary]
nickname =            ; 显示名，留空 = 用账号名
photo_id = 456        ; 头像曲绘 songid，留空 = 随机
prefer_button = 6,8   ; 高亮的按键模式
info = steam 179448484; 签名栏文字，留空 = 不写

[target]
floor_cap =           ; 难度上限（floor），留空 = 不限制
balance_rounds = 8    ; basic/new 配额平衡轮数

[refresh]
max_age_days = 7      ; 曲库/DLC/换算系数超过 N 天重下，0 = 每次都更新
```

- `[summary]` 对本账号总结图和“查询他人 → 总结图”都生效（查询他人时 `nickname` 会被忽略，
  始终显示对方账号名）；
- `[target]` 的 `floor_cap` 是默认值，菜单里仍可临时输入覆盖（回车 = 用 ini 的值，输入
  `none` = 强制不限制）；`balance_rounds` 只从 ini 读，不再询问。

## 其他细节

- `[4] 游玩历史`：直接回车 = 最近一天；输入 `20261012` 这样的日期 = 指定那一天（格式错误会
  重新询问）。
- `[9] 查询他人 → 总结图 / 最近 100 局` 不再询问按键模式（这两张图本来就跨 4 个模式）。

菜单和脚本版的完全一致：刷新、全量出图、总结、游玩历史、目标 DJPower、单图生成
（Top 100 / 等级 / 新曲 / 曲包 / PP / 标签 / 单曲轨迹）、改账号、打开输出目录，以及
**查询他人成绩**。

## 查询他人成绩（菜单 [9]）

输入对方账号后可选：Top 100、等级成绩、新曲、曲包、Perfect Play、标签推歌、单曲轨迹、
总结图、最近 100 局、目标 DJPower 规划。总结图和最近 100 局不需要选按键模式（它们本来就
跨 4 个模式），其余图表会先问一次模式。

- 成绩直接从 V-ARCHIVE 拉取，**只保存在内存**，不写入 `data/records`，不影响之后查自己；
- 结果写到 `output/inspect/<账号>/`；
- 每次查询需要联网（和刷新成绩一样，是唯一联网的两类操作）；
- 返回主菜单后分析器会自动重置，下一次查自己仍读本地记录库。

## 体积与启动时间

| 指标 | 数值 |
|---|---|
| exe | 118.3 MB |
| 首次启动（只释放占位图） | ≈ 3.2 s |
| 之后每次启动（自解压） | ≈ 3.2 s |
| 首次刷新（下载 846 张曲绘） | ≈ 16 s |
| 之后刷新（曲库未过期） | ≈ 5 s |
| 单张 Top 100 渲染（含启动） | ≈ 6.6 s |
| 总结图 + 4 张模式卡（含启动） | ≈ 17 s（matplotlib 较慢） |

单文件版的代价就是每次启动要自解压一次；换来的是“只有一个 exe”，没有 `_internal/`、没有
Python 目录。如果更在意启动速度，可以改成 onedir（`DJMAX-Bests.exe` + `_internal/`），
启动能降到 1 秒内，但根目录会多一个文件夹。

## 仓库结构

```
app.py               exe 入口：菜单、账号、任务分发、查询他人
djmax_bests/         数据层（api_handler / analyzer / history）+ 渲染器 + 刷新逻辑
DJMAX-Bests.spec     PyInstaller 配置（onefile，只带占位曲绘）
build_exe.ps1        构建脚本：生成 dist-exe\DJMAX-Bests\ 和 zip
```

早期脚本入口（`refresh.py` / `all.py` / `summary.py` / `runrun.py` / `target.py` /
`inspect_*.py` / `prefetch_covers.py`）已移除，对应功能全部在 exe 菜单里。

## 重新打包

需要 `.venv`（Python 3.14）：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1        # 生成 dist-exe\DJMAX-Bests\
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Zip   # 顺便打 zip
```

脚本会自动把 PyInstaller 装进 `.venv`（仅构建用，不随包分发），然后：

1. 按 `DJMAX-Bests.spec` 打包 `app.py` 为单文件 exe；
2. 附带素材：`djmax_bests/generators`（PNG/TTF/CSV/JPG）、占位曲绘 `dummy.jpg`、标签表、
   `tzdata`（真实曲绘不打包，首次刷新下载）；
3. 组装 `dist-exe\DJMAX-Bests\`（exe + `使用说明.txt` + 预置 `settings.ini` + 空 `data/`、`output/`），
   可选打 zip。

产物：`dist-exe\DJMAX-Bests\`（约 118 MB）与 `dist-exe\DJMAX-Bests.zip`（约 118 MB）。

## 注意

- 未签名，SmartScreen 可能提示，选“更多信息 → 仍要运行”；
- 单文件 exe 每次启动都会解压到 `%TEMP%`，杀软扫描可能让首次启动更慢；
- `data/records/` 是个人成绩，分发时不要带上；
- 升级依赖或改代码后必须重新打包，exe 不会自动更新。
