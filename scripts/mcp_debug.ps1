# Writes MCP diagnostics to mcp_debug.txt so Claude can read it.
$out = Join-Path (Split-Path -Parent $PSScriptRoot) "mcp_debug.txt"
Set-Location (Split-Path -Parent $PSScriptRoot)
"== docker compose ps ==" | Out-File $out -Encoding utf8
docker compose ps 2>&1 | Out-File $out -Append -Encoding utf8
"== import test ==" | Out-File $out -Append -Encoding utf8
docker compose exec -T api python -c "import app.mcp_server; print('MCP import OK')" 2>&1 | Out-File $out -Append -Encoding utf8
"== handshake test ==" | Out-File $out -Append -Encoding utf8
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"debug","version":"1"}}}' | docker compose exec -T api python -m app.mcp_server 2>&1 | Out-File $out -Append -Encoding utf8
"== claude mcp log ==" | Out-File $out -Append -Encoding utf8
$log = Join-Path $env:LOCALAPPDATA "Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\logs\mcp-server-policypilot.log"
if (Test-Path $log) { Get-Content $log -Tail 40 | Out-File $out -Append -Encoding utf8 } else { "no log at $log" | Out-File $out -Append -Encoding utf8 }
Write-Host "done - tell Claude"
