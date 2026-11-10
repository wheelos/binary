#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 ]]; then
  echo "Usage: $0 <archive.tar.gz> <release/public/library/version/platform[/variant]>" >&2
  exit 1
fi

archive="$(realpath "$1")"
prefix="${2%/}"
name="$(basename "${archive}")"
if [[ ! "${prefix}" =~ ^release/public/[0-9A-Za-z._-]+(/[0-9A-Za-z._-]+)+$ ]] \
  || [[ "/${prefix}/" == *"/../"* || "/${prefix}/" == *"/./"* ]] \
  || [[ ! "${name}" =~ ^[0-9A-Za-z._-]+\.tar\.gz$ ]]; then
  echo "Invalid public release prefix or archive name" >&2
  exit 1
fi

# Accept only the sidecar for this archive, not arbitrary paths from its contents.
read -r digest checksum_name < "${archive}.sha256"
if [[ ! "${digest}" =~ ^[0-9a-f]{64}$ || "${checksum_name}" != "${name}" ]] \
  || [[ "$(wc -l < "${archive}.sha256")" -ne 1 ]]; then
  echo "Invalid SHA256 sidecar: ${archive}.sha256" >&2
  exit 1
fi
printf '%s  %s\n' "${digest}" "${archive}" | sha256sum --check -

export AWS_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID:-${AWS_ACCESS_KEY_ID:-}}"
export AWS_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY:-${AWS_SECRET_ACCESS_KEY:-}}"
export AWS_DEFAULT_REGION=auto AWS_REGION=auto AWS_EC2_METADATA_DISABLED=true AWS_PAGER=""
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
account="${R2_ACCOUNT_ID:-${CF_ACCOUNT_ID:-}}"
bucket="${R2_BUCKET_NAME:-${R2_BUCKET:-wheelos-assets}}"
: "${AWS_ACCESS_KEY_ID:?R2_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?R2_SECRET_ACCESS_KEY is required}"
: "${account:?R2_ACCOUNT_ID is required}"
endpoint="https://${account}.r2.cloudflarestorage.com"
public_url="${PUBLIC_DOWNLOAD_BASE_URL:-https://dl.wheelos.cn}"
public_url="${public_url%/}/${prefix}/${name}"

for suffix in "" ".sha256"; do
  key="${prefix}/${name}${suffix}"
  if error="$(aws --endpoint-url "${endpoint}" s3api head-object \
    --bucket "${bucket}" --key "${key}" 2>&1)"; then
    echo "Refusing to overwrite existing release object: ${key}" >&2
    exit 1
  else
    status=$?
    if [[ "${error}" != *"(404)"* && "${error}" != *"Not Found"* ]]; then
      printf '%s\n' "${error}" >&2
      exit "${status}"
    fi
  fi
done

for suffix in "" ".sha256"; do
  aws --endpoint-url "${endpoint}" s3api put-object \
    --bucket "${bucket}" --key "${prefix}/${name}${suffix}" \
    --body "${archive}${suffix}" --if-none-match '*' \
    --cache-control 'public, max-age=31536000, immutable' >/dev/null
done

download_dir="$(mktemp -d)"
trap 'rm -f -- "${download_dir}/archive" "${download_dir}/checksum"; rmdir -- "${download_dir}"' EXIT
curl --fail --silent --show-error --location --retry 3 \
  "${public_url}" --output "${download_dir}/archive"
printf '%s  %s\n' "${digest}" "${download_dir}/archive" | sha256sum --check -
curl --fail --silent --show-error --location --retry 3 \
  "${public_url}.sha256" --output "${download_dir}/checksum"
cmp "${archive}.sha256" "${download_dir}/checksum"

printf 'Download: %s\nSHA256: %s\nChecksum: %s.sha256\n' "${public_url}" "${digest}" "${public_url}"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    printf '\n### %s\n\n' "${name}"
    printf -- '- Download: [%s](%s)\n' "${name}" "${public_url}"
    printf -- "- SHA256: \`%s\` ([sidecar](%s.sha256))\n" "${digest}" "${public_url}"
  } >> "${GITHUB_STEP_SUMMARY}"
fi
