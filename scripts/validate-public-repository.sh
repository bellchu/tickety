#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

die() { echo "Public repository validation failed: $*" >&2; exit 1; }

tracked=$(git ls-files)

agent_path_pattern='(^|/)(AGENTS|CLAUDE|GEMINI)\.md$|(^|/)(\.cursorrules|\.clinerules|\.windsurfrules)$|(^|/)(\.agents|\.codex|\.claude|\.cursor|\.roo)(/|$)|(^|/)copilot-instructions\.md$'
if grep -Eq "$agent_path_pattern" <<<"$tracked"; then
  die "tracked AI-agent instruction or configuration file"
fi

workspace_agent_files=$(find . \
  \( -path './.git' -o -path './.venv' -o -path '*/node_modules' -o -path '*/.next' -o -path '*/dist' -o -path '*/coverage' -o -path '*/__pycache__' \) -prune -o \
  -type f \( -name AGENTS.md -o -name CLAUDE.md -o -name GEMINI.md -o -name .cursorrules -o -name .clinerules -o -name .windsurfrules -o -name copilot-instructions.md \) -print)
[[ -z $workspace_agent_files ]] || die "workspace contains AI-agent instruction files"

workspace_agent_dirs=$(find . \
  \( -path './.git' -o -path './.venv' -o -path '*/node_modules' -o -path '*/.next' -o -path '*/dist' -o -path '*/coverage' -o -path '*/__pycache__' \) -prune -o \
  -type d \( -name .agents -o -name .codex -o -name .claude -o -name .cursor -o -name .roo \) -print)
[[ -z $workspace_agent_dirs ]] || die "workspace contains AI-agent configuration directories"

if grep -Eiq '(^|/)(AGENTS|CLAUDE|GEMINI)\.md|\.codex|\.agents|\.claude|\.cursor|\.cursorrules|\.clinerules|\.windsurfrules|copilot-instructions' .gitignore; then
  die ".gitignore conceals AI-agent instructions or configuration"
fi

while IFS= read -r path; do
  [[ $path == .env.example ]] && continue
  if [[ $path =~ (^|/)\.env($|\.)|(^|/)(screenshots?|fixtures?|samples?)(/|$)|\.(pem|key|p12|pfx|jks|keystore|db|sqlite3?|dump|bak|backup|log|pen)$ ]]; then
    die "tracked secret or data artifact: $path"
  fi
done <<<"$tracked"

for removed_path in app/backend/seed.py docs/screenshots tickety.pen; do
  [[ ! -e $removed_path ]] || die "retired sample-data artifact remains: $removed_path"
done

secret_pattern='-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\b(AKIA|ASIA)[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bxox[baprs]-[A-Za-z0-9-]{20,}\b|\bsk-[A-Za-z0-9_-]{20,}\b|\bAIza[0-9A-Za-z_-]{35}\b|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'
set +e
git grep -IlP -e "$secret_pattern" -- >/dev/null 2>&1
secret_scan_status=$?
set -e
if [[ $secret_scan_status == 0 ]]; then
  die "a tracked file matches a high-confidence credential signature"
fi
[[ $secret_scan_status == 1 ]] || die "credential scanner failed to execute"

[[ $(git rev-list --all --count) == 1 ]] || die "repository must expose exactly one reachable commit"
[[ $(git rev-list --all --max-parents=0 --count) == 1 ]] || die "repository must expose exactly one root commit"
[[ -z $(git show -s --format=%P HEAD) ]] || die "HEAD must be a root commit with no parent"
[[ $(git log --all --format='%an <%ae>' | sort -u) == 'Tickety Maintainers <opensource@tickety.situ.io>' ]] || die "commit metadata exposes a non-public maintainer identity"

if git fsck --full --no-reflogs --unreachable 2>/dev/null | grep -q .; then
  die "repository object database retains unreachable history objects"
fi

# Customer-specific names, retired hosting references, and the former resolver
# taxonomy must not return through examples, fixtures, documentation, or code.
# Character classes keep this validator from matching its own pattern source.
retired_identity_pattern='N[e]xora|A[c]me|C[o]ntoso|F[a]brikam|dev[.]azure[.]com|visualstudio[.]com|[I]NFRA_(HELPDESK|NETWORK|SYSTEMS|ARCH)|[A]PP_(BUSINESS|RPA|SQL|ERP|ERP_FUNCTIONAL|WMS|LEGACY|WEB|EDI_API|PM)'
for retired_fixture in N'exora' A'cme' C'ontoso' dev'.azure.com/example' I'NFRA_HELPDESK' A'PP_ERP_FUNCTIONAL'; do
  if ! grep -Eiq "$retired_identity_pattern" <<<"$retired_fixture"; then
    die "retired-identity guard does not detect its regression fixtures"
  fi
done
if grep -Eiq "$retired_identity_pattern" <<<'example.freshservice.com'; then
  die "retired-identity guard rejects the neutral example domain"
fi
if git grep -IilE "$retired_identity_pattern" -- >/dev/null 2>&1; then
  die "tracked content contains a retired company, hosting, or resolver identity"
fi

echo "Public repository validation passed."
