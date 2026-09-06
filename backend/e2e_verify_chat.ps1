$ErrorActionPreference = "Continue"
$base = "http://127.0.0.1:8000"
$ts = Get-Date -Format "yyyyMMddHHmmss"
$userA = "e2e_userA_" + $ts
$userB = "e2e_userB_" + $ts
$passA = "PassA_" + $ts + "!"
$passB = "PassB_" + $ts + "!"

# Pre-built body files (UTF-8, made by make_bodies.py)
$bodiesDir = $args[0]
if (-not $bodiesDir) { Write-Host "Usage: powershell -File e2e_verify_chat.ps1 <bodies_dir>"; exit 1 }

$results = New-Object System.Collections.Generic.List[object]
$failures = 0
function Add-Result {
    param($Step, $Name, $Ok, $Detail = "")
    $r = [PSCustomObject]@{
        Step    = $Step
        Name    = $Name
        Result  = if ($Ok) { "PASS" } else { "FAIL" }
        Detail  = $Detail
    }
    $script:results.Add($r) | Out-Null
    if (-not $Ok) { $script:failures++ }
    $color = if ($Ok) { "Green" } else { "Red" }
    Write-Host ("[{0}] {1,-30} {2,-5} {3}" -f $Step, $Name, $r.Result, $Detail) -ForegroundColor $color
}

