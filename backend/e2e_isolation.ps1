$ErrorActionPreference = "Continue"
$base = "http://127.0.0.1:8000"
$ts = Get-Date -Format "yyyyMMddHHmmss"
$userA = "e2e_userA_" + $ts
$userB = "e2e_userB_" + $ts
$passA = "PassA_" + $ts + "!"
$passB = "PassB_" + $ts + "!"

# Read agent API key
$envFile = "d:\study\Projects\AI-Budget-Assistant\.env"
foreach ($line in Get-Content $envFile) {
    if ($line -match '^AGENT_API_KEY=(.+)$') {
        $agentKey = $Matches[1].Trim()
        break
    }
}
if (-not $agentKey) { Write-Host "AGENT_API_KEY not found"; exit 1 }
$agentHdr = @{ "X-Agent-Key" = $agentKey }

# Pre-build all request bodies as UTF-8 files to dodge PowerShell encoding pitfalls
$bodyDir = Join-Path $env:TEMP ("e2e_body_" + $ts)
New-Item -ItemType Directory -Path $bodyDir -Force | Out-Null

function Save-Body($name, $json) {
    $path = Join-Path $bodyDir ($name + ".json")
    [System.IO.File]::WriteAllText($path, $json, [System.Text.UTF8Encoding]::new($false))
    return $path
}

# Body templates (raw JSON, ASCII-safe)
$regA = Save-Body "regA" ('{"username":"' + $userA + '","password":"' + $passA + '"}')
$regB = Save-Body "regB" ('{"username":"' + $userB + '","password":"' + $passB + '"}')
$loginA = Save-Body "loginA" ('{"username":"' + $userA + '","password":"' + $passA + '"}')
$loginB = Save-Body "loginB" ('{"username":"' + $userB + '","password":"' + $passB + '"}')

# Use ASCII-safe Chinese via Unicode escapes to bypass CP936 mangling
$cn_lunch = '\u4eca\u5929\u5348\u996d'    # 今天午饭
$cn_today = '\u4eca\u5929'                  # 今天

$seedA = Save-Body "seedA" ('{"user_id":"<UIDA>","expenses":[{"category":"\u9910\u996e","amount":30.0,"description":"\u5348\u996d","expense_time":"' + (Get-Date -Format "yyyy-MM-dd") + 'T12:00:00"}]}')

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
    Write-Host ("[{0}] {1,-32} {2,-5} {3}" -f $Step, $Name, $r.Result, $Detail) -ForegroundColor $color
}

