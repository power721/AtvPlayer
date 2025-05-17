pyinstaller --name=AtvPlayer --onefile --windowed --add-data "resources.qrc:." --icon=app_icon.png main.py
ls -l dist