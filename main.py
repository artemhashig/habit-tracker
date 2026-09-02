import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pyngrok import ngrok

app = FastAPI(title="Habit Tracker PWA")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>Мои Привычки</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="manifest" href="/manifest.json">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    </head>
    <body class="bg-gray-900 text-white font-sans p-4">
        <div class="max-w-md mx-auto">
            <h1 class="text-2xl font-bold mb-4 text-center">Трекер Привычек</h1>

            <div id="pushups-card" class="bg-gray-800 p-4 rounded-2xl mb-4 border border-gray-700">
                <div class="flex justify-between items-center">
                    <div>
                        <h2 class="font-semibold text-lg">Отжимания</h2>
                        <p id="pushups-target" class="text-sm text-gray-400">Загрузка плана...</p>
                    </div>
                    <button onclick="logPushups()" class="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-xl font-medium active:scale-95 transition">
                        Выполнено
                    </button>
                </div>
            </div>

            <div class="bg-gray-800 p-4 rounded-2xl border border-gray-700">
                <h3 class="text-sm text-gray-400 mb-2">Активность</h3>
                <div class="h-24 bg-gray-900 rounded-xl flex items-center justify-center text-xs text-gray-500">
                    [Здесь будет тепловая карта]
                </div>
            </div>
        </div>

        <script>
            // Простая логика определения нормы отжиманий по дням недели
            const days = ['вск', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
            const pushupSchedule = {
                'пн': 70, 'ср': 70, 'чт': 70,
                'вт': 84, 'пт': 84,
                'сб': 56, 'вск': 0
            };

            const today = days[new Date().getDay()];
            const target = pushupSchedule[today] || 0;

            document.getElementById('pushups-target').innerText = 
                target > 0 ? `Сегодня цель: ${target} повторений` : 'Сегодня отдых!';

            function logPushups() {
                alert(`Записано выполнение на ${target} отжиманий!`);
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
  public_url = ngrok.connect(8000).public_url
  print("\n" + "=" * 50)
  print(f" ССЫЛКА ДЛЯ ТЕЛЕФОНА (Safari): {public_url}")
  print("=" * 50 + "\n")

  uvicorn.run(app, host="127.0.0.1", port=8000)