function Post-Body($url, $headers, $bodyPath) {
    $bytes = [System.IO.File]::ReadAllBytes($bodyPath)
    return Invoke-RestMethod -Uri $url -Method Post -ContentType "application/json; charset=utf-8" -Headers $headers -Body $bytes -TimeoutSec 120
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " E2E Chat Verification (Task 13) - UTF-8 body files" -ForegroundColor Cyan
Write-Host (" Base URL : " + $base) -ForegroundColor Cyan
Write-Host (" User A   : " + $userA) -ForegroundColor Cyan
Write-Host (" User B   : " + $userB) -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Register
$rA = Invoke-RestMethod -Uri ($base + "/register") -Method Post -ContentType "application/json" -Body (@{username=$userA; password=$passA} | ConvertTo-Json) -TimeoutSec 10
$rB = Invoke-RestMethod -Uri ($base + "/register") -Method Post -ContentType "application/json" -Body (@{username=$userB; password=$passB} | ConvertTo-Json) -TimeoutSec 10
$uidA = $rA.id; $uidB = $rB.id
Add-Result "REG" "register A & B" (($uidA -gt 0) -and ($uidB -gt 0)) ("A_id=" + $uidA + " B_id=" + $uidB)

# Login
$lA = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -Body (@{username=$userA; password=$passA} | ConvertTo-Json) -TimeoutSec 10
$lB = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -Body (@{username=$userB; password=$passB} | ConvertTo-Json) -TimeoutSec 10
$tokA = $lA.access_token; $tokB = $lB.access_token
$hdrA = @{ Authorization = "Bearer " + $tokA }
$hdrB = @{ Authorization = "Bearer " + $tokB }
Add-Result "LOGIN" "login A & B" ($tokA -and $tokB) ("tokenA_len=" + $tokA.Length + " tokenB_len=" + $tokB.Length)

# S4-S5 User A records lunch via /chat (with valid UTF-8 body)
$chat = Post-Body ($base + "/chat") $hdrA (Join-Path $bodiesDir "a_lunch.json")
$aiReply = $chat.answer
Add-Result "S4" "POST /chat A lunch" ($aiReply -and $aiReply.Length -gt 0) ("reply_len=" + $aiReply.Length)

Start-Sleep -Seconds 2

$listA = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrA -TimeoutSec 10
$hasLunch = $false
foreach ($e in $listA) {
    if (($e.description -match "午饭") -or ($e.amount -eq 30)) { $hasLunch = $true; break }
}
Add-Result "S5" "GET /expense A has lunch" ($listA.Count -gt 0 -and $hasLunch) ("count=" + $listA.Count)
if ($listA.Count -gt 0) {
    Write-Host "    [A expenses]" -ForegroundColor Gray
    $listA | ForEach-Object {
        Write-Host ("      id=" + $_.id + " amount=" + $_.amount + " cat=" + $_.category + " desc=" + $_.description + " time=" + $_.expense_time) -ForegroundColor Gray
    }
}

$listB = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrB -TimeoutSec 10
Add-Result "S5" "GET /expense B is empty" ($listB.Count -eq 0) ("count=" + $listB.Count)

# S6 history
$histA = Invoke-RestMethod -Uri ($base + "/chat/history?limit=50") -Method Get -Headers $hdrA -TimeoutSec 10
$hasUserMsg = $false
foreach ($m in $histA) {
    if ($m.user_input -and ($m.user_input -match "午饭30")) { $hasUserMsg = $true; break }
}
Add-Result "S6" "history A has lunch" ($histA.Count -ge 1 -and $hasUserMsg) ("count=" + $histA.Count)

# S8 query
$today = Get-Date -Format "yyyy-MM-dd"
$tomorrow = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")
$qA = Invoke-RestMethod -Uri ($base + "/expense/query?start_time=${today}T00:00:00&end_time=${tomorrow}T00:00:00") -Method Get -Headers $hdrA -TimeoutSec 10
$ok = ($qA.total_amount -ge 30) -and ($qA.expense_count -ge 1)
Add-Result "S8" "query A today >=30" $ok ("total=" + $qA.total_amount + " count=" + $qA.expense_count)

$qB = Invoke-RestMethod -Uri ($base + "/expense/query?start_time=${today}T00:00:00&end_time=${tomorrow}T00:00:00") -Method Get -Headers $hdrB -TimeoutSec 10
Add-Result "S8" "query B is 0" (($qB.total_amount -eq 0) -and ($qB.expense_count -eq 0)) ("total=" + $qB.total_amount + " count=" + $qB.expense_count)

# S9 summary
$s = Invoke-RestMethod -Uri ($base + "/summary") -Method Get -Headers $hdrA -TimeoutSec 10
Add-Result "S9" "summary A total>=30" ($s.total_amount -ge 30) ("total=" + $s.total_amount + " count=" + $s.expense_count)

$yr = (Get-Date).Year; $mo = (Get-Date).Month
$m = Invoke-RestMethod -Uri ($base + "/expense/month?year=$yr&month=$mo") -Method Get -Headers $hdrA -TimeoutSec 10
Add-Result "S9" "month A >=30" ($m.total_amount -ge 30) ("total=" + $m.total_amount + " count=" + $m.expense_count)

# S10 KEY: B asks "how much today"
$chatB = Post-Body ($base + "/chat") $hdrB (Join-Path $bodiesDir "b_query.json")
$replyB = $chatB.answer
$numHits = [regex]::Matches($replyB, "\d+(\.\d+)?")
$mentionsThirty = $false
foreach ($n in $numHits) { if ([double]$n.Value -eq 30.0) { $mentionsThirty = $true; break } }
Add-Result "S10" "B AI reply excludes 30" (-not $mentionsThirty) ("reply_len=" + $replyB.Length)

# S12 re-login
$lA2 = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -Body (@{username=$userA; password=$passA} | ConvertTo-Json) -TimeoutSec 10
$tokA2 = $lA2.access_token
$listA2 = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers @{Authorization="Bearer " + $tokA2} -TimeoutSec 10
Add-Result "S12" "new A token reads A" (($listA2.Count -ge 1) -and ($tokA2 -ne $tokA)) ("new_diff=" + ($tokA2 -ne $tokA) + " A_count=" + $listA2.Count)

# S13 B records dinner
$chatB2 = Post-Body ($base + "/chat") $hdrB (Join-Path $bodiesDir "b_dinner.json")
Start-Sleep -Seconds 2
$listB2 = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrB -TimeoutSec 10
$listA3 = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrA -TimeoutSec 10
$bHasLunch = $false; $aHasDinner = $false
foreach ($e in $listB2) { if ($e.description -match "午饭") { $bHasLunch = $true } }
foreach ($e in $listA3) { if ($e.description -match "晚饭") { $aHasDinner = $true } }
Add-Result "S13" "B list no A lunch" (-not $bHasLunch) ("B_count=" + $listB2.Count)
Add-Result "S13" "A list no B dinner" (-not $aHasDinner) ("A_count=" + $listA3.Count)
if ($listB2.Count -gt 0) {
    Write-Host "    [B expenses]" -ForegroundColor Gray
    $listB2 | ForEach-Object { Write-Host ("      id=" + $_.id + " amount=" + $_.amount + " desc=" + $_.description) -ForegroundColor Gray }
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
$results | Format-Table Step,Name,Result,Detail -AutoSize -Wrap
$passCount = $results.Count - $failures
Write-Host ("Passed: " + $passCount + " / Failed: " + $failures) -ForegroundColor $(if($failures -eq 0){"Green"}else{"Red"})

if ($failures -gt 0) { exit 1 } else { exit 0 }