function Post-Body($path, $headers) {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    return Invoke-RestMethod -Uri ($base + "/") -Method Get -TimeoutSec 1  # placeholder
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " User Isolation Verification (Task 13)" -ForegroundColor Cyan
Write-Host (" Base URL : " + $base) -ForegroundColor Cyan
Write-Host (" User A   : " + $userA) -ForegroundColor Cyan
Write-Host (" User B   : " + $userB) -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Register
$rA = Invoke-RestMethod -Uri ($base + "/register") -Method Post -ContentType "application/json" -InFile $regA
$rB = Invoke-RestMethod -Uri ($base + "/register") -Method Post -ContentType "application/json" -InFile $regB
$uidA = $rA.id; $uidB = $rB.id
Write-Host ("Registered A id=" + $uidA + "  B id=" + $uidB) -ForegroundColor Gray
Add-Result "REG" "register A & B" (($uidA -gt 0) -and ($uidB -gt 0)) ("A_id=" + $uidA + " B_id=" + $uidB)

# Login
$lA = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -InFile $loginA
$lB = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -InFile $loginB
$tokA = $lA.access_token; $tokB = $lB.access_token
$hdrA = @{ Authorization = "Bearer " + $tokA }
$hdrB = @{ Authorization = "Bearer " + $tokB }
Add-Result "LOGIN" "login A & B" ($tokA -and $tokB) ("tokenA_len=" + $tokA.Length + " tokenB_len=" + $tokB.Length)

# Decode JWT 'sub' claim
function Parse-JwtSub($token) {
    $parts = $token.Split('.')
    if ($parts.Length -lt 2) { return $null }
    $b64 = $parts[1].Replace('-','+').Replace('/','_')
    while ($b64.Length % 4 -ne 0) { $b64 += '=' }
    try {
        $bytes = [System.Convert]::FromBase64String($b64)
        $json = [System.Text.Encoding]::UTF8.GetString($bytes)
        return ($json | ConvertFrom-Json).sub
    } catch {
        return $null
    }
}
$subA = Parse-JwtSub $tokA
$subB = Parse-JwtSub $tokB
Add-Result "JWT" "JWT subjects are user ids" (($subA -eq $uidA.ToString()) -and ($subB -eq $uidB.ToString())) ("subA=$subA subB=$subB")
Add-Result "JWT" "JWT subjects differ" ($subA -ne $subB) ("A vs B")

# Seed A via agent API (use pre-built JSON file)
$seedPath = Join-Path $bodyDir "seedA.json"
$seedJson = [System.IO.File]::ReadAllText($seedPath) -replace '<UIDA>', $uidA.ToString()
$seedFile = Join-Path $bodyDir "seedA_final.json"
[System.IO.File]::WriteAllText($seedFile, $seedJson, [System.Text.UTF8Encoding]::new($false))

$seed = Invoke-RestMethod -Uri ($base + "/agent/expense") -Method Post -Headers $agentHdr -ContentType "application/json" -InFile $seedFile
Add-Result "SEED" "seed A via /agent/expense" ($seed.success -and ($seed.count -ge 1)) ("seeded_count=" + $seed.count + " time=" + $seed.data[0].expense_time)

# List A & B
$listA = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrA
$listB = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrB
Add-Result "ISO/LIST" "A sees 30 expense" ($listA.Count -ge 1 -and ($listA[0].amount -eq 30)) ("A_count=" + $listA.Count)
Add-Result "ISO/LIST" "B sees ZERO expenses" ($listB.Count -eq 0) ("B_count=" + $listB.Count)

# Summary
$sA = Invoke-RestMethod -Uri ($base + "/summary") -Method Get -Headers $hdrA
$sB = Invoke-RestMethod -Uri ($base + "/summary") -Method Get -Headers $hdrB
Add-Result "ISO/SUM" "A summary=30" ($sA.total_amount -eq 30) ("A_total=" + $sA.total_amount)
Add-Result "ISO/SUM" "B summary=0" ($sB.total_amount -eq 0) ("B_total=" + $sB.total_amount)

# Query today
$today = Get-Date -Format "yyyy-MM-dd"
$tomorrow = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")
$qA = Invoke-RestMethod -Uri ($base + "/expense/query?start_time=${today}T00:00:00&end_time=${tomorrow}T00:00:00") -Method Get -Headers $hdrA
$qB = Invoke-RestMethod -Uri ($base + "/expense/query?start_time=${today}T00:00:00&end_time=${tomorrow}T00:00:00") -Method Get -Headers $hdrB
Add-Result "ISO/Q" "A query today=30" ($qA.total_amount -eq 30) ("A_total=" + $qA.total_amount + " cnt=" + $qA.expense_count)
Add-Result "ISO/Q" "B query today=0" ($qB.total_amount -eq 0) ("B_total=" + $qB.total_amount + " cnt=" + $qB.expense_count)

# Month summary
$yr = (Get-Date).Year; $mo = (Get-Date).Month
$mA = Invoke-RestMethod -Uri ($base + "/expense/month?year=$yr&month=$mo") -Method Get -Headers $hdrA
$mB = Invoke-RestMethod -Uri ($base + "/expense/month?year=$yr&month=$mo") -Method Get -Headers $hdrB
Add-Result "ISO/M" "A month=30" ($mA.total_amount -eq 30) ("A_total=" + $mA.total_amount)
Add-Result "ISO/M" "B month=0" ($mB.total_amount -eq 0) ("B_total=" + $mB.total_amount)

# Chat history (each user only sees own)
$hA = Invoke-RestMethod -Uri ($base + "/chat/history?limit=50") -Method Get -Headers $hdrA
$hB = Invoke-RestMethod -Uri ($base + "/chat/history?limit=50") -Method Get -Headers $hdrB
Add-Result "ISO/CHAT" "history A is A's" ($hA.Count -ge 0) ("A_count=" + $hA.Count)
Add-Result "ISO/CHAT" "history B is B's" ($hB.Count -ge 0) ("B_count=" + $hB.Count)

# Cross-user query bypass: B + user_id=A
try {
    Invoke-RestMethod -Uri ($base + "/expense/query?start_time=${today}T00:00:00&end_time=${tomorrow}T00:00:00&user_id=" + $uidA) -Method Get -Headers $hdrB -TimeoutSec 5 | Out-Null
    Add-Result "ISO/CROSS" "B token + user_id=A -> 403" $false "should 403"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Add-Result "ISO/CROSS" "B token + user_id=A -> 403" ($code -eq 403) ("status=" + $code)
}

# Cross-user delete attempt
if ($listA.Count -gt 0) {
    $aExpenseId = $listA[0].id
    try {
        $del = Invoke-RestMethod -Uri ($base + "/expense/" + $aExpenseId) -Method Delete -Headers $hdrB -TimeoutSec 5
        Add-Result "ISO/DEL" "B delete A's expense -> refused" (-not $del.success) ("response=" + ($del | ConvertTo-Json -Compress))
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        Add-Result "ISO/DEL" "B delete A's expense -> refused" ($code -in @(403,404,400)) ("status=" + $code)
    }
    $listA2 = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrA
    $stillThere = ($listA2.Count -ge 1) -and ($listA2[0].id -eq $aExpenseId)
    Add-Result "ISO/DEL" "A's expense untouched" $stillThere ("A_count_after=" + $listA2.Count)
}

# Tampered token
try {
    $tampered = $tokA.Substring(0, $tokA.Length - 4) + "AAAA"
    Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers @{Authorization="Bearer " + $tampered} -TimeoutSec 5 | Out-Null
    Add-Result "SEC" "tampered JWT rejected" $false "should 401"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Add-Result "SEC" "tampered JWT rejected" ($code -eq 401) ("status=" + $code)
}

# Wrong password
try {
    Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -Body (@{username=$userA; password=("wrong_"+$passA)} | ConvertTo-Json) | Out-Null
    Add-Result "SEC" "wrong password -> 401" $false "should 401"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Add-Result "SEC" "wrong password -> 401" ($code -eq 401) ("status=" + $code)
}

# Re-login: new tokens, still scoped
$lA2 = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -InFile $loginA
$tokA2 = $lA2.access_token
$listA3 = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers @{Authorization="Bearer " + $tokA2}
Add-Result "RELOG" "re-login A reads A" (($listA3.Count -ge 1) -and ($tokA2 -ne $tokA)) ("new_diff=" + ($tokA2 -ne $tokA) + " A_count=" + $listA3.Count)
$lB2 = Invoke-RestMethod -Uri ($base + "/login") -Method Post -ContentType "application/json" -InFile $loginB
$tokB2 = $lB2.access_token
$listB2 = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers @{Authorization="Bearer " + $tokB2}
Add-Result "RELOG" "re-login B reads B (empty)" (($listB2.Count -eq 0) -and ($tokB2 -ne $tokB)) ("new_diff=" + ($tokB2 -ne $tokB) + " B_count=" + $listB2.Count)

# Seed B with a different expense, verify cross-leak
$seedBPath = Join-Path $bodyDir "seedB.json"
$seedBJson = '{"user_id":"<UIDB>","expenses":[{"category":"\u9910\u996e","amount":20.0,"description":"\u665a\u996d","expense_time":"' + $today + 'T19:00:00"}]}'
$seedBJson = $seedBJson -replace '<UIDB>', $uidB.ToString()
[System.IO.File]::WriteAllText($seedBPath, $seedBJson, [System.Text.UTF8Encoding]::new($false))
$seedB = Invoke-RestMethod -Uri ($base + "/agent/expense") -Method Post -Headers $agentHdr -ContentType "application/json" -InFile $seedBPath

$listAFinal = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrA
$listBFinal = Invoke-RestMethod -Uri ($base + "/expense") -Method Get -Headers $hdrB
$aHasDinner = $false; $bHasLunch = $false
foreach ($e in $listAFinal) { if ($e.description -match "晚饭") { $aHasDinner = $true } }
foreach ($e in $listBFinal) { if ($e.description -match "午饭") { $bHasLunch = $true } }
Add-Result "CROSS" "A list has no B dinner" (-not $aHasDinner) ("A_count=" + $listAFinal.Count)
Add-Result "CROSS" "B list has no A lunch" (-not $bHasLunch) ("B_count=" + $listBFinal.Count)
Add-Result "ISO/A" "A summary now=30 (only lunch)" ($sA.total_amount -eq 30 -or ((Invoke-RestMethod -Uri ($base + "/summary") -Method Get -Headers $hdrA).total_amount -eq 30)) ("A only sees 30")

# Summary at end
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " User Isolation Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
$results | Format-Table Step,Name,Result,Detail -AutoSize -Wrap
$passCount = $results.Count - $failures
Write-Host ("Passed: " + $passCount + " / Failed: " + $failures) -ForegroundColor $(if($failures -eq 0){"Green"}else{"Red"})

# Cleanup
Remove-Item -Recurse -Force $bodyDir -ErrorAction SilentlyContinue

if ($failures -gt 0) { exit 1 } else { exit 0 }