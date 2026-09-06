$ErrorActionPreference = "Continue"
$base = "http://127.0.0.1:8000"
$ts = Get-Date -Format "yyyyMMddHHmmss"
$userA = "e2e_userA_" + $ts
$userB = "e2e_userB_" + $ts
$passA = "PassA_" + $ts + "!"
$passB = "PassB_" + $ts + "!"

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

$chatBodyDir = Join-Path $env:TEMP ("e2e_chatbody_" + (Get-Date -Format "yyyyMMddHHmmss"))
New-Item -ItemType Directory -Path $chatBodyDir -Force | Out-Null
function Save-ChatBody($name, $json) {
    $path = Join-Path $chatBodyDir ($name + ".json")
    [System.IO.File]::WriteAllText($path, $json, [System.Text.UTF8Encoding]::new($false))
    return $path
}
function Post-ChatBody($url, $headers, $bodyPath) {
    $bytes = [System.IO.File]::ReadAllBytes($bodyPath)
    return Invoke-RestMethod -Uri $url -Method Post -ContentType "application/json; charset=utf-8" -Headers $headers -Body $bytes -TimeoutSec 120
}
    Write-Host ("[{0}] {1,-30} {2,-5} {3}" -f $Step, $Name, $r.Result, $Detail) -ForegroundColor $color
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " E2E Full Verification (Task 13)" -ForegroundColor Cyan
Write-Host (" Base URL : " + $base) -ForegroundColor Cyan
Write-Host (" User A   : " + $userA) -ForegroundColor Cyan
Write-Host (" User B   : " + $userB) -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# S1 health
Write-Host "`n[STEP 1] Server health" -ForegroundColor Yellow
try {
    $root = Invoke-RestMethod -Uri ($base + "/") -Method Get -TimeoutSec 5
    Add-Result "S1" "GET /" ($root.message -match "Running") $root.message
} catch { Add-Result "S1" "GET /" $false $_.Exception.Message }

# S2 register
Write-Host "`n[STEP 2] Register A and B" -ForegroundColor Yellow
try {
    $bodyA = (@{username=$userA; password=$passA} | ConvertTo-Json)
    $rA = Invoke-RestMethod -Uri ($base + "/register") -Method Post -ContentType "application/json" -TimeoutSec 10 -Body $bodyA
    Add-Result "S2" "POST /register A" ($rA.id -gt 0) ("id=" + $rA.id + " username=" + $rA.username)
} catch { Add-Result "S2" "POST /register A" $false $_.Exception.Message }
try {
    $bodyB = (@{username=$userB; password=$passB} | ConvertTo-Json)
    $rB = Invoke-RestMethod -Uri ($base + "/register") -Method Post -ContentType "application/json" -TimeoutSec 10 -Body $bodyB
    Add-Result "S2" "POST /register B" ($rB.id -gt 0) ("id=" + $rB.id + " username=" + $rB.username)
} catch { Add-Result "S2" "POST /register B" $false $_.Exception.Message }

# S3 login
Write-Host "`n[STEP 3] Login -> JWT" -ForegroundColor Yellow
$tokA = $null; $tokB = $null
try {
    $lA = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -TimeoutSec 10 -Body (@{username=$userA; password=$passA} | ConvertTo-Json)
    $tokA = $lA.access_token
    Add-Result "S3" "POST /login A" ($tokA -and $tokA.Length -gt 50) ("token_len=" + $tokA.Length)
} catch { Add-Result "S3" "POST /login A" $false $_.Exception.Message }
try {
    $lB = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -TimeoutSec 10 -Body (@{username=$userB; password=$passB} | ConvertTo-Json)
    $tokB = $lB.access_token
    Add-Result "S3" "POST /login B" ($tokB -and $tokB.Length -gt 50) ("token_len=" + $tokB.Length)
} catch { Add-Result "S3" "POST /login B" $false $_.Exception.Message }

if (-not $tokA -or -not $tokB) {
    Write-Host "Missing tokens, aborting." -ForegroundColor Red
    $results | Format-Table -AutoSize
    exit 1
}

