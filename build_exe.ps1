<#
.SYNOPSIS
    Build the single-file DJMAX-Bests.exe (PyInstaller onefile) and assemble a clean
    distribution folder: the exe, a short readme, and an empty data/ directory.

.DESCRIPTION
    The exe embeds CPython, every dependency, all renderer assets and the jackets, so the
    root of the distribution is just:

        DJMAX-Bests.exe
        使用说明.txt
        data/            (created on first run: account, cache, covers, records, output)

    PyInstaller is installed into .venv on first use (build-only; it is not shipped).

.PARAMETER Zip
    Also produce dist-exe\DJMAX-Bests.zip.

.PARAMETER NoClean
    Skip PyInstaller --clean (faster incremental build).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Zip
#>
param(
    [switch]$Zip,
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) { throw "缺少 .venv\Scripts\python.exe，请先创建 .venv（uv venv .venv --python 3.14）。" }

Push-Location $root
try {
    $hasPyi = $false
    try {
        & $py -m PyInstaller --version *> $null
        $hasPyi = ($LASTEXITCODE -eq 0)
    } catch {
        $hasPyi = $false
    }
    if (-not $hasPyi) {
        Write-Host "==> installing PyInstaller into .venv (build-only)"
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            & uv pip install --python $py pyinstaller
        } else {
            & $py -m pip install pyinstaller
        }
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 安装失败" }
    }

    Write-Host "==> building onefile exe"
    $pyiArgs = @("-m", "PyInstaller", "--noconfirm", "--distpath", "dist-exe", "--workpath", "build\pyinstaller")
    if (-not $NoClean) { $pyiArgs += "--clean" }
    $pyiArgs += "DJMAX-Bests.spec"
    & $py @pyiArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

    $exe = Join-Path $root "dist-exe\DJMAX-Bests.exe"
    if (-not (Test-Path $exe)) { throw "没有生成 $exe" }

    $out = Join-Path $root "dist-exe\DJMAX-Bests"
    if (Test-Path $out) { Remove-Item $out -Recurse -Force }
    New-Item -ItemType Directory -Path (Join-Path $out "data"), (Join-Path $out "output") -Force | Out-Null
    Copy-Item $exe $out
    # The tag table ships as an editable file beside the exe; replacing it needs no rebuild.
    Copy-Item (Join-Path $root "djmax_bests\analyzer\djmax_songs_tags.csv") (Join-Path $out "data\djmax_songs_tags.csv")

    # Pre-create settings.ini from the app's own template (single source of truth), so the
    # knobs are visible before the first launch instead of appearing after it.
    $iniScript = "from djmax_bests import settings; from pathlib import Path; Path(r'$out').mkdir(parents=True, exist_ok=True); Path(r'$out\settings.ini').write_text(settings.DEFAULT_TEXT, encoding='utf-8')"
    & $py -c $iniScript
    if ($LASTEXITCODE -ne 0) { throw "生成 settings.ini 失败" }

    $readme = @"
DJMAX 成绩图生成器（单文件版）

1. 把整个文件夹放在任意可写位置（不要放 C:\Program Files，那里没有写权限）。
2. 双击 DJMAX-Bests.exe。
3. 首次运行输入你的 V-ARCHIVE 账号名，然后选 [1] 刷新成绩（需要联网）。
4. 之后选 [2]~[9] 出图，结果都在 output\ 下。

目录说明
  DJMAX-Bests.exe   程序本体和全部依赖（不需要安装 Python）
  settings.ini      总结图 / 目标规划 / 刷新策略的默认参数（用记事本编辑，保存即生效）
  data\account.txt  你的账号
  data\cache\       歌曲库 / DLC 列表 / 换算系数缓存
  data\covers\      曲绘（exe 只带占位图，首次刷新时下载全部封面）
  data\records\     成绩记录库（刷新后生成，删了要重新刷新）
  data\djmax_songs_tags.csv  谱面标签表（可单独替换，不用重新打包）
  output\           生成的图片（与 data 同级）

常用操作
  * [1] 刷新成绩：成绩每次都刷新；歌曲库 / DLC 列表 / 换算系数超过 7 天才重下
    （可在 settings.ini 的 [refresh] max_age_days 修改，0 = 每次都更新）。
  * 更新标签表：直接替换 data\djmax_songs_tags.csv，下次出图会自动重建记录库。
  * [4] 游玩历史：直接回车 = 最近一天；输入 20261012 这样的日期 = 指定那一天。
  * [5] 目标规划：难度上限留空 = 使用 settings.ini 里的 floor_cap；输入 6.0 可临时覆盖。
  * [9] 查询他人成绩：成绩只在内存中使用，不写入 data\records。

注意
  * 单文件版每次启动要自解压 2~4 秒，属正常现象。
  * 刷新成绩 / 查询他人都需要联网；出图完全离线。
  * 首次刷新会下载 800 多张曲绘，约 1 分钟；之后只补新曲。
  * 整个文件夹可以拷到别的电脑直接用；data\records 是个人的成绩，别发给别人。
  * 程序未签名，Windows SmartScreen 可能提示，选择“更多信息 -> 仍要运行”。
  * 出图失败时先运行 [1] 刷新成绩；本地记录库缺失会给出提示。
"@
    $utf8Bom = New-Object System.Text.UTF8Encoding($true)
    [IO.File]::WriteAllText((Join-Path $out "使用说明.txt"), ($readme -replace "`r?`n", "`r`n"), $utf8Bom)

    if ($Zip) {
        $zipPath = Join-Path $root "dist-exe\DJMAX-Bests.zip"
        if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
        Write-Host "==> compressing -> $zipPath"
        Push-Location (Join-Path $root "dist-exe")
        try {
            & tar.exe -a -c -f $zipPath "DJMAX-Bests"
            if ($LASTEXITCODE -ne 0) { throw "tar 打包失败" }
        } finally {
            Pop-Location
        }
        Write-Host ("    {0} ({1:N1} MB)" -f $zipPath, ((Get-Item $zipPath).Length / 1MB))
    }

    $size = (Get-Item $exe).Length / 1MB
    Write-Host ""
    Write-Host "done: $out"
    Write-Host ("      DJMAX-Bests.exe  {0:N1} MB" -f $size)
} finally {
    Pop-Location
}
