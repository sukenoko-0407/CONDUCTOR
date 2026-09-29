param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $OutputPath) {
    $OutputPath = Join-Path $projectRoot "CONDUCTOR_modules\docs\CONDUCTOR_0.2.1_overview_slides.pptx"
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
$processImage = Join-Path $projectRoot "CONDUCTOR_modules\docs\images\CONDUCTOR_0.2.1_process_overview.png"
$overviewImage = Join-Path $projectRoot "CONDUCTOR_modules\docs\images\CONDUCTOR_report_overview_mock.png"
$findingImage = Join-Path $projectRoot "CONDUCTOR_modules\docs\images\CONDUCTOR_L2a_report_mock.png"

foreach ($path in @($processImage, $overviewImage, $findingImage)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required slide asset is missing: $path" }
}
if (Test-Path -LiteralPath $OutputPath) { throw "Refusing to overwrite existing deck: $OutputPath" }

function Color([int]$r, [int]$g, [int]$b) { return $r + 256 * $g + 65536 * $b }
$navy = Color 13 39 80
$blue = Color 28 111 184
$cyan = Color 31 157 180
$green = Color 32 151 94
$orange = Color 233 132 35
$red = Color 198 55 68
$ink = Color 28 38 49
$muted = Color 86 102 117
$line = Color 207 218 227
$wash = Color 244 247 249
$white = Color 255 255 255
$paleBlue = Color 231 243 250
$paleOrange = Color 255 243 225
$paleGreen = Color 230 246 237

function Add-Text($slide, [double]$x, [double]$y, [double]$w, [double]$h, [string]$text,
                  [double]$size = 18, [int]$color = $ink, [bool]$bold = $false,
                  [int]$align = 1) {
    $shape = $slide.Shapes.AddTextbox(1, $x, $y, $w, $h)
    $shape.TextFrame.MarginLeft = 0
    $shape.TextFrame.MarginRight = 0
    $shape.TextFrame.MarginTop = 0
    $shape.TextFrame.MarginBottom = 0
    $shape.TextFrame.WordWrap = -1
    $range = $shape.TextFrame.TextRange
    $range.Text = $text
    $range.Font.Name = "Yu Gothic"
    $range.Font.NameFarEast = "Yu Gothic"
    $range.Font.Size = $size
    $range.Font.Bold = $(if ($bold) { -1 } else { 0 })
    $range.Font.Color.RGB = $color
    $range.ParagraphFormat.Alignment = $align
    return $shape
}

function Add-Box($slide, [double]$x, [double]$y, [double]$w, [double]$h,
                 [int]$fill, [int]$stroke = $line, [double]$radius = 5) {
    $shape = $slide.Shapes.AddShape(5, $x, $y, $w, $h)
    $shape.Fill.Solid()
    $shape.Fill.ForeColor.RGB = $fill
    $shape.Line.ForeColor.RGB = $stroke
    $shape.Line.Weight = 1.25
    return $shape
}

function Add-Arrow($slide, [double]$x1, [double]$y1, [double]$x2, [double]$y2, [int]$color = $blue) {
    $lineShape = $slide.Shapes.AddLine($x1, $y1, $x2, $y2)
    $lineShape.Line.ForeColor.RGB = $color
    $lineShape.Line.Weight = 2.5
    $lineShape.Line.EndArrowheadStyle = 3
    return $lineShape
}

function Add-Title($slide, [string]$number, [string]$title, [string]$subtitle = "") {
    Add-Text $slide 42 22 70 25 $number 11 $cyan $true | Out-Null
    Add-Text $slide 42 47 870 44 $title 28 $navy $true | Out-Null
    if ($subtitle) { Add-Text $slide 44 94 850 28 $subtitle 12 $muted $false | Out-Null }
    $rule = $slide.Shapes.AddLine(42, 128, 918, 128)
    $rule.Line.ForeColor.RGB = $line
    $rule.Line.Weight = 1.25
}

function Add-Footer($slide) {
    Add-Text $slide 42 516 500 14 "CONDUCTOR 0.2.1  |  2026-09-29" 8 $muted $false | Out-Null
    Add-Text $slide 880 516 38 14 ([string]$slide.SlideIndex) 8 $muted $false 3 | Out-Null
}

function Add-Node($slide, [double]$x, [double]$y, [double]$size, [int]$fill, [string]$label) {
    $circle = $slide.Shapes.AddShape(9, $x, $y, $size, $size)
    $circle.Fill.Solid(); $circle.Fill.ForeColor.RGB = $fill
    $circle.Line.Visible = 0
    Add-Text $slide $x ($y + $size + 4) $size 22 $label 10 $ink $true 2 | Out-Null
}

$powerPoint = $null
$presentation = $null
try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $powerPoint.Visible = -1
    $presentation = $powerPoint.Presentations.Add()
    $presentation.PageSetup.SlideWidth = 960
    $presentation.PageSetup.SlideHeight = 540

    # 1 — Problem and value
    $slide = $presentation.Slides.Add(1, 12)
    $slide.Background.Fill.Solid(); $slide.Background.Fill.ForeColor.RGB = $wash
    Add-Title $slide "01 / 08" "複雑なSARを「検証可能な知見」へ" "全体平均では見えない条件依存構造を、網羅探索・統計・反証・引用で絞り込む"
    Add-Box $slide 42 158 270 270 $white | Out-Null
    Add-Text $slide 62 177 230 28 "従来の詰まりどころ" 18 $red $true | Out-Null
    Add-Text $slide 64 221 220 160 "• 特徴量と条件の組合せが広すぎる`r`n• 全体傾向が局所SARを隠す`r`n• p値一覧だけでは次の実験に繋がらない`r`n• LLMだけでは再現性・監査性が不足" 15 $ink $false | Out-Null
    Add-Node $slide 395 190 68 $blue "構造"
    Add-Node $slide 505 190 68 $cyan "条件"
    Add-Node $slide 615 190 68 $orange "反証"
    Add-Arrow $slide 463 224 500 224 $muted | Out-Null
    Add-Arrow $slide 573 224 610 224 $muted | Out-Null
    Add-Arrow $slide 683 224 735 224 $green | Out-Null
    Add-Box $slide 748 168 170 190 $paleGreen $green | Out-Null
    Add-Text $slide 770 190 126 26 "Finding" 20 $green $true 2 | Out-Null
    Add-Text $slide 766 230 134 105 "claim`r`n効果・support`r`np/q・score`r`n反証状態`r`n引用Evidence" 14 $ink $false 2 | Out-Null
    Add-Box $slide 342 390 576 78 $navy $navy | Out-Null
    Add-Text $slide 365 407 530 42 "人間が読めるHTML  ×  機械監査できるJSON/manifest" 19 $white $true 2 | Out-Null
    Add-Footer $slide

    # 2 — End-to-end process (existing authoritative image)
    $slide = $presentation.Slides.Add(2, 12)
    $slide.Background.Fill.Solid(); $slide.Background.Fill.ForeColor.RGB = $white
    Add-Title $slide "02 / 08" "Phase 1～6：発見から受入まで" "数値解析はUbuntu CPU、Local LLMは限定的な選択と文章化だけ"
    $slide.Shapes.AddPicture($processImage, 0, -1, 42, 145, 876, 349) | Out-Null
    Add-Footer $slide

    # 3 — Data and reusable assets
    $slide = $presentation.Slides.Add(3, 12)
    $slide.Background.Fill.Solid(); $slide.Background.Fill.ForeColor.RGB = $wash
    Add-Title $slide "03 / 08" "構造資産を再利用し、Endpoint解析は独立させる" "Description DatabaseはProgram単位。互換性が一致するrecordだけをcache hitにする"
    Add-Box $slide 42 155 245 310 $white | Out-Null
    Add-Text $slide 62 176 205 25 "入力とidentity" 17 $navy $true | Out-Null
    Add-Text $slide 62 216 205 170 "compound ID`r`ncanonical SMILES`r`ncalculation version`r`ncalculation signature`r`ndataset signature" 15 $ink $false | Out-Null
    Add-Text $slide 62 402 205 38 "同一ID・異構造は fail-fast" 12 $red $true | Out-Null
    Add-Arrow $slide 298 310 345 310 $blue | Out-Null
    Add-Box $slide 356 155 250 310 $paleBlue $blue | Out-Null
    Add-Text $slide 378 176 205 25 "18 Description" 18 $blue $true 2 | Out-Null
    $labels = @("2D物性","Fingerprint","Scaffold","Pharmacophore","3D形状","Mordred")
    for ($i=0; $i -lt 6; $i++) {
        $col = $i % 2; $row = [math]::Floor($i / 2)
        Add-Box $slide (378 + 105*$col) (224 + 62*$row) 92 43 $white $line | Out-Null
        Add-Text $slide (383 + 105*$col) (237 + 62*$row) 82 20 $labels[$i] 11 $ink $true 2 | Out-Null
    }
    Add-Text $slide 382 416 198 22 "terminal SKIPも理由付きで保存" 11 $muted $false 2 | Out-Null
    Add-Arrow $slide 616 310 663 310 $green | Out-Null
    Add-Box $slide 674 155 244 310 $paleGreen $green | Out-Null
    Add-Text $slide 696 176 200 25 "別Endpoint Run" 18 $green $true 2 | Out-Null
    Add-Text $slide 700 226 192 145 "構造資産：再利用`r`nEndpoint table：新規`r`nLens：新規`r`nScoring：新規`r`nDeep dive：新規`r`nReport：新規" 15 $ink $false | Out-Null
    Add-Text $slide 700 402 190 38 "旧Findingやnarrativeは流用しない" 11 $red $true | Out-Null
    Add-Footer $slide

    # 4 — Lenses
    $slide = $presentation.Slides.Add(4, 12)
    $slide.Background.Fill.Solid(); $slide.Background.Fill.ForeColor.RGB = $white
    Add-Title $slide "04 / 08" "6つのLensで異なるSARの問いを立てる" "同じデータを一つのクラスタリングへ還元せず、問いごとに統計族とEvidenceを分離"
    $lensCards = @(
        @("L1b","局所SAR","近傍の中で外れる化合物",$blue),
        @("L2a","文脈依存MMP","同じ置換が条件で変わる",$cyan),
        @("L2b","fragment効果","系列を越えた一貫性／異質性",$green),
        @("L4","Frontier","未探索で到達可能な候補",$orange),
        @("L5","相関反転","feature関係が文脈で逆転",$red),
        @("L7","系列移植性","同じR基の効果を系列間比較",$navy)
    )
    for ($i=0; $i -lt 6; $i++) {
        $col = $i % 3; $row = [math]::Floor($i / 3)
        $x = 42 + 300*$col; $y = 156 + 165*$row
        Add-Box $slide $x $y 276 140 $white $lensCards[$i][3] | Out-Null
        $circle = $slide.Shapes.AddShape(9, $x+18, $y+18, 48, 48)
        $circle.Fill.Solid(); $circle.Fill.ForeColor.RGB = $lensCards[$i][3]; $circle.Line.Visible=0
        Add-Text $slide ($x+18) ($y+33) 48 18 $lensCards[$i][0] 11 $white $true 2 | Out-Null
        Add-Text $slide ($x+80) ($y+18) 174 23 $lensCards[$i][1] 16 $navy $true | Out-Null
        Add-Text $slide ($x+80) ($y+52) 174 52 $lensCards[$i][2] 12 $ink $false | Out-Null
        $mini = $slide.Shapes.AddLine($x+23,$y+116,$x+248,$y+116)
        $mini.Line.ForeColor.RGB = $lensCards[$i][3]; $mini.Line.Weight=3
    }
    Add-Footer $slide

    # 5 — Deterministic / LLM boundary
    $slide = $presentation.Slides.Add(5, 12)
    $slide.Background.Fill.Solid(); $slide.Background.Fill.ForeColor.RGB = $wash
    Add-Title $slide "05 / 08" "決定論コードとLocal LLMの境界" "LLMは結果を決めない。許可された候補選択と、引用付き文章化だけを担当"
    Add-Box $slide 42 156 420 292 $paleBlue $blue | Out-Null
    Add-Text $slide 66 176 370 25 "決定論レイヤー（CPU）" 18 $blue $true | Out-Null
    $det = @("Description・距離・クラスタ","効果量・p/q値・多重性","Finding生成・score・state","template実行・引用検証")
    for ($i=0; $i -lt 4; $i++) {
        Add-Box $slide 70 (220+52*$i) 360 38 $white $line | Out-Null
        Add-Text $slide 84 (231+52*$i) 330 18 ("✓  " + $det[$i]) 13 $ink $true | Out-Null
    }
    Add-Box $slide 498 156 420 292 $paleOrange $orange | Out-Null
    Add-Text $slide 522 176 370 25 "Local LLM（別GPU vLLM）" 18 $orange $true | Out-Null
    $llm = @("select_deep_dive","summarize_deep_dive","compose_component_narrative")
    for ($i=0; $i -lt 3; $i++) {
        Add-Box $slide 540 (226+60*$i) 336 42 $white $line | Out-Null
        Add-Text $slide 554 (238+60*$i) 306 18 $llm[$i] 13 $ink $true 2 | Out-Null
    }
    Add-Arrow $slide 462 302 498 302 $orange | Out-Null
    Add-Text $slide 448 274 65 18 "JSONL" 9 $muted $true 2 | Out-Null
    Add-Box $slide 178 466 604 36 (Color 255 235 237) $red | Out-Null
    Add-Text $slide 195 476 570 18 "LLMは特徴量・数値・順位・最終判定を変更しない" 13 $red $true 2 | Out-Null
    Add-Footer $slide

    # 6 — Human reports
    $slide = $presentation.Slides.Add(6, 12)
    $slide.Background.Fill.Solid(); $slide.Background.Fill.ForeColor.RGB = $white
    Add-Title $slide "06 / 08" "出力は「一覧」ではなく、知見を読むためのレポート" "上位20件すべてにLens固有の個別HTML。表紙は1～10位を詳述、11～20位はタイトルのみ"
    Add-Box $slide 42 151 419 326 $white $line | Out-Null
    $slide.Shapes.AddPicture($overviewImage, 0, -1, 50, 159, 403, 252) | Out-Null
    Add-Text $slide 62 420 379 42 "全体 report.html`r`n重要度、Lens構成、component、監査付録" 11 $ink $true 2 | Out-Null
    Add-Box $slide 499 151 419 326 $white $line | Out-Null
    $slide.Shapes.AddPicture($findingImage, 0, -1, 507, 159, 403, 252) | Out-Null
    Add-Text $slide 519 420 379 42 "個別 finding_reports/*.html`r`n構造図、統計、deep dive、反証、Evidence" 11 $ink $true 2 | Out-Null
    Add-Footer $slide

    # 7 — Reliability
    $slide = $presentation.Slides.Add(7, 12)
    $slide.Background.Fill.Solid(); $slide.Background.Fill.ForeColor.RGB = $wash
    Add-Title $slide "07 / 08" "Fail-closedで監査可能なRunを作る" "停止は失敗ではなく、入力・設計・証拠の不整合を隠さないための制御"
    $stages = @(
        @("1","Preflight","入力・domain・DB・provider",$blue),
        @("2","Runtime","DAG・lease・retry・single writer",$cyan),
        @("3","Artifact","入力hash・出力hash・manifest",$green),
        @("4","Statistics","固定seed・多重性・guard",$orange),
        @("5","Citation","数値・ID・rowを再照合",$red)
    )
    for ($i=0; $i -lt 5; $i++) {
        $x = 42 + 176*$i
        Add-Box $slide $x 180 156 142 $white $stages[$i][3] | Out-Null
        Add-Text $slide ($x+14) 196 30 22 $stages[$i][0] 15 $stages[$i][3] $true | Out-Null
        Add-Text $slide ($x+14) 228 128 24 $stages[$i][1] 15 $navy $true | Out-Null
        Add-Text $slide ($x+14) 265 128 42 $stages[$i][2] 10 $ink $false | Out-Null
        if ($i -lt 4) { Add-Arrow $slide ($x+156) 250 ($x+174) 250 $muted | Out-Null }
    }
    Add-Box $slide 74 356 244 76 $paleGreen $green | Out-Null
    Add-Text $slide 92 372 208 20 "succeeded" 16 $green $true 2 | Out-Null
    Add-Text $slide 92 398 208 18 "検証済み成果物を受入" 11 $ink $false 2 | Out-Null
    Add-Box $slide 358 356 244 76 $paleOrange $orange | Out-Null
    Add-Text $slide 376 372 208 20 "needs_design_review" 14 $orange $true 2 | Out-Null
    Add-Text $slide 376 398 208 18 "人間判断まで停止" 11 $ink $false 2 | Out-Null
    Add-Box $slide 642 356 244 76 (Color 255 235 237) $red | Out-Null
    Add-Text $slide 660 372 208 20 "failed" 16 $red $true 2 | Out-Null
    Add-Text $slide 660 398 208 18 "原因を分類し最小復旧" 11 $ink $false 2 | Out-Null
    Add-Text $slide 154 458 650 23 "3D生成不能は理由付きterminal SKIPとしてDBへ記録し、解析可能な母集団で継続" 12 $navy $true 2 | Out-Null
    Add-Footer $slide

    # 8 — Operational delivery
    $slide = $presentation.Slides.Add(8, 12)
    $slide.Background.Fill.Solid(); $slide.Background.Fill.ForeColor.RGB = $white
    Add-Title $slide "08 / 08" "運用で得られるもの" "Runを保存し、構造資産を再利用しながら別Endpointへ展開する"
    Add-Box $slide 42 155 410 310 $paleBlue $blue | Out-Null
    Add-Text $slide 66 176 360 25 "利用者の流れ" 18 $blue $true | Out-Null
    $ops = @("1  Run Specと入力を準備","2  Preflight receiptを取得","3  固定DAGでPhase 1～6","4  read-only監査で正式受入","5  HTMLから追試候補を検討")
    for ($i=0; $i -lt 5; $i++) {
        Add-Box $slide 70 (220+45*$i) 350 33 $white $line | Out-Null
        Add-Text $slide 84 (229+45*$i) 320 16 $ops[$i] 12 $ink $true | Out-Null
    }
    Add-Box $slide 488 155 430 310 $paleGreen $green | Out-Null
    Add-Text $slide 512 176 382 25 "1 Runの成果物" 18 $green $true | Out-Null
    Add-Text $slide 516 220 170 168 "runtime.sqlite`r`nExecution Requests`r`nDescription audit`r`nFinding + Evidence`r`nDeep-dive tree`r`nreport.html`r`n個別HTML × Top20" 13 $ink $false | Out-Null
    Add-Text $slide 714 220 176 168 "入力/config/code hash`r`nNode attempt log`r`nLens telemetry`r`nCitation validation`r`nArtifact manifests`r`nLLM failure ledger`r`n復旧可能な状態" 13 $ink $false | Out-Null
    Add-Box $slide 512 407 382 37 $navy $navy | Out-Null
    Add-Text $slide 524 417 358 17 "次Endpoint：Description DB hit → Endpoint依存部を新規解析" 11 $white $true 2 | Out-Null
    Add-Footer $slide

    $presentation.SaveAs($OutputPath, 24)
}
finally {
    if ($presentation -ne $null) { $presentation.Close() }
    if ($powerPoint -ne $null) { $powerPoint.Quit() }
    if ($presentation -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) }
    if ($powerPoint -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint) }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}

Write-Output $OutputPath

