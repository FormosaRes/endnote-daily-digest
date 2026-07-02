@echo off
chcp 65001 >nul
REM Periodic EndNote archival — run AFTER you've imported keepers.ris into EndNote
REM and re-exported the library to XML (Desktop\My EndNote Library-Converted.xml).
REM This refreshes the endnote-mcp search + vector DB so new papers become
REM first-class library entries (dedup, Tier-1 seeds, semantic affinity).
echo Re-indexing EndNote library into endnote-mcp...
"%APPDATA%\uv\tools\endnote-mcp\Scripts\endnote-mcp.exe" index
echo.
echo Generating semantic embeddings for any new references...
"%APPDATA%\uv\tools\endnote-mcp\Scripts\endnote-mcp.exe" embed
echo.
echo Done. Restart the endnote MCP (reconnect in the app) if search_semantic looks stale.
pause
