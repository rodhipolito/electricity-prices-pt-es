@echo off
cd /d C:\Users\rodri\Desktop\Projetos\energia-precos
call venv\Scripts\activate.bat
set DB_TARGET=neon
python scripts\extract_prices.py