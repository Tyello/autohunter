#!/usr/bin/env bash
# spec-kit installer (Linux / macOS / WSL / Git Bash)
# Uso:
#   ./install.sh                  -> instala no projeto atual
#   ./install.sh /caminho/repo    -> instala no projeto indicado
#   ./install.sh -g               -> instala globalmente (~/.claude)
#   FORCE=1 ./install.sh          -> sobrescreve agentes existentes

set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$(pwd)"
GLOBAL=0

for arg in "$@"; do
  case "$arg" in
    -g|--global) GLOBAL=1 ;;
    *) TARGET="$arg" ;;
  esac
done

if [ "$GLOBAL" -eq 1 ]; then
  CLAUDE_DIR="$HOME/.claude"
  SCOPE="global (~/.claude)"
else
  [ -d "$TARGET" ] || { echo "Diretório de destino não existe: $TARGET" >&2; exit 1; }
  CLAUDE_DIR="$TARGET/.claude"
  SCOPE="projeto ($TARGET)"
fi

SKILLS_DIR="$CLAUDE_DIR/skills/spec-kit"
AGENTS_DIR="$CLAUDE_DIR/agents"

echo ""
echo "spec-kit installer"
echo "Escopo: $SCOPE"
echo ""

# 1. Skill
mkdir -p "$SKILLS_DIR"
cp "$SKILL_ROOT/SKILL.md" "$SKILLS_DIR/"
cp -r "$SKILL_ROOT/references" "$SKILLS_DIR/"
cp -r "$SKILL_ROOT/agents" "$SKILLS_DIR/"
echo "[ok] Skill instalada em $SKILLS_DIR"

# 2. Subagentes
mkdir -p "$AGENTS_DIR"
for a in "$SKILL_ROOT"/agents/*.md; do
  name="$(basename "$a")"
  if [ -e "$AGENTS_DIR/$name" ] && [ "${FORCE:-0}" != "1" ]; then
    echo "[pulado] $name já existe em .claude/agents (FORCE=1 para sobrescrever)"
  else
    cp "$a" "$AGENTS_DIR/$name"
    echo "[ok] Agente: $name"
  fi
done

# 3. Estrutura de trabalho (só em projeto)
if [ "$GLOBAL" -eq 0 ]; then
  mkdir -p "$TARGET/specs" && echo "[ok] specs/ pronto"
  if [ ! -e "$TARGET/SPEC-LESSONS.md" ]; then
    cat > "$TARGET/SPEC-LESSONS.md" << 'EOF'
# SPEC-LESSONS — lições colhidas pelo spec-kit

Formato: - [data | origem | verificada|não verificada] lição em 1-3 linhas + beco descartado, se houver.
Poda: acima de ~40 lições, consolidar (promover recorrentes à constituição, deletar obsoletas).
Nunca registrar valores de segredos — apenas onde encontrá-los.
EOF
    echo "[ok] SPEC-LESSONS.md (semente) criado"
  fi
  [ -e "$TARGET/SPEC-CONSTITUTION.md" ] || echo "[aviso] SPEC-CONSTITUTION.md não encontrado — opcional, mas recomendado."
fi

echo ""
echo "Instalação concluída."
echo "Verifique no Claude Code com: /agents (devem aparecer os 5 agentes spec-*)"
echo "Uso: peça qualquer tarefa de código normalmente, ou 'usando o spec-kit, <tarefa>'."
