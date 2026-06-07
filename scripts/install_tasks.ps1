# ============================================================================
# install_tasks.ps1 — registra as tarefas no Windows Task Scheduler.
#
# Cria 2 tarefas que, juntas, dão a resiliência pedida:
#   1. ResearchDeOpcoes_Hourly   -> de hora em hora, 10h–17h, seg–sex.
#        -StartWhenAvailable  = se o PC estava DESLIGADO na hora marcada,
#                               roda assim que ligar (CATCH-UP pós-reboot).
#        -RestartCount 3      = se a tarefa falhar (bug), tenta de novo
#                               a cada 1 min, até 3x (resiliência a bugs).
#   2. ResearchDeOpcoes_AtStartup -> roda 1x na inicialização do Windows
#        (cobre reinício no meio do pregão). O /market/status garante no-op
#        fora do horário.
#
# Uso (PowerShell como Administrador, na raiz do repo):
#   .\scripts\install_tasks.ps1
# ============================================================================
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $repo "scripts\run_once.bat"

$action = New-ScheduledTaskAction -Execute $runner -WorkingDirectory $repo

# --- Trigger horário 10h–17h, seg–sex (repetição a cada 1h por 7h) ---
$hourly = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:00am
$rep = (New-ScheduledTaskTrigger -Once -At 10:00am `
        -RepetitionInterval (New-TimeSpan -Hours 1) `
        -RepetitionDuration (New-TimeSpan -Hours 7)).Repetition
$hourly.Repetition = $rep

$startup = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew `
    -DontStopOnIdleEnd

Register-ScheduledTask -TaskName "ResearchDeOpcoes_Hourly" `
    -Action $action -Trigger $hourly -Settings $settings -Force `
    -Description "Motor de opções (Escudo+Radar) — horário, com catch-up e restart."

Register-ScheduledTask -TaskName "ResearchDeOpcoes_AtStartup" `
    -Action $action -Trigger $startup -Settings $settings -Force `
    -Description "Motor de opções — catch-up na inicialização do Windows."

Write-Host "Tarefas registradas. Verifique em 'Agendador de Tarefas'." -ForegroundColor Green
