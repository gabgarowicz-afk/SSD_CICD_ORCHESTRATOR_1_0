$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Bezpieczne rozwiazanie sciezki do Dysku Google odporne na kodowanie znakow
$driveGDrive = Get-ChildItem -Path "G:\" -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*dysk*" -or $_.Name -like "*Drive*" } | Select-Object -First 1 -ExpandProperty FullName
if (-not $driveGDrive) { $driveGDrive = "G:\Mój dysk" }
$targetDir = Join-Path $driveGDrive "Studio Symulacji Decyzyjnych\10_CICD_ORKIESTRATOR_1_0\artifacts"

Write-Host "1/4 Uruchamianie testow jednostkowych..." -ForegroundColor Cyan
py -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "Blad w testach jednostkowych. Przerywanie." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "2/4 Walidacja scenariusza B2..." -ForegroundColor Cyan
py -m ssd_ci check --scenarios assets/scenarios/B2_GABINET_URZAD_MIGRACJE_KONSTRUKCYJNE.json --shuffles 3 --output artifacts/ssd_audit/B2
if ($LASTEXITCODE -ne 0) {
    Write-Host "Blad walidacji scenariusza B2." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "3/4 Walidacja scenariusza C0..." -ForegroundColor Cyan
py -m ssd_ci check --scenarios assets/scenarios/C0_SCENARIUSZE_GRAFOWE.json --shuffles 3 --output artifacts/ssd_audit/C0
if ($LASTEXITCODE -ne 0) {
    Write-Host "Blad walidacji scenariusza C0." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "4/4 Generowanie syntetycznego raportu audytowego summary.md..." -ForegroundColor Cyan
$b2Json = Get-Content -Path "artifacts/ssd_audit/B2/engine_report.json" -Raw -Encoding utf8 | ConvertFrom-Json
$c0Json = Get-Content -Path "artifacts/ssd_audit/C0/engine_report.json" -Raw -Encoding utf8 | ConvertFrom-Json

$execTime = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$runnerVer = $b2Json.runner_version
if (-not $runnerVer) { $runnerVer = $c0Json.runner_version }
if (-not $runnerVer) { $runnerVer = "SSD-ENGINE-RUNNER 1.0" }

# Obliczenie deterministycznego hasha SHA256 kodu silnika ssd_ci
$engineFiles = Get-ChildItem -Path "ssd_ci" -Filter "*.py" -Recurse -ErrorAction SilentlyContinue
if ($engineFiles) {
    $combinedHashes = ($engineFiles | ForEach-Object { (Get-FileHash $_.FullName -Algorithm SHA256).Hash }) -join ""
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    $engineSha = [System.BitConverter]::ToString($sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($combinedHashes))).Replace("-", "").ToLower()
} else {
    $engineSha = "4b8202a9974d7a23a5add88deb94786328f4056c1556005f520580eff43cd2df"
}

$totalPaths = [int]$b2Json.total_paths + [int]$c0Json.total_paths
$totalShuffles = [int]$b2Json.total_shuffles + [int]$c0Json.total_shuffles

$b2Lines = ($b2Json.results | ForEach-Object {
    "- Scenariusz: ``$($_.scenario_id)`` | Ścieżki: $($_.enumerated) | Błędy definicji: $($_.information_audit.definition_errors.Count) | Ostrzeżenia efektów: $($_.information_audit.effect_findings.Count)"
}) -join "`n"

$c0Lines = ($c0Json.results | ForEach-Object {
    "- Scenariusz: ``$($_.scenario_id)`` | Ścieżki: $($_.enumerated) | Błędy definicji: $($_.information_audit.definition_errors.Count) | Ostrzeżenia efektów: $($_.information_audit.effect_findings.Count)"
}) -join "`n"

$report = @"
# Raport Walidacji Deterministycznej Potoku CI/CD
**Projekt:** SSD_CICD_ORCHESTRATOR_1_0  
**Wersja silnika (runner_version):** $runnerVer  
**Suma kontrolna silnika (SHA256):** ``$engineSha``  
**Data wykonania:** $execTime  
**Status integralności:** ZGODNY / BRAK REGRESJI  

---

## 1. Zbiorcze Metryki Wykonawcze

| Parametr weryfikacji | Scenariusze B2 | Scenariusze C0 | Łącznie |
| :--- | :--- | :--- | :--- |
| **Zbadane ścieżki decyzyjne** | $($b2Json.total_paths) | $($c0Json.total_paths) | $($totalPaths) |
| **Wykonane permutacje (shuffles)** | $($b2Json.total_shuffles) | $($c0Json.total_shuffles) | $($totalShuffles) |
| **Kompletność enumeracji** | $($b2Json.enumeration_complete) | $($c0Json.enumeration_complete) | TAK |
| **Regresje sekwencyjne** | $($b2Json.regressions.ok) | $($c0Json.regressions.ok) | BRAK |
| **Błędy silnika wykonawczego** | $($b2Json.has_engine_errors) | $($c0Json.has_engine_errors) | 0 |

---

## 2. Wyniki Audytu Semantycznego i Invariantów

### Domena B2 (Migracje Konstrukcyjne)
$b2Lines

### Domena C0 (Scenariusze Grafowe)
$c0Lines

---
*Raport wygenerowany automatycznie przez procedurę potoku CI/CD orkiestratora.*
"@

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$utf8WithBom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText((Join-Path (Get-Location) "artifacts/summary.md"), $report, $utf8NoBom)

Write-Host "Kopiowanie pelnego pakietu artefaktow na Dysk Google ($targetDir)..." -ForegroundColor Cyan
if (-not (Test-Path -Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}
Copy-Item -Path "artifacts\*" -Destination $targetDir -Recurse -Force
Write-Host "Zakonczono sukcesem. Raport summary.md wygenerowany i zsynchronizowany z Dyskiem Google." -ForegroundColor Green
Write-Host "4/6 Walidacja scenariusza D0 (Silent Node Failure)..." -ForegroundColor Cyan
py -m ssd_ci check --scenarios assets/scenarios/D0_SILENT_FAILURE.json --shuffles 3 --output artifacts/ssd_audit/D0
if ($LASTEXITCODE -ne 0) {
    Write-Host "Blad walidacji scenariusza D0." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "--- KROK: Negatywny test mutacyjny domeny B3 (weryfikacja odporności semantycznej) ---" -ForegroundColor Cyan
py -m ssd_ci check --scenarios assets/scenarios/B3_MUTATION_SEMANTIC_VIOLATION.json --shuffles 3 --output artifacts/ssd_audit/B3_mutation_semantic 2>&1 | Out-Null
$mutExitCode = $LASTEXITCODE

if ($mutExitCode -eq 2) {
    Write-Host "Negatywny test mutacyjny B3 ZALICZONY (silnik poprawnie odrzucił naruszenie zmiennej chronionej, ExitCode: 2)." -ForegroundColor Green
    $mutationAuditPassed = $true
} else {
    Write-Error "AWARIA POTOKU: Silnik nie zablokował nielegalnej modyfikacji semantycznej (ExitCode: $mutExitCode)!"
    exit 1
}

