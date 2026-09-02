from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()

@app.get("/manifest.json")
async def get_manifest():
    return JSONResponse(content={
        "name": "Трекер Привычек",
        "short_name": "Привычки",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#000000",
        "theme_color": "#000000",
        "icons": [
            {
                "src": "https://img.icons8.com/ios-filled/500/787aff/checkmark.png",
                "sizes": "500x500",
                "type": "image/png"
            }
        ]
    })


HTML_CONTENT = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">

    <!-- PWA / iOS нативные настройки -->
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Привычки">
    <link rel="apple-touch-icon" href="https://img.icons8.com/ios-filled/500/787aff/checkmark.png">
    <link rel="manifest" href="/manifest.json">

    <title>Трекер Привычек</title>
    <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet" />
    <style>
        :root {
            --bg-color: #000000;
            --card-bg: #1C1C1E;
            --text-main: #FFFFFF;
            --text-secondary: #8E8E93;
            --accent-purple: #787AFF;
            --green-habit: #163B22;
            --yellow-habit: #CC9900;
            --safe-area-top: env(safe-area-inset-top);
            --safe-area-bottom: env(safe-area-inset-bottom);
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 0;
            padding-top: var(--safe-area-top);
            padding-bottom: calc(80px + var(--safe-area-bottom));
            user-select: none;
            -webkit-tap-highlight-color: transparent;
        }

        header {
            padding: 15px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: var(--safe-area-top);
            background-color: var(--bg-color);
            z-index: 100;
        }

        .header-left {
            display: flex;
            gap: 10px;
            background: var(--card-bg);
            padding: 5px;
            border-radius: 12px;
        }

        .icon-btn {
            background: none;
            border: none;
            color: var(--text-main);
            cursor: pointer;
            padding: 5px;
        }

        .current-date {
            font-size: 18px;
            font-weight: 600;
        }

        .add-habit-btn {
            background-color: var(--accent-purple);
            color: white;
            border: none;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
        }

        .week-calendar {
            display: flex;
            justify-content: space-between;
            padding: 10px 20px;
            margin-bottom: 20px;
        }

        .day-cell {
            text-align: center;
            width: 40px;
        }

        .day-name {
            color: var(--text-secondary);
            font-size: 12px;
            margin-bottom: 5px;
            text-transform: uppercase;
        }

        .day-number {
            font-size: 16px;
            font-weight: 500;
            width: 36px;
            height: 36px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto;
        }

        .day-cell.active .day-number {
            background-color: var(--accent-purple);
            border-radius: 50%;
            font-weight: 600;
        }

        .day-cell.today .day-number {
            color: var(--accent-purple);
        }

        .content {
            padding: 0 15px;
        }

        .category-container {
            background-color: var(--card-bg);
            border-radius: 20px;
            margin-bottom: 15px;
            overflow: hidden;
            border: 1px solid #2C2C2E;
        }

        .category-header {
            padding: 15px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            cursor: pointer;
        }

        .category-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 17px;
            font-weight: 600;
        }

        .category-icon {
            font-size: 20px;
            color: var(--text-secondary);
        }

        .category-habits {
            padding: 0 10px 10px 10px;
        }

        .habit-card {
            border-radius: 15px;
            margin-bottom: 8px;
            padding: 15px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: relative;
            overflow: hidden;
        }

        .habit-info {
            display: flex;
            align-items: center;
            gap: 12px;
            z-index: 2;
        }

        .habit-icon-bg {
            background: rgba(255, 255, 255, 0.1);
            padding: 8px;
            border-radius: 10px;
            display: flex;
        }

        .habit-details {
            display: flex;
            flex-direction: column;
        }

        .habit-name {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 2px;
        }

        .habit-desc {
            font-size: 12px;
            color: rgba(255, 255, 255, 0.7);
        }

        .habit-action {
            z-index: 2;
        }

        .check-btn {
            background: none;
            border: 2px solid rgba(255, 255, 255, 0.3);
            color: white;
            border-radius: 50%;
            width: 36px;
            height: 36px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
        }

        .habit-card.green { background-color: var(--green-habit); }
        .habit-card.yellow { background-color: var(--yellow-habit); }

        .progress-fill {
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            background: rgba(255, 255, 255, 0.15);
            z-index: 1;
            transition: width 0.3s ease;
        }

        .tabbar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background-color: #121212;
            border-top: 1px solid #2C2C2E;
            display: flex;
            justify-content: space-around;
            padding: 10px 10px calc(10px + var(--safe-area-bottom)) 10px;
            z-index: 1000;
        }

        .tab-item {
            text-align: center;
            color: var(--text-secondary);
            text-decoration: none;
            display: flex;
            flex-direction: column;
            align-items: center;
            width: 25%;
        }

        .tab-item.active {
            color: var(--accent-purple);
        }

        .tab-icon {
            font-size: 24px;
            margin-bottom: 4px;
        }

        .tab-label {
            font-size: 10px;
            font-weight: 500;
        }

        .material-symbols-rounded {
          font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24
        }
        .active .material-symbols-rounded, .add-habit-btn .material-symbols-rounded {
          font-variation-settings: 'FILL' 1
        }
    </style>
