@echo off
rem Double-click to start Knowledge Tester. Guide: docs\quick-start.uk.md
title Knowledge Tester
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
if errorlevel 1 pause
