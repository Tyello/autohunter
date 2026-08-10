# spec-kit installer (Windows / PowerShell)
# Uso:
#   .\install.ps1                     -> instala no projeto atual (.claude/ do diretório corrente)
#   .\install.ps1 -Target C:\repo    -> instala no projeto indicado
#   .\install.ps1 -Global             -> instala globalmente (~/.claude), vale para todos os projetos
#   .\install.ps1 -Force              -> sobrescreve arquivos existentes sem perguntar

param(
    [string]$Target = (Get-Location).Path,
    [switch]$Global,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# Raiz da skill = pasta pai deste script
$SkillRoot = Split-Path -Parent $PSScriptRoot

if ($Global) {
    $ClaudeDir = Join-Path $HOME ".claude"
    $Scope = "global (~/.claude)"
} else {
    if (-not (Test-Path $Target)) { Write-Error "Diretório de destino não existe: $Target" }
    $ClaudeDir = Join-Path $Target ".claude"
    $Scope = "projeto ($Target)"
}

$SkillsDir = Join-Path $ClaudeDir "skills\spec-kit"
$AgentsDir = Join-Path $ClaudeDir "agents"

Write-Host ""
Write-Host "spec-kit installer" -ForegroundColor Cyan
Write-Host "Escopo: $Scope"
Write-Host ""

# 1. Skill (SKILL.md + references + agents de referência)
New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null
Copy-Item -Path (Join-Path $SkillRoot "SKILL.md") -Destination $SkillsDir -Force
Copy-Item -Path (Join-Path $SkillRoot "references") -Destination $SkillsDir -Recurse -Force
Copy-Item -Path (Join-Path $SkillRoot "agents") -Destination $SkillsDir -Recurse -Force
Write-Host "[ok] Skill instalada em $SkillsDir"

# 2. Subagentes (é isso que o Claude Code carrega de fato)
New-Item -ItemType Directory -Force -Path $AgentsDir | Out-Null
$agents = Get-ChildItem (Join-Path $SkillRoot "agents") -Filter "*.md"
foreach ($a in $agents) {
    $dest = Join-Path $AgentsDir $a.Name
    if ((Test-Path $dest) -and (-not $Force)) {
        Write-Host "[pulado] $($a.Name) já existe em .claude\agents (use -Force para sobrescrever)" -ForegroundColor Yellow
    } else {
        Copy-Item $a.FullName $dest -Force
        Write-Host "[ok] Agente: $($a.Name)"
    }
}

# 3. Estrutura de trabalho no projeto (só em instalação de projeto)
if (-not $Global) {
    $SpecsDir = Join-Path $Target "specs"
    if (-not (Test-Path $SpecsDir)) {
        New-Item -ItemType Directory -Path $SpecsDir | Out-Null
        Write-Host "[ok] Criado specs/"
    }
    $Lessons = Join-Path $Target "SPEC-LESSONS.md"
    if (-not (Test-Path $Lessons)) {
        @"
# SPEC-LESSONS — lições colhidas pelo spec-kit

Formato: - [data | origem | verificada|não verificada] lição em 1-3 linhas + beco descartado, se houver.
Poda: acima de ~40 lições, consolidar (promover recorrentes à constituição, deletar obsoletas).
Nunca registrar valores de segredos — apenas onde encontrá-los.
"@ | Set-Content -Path $Lessons -Encoding UTF8
        Write-Host "[ok] Criado SPEC-LESSONS.md (semente)"
    }
    if (-not (Test-Path (Join-Path $Target "SPEC-CONSTITUTION.md"))) {
        Write-Host "[aviso] SPEC-CONSTITUTION.md não encontrado — opcional, mas recomendado." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Instalação concluída." -ForegroundColor Green
Write-Host "Verifique no Claude Code com: /agents  (devem aparecer spec-executor, spec-reviewer, spec-reviewer-senior, spec-resolver, spec-verifier)"
Write-Host "Uso: peça qualquer tarefa de código normalmente, ou 'usando o spec-kit, <tarefa>'."
