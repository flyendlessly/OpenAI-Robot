# PowerShell migration deployment script
param([switch]$DryRun)

Write-Host "=== Database Migration Deployment ===" -ForegroundColor Cyan

# Backup
$backup = "data/billing.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss').db"
if (Test-Path "data/billing.db") {
    Copy-Item "data/billing.db" $backup
    Write-Host "Backup created: $backup" -ForegroundColor Green
}

# Status check
Write-Host "`nChecking migration status..." -ForegroundColor Yellow
python migrations/migrate.py status

# Apply migrations
if (-not $DryRun) {
    Write-Host "`nApplying migrations..." -ForegroundColor Yellow
    python migrations/migrate.py migrate
    Write-Host "`nDeployment completed!" -ForegroundColor Green
} else {
    Write-Host "`nDry run mode - no changes applied" -ForegroundColor Gray
}
