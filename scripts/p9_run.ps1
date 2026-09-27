# Phase 9 in one go: rebuild, test, create the Faversham revision, run the eval.
#   powershell -ExecutionPolicy Bypass -File scripts/p9_run.ps1
$ErrorActionPreference = "Stop"
docker compose up -d --build
Start-Sleep -Seconds 15
docker compose exec api python -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "tests failed, stopping"; exit 1 }

# tag organisations (safe to re-run)
docker compose exec db psql -U policypilot -c "UPDATE documents SET organisation='Faversham Town Council' WHERE policy_key LIKE 'faversham%' AND organisation IS NULL; UPDATE documents SET organisation='East Dunbartonshire Council' WHERE policy_key LIKE 'east%' AND organisation IS NULL; UPDATE documents SET organisation='University of Liverpool' WHERE policy_key LIKE 'uol%' AND organisation IS NULL;"

# create the 2025 revision only if it doesn't exist yet
$fav = (docker compose exec -T db psql -U policypilot -tA -c "SELECT id FROM documents WHERE policy_key LIKE 'faversham%' AND is_current ORDER BY id LIMIT 1").Trim()
$ver = (docker compose exec -T db psql -U policypilot -tA -c "SELECT version FROM documents WHERE id=$fav").Trim()
if ($ver -eq "1") {
  docker compose exec api python scripts/make_revision.py --document-id $fav
} else { Write-Host "Faversham is already at version $ver, skipping revision" }

docker compose exec api python -m evals.run --name p9_versions --rerank-strategy cross_fused --rerank-model cross-encoder/ms-marco-MiniLM-L-6-v2
docker compose exec -T db psql -U policypilot -c "SELECT id, policy_key, version, is_current, organisation FROM documents ORDER BY policy_key, version"
