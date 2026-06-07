# ============================================================================
# setup.ps1 — prepara o ambiente no Dell (Windows).
#   Uso (PowerShell na raiz do repo):  .\scripts\setup.ps1
# ============================================================================
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host "==> Criando ambiente virtual (.venv)..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv }

Write-Host "==> Instalando dependências..." -ForegroundColor Cyan
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "==> .env criado a partir do exemplo. PREENCHA os segredos!" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "OK. Próximos passos:" -ForegroundColor Green
Write-Host "  1) Edite .env (SPREADSHEET_ID, OPLAB_TOKEN, EMAIL_*)."
Write-Host "  2) Coloque credenciais.json na raiz."
Write-Host "  3) Teste:    .venv\Scripts\python.exe main.py"
Write-Host "  4) Agende:   .\scripts\install_tasks.ps1"
