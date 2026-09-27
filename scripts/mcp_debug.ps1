# Writes MCP diagnostics to mcp_debug.txt so Claude can read it.
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "mcp_debug.txt"
Set-Location $root
"== docker compose ps ==" | Out-File $out -Encoding utf8
docker compose ps 2>&1 | Out-File $out -Append -Encoding utf8
"== full session: initialize + list_policies + ask_policy ==" | Out-File $out -Append -Encoding utf8
$msgs = @(
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"debug","version":"1"}}}',
 '{"jsonrpc":"2.0","method":"notifications/initialized"}',
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
 '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_policies","arguments":{}}}',
 '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"search_policies","arguments":{"query":"annual leave","top_k":1}}}'
) -join "`n"
$msgs | docker compose exec -T api python -m app.mcp_server 2>&1 | Out-File $out -Append -Encoding utf8
"== claude logs ==" | Out-File $out -Append -Encoding utf8
foreach ($d in @("$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\logs", "$env:APPDATA\Claude\logs")) {
  if (Test-Path $d) {
    "-- $d" | Out-File $out -Append -Encoding utf8
    Get-ChildItem $d -Filter "mcp*" | ForEach-Object {
      "--- $($_.Name)" | Out-File $out -Append -Encoding utf8
      Get-Content $_.FullName -Tail 40 | Out-File $out -Append -Encoding utf8
    }
  }
}
Write-Host "done - tell Claude"