$hdrA = @{ Authorization = "Bearer " + $tokA }
$hdrB = @{ Authorization = "Bearer " + $tokB }

# negative: wrong password
try {
    Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -TimeoutSec 10 -Body (@{username=$userA; password=("wrong_" + $passA)} | ConvertTo-Json) | Out-Null
    Add-Result "S3" "wrong pass -> 401" $false "should 401"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Add-Result "S3" "wrong pass -> 401" ($code -eq 401) ("status=" + $code)
}

# negative: no token
try {
    Invoke-RestMethod -Uri ($base + "/expense") -Method Get -TimeoutSec 10 | Out-Null
    Add-Result "S3" "no token -> 401" $false "should 401"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Add-Result "S3" "no token -> 401" ($code -eq 401) ("status=" + $code)
}

# S4-S5 AI chat A
Write-Host "`n[STEP 4-5] AI chat - User A records lunch" -ForegroundColor Yellow
$aiReply = $null
try {
    $cb = Save-ChatBody "a_lunch" (Write-BodyBytes ('{"message":"今天午饭30元"}'))
    $chat = Post-ChatBody ($base + "/chat") $hdrA $cb
    $aiReply = $chat.answer
    Add-Result "S4" "POST /chat A lunch" ($aiReply -and $aiReply.Length -gt 0) ("reply_len=" + $aiReply.Length)
    Write-Host ("    [A reply] " + $aiReply) -ForegroundColor Gray
} catch { Add-Result "S4" "POST /chat A lunch" $false $_.Exception.Message }

Start-Sleep -Seconds 2

try {
    $listA = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrA -TimeoutSec 10
    $hasLunch = $false
    foreach ($e in $listA) {
        if (($e.description -match "lunch|午饭") -or ($e.amount -eq 30)) { $hasLunch = $true; break }
    }
    Add-Result "S5" "GET /expense A has lunch" ($listA.Count -gt 0 -and $hasLunch) ("count=" + $listA.Count + " has=" + $hasLunch)
    if ($listA.Count -gt 0) {
        Write-Host "    [A expenses]" -ForegroundColor Gray
        $listA | ForEach-Object {
            Write-Host ("      id=" + $_.id + " amount=" + $_.amount + " category=" + $_.category + " desc=" + $_.description + " time=" + $_.expense_time) -ForegroundColor Gray
        }
    }
} catch { Add-Result "S5" "GET /expense A" $false $_.Exception.Message }

try {
    $listB = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrB -TimeoutSec 10
    Add-Result "S5" "GET /expense B is empty" ($listB.Count -eq 0) ("count=" + $listB.Count)
} catch { Add-Result "S5" "GET /expense B" $false $_.Exception.Message }

# S6-S7 chat history restore
Write-Host "`n[STEP 6-7] Refresh - chat history restore" -ForegroundColor Yellow
try {
    $histA = Invoke-RestMethod -Uri ($base + "/chat/history?limit=50") -Method Get -Headers $hdrA -TimeoutSec 10
    $hasUserMsg = $false
    foreach ($m in $histA) {
        if ($m.role -eq "user" -and ($m.content -match "lunch 30" -or $m.content -match "午饭30")) { $hasUserMsg = $true; break }
    }
    Add-Result "S6" "history A has lunch" ($histA.Count -ge 2 -and $hasUserMsg) ("count=" + $histA.Count)
    Write-Host ("    [A history count] " + $histA.Count) -ForegroundColor Gray
} catch { Add-Result "S6" "GET history A" $false $_.Exception.Message }

try {
    $histB = Invoke-RestMethod -Uri ($base + "/chat/history?limit=50") -Method Get -Headers $hdrB -TimeoutSec 10
    $bHasA = $false
    foreach ($m in $histB) {
        if ($m.role -eq "user" -and ($m.content -match "lunch 30" -or $m.content -match "午饭30")) { $bHasA = $true; break }
    }
    Add-Result "S6" "history B no A msg" (-not $bHasA) ("count=" + $histB.Count + " leaked=" + $bHasA)
} catch { Add-Result "S6" "GET history B" $false $_.Exception.Message }

