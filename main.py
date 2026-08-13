from flask import Flask, render_template_string, request, jsonify
import uuid
from collections import defaultdict
import statistics

app = Flask(__name__)

ratings = defaultdict(list)
refusals = defaultdict(int)

HOST_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Оценка меня</title>
    <script src="https://cdn.jsdelivr.net/npm/qrcode@1.5.3/build/qrcode.min.js"></script>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
            margin: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 20px;
            text-align: center;
        }
        .card {
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(12px);
            border-radius: 24px;
            padding: 28px 24px;
            max-width: 400px;
            width: 100%;
            box-shadow: 0 10px 40px rgba(0,0,0,0.25);
        }
        h1 { margin: 0 0 8px; font-size: 1.7rem; }
        #qrcode { 
            margin: 18px auto; 
            background: white; 
            padding: 12px; 
            border-radius: 16px; 
            display: inline-block; 
        }
        .stats {
            font-size: 2.8rem;
            font-weight: 800;
            margin: 12px 0 4px;
            letter-spacing: -1px;
        }
        .sub {
            font-size: 1.05rem;
            opacity: 0.9;
            margin-bottom: 6px;
        }
        .progress {
            background: rgba(255,255,255,0.2);
            border-radius: 50px;
            height: 10px;
            margin: 16px 0 8px;
            overflow: hidden;
        }
        .progress-bar {
            height: 100%;
            background: white;
            border-radius: 50px;
            transition: width 0.4s ease;
        }
        button {
            background: white;
            color: #5b21b6;
            border: none;
            padding: 15px 28px;
            font-size: 1.05rem;
            border-radius: 50px;
            cursor: pointer;
            font-weight: 700;
            margin-top: 18px;
            width: 100%;
            transition: transform 0.15s;
        }
        button:active { transform: scale(0.97); }
        .hint {
            font-size: 0.85rem;
            opacity: 0.75;
            margin-top: 14px;
            line-height: 1.4;
        }
        .ref-count {
            margin-top: 10px;
            font-size: 0.95rem;
            opacity: 0.85;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>Анонимная оценка</h1>
        
        <div id="no-session">
            <p style="opacity:0.9; margin-bottom: 24px;">Нажми кнопку — появится QR-код</p>
            <button onclick="startNew()">Начать новую оценку</button>
        </div>

        <div id="active-session" style="display:none;">
            <div id="qrcode"></div>
            
            <div class="stats" id="average">—</div>
            <div class="sub" id="status">Ждём первые 10 оценок</div>
            
            <div class="progress">
                <div class="progress-bar" id="bar" style="width: 0%"></div>
            </div>
            <div class="sub" id="count-text">0 оценок</div>
            <div class="ref-count" id="refusal-text">Отказов: 0</div>
            
            <button onclick="startNew()">Новая сессия</button>
            <div class="hint">
                Средняя появляется каждые 10 оценок<br>
                Отказы не влияют на среднюю
            </div>
        </div>
    </div>

    <script>
        let currentSession = null;
        let pollInterval = null;
        let lastShownAverage = null;

        function startNew() {
            fetch('/new_session')
                .then(r => r.json())
                .then(data => {
                    currentSession = data.session_id;
                    lastShownAverage = null;

                    document.getElementById('no-session').style.display = 'none';
                    document.getElementById('active-session').style.display = 'block';

                    const rateUrl = window.location.origin + '/rate/' + currentSession;
                    document.getElementById('qrcode').innerHTML = '';
                    QRCode.toCanvas(document.createElement('canvas'), rateUrl, {
                        width: 200,
                        margin: 1,
                        color: { dark: '#5b21b6', light: '#ffffff' }
                    }, function (err, canvas) {
                        if (!err) document.getElementById('qrcode').appendChild(canvas);
                    });

                    if (pollInterval) clearInterval(pollInterval);
                    updateStats();
                    pollInterval = setInterval(updateStats, 1500);
                });
        }

        function updateStats() {
            if (!currentSession) return;
            
            fetch('/stats/' + currentSession)
                .then(r => r.json())
                .then(data => {
                    const count = data.count;
                    const avg = data.average;
                    const refs = data.refusals;

                    const progressInBlock = count % 10;
                    document.getElementById('bar').style.width = (progressInBlock / 10 * 100) + '%';
                    document.getElementById('count-text').textContent = count + ' ' + pluralize(count);
                    document.getElementById('refusal-text').textContent = 'Отказов: ' + refs;

                    if (count >= 10 && count % 10 === 0) {
                        lastShownAverage = avg;
                        document.getElementById('average').textContent = avg.toFixed(2);
                        document.getElementById('status').textContent = `Средняя на ${count} оценках`;
                    } 
                    else if (lastShownAverage !== null) {
                        document.getElementById('average').textContent = lastShownAverage.toFixed(2);
                        const left = 10 - (count % 10);
                        document.getElementById('status').textContent = `Следующее обновление через ${left}`;
                    } 
                    else {
                        document.getElementById('average').textContent = '—';
                        const left = 10 - count;
                        document.getElementById('status').textContent = `Ещё ${left} до первой средней`;
                    }
                });
        }

        function pluralize(n) {
            if (n % 10 === 1 && n % 100 !== 11) return 'оценка';
            if ([2,3,4].includes(n % 10) && ![12,13,14].includes(n % 100)) return 'оценки';
            return 'оценок';
        }
    </script>
</body>
</html>
"""

RATE_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Анонимная оценка</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 16px;
            text-align: center;
        }
        .card {
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(12px);
            border-radius: 24px;
            padding: 28px 18px;
            max-width: 360px;
            width: 100%;
        }
        h1 { margin: 0 0 8px; font-size: 1.45rem; }
        .desc {
            font-size: 0.95rem;
            opacity: 0.9;
            line-height: 1.45;
            margin-bottom: 20px;
        }
        .buttons {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 8px;
            margin-bottom: 14px;
        }
        .rate-btn {
            background: white;
            color: #5b21b6;
            border: none;
            padding: 18px 0;
            font-size: 1.35rem;
            font-weight: 700;
            border-radius: 14px;
            cursor: pointer;
        }
        .rate-btn:active { transform: scale(0.9); }
        .refuse-btn {
            background: transparent;
            border: 2px solid rgba(255,255,255,0.45);
            color: white;
            padding: 12px;
            border-radius: 14px;
            font-size: 0.95rem;
            width: 100%;
            cursor: pointer;
        }
        .message {
            display: none;
            font-size: 1.1rem;
            padding: 12px 0;
            opacity: 0.95;
        }
        .live-stats {
            margin-top: 22px;
            padding-top: 18px;
            border-top: 1px solid rgba(255,255,255,0.25);
        }
        .avg-big {
            font-size: 2.3rem;
            font-weight: 800;
            margin: 8px 0 4px;
        }
        .avg-sub {
            font-size: 0.95rem;
            opacity: 0.9;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>Анонимная оценка</h1>
        <div class="desc">
            Это социальный эксперимент.<br>
            Поставь оценку внешности от 1 до 10.<br>
            Полностью анонимно. Никаких данных не собирается.
        </div>

        <div id="form">
            <div class="buttons">
                {% for i in range(1, 11) %}
                <button class="rate-btn" onclick="send({{ i }})">{{ i }}</button>
                {% endfor %}
            </div>
            <button class="refuse-btn" id="refuse-btn" onclick="refuse()">Не хочу оценивать</button>
        </div>

        <div class="message" id="message"></div>

        <div class="live-stats">
            <div class="avg-big" id="girl-average">—</div>
            <div class="avg-sub" id="girl-status">Средняя появится после 10 оценок</div>
            <div class="avg-sub" id="girl-count" style="margin-top:6px; opacity:0.8;"></div>
        </div>
    </div>

    <script>
        const sessionId = "{{ session_id }}";
        let lastShownAverage = null;
        let hasRefused = false;

        function send(score) {
            fetch('/submit/' + sessionId, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({score: score})
            }).then(() => {
                document.getElementById('message').style.display = 'block';
                document.getElementById('message').textContent = 'Спасибо! Оценка отправлена';
                updateGirlStats();
            });
        }

        function refuse() {
            if (hasRefused) return;
            hasRefused = true;
            
            fetch('/refuse/' + sessionId, { method: 'POST' })
            .then(() => {
                document.getElementById('message').style.display = 'block';
                document.getElementById('message').textContent = 'Отказ учтён. Можешь всё равно поставить оценку, если передумаешь';
                document.getElementById('refuse-btn').style.opacity = '0.4';
                document.getElementById('refuse-btn').style.pointerEvents = 'none';
                updateGirlStats();
            });
        }

        function updateGirlStats() {
            fetch('/stats/' + sessionId)
                .then(r => r.json())
                .then(data => {
                    const count = data.count;
                    const avg = data.average;
                    const refs = data.refusals;

                    document.getElementById('girl-count').textContent = 
                        count + ' оценок • ' + refs + ' отказов';

                    if (count >= 10 && count % 10 === 0) {
                        lastShownAverage = avg;
                        document.getElementById('girl-average').textContent = avg.toFixed(2);
                        document.getElementById('girl-status').textContent = `Текущая средняя (на ${count})`;
                    } 
                    else if (lastShownAverage !== null) {
                        document.getElementById('girl-average').textContent = lastShownAverage.toFixed(2);
                        const left = 10 - (count % 10);
                        document.getElementById('girl-status').textContent = `Следующее обновление через ${left}`;
                    } 
                    else {
                        document.getElementById('girl-average').textContent = '—';
                        const left = 10 - count;
                        document.getElementById('girl-status').textContent = `Ещё ${left} до открытия средней`;
                    }
                });
        }

        updateGirlStats();
        setInterval(updateGirlStats, 2000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HOST_HTML)

@app.route('/new_session')
def new_session():
    session_id = str(uuid.uuid4())[:8]
    ratings[session_id] = []
    refusals[session_id] = 0
    return jsonify({'session_id': session_id})

@app.route('/rate/<session_id>')
def rate(session_id):
    return render_template_string(RATE_HTML, session_id=session_id)

@app.route('/submit/<session_id>', methods=['POST'])
def submit(session_id):
    data = request.get_json()
    score = data.get('score')
    if isinstance(score, (int, float)) and 1 <= score <= 10:
        ratings[session_id].append(int(score))
    return jsonify({'ok': True})

@app.route('/refuse/<session_id>', methods=['POST'])
def refuse(session_id):
    refusals[session_id] += 1
    return jsonify({'ok': True})

@app.route('/stats/<session_id>')
def stats(session_id):
    scores = ratings.get(session_id, [])
    ref_count = refusals.get(session_id, 0)
    if not scores:
        return jsonify({'average': 0, 'count': 0, 'refusals': ref_count})
    return jsonify({
        'average': round(statistics.mean(scores), 2),
        'count': len(scores),
        'refusals': ref_count
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
