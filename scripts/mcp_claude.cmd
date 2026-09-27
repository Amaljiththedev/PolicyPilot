@echo off
REM Launcher for Claude Desktop: runs the MCP server in the api container and logs stderr for debugging.
cd /d "%~dp0.."
echo [%date% %time%] starting >> mcp_stderr.log
"C:\Program Files\Docker\Docker\resources\bin\docker.exe" compose exec -T api python -m app.mcp_server 2>> mcp_stderr.log
echo [%date% %time%] exited with %errorlevel% >> mcp_stderr.log
