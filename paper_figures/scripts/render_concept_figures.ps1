<#
.SYNOPSIS
用 Visio 原生图形生成可编辑的论文模型图和算法图，并导出 PDF/SVG/PNG。
.DESCRIPTION
构图参数来自 assets/*.scene.json。使用独立不可见 Visio 实例，避免修改用户
已经打开的文档；发生异常时保留错误上下文并确保关闭本脚本创建的实例。
#>
[CmdletBinding()]
param([string]$FigureName = '*')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$figureRoot = Split-Path -Parent $PSScriptRoot
$script:app = $null
$script:doc = $null
$script:page = $null
$script:scale = 1.0
$script:pageHeight = 0.0
$script:shapeIndex = @{}

function Set-Cell($Shape, [string]$Name, [string]$Formula) {
    $Shape.CellsU($Name).FormulaU = $Formula
}

function Get-ColorFormula([string]$Color) {
    $value = $Color.TrimStart('#')
    $red = [Convert]::ToInt32($value.Substring(0, 2), 16)
    $green = [Convert]::ToInt32($value.Substring(2, 2), 16)
    $blue = [Convert]::ToInt32($value.Substring(4, 2), 16)
    return "RGB($red,$green,$blue)"
}

function Get-Property($Value, [string]$Name, $Default) {
    if ($null -ne $Value.PSObject.Properties[$Name]) { return $Value.$Name }
    return $Default
}

function Set-ShapeStyle($Shape, $Spec) {
    # 显式设置 ShapeSheet 样式，防止默认 Office 主题引入阴影、渐变或字体替换。
    if ($null -eq $Spec.fill) { Set-Cell $Shape 'FillPattern' '0' }
    else {
        Set-Cell $Shape 'FillPattern' '1'
        Set-Cell $Shape 'FillForegnd' (Get-ColorFormula $Spec.fill)
    }
    if ($null -eq $Spec.stroke) { Set-Cell $Shape 'LinePattern' '0' }
    else {
        Set-Cell $Shape 'LineColor' (Get-ColorFormula $Spec.stroke)
        Set-Cell $Shape 'LinePattern' ([string](Get-Property $Spec 'dash' 1))
        Set-Cell $Shape 'LineWeight' (([string](Get-Property $Spec 'linePt' 0.75)) + ' pt')
    }
    Set-Cell $Shape 'ShdwPattern' '0'
    $Shape.NameU = $Spec.id
    $script:shapeIndex[$Spec.id] = $Shape
}

function New-SceneShape($Spec) {
    $shape = $null
    switch ($Spec.type) {
        { $_ -in 'rect', 'text', 'ellipse' } {
            $left = $Spec.x * $script:scale
            $right = ($Spec.x + $Spec.w) * $script:scale
            $top = ($script:pageHeight - $Spec.y) * $script:scale
            $bottom = ($script:pageHeight - $Spec.y - $Spec.h) * $script:scale
            if ($Spec.type -eq 'ellipse') { $shape = $script:page.DrawOval($left, $bottom, $right, $top) }
            else { $shape = $script:page.DrawRectangle($left, $bottom, $right, $top) }
        }
        { $_ -in 'polyline', 'polygon' } {
            # DrawPolyline 创建真实的可编辑 Visio 几何，不依赖嵌入式图片。
            $coords = [System.Collections.Generic.List[double]]::new()
            foreach ($point in $Spec.points) {
                $coords.Add([double]$point[0] * $script:scale)
                $coords.Add(($script:pageHeight - [double]$point[1]) * $script:scale)
            }
            $shape = $script:page.DrawPolyline($coords.ToArray(), 0)
        }
        'bezier' {
            # 将网络素材的三次贝塞尔轮廓转换为原生 Visio 几何，保留曲线编辑能力。
            $coords = [System.Collections.Generic.List[double]]::new()
            foreach ($point in $Spec.points) {
                $coords.Add([double]$point[0] * $script:scale)
                $coords.Add(($script:pageHeight - [double]$point[1]) * $script:scale)
            }
            $shape = $script:page.DrawBezier($coords.ToArray(), 3, 0)
        }
        default { throw "未知图形类型: $($Spec.type)，图形: $($Spec.id)" }
    }
    Set-ShapeStyle $shape $Spec
    if ((Get-Property $Spec 'arrow' $false)) {
        Set-Cell $shape 'EndArrow' '4'
        Set-Cell $shape 'EndArrowSize' '1'
    }
    if ($Spec.type -eq 'text') {
        $shape.Text = $Spec.text
        $fontName = Get-Property $Spec 'font' 'Times New Roman'
        Set-Cell $shape 'Char.Font' ([string]$script:doc.Fonts.Item($fontName).ID)
        Set-Cell $shape 'Char.Size' ($Spec.fontPt.ToString([Globalization.CultureInfo]::InvariantCulture) + ' pt')
        $style = 0
        if ($Spec.bold) { $style += 1 }
        if (Get-Property $Spec 'italic' $false) { $style += 2 }
        Set-Cell $shape 'Char.Style' ([string]$style)
        Set-Cell $shape 'Char.Color' (Get-ColorFormula $Spec.color)
        Set-Cell $shape 'Para.HorzAlign' $(if ($Spec.align -eq 'left') { '0' } else { '1' })
        Set-Cell $shape 'VerticalAlign' '1'
        foreach ($margin in 'LeftMargin','RightMargin','TopMargin','BottomMargin') { Set-Cell $shape $margin '0 in' }
        Set-Cell $shape 'Para.SpLine' '-100%'
        Set-Cell $shape 'TextBkgnd' '0'
    }
}

function Export-Scene($Scene) {
    $script:shapeIndex = @{}
    $script:doc = $script:app.Documents.Add('')
    $script:page = $script:doc.Pages.Item(1)
    $script:page.Name = $Scene.name
    $script:scale = [double]$Scene.widthMm / 25.4 / [double]$Scene.width
    $script:pageHeight = [double]$Scene.height
    $script:page.PageSheet.CellsU('PageWidth').ResultIU = [double]$Scene.width * $script:scale
    $script:page.PageSheet.CellsU('PageHeight').ResultIU = [double]$Scene.height * $script:scale
    Set-Cell $script:page.PageSheet 'DrawingScale' '1 in'
    Set-Cell $script:page.PageSheet 'PageScale' '1 in'
    Set-Cell $script:page.PageSheet 'ShdwOffsetX' '0 in'
    Set-Cell $script:page.PageSheet 'ShdwOffsetY' '0 in'
    foreach ($spec in $Scene.shapes) { New-SceneShape $spec }

    # 图层保留业务语义；独立文本和路径继续可编辑，避免分组重排遮挡顺序。
    foreach ($family in ($Scene.shapes | Group-Object group)) {
        $layer = $script:page.Layers.Add([string]$family.Name)
        foreach ($spec in $family.Group) { $layer.Add($script:shapeIndex[$spec.id], 0) }
    }
    $vsdx = Join-Path $figureRoot "visio/$($Scene.name).vsdx"
    # 先检查目标文件是否被用户打开，避免 Visio 将文件占用报告为不透明的 DOS 句柄错误。
    if (Test-Path -LiteralPath $vsdx) {
        $fileProbe = [IO.File]::Open($vsdx, 'Open', 'ReadWrite', 'None')
        $fileProbe.Dispose()
    }
    [void]$script:doc.SaveAs($vsdx)
    $svg = Join-Path $figureRoot "output/svg/$($Scene.name).svg"
    $png = Join-Path $figureRoot "output/png/$($Scene.name).png"
    $pdf = Join-Path $figureRoot "output/pdf/$($Scene.name).pdf"
    $script:page.Export($svg)
    # 预览使用 300 dpi；论文源文件和 PDF/SVG 始终保持矢量。
    $script:app.Settings.SetRasterExportResolution(3, 300, 300, 0)
    $script:page.Export($png)
    $script:doc.ExportAsFixedFormat(1, $pdf, 1, 0)
    $shapeCount = $script:page.Shapes.Count
    $script:doc.Saved = $true
    $script:doc.Close()
    $script:doc = $null

    # 重新打开保存后的文件核对图形数量和可编辑性，导出成功不等于源文件可用。
    $verify = $script:app.Documents.OpenEx($vsdx, 64)
    if ($verify.Pages.Count -ne 1 -or $verify.Pages.Item(1).Shapes.Count -ne $shapeCount) {
        throw "Visio 重开校验失败: $vsdx"
    }
    $verify.Close()
    foreach ($path in $vsdx, $svg, $png, $pdf) {
        if ((Get-Item -LiteralPath $path).Length -le 0) { throw "导出文件为空: $path" }
    }
    Write-Host "已生成 $($Scene.name)：$shapeCount 个原生图形，VSDX/PDF/SVG/PNG。"
}

try {
    foreach ($folder in 'visio','output/svg','output/png','output/pdf') {
        [void][IO.Directory]::CreateDirectory((Join-Path $figureRoot $folder))
    }
    $scenes = @(Get-ChildItem -LiteralPath (Join-Path $figureRoot 'visio/assets') -Filter "$FigureName.scene.json")
    if ($scenes.Count -eq 0) { throw "未找到构图规范，请检查 visio/assets 中的最终版 .scene.json 文件及 FigureName 参数。" }
    $script:app = New-Object -ComObject Visio.InvisibleApp
    $script:app.AlertResponse = 7
    foreach ($file in $scenes) {
        Export-Scene (Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json)
    }
} catch {
    Write-Error "论文矢量图生成失败：$($_.Exception.Message)`n$($_.ScriptStackTrace)"
    throw
} finally {
    # 只关闭本脚本创建的不可见实例，不连接或终止用户的交互式 Visio。
    if ($null -ne $script:doc) { $script:doc.Saved = $true; $script:doc.Close() }
    if ($null -ne $script:app) {
        $script:app.Quit()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($script:app)
    }
}
