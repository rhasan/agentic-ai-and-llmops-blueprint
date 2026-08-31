# Export the Zscaler root certificate from the Windows trust store into certs/,
# so the app image can trust the TLS-inspecting proxy for outbound HTTPS to
# cloud model providers. Only needed on machines behind Zscaler. Safe to re-run;
# no-ops if none found.
#
# Usage: powershell -ExecutionPolicy Bypass -File infra/serving/setup-cert.ps1
$ErrorActionPreference = "Stop"

$dir = Join-Path $PSScriptRoot "certs"
New-Item -ItemType Directory -Force $dir | Out-Null

$cert = Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root |
        Where-Object { $_.Subject -like "*Zscaler Root CA*" } |
        Select-Object -First 1

if (-not $cert) {
    Write-Warning "No 'Zscaler Root CA' found in the trust store. Nothing to export."
    exit 0
}

$b = [Convert]::ToBase64String($cert.RawData, "InsertLineBreaks")
$out = Join-Path $dir "zscaler-root-ca.crt"
"-----BEGIN CERTIFICATE-----`n$b`n-----END CERTIFICATE-----" | Out-File -Encoding ascii $out

Write-Output ("Exported " + $cert.Subject)
Write-Output ("  -> $out  (expires " + $cert.NotAfter + ")")
