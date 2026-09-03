from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Habit Tracker</title>
        <style>
            body {
                background-color: #ffffff;
                margin: 0;
                height: 100vh;
            }
        </style>
    </head>
    <body>
    </body>
    </html>
    """