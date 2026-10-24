# 单文件 exe 版：安装与使用

> 想在自己的代码里调用生图模块？接口说明见 [README_zh.md](README_zh.md)（[English](README.md)）。
> 本文只讲 exe 的安装、菜单、配置与打包。

`DJMAX-Bests.exe` 里打包了 CPython、全部依赖和渲染素材（真实曲绘不打包，只带占位图）。
目标电脑上不需要安装 Python，解压双击即用。

---

## 快速开始

1. 解压到任意**可写**目录（不要放 `C:\Program Files`）；
2. 双击 `DJMAX-Bests.exe`；
3. 第一次运行输入你的 V-ARCHIVE 账号名（区分大小写）；
4. 选 `[1] 刷新成绩`——唯一必须联网的步骤，首次还会下载 800 多张曲绘（视网络约 15–60 秒）；
5. 选 `[2]`～`[9]` 生成图片，结果都在 `output/` 下。

> 刷新之后出图完全离线。换电脑时把整个文件夹拷走即可。

## 主菜单

| 菜单 | 功能 | 联网 |
|---|---|---|
| `[1]` | 刷新成绩 | 是 |
| `[2]` | 生成全部图片（约 200 张） | 否 |
| `[3]` | 总结图 + 4 张模式卡 | 否 |
| `[4]` | 游玩历史（可指定日期） | 否 |
| `[5]` | 目标 DJPower 规划 | 否 |
| `[6]` | 单图生成（8 种图） | 否 |
| `[7]` | 打开 `output/` | — |
| `[8]` | 修改账号 | — |
| `[9]` | 查询他人成绩 | 是 |

刷新策略：成绩每次都刷新；歌曲库、DLC 列表、DJ POWER 换算系数只在**超过 7 天**时重新下载
（`settings.ini` 的 `[refresh] max_age_days` 可改，`0` = 每次都更新）。

---

## 能生成哪些图

| 入口 | 内容 | 输出 |
|---|---|---|
| `[6] → [1]` | Top 100（70 Basic + 30 New，含等级分布直方图） | `output/best_<账号>_<模式>B.png` |
| `[6] → [2]` | 等级成绩总览（SC / 非 SC 各一张） | `output/level_<模式>B/scorelist_<模式>B_<等级>.png` |
| `[6] → [3]` | 新曲成绩总览 | `output/level_<模式>B/scorelist_new_<模式>B<难度>.png` |
| `[6] → [4]` | 曲包成绩总览 | `output/level_<模式>B/dlc/scorelist_<曲包>_<模式>B<难度>.png` |
| `[6] → [5]` | Perfect Play 总览 | `output/perfect_<模式>B.png` |
| `[6] → [6]` | 标签推歌进度（标签 + 难度 1–3） | `output/tag_<模式>B/<标签>_<等级>.png` |
| `[6] → [7]` | 单曲成绩轨迹（songid + 难度） | `output/history/songs/SongHistory_<模式>B<难度>_<songid>.png` |
| `[6] → [8]` | 理论值 Top 100（不需要账号成绩） | `output/theoretical/theoretical_<模式>B.png` |
| `[3]` | 总结图 + 4 张模式卡 | `output/summary.png` / `summary_<模式>B.png` |
| `[4]` | 游玩历史（默认最近一天，可输日期） | `output/history/History_<日期>.png` |
| `[5]` | 目标 DJPower 规划 | `output/target/target_<账号>_<模式>B_<总分>_<准确率>pct[_cap<上限>].png` |
| `[2]` | 全部图片（上面的 Top 100 / 等级 / 新曲 / PP / 理论值） | 各子目录 |

补充说明：

- **Top 100** 顶部有账号、段位、DJ POWER、换算系数和等级分布直方图；直方图背后的灰色虚影是
  该等级理论上能贡献的上限。
- **理论值** 把每张谱面按 100% 计算，标题为 `Max DJPower`；只依赖歌曲库，首次会下载
  `songs.json`（644 KB），**不需要先刷新成绩**。
- **游玩历史** 只显示某一天（默认最近一天）；历史来自每次刷新的快照 diff，玩完一局后刷新
  一次才能留下记录。
- **目标规划** 会标出要打的谱面：金色 `NEW` = 新打，青色 `UP` = 提升；不可达时标
  `BEST EFFORT` 并给出最低准确率。难度上限留空 = 用 `settings.ini` 的 `floor_cap`，输入
  `none` = 强制不限制。
- **总结图** 的头像、显示名、主按键、签名可在 `settings.ini` 的 `[summary]` 配置。
- **总结图** 与 **单曲轨迹** 里的技能雷达用系统字体 Sarasa Mono HC SemiBold（不随 exe 分发），
  没装会回退到默认字体，见“常见问题”。

## 查询他人成绩

`[9]`，输入对方账号（区分大小写），可选：

| 选项 | 内容 |
|---|---|
| `[1]` | Top 100 |
| `[2]` | 等级成绩总览（含 SC） |
| `[3]` | 新曲成绩总览 |
| `[4]` | 曲包成绩总览 |
| `[5]` | Perfect Play 总览 |
| `[6]` | 标签推歌进度 |
| `[7]` | 单曲成绩轨迹 |
| `[8]` | 总结图（跨模式，不需要选按键模式） |
| `[9]` | 最近 50 局 / 最近一天（跨模式） |
| `[10]` | 目标 DJPower 规划 |