# S8 query
Write-Host "`n[STEP 8] Query - User A" -ForegroundColor Yellow
try {
    $today = Get-Date -Format "yyyy-MM-dd"
    $tomorrow = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")
    $url = ($base + "/expense/query?start_time=" + $today + "T00:00:00&end_time=" + $tomorrow + "T00:00:00")
    $q = Invoke-RestMethod -Uri $url -Method Get -Headers $hdrA -TimeoutSec 10
    $ok = ($q.total_amount -ge 30) -and ($q.expense_count -ge 1)
    Add-Result "S8" "query A today >=30" $ok ("total=" + $q.total_amount + " count=" + $q.expense_count)
} catch { Add-Result "S8" "query A" $false $_.Exception.Message }

try {
    $today = Get-Date -Format "yyyy-MM-dd"
    $tomorrow = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")
    $url = ($base + "/expense/query?start_time=" + $today + "T00:00:00&end_time=" + $tomorrow + "T00:00:00")
    $qB = Invoke-RestMethod -Uri $url -Method Get -Headers $hdrB -TimeoutSec 10
    $ok = ($qB.total_amount -eq 0) -and ($qB.expense_count -eq 0)
    Add-Result "S8" "query B is 0" $ok ("total=" + $qB.total_amount + " count=" + $qB.expense_count)
} catch { Add-Result "S8" "query B" $false $_.Exception.Message }

# S9 summary
Write-Host "`n[STEP 9] Statistics" -ForegroundColor Yellow
try {
    $s = Invoke-RestMethod -Uri ($base + "/summary") -Method Get -Headers $hdrA -TimeoutSec 10
    Add-Result "S9" "summary A total>=30" ($s.total_amount -ge 30) ("total=" + $s.total_amount + " count=" + $s.expense_count)
} catch { Add-Result "S9" "summary A" $false $_.Exception.Message }

try {
    $year = (Get-Date).Year; $month = (Get-Date).Month
    $m = Invoke-RestMethod -Uri ($base + "/expense/month?year=" + $year + "&month=" + $month) -Method Get -Headers $hdrA -TimeoutSec 10
    Add-Result "S9" "month A >=30" ($m.total_amount -ge 30) ("total=" + $m.total_amount + " count=" + $m.expense_count)
} catch { Add-Result "S9" "month A" $false $_.Exception.Message }

try {
    $sB = Invoke-RestMethod -Uri ($base + "/summary") -Method Get -Headers $hdrB -TimeoutSec 10
    Add-Result "S9" "summary B is 0" (($sB.total_amount -eq 0) -and ($sB.expense_count -eq 0)) ("total=" + $sB.total_amount + " count=" + $sB.expense_count)
} catch { Add-Result "S9" "summary B" $false $_.Exception.Message }

# S10 critical isolation: User B asks "how much today"
Write-Host "`n[STEP 10] KEY: User B asks 'how much today' must NOT include A's 30" -ForegroundColor Yellow
try {
    $msgBody = (@{ message = "我今天花了多少钱？" } | ConvertTo-Json)
    $chatB = Invoke-RestMethod -Uri ($base + "/chat") -Method Post -ContentType "application/json" -Headers $hdrB -TimeoutSec 120 -Body $msgBody
    $replyB = $chatB.answer
    Write-Host ("    [B reply] " + $replyB) -ForegroundColor Gray
    $numHits = ([regex]::Matches($replyB, "\d+(\.\d+)?"))
    $mentionsThirty = $false
    foreach ($n in $numHits) { if ([double]$n.Value -eq 30.0) { $mentionsThirty = $true; break } }
    Add-Result "S10" "B AI reply excludes 30" (-not $mentionsThirty) ("reply=" + $replyB)
} catch { Add-Result "S10" "POST /chat B" $false $_.Exception.Message }

# S11 fake token
try {
    Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers @{Authorization="Bearer fake.token.value"} -TimeoutSec 10 | Out-Null
    Add-Result "S11" "fake token -> 401" $false "should 401"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Add-Result "S11" "fake token -> 401" ($code -eq 401) ("status=" + $code)
}

