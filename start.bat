@echo off
:: Run the app and pipe output to a log file
python PTTApp\main.py > app.log 2>&1