- 成绩直接从 V-ARCHIVE 拉取，**只保存在内存**，不写入 `data/records`；
- 单快照无法知道被打破的旧成绩，所以历史类图只画结果，没有增量；
- 输出在 `output/inspect/<账号>/`；
- 返回主菜单后自动重置分析器，下次查自己仍读本地记录库。

---

## 输出目录

```
output/
├── best_<账号>_<模式>B.png          单张 Top 100
├── best_<模式>B/                    全量出图时的缩放副本
├── level_<模式>B/                   等级 / 新曲 / 曲包总览
├── perfect_<模式>B.png
├── tag_<模式>B/
├── theoretical/
├── history/
│   └── songs/
├── target/
├── summary.png / summary_<模式>B.png
└── inspect/<账号>/                  查询他人的结果
```

`output/` 与 `data/` 同级，不随程序更新丢失。

## 配置：settings.ini

在 exe 旁边，首次运行前已生成。用记事本编辑，保存后**下一次生成即生效**（不需要重启）。

```ini
[summary]
nickname =            ; 显示名；留空 = 账号名
photo_id =            ; 头像曲绘 songid；留空 = 随机
prefer_button = 4     ; 高亮的按键模式；留空 = 4,5,6,8 全高亮
info =                ; 签名栏文字；留空 = 不写

[target]
floor_cap =           ; 默认难度上限（floor）；留空 = 不限制
balance_rounds = 8    ; basic/new 配额平衡轮数

[refresh]
max_age_days = 7      ; 曲库 / DLC / 换算系数超过 N 天重下，0 = 每次都更新
```

`[summary]` 对“自己的总结图”和“查询他人的总结图”都生效；查询他人时 `nickname` 会被忽略，
始终显示对方账号名。

## 数据与缓存

```
data/
├── account.txt              账号
├── cache/                   songs.json / dlcs.json / maxpower_*.txt
├── covers/                  曲绘（首次刷新时下载）
├── records/                 成绩记录库与游玩历史
├── djmax_songs_tags.csv     谱面标签表（可替换）
└── .matplotlib/             字体缓存
```

- **成绩**：每次 `[1]` 重写 4 个模式的原始记录并重建 `records_db.parquet`；
- **曲库 / DLC / 换算系数**：按 `[refresh] max_age_days` 过期重下；
- **曲绘**：exe 只带一张占位图；首次刷新下载全部封面，之后新曲按需补；
- **标签表**：替换 `data/djmax_songs_tags.csv` 即可，下次出图会自动离线重建记录库，
  不需要重新打包；
- **删除 `data/records/history/` 会永久丢失被打破的旧成绩（API 无法重放）。**

---

## 常见问题

**没有账号 / 只想看理论值？**
`[6] → [8]` 不需要账号成绩，只依赖歌曲库（首次下载 644 KB）。

**图里出现灰色占位封面？**
封面还没下载到 `data/covers`。联网跑一次 `[1]`，或重新生成一次触发按需下载。

**总结图 / 单曲轨迹里的雷达图字体不对，控制台一直刷 `findfont: ... not found`？**
雷达用的 **Sarasa Mono HC SemiBold** 不在 exe 里（也不在 `data/` 里），需要单独装到系统：
从 [Sarasa-Gothic](https://github.com/be5invis/Sarasa-Gothic) 的 Release 下载
`SarasaMonoHC-TTF-<版本>.7z`，解压后右键 `SarasaMonoHC-SemiBold.ttf` → “安装”，
再删掉 `data/.matplotlib/` 重新生成。不装不影响出图，只是雷达标签会换成 DejaVu Sans。

**新曲没出现 / 定数不对？**
曲库缓存过期。把 `max_age_days` 改成 `0` 再 `[1]`，或删除 `data/cache/songs.json`。

**第一次启动很慢？**
单文件 exe 每次启动要自解压；首次刷新还要下载 846 张曲绘（约 15–60 秒）。

**目标规划显示不可达？**
提高预计准确率、放宽 `floor_cap` 或降低目标总分；图上的 `MIN ACC` 是理论最低要求。

**SmartScreen / 杀毒软件报警？**
程序未签名，选择“更多信息 → 仍要运行”。

**能放到 U 盘里吗？**
可以，路径尽量短；首次运行会写 `data/` 和 `output/`。

---

## 构建

需要 Python 3.14 和 `.venv`：

```powershell
uv venv .venv --python 3.14
uv pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Zip
```

产物在 `dist-exe\DJMAX-Bests\`（exe + settings.ini + 使用说明 + 空 data/、output/）。

打包时会：

1. 按 `DJMAX-Bests.spec` 把 `app.py` 打成单文件 exe；
2. 附带 `generators` 下的 PNG / TTF / CSV / JPG、占位曲绘、标签表和 `tzdata`；
3. 复制当前标签表到 `data/`，并生成 `settings.ini` 与 `使用说明.txt`。

## 仓库结构

```
app.py                 exe 入口：菜单、账号、任务、查询他人
djmax_bests/           数据层（V-ARCHIVE / records_db / history）+ 渲染器
DJMAX-Bests.spec       PyInstaller 配置
build_exe.ps1          构建脚本
README-EXE.md          本文（exe 使用与打包）
README_zh.md           生图模块接口说明（中文）
README.md              生图模块接口说明（英文）
```

单文件 exe 每次启动都要自解压一次（约 3 秒）；如果更在意启动速度，可以改成 onedir
（`exe + _internal/`），代价是根目录多一个文件夹。