</head>
<body>

    <header>
        <div class="header-left">
            <button class="icon-btn"><span class="material-symbols-rounded">format_list_bulleted</span></button>
            <button class="icon-btn"><span class="material-symbols-rounded">sort</span></button>
        </div>
        <div class="current-date">3 сент. (v2)</div>
        <button class="add-habit-btn"><span class="material-symbols-rounded">add</span></button>
    </header>

    <div class="week-calendar">
        <div class="day-cell"><div class="day-name">Ср</div><div class="day-number">26</div></div>
        <div class="day-cell"><div class="day-name">Чт</div><div class="day-number">27</div></div>
        <div class="day-cell"><div class="day-name">Пт</div><div class="day-number">28</div></div>
        <div class="day-cell"><div class="day-name">Сб</div><div class="day-number">29</div></div>
        <div class="day-cell today"><div class="day-name">Вс</div><div class="day-number">30</div></div>
        <div class="day-cell active"><div class="day-name">Пн</div><div class="day-number">31</div></div>
        <div class="day-cell"><div class="day-name">Вт</div><div class="day-number">1</div></div>
    </div>

    <div class="content">

        <div class="category-container">
            <div class="category-header" onclick="toggleCategory(this)">
                <div class="category-title">
                    <span class="material-symbols-rounded category-icon">psychology</span>
                    Саморазвитие
                </div>
                <span class="material-symbols-rounded expand-icon">expand_more</span>
            </div>
            <div class="category-habits">
                <div class="habit-card green">
                    <div class="habit-info">
                        <div class="habit-icon-bg"><span class="material-symbols-rounded">translate</span></div>
                        <div class="habit-details">
                            <div class="habit-name">Абхазский язык</div>
                            <div class="habit-desc">Пн — Сб, 0/3 сеанса</div>
                        </div>
                    </div>
                    <div class="habit-action">
                        <button class="check-btn"><span class="material-symbols-rounded">add</span></button>
                    </div>
                </div>
            </div>
        </div>

        <div class="category-container">
            <div class="category-header" onclick="toggleCategory(this)">
                <div class="category-title">
                    <span class="material-symbols-rounded category-icon">fitness_center</span>
                    Спорт
                </div>
                <span class="material-symbols-rounded expand-icon">expand_less</span>
            </div>
            <div class="category-habits" style="display: block;">
                <div class="habit-card yellow">
                    <div class="progress-fill" style="width: 40%;"></div>
                    <div class="habit-info">
                        <div class="habit-icon-bg"><span class="material-symbols-rounded">directions_run</span></div>
                        <div class="habit-details">
                            <div class="habit-name">Отжимания</div>
                            <div class="habit-desc">Пн, Ср, Пт, 28/70 повторений</div>
                        </div>
                    </div>
                    <div class="habit-action">
                        <button class="check-btn"><span class="material-symbols-rounded">add</span></button>
                    </div>
                </div>
            </div>
        </div>

    </div>

    <nav class="tabbar">
        <a href="#" class="tab-item active">
            <span class="material-symbols-rounded tab-icon">visibility</span>
            <span class="tab-label">Привычки</span>
        </a>
        <a href="#" class="tab-item">
            <span class="material-symbols-rounded tab-icon">bar_chart</span>
            <span class="tab-label">Статистика</span>
        </a>
        <a href="#" class="tab-item">
            <span class="material-symbols-rounded tab-icon">group</span>
            <span class="tab-label">Общий доступ</span>
        </a>
        <a href="#" class="tab-item">
            <span class="material-symbols-rounded tab-icon">settings</span>
            <span class="tab-label">Настройки</span>
        </a>
    </nav>

    <script>
        function toggleCategory(header) {
            const habitsBlock = header.nextElementSibling;
            const icon = header.querySelector('.expand-icon');

            if (habitsBlock.style.display === "block") {
                habitsBlock.style.display = "none";
                icon.textContent = "expand_more";
            } else {
                habitsBlock.style.display = "block";
                icon.textContent = "expand_less";
            }
        }
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def read_root():
    return HTML_CONTENT