# S12 re-login
Write-Host "`n[STEP 12] Re-login A and B (new tokens)" -ForegroundColor Yellow
$tokA2 = $null; $tokB2 = $null
try {
    $lA2 = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -TimeoutSec 10 -Body (@{username=$userA; password=$passA} | ConvertTo-Json)
    $tokA2 = $lA2.access_token
    Add-Result "S12" "login A again" ($tokA2 -and ($tokA2 -ne $tokA)) ("new_len=" + $tokA2.Length)
} catch { Add-Result "S12" "login A again" $false $_.Exception.Message }

try {
    $lB2 = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -TimeoutSec 10 -Body (@{username=$userB; password=$passB} | ConvertTo-Json)
    $tokB2 = $lB2.access_token
    Add-Result "S12" "login B again" ($tokB2 -and ($tokB2 -ne $tokB)) ("new_len=" + $tokB2.Length)
} catch { Add-Result "S12" "login B again" $false $_.Exception.Message }

try {
    $listA2 = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers @{Authorization="Bearer " + $tokA2} -TimeoutSec 10
    Add-Result "S12" "new token reads A" ($listA2.Count -gt 0) ("count=" + $listA2.Count)
} catch { Add-Result "S12" "new token A" $false $_.Exception.Message }

try {
    $listA3 = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrA -TimeoutSec 10
    Add-Result "S12" "old A token still works" ($listA3.Count -gt 0) ("count=" + $listA3.Count)
} catch { Add-Result "S12" "old A token" $false $_.Exception.Message }

# Cross-user query bypass attempt -> 403
try {
    $today = Get-Date -Format "yyyy-MM-dd"
    $tomorrow = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")
    $url = ($base + "/expense/query?start_time=" + $today + "T00:00:00&end_time=" + $tomorrow + "T00:00:00&user_id=1")
    Invoke-RestMethod -Uri $url -Method Get -Headers $hdrB -TimeoutSec 10 | Out-Null
    Add-Result "ISO" "B crosses to A query -> 403" $false "should 403"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Add-Result "ISO" "B crosses to A query -> 403" ($code -eq 403) ("status=" + $code)
}

# S13 B records dinner, cross-check isolation
Write-Host "`n[STEP 13] User B records dinner -> isolation cross-check" -ForegroundColor Yellow
try {
    $msgBody = (@{ message = "今天晚饭20元" } | ConvertTo-Json)
    $chatB2 = Invoke-RestMethod -Uri ($base + "/chat") -Method Post -ContentType "application/json" -Headers $hdrB -TimeoutSec 120 -Body $msgBody
    Write-Host ("    [B reply 2] " + $chatB2.answer) -ForegroundColor Gray
} catch { Add-Result "S13" "B dinner" $false $_.Exception.Message }

Start-Sleep -Seconds 2
try {
    $listB2 = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrB -TimeoutSec 10
    $listA4 = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrA -TimeoutSec 10
    $bHasLunch = $false; $aHasDinner = $false
    foreach ($e in $listB2) { if ($e.description -match "lunch|午饭") { $bHasLunch = $true } }
    foreach ($e in $listA4) { if ($e.description -match "dinner|晚饭") { $aHasDinner = $true } }
    Add-Result "S13" "B list no A lunch" (-not $bHasLunch) ("B_count=" + $listB2.Count)
    Add-Result "S13" "A list no B dinner" (-not $aHasDinner) ("A_count=" + $listA4.Count)
    if ($listB2.Count -gt 0) {
        Write-Host "    [B expenses]" -ForegroundColor Gray
        $listB2 | ForEach-Object {
            Write-Host ("      id=" + $_.id + " amount=" + $_.amount + " desc=" + $_.description) -ForegroundColor Gray
        }
    }
} catch { Add-Result "S13" "cross check" $false $_.Exception.Message }

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
$results | Format-Table Step,Name,Result,Detail -AutoSize -Wrap
$passCount = $results.Count - $failures
Write-Host ("Passed: " + $passCount + " / Failed: " + $failures) -ForegroundColor $(if($failures -eq 0){"Green"}else{"Red"})

if ($failures -gt 0) { exit 1 } else { exit 0 }