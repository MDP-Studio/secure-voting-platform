<#
Test script for login human-check behaviors.
Usage (PowerShell):
  .\scripts\test_login_automated.ps1 -BaseUrl http://127.0.0.1:5000

This script runs three tests:
  1) POST with no nonce and curl-like User-Agent (expect human-verification rejection)
  2) POST with gotcha field populated (expect GOTCHA rejection)
  3) Fetch /login-nonce then POST with browser-like headers (expect nonce accepted; next failure may be invalid password or user-not-found)
After tests it optionally fetches /metrics to show counter values.
#>

param(
  [string]$BaseUrl = "http://127.0.0.1:5000",
  [switch]$ShowMetrics
)

function Show-Result($name, $resp) {
  Write-Host "--- $name ---" -ForegroundColor Cyan
  Write-Host "StatusCode: $($resp.StatusCode)"
  $text = $resp.Content
  if ($text.Length -gt 1000) { $snippet = $text.Substring(0,1000) + "..." } else { $snippet = $text }
  Write-Host $snippet
  Write-Host "`n"
}

try {
  # Test 1: No nonce, CLI UA
  $form = @{ username='testuser'; password='x' }
  $headers = @{ 'User-Agent'='curl/7.85.0' }
  $r1 = Invoke-WebRequest -Uri "$BaseUrl/login" -Method POST -Body $form -Headers $headers -UseBasicParsing -ErrorAction Stop
  Show-Result "No-nonce with curl UA" $r1
} catch {
  Write-Host "No-nonce test error: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
  # Test 2: Gotcha filled
  $form2 = @{ username='testuser'; password='x'; gotcha='botfilled' }
  $r2 = Invoke-WebRequest -Uri "$BaseUrl/login" -Method POST -Body $form2 -UseBasicParsing -ErrorAction Stop
  Show-Result "Gotcha-filled" $r2
} catch {
  Write-Host "Gotcha test error: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
  # Test 3: Fetch nonce then post with browser-like headers
  $sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $nresp = Invoke-WebRequest -Uri "$BaseUrl/login-nonce" -WebSession $sess -UseBasicParsing -ErrorAction Stop
  $json = $nresp.Content | ConvertFrom-Json
  $nonce = $json.nonce
  Write-Host "Fetched nonce: $nonce" -ForegroundColor Green

  $form3 = @{ username='testuser'; password='x'; login_nonce=$nonce }
  $headers3 = @{ 'User-Agent'='Mozilla/5.0 (Windows NT 10.0; Win64; x64)'; 'Origin'=$BaseUrl }
  $r3 = Invoke-WebRequest -Uri "$BaseUrl/login" -Method POST -Body $form3 -WebSession $sess -Headers $headers3 -UseBasicParsing -ErrorAction Stop -AllowRedirect
  Show-Result "Nonce + browser-like headers" $r3
} catch {
  Write-Host "Nonce test error: $($_.Exception.Message)" -ForegroundColor Yellow
}

if ($ShowMetrics) {
  try {
    $m = Invoke-WebRequest -Uri "$BaseUrl/metrics" -UseBasicParsing -ErrorAction Stop
    Write-Host "--- /metrics ---" -ForegroundColor Cyan
    Write-Host $m.Content
  } catch {
    Write-Host "Metrics fetch error: $($_.Exception.Message)" -ForegroundColor Yellow
  }
}
