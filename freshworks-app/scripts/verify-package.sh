#!/usr/bin/env bash
set -euo pipefail

archive="${1:-dist/freshworks-app.zip}"

fail() {
  echo "Freshworks package verification failed: $*" >&2
  exit 1
}

if [[ ! -f "$archive" ]]; then
  fail "archive not found: $archive"
fi

listing_file="$(mktemp "${TMPDIR:-/tmp}/tickety-freshworks-listing.XXXXXX")"
entries_file="$(mktemp "${TMPDIR:-/tmp}/tickety-freshworks-entries.XXXXXX")"
folded_entries_file="$(mktemp "${TMPDIR:-/tmp}/tickety-freshworks-folded-entries.XXXXXX")"
files_file="$(mktemp "${TMPDIR:-/tmp}/tickety-freshworks-files.XXXXXX")"
content_file="$(mktemp "${TMPDIR:-/tmp}/tickety-freshworks-content.XXXXXX")"
trap 'rm -f "$listing_file" "$entries_file" "$folded_entries_file" "$files_file" "$content_file"' EXIT HUP INT TERM

if ! unzip -Z1 "$archive" > "$listing_file"; then
  fail "cannot read ZIP central directory"
fi

# Validate the archive names before extracting anything. FDK writes every ZIP
# entry with exactly one leading "./"; anything else is not an FDK 10 artifact.
while IFS= read -r raw_entry || [[ -n "$raw_entry" ]]; do
  entry="$raw_entry"
  is_directory=0
  if [[ "$entry" == */ ]]; then
    is_directory=1
    entry="${entry%/}"
  fi
  if [[ "$entry" != ./* ]]; then
    fail "missing FDK ./ prefix in archive entry: $raw_entry"
  fi
  entry="${entry#./}"

  if [[ -z "$entry" || "$entry" == /* || "$entry" == . || "$entry" == .. || "$entry" == ./* || "$entry" == ../* || "$entry" == */ || "$entry" == *//* || "$entry" == *\\* || "$entry" == *"/./"* || "$entry" == *"/../"* ]]; then
    fail "non-canonical archive entry: $raw_entry"
  fi
  is_fdk_dot_metadata=0
  if [[ "$entry" == ".report.json" || "$entry" == ".usage.json" ]]; then
    is_fdk_dot_metadata=1
  elif [[ ! "$entry" =~ ^[A-Za-z0-9_][A-Za-z0-9._/-]*$ ]]; then
    fail "unsafe archive entry: $raw_entry"
  fi

  if [[ "$is_fdk_dot_metadata" -eq 0 ]]; then
    IFS='/' read -r -a path_parts <<< "$entry"
    for part in "${path_parts[@]}"; do
      if [[ ! "$part" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]*$ ]]; then
        fail "unsafe archive path segment: $raw_entry"
      fi
    done
  fi

  folded_entry="$(printf '%s' "$entry" | tr '[:upper:]' '[:lower:]')"
  if grep -Fqx "$folded_entry" "$folded_entries_file"; then
    fail "duplicate or case-colliding archive entry: $entry"
  fi
  printf '%s\n' "$entry" >> "$entries_file"
  printf '%s\n' "$folded_entry" >> "$folded_entries_file"
  if [[ "$is_directory" -eq 0 ]]; then
    printf '%s\n' "$entry" >> "$files_file"
  fi
done < "$listing_file"

require_file() {
  local entry="$1"
  if ! grep -Fqx "$entry" "$files_file"; then
    fail "missing required archive file: $entry"
  fi
}

extract_file() {
  local entry="$1"
  if ! unzip -p "$archive" "./$entry" > "$content_file" 2>/dev/null; then
    fail "cannot read archive file: $entry"
  fi
}

validate_static_runtime_surface() {
  local entry="$1"
  if ! node --input-type=module -e '
    import { readFileSync } from "node:fs";

    const entry = process.argv[1];
    const source = readFileSync(0, "utf8");
    const fail = (message) => {
      console.error(message);
      process.exit(1);
    };

    // This retired application is deliberately a closed local bundle, not a
    // general static web page. A remote image, stylesheet, SVG reference, or
    // navigation primitive would make an otherwise non-executable package
    // contact another origin or leave the Freshworks frame. Keep the only two
    // URL-bearing attributes exact and local instead of trying to blacklist
    // every URL spelling.
    if (entry === "app/index.html") {
      if (/<[\t\n\f\r ]*base(?:[\t\n\f\r />]|$)/i.test(source)) {
        fail("base navigation markup found");
      }
      if (/<[\t\n\f\r ]*form(?:[\t\n\f\r />]|$)/i.test(source)) {
        fail("form navigation markup found");
      }
      if (/<[\t\n\f\r ]*meta\b[^>]*\bhttp-equiv[\t\n\f\r ]*=[\t\n\f\r ]*(?:\"[\t\n\f\r ]*refresh[\t\n\f\r ]*\"|\047[\t\n\f\r ]*refresh[\t\n\f\r ]*\047|refresh(?:[\t\n\f\r />]|$))/i.test(source)) {
        fail("meta refresh markup found");
      }

      const allowed = new Map([
        ["href", "styles/styles.css"],
        ["src", "styles/images/icon.svg"],
      ]);
      const urlAttribute = /\b(href|src|action|poster|data|srcset)\s*=\s*(?:\"([^\"]*)\"|\047([^\047]*)\047|([^\s\"\047=<>`]+))/gi;
      for (const match of source.matchAll(urlAttribute)) {
        const attribute = match[1].toLowerCase();
        const value = match[2] ?? match[3] ?? match[4] ?? "";
        if (allowed.get(attribute) !== value) {
          fail(`non-local or unexpected ${attribute} reference found`);
        }
      }
    }

    // Neither the stylesheet nor the SVG needs URL resolution. Reject every
    // CSS URL/import and SVG href/src rather than allowing relative paths that
    // could later be repointed by a base URI or packaging change.
    if (/@import\b|url\s*\(/i.test(source)) {
      fail("external-capable CSS URL markup found");
    }
    if (entry === "app/styles/images/icon.svg" && /\b(?:href|src)\s*=/i.test(source)) {
      fail("SVG resource reference found");
    }
  ' "$entry" < "$content_file"; then
    fail "invalid disabled static navigation contract in $entry"
  fi
}

validate_json() {
  local kind="$1"
  if ! node --input-type=module -e '
    import { readFileSync } from "node:fs";

    const kind = process.argv[1];
    let value;
    try {
      value = JSON.parse(readFileSync(0, "utf8"));
    } catch {
      console.error(`invalid ${kind} JSON`);
      process.exit(1);
    }

    function containsRequestsKey(candidate) {
      if (Array.isArray(candidate)) return candidate.some(containsRequestsKey);
      if (candidate && typeof candidate === "object") {
        return Object.entries(candidate).some(([key, nested]) =>
          key === "requests" || containsRequestsKey(nested),
        );
      }
      return false;
    }

    function hasOnlyStaticLocationReferences(candidate) {
      if (Array.isArray(candidate)) return candidate.every(hasOnlyStaticLocationReferences);
      if (!candidate || typeof candidate !== "object") return true;
      return Object.entries(candidate).every(([key, nested]) => {
        if (key === "url") return nested === "index.html";
        if (key === "icon") return nested === "styles/images/icon.svg";
        return hasOnlyStaticLocationReferences(nested);
      });
    }

    if (kind === "manifest") {
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        console.error("manifest must be a JSON object");
        process.exit(1);
      }
      if (containsRequestsKey(value)) {
        console.error("manifest must not declare request templates");
        process.exit(1);
      }
      if (!hasOnlyStaticLocationReferences(value)) {
        console.error("manifest must point only to static runtime assets");
        process.exit(1);
      }
    } else if (kind === "report") {
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        console.error("report must be a JSON object");
        process.exit(1);
      }
      if ("coverage" in value || "unitTestCoverage" in value) {
        console.error("report must not contain raw coverage payloads");
        process.exit(1);
      }
    } else if (kind === "usage") {
      if (!Array.isArray(value)) {
        console.error("usage must be a JSON array");
        process.exit(1);
      }
    } else if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length !== 0) {
      console.error(`${kind} must be a strictly empty JSON object`);
      process.exit(1);
    }
  ' "$kind" < "$content_file"; then
    fail "invalid disabled-access JSON contract in $kind"
  fi
}

static_runtime_files=(
  manifest.json
  config/iparams.json
  config/requests.json
  app/index.html
  app/styles/styles.css
  app/styles/images/icon.svg
)

fdk_pack_metadata_files=(
  .report.json
  README.md
  package.json
  vitest.config.js
  tests/app.test.js
  tests/static-notice-policy.js
  digest.md5
)

is_allowed_archive_file() {
  local entry="$1"
  local allowed
  for allowed in "${static_runtime_files[@]}" "${fdk_pack_metadata_files[@]}"; do
    if [[ "$entry" == "$allowed" ]]; then
      return 0
    fi
  done
  return 1
}

while IFS= read -r entry || [[ -n "$entry" ]]; do
  if [[ "$entry" != ".usage.json" ]] && ! is_allowed_archive_file "$entry"; then
    fail "unexpected archive file in disabled package: $entry"
  fi
done < "$files_file"

for required in "${static_runtime_files[@]}" "${fdk_pack_metadata_files[@]}"; do
  require_file "$required"
done

extract_file manifest.json
validate_json manifest
for entry in config/iparams.json config/requests.json; do
  extract_file "$entry"
  validate_json "$entry"
done

extract_file .report.json
validate_json report
if grep -Fqx ".usage.json" "$files_file"; then
  extract_file .usage.json
  validate_json usage
fi
extract_file digest.md5
if ! grep -Eq '^[[:xdigit:]]{32}$' "$content_file"; then
  fail "invalid FDK digest"
fi

# With no JavaScript files in the allowlist, reject every remaining executable
# HTML/SVG/CSS construct. This is a capability boundary, not a list of old API
# spellings, so computed-property variants cannot re-enable the platform client.
for entry in app/index.html app/styles/styles.css app/styles/images/icon.svg; do
  extract_file "$entry"
  if grep -Eiq '<[[:space:]]*script([[:space:]>]|/)' "$content_file"; then
    fail "executable script markup found in $entry"
  fi
  if grep -Eiq '<[[:space:]]*(iframe|object|embed)([[:space:]>]|/)' "$content_file"; then
    fail "embedded executable markup found in $entry"
  fi
  if grep -Eiq '(^|[[:space:]/])on[a-z0-9_-]+[[:space:]]*=' "$content_file"; then
    fail "inline event handler found in $entry"
  fi
  if grep -Eiq 'javascript[[:space:]]*:' "$content_file"; then
    fail "JavaScript URI found in $entry"
  fi
  if grep -Fqi '{{{appclient}}}' "$content_file"; then
    fail "Freshworks client template found in $entry"
  fi
  validate_static_runtime_surface "$entry"
done

echo "Freshworks package verified: disabled embedded access surface only"
