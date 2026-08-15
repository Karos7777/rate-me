from flask import Flask, render_template_string, request, jsonify
import uuid
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import statistics
from contextlib import contextmanager

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

# Каждые сколько оценок открывается средняя
REVEAL_STEP = 10

# Шкала с подписями. Меняй тексты здесь — они подтянутся везде.
SCALE = [
    (1,  "Совсем не моё"),
    (2,  "Не заметила бы на улице"),
    (3,  "Заметила бы и забыла"),
    (4,  "Симпатичный, но не мой типаж"),
    (5,  "Обычный, таких много"),
    (6,  "Приятный, задержала бы взгляд"),
    (7,  "Обернулась бы вслед"),
    (8,  "Ответила бы, если бы подошёл"),
    (9,  "Дала бы номер"),
    (10, "Сама бы нашла повод заговорить"),
]


def get_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ratings (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT REFERENCES sessions(session_id),
                    score INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS refusals (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT REFERENCES sessions(session_id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)


try:
    init_db()
except Exception as e:
    print("DB init error:", e)


HOST_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Оценка меня</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
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
  .stats { font-size: 2.8rem; font-weight: 800; margin: 12px 0 4px; }
  .sub { font-size: 1.05rem; opacity: 0.9; margin-bottom: 6px; }
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
    padding: 14px 28px;
    font-size: 1.05rem;
    border-radius: 50px;
    cursor: pointer;
    font-weight: 700;
    margin-top: 12px;
    width: 100%;
  }
  button.secondary {
    background: transparent;
    border: 2px solid rgba(255,255,255,0.5);
    color: white;
  }
  .hint { font-size: 0.85rem; opacity: 0.75; margin-top: 14px; line-height: 1.4; }
  .ref-count { margin-top: 10px; font-size: 0.95rem; opacity: 0.85; }
  .copy-msg {
    font-size: 0.9rem;
    margin-top: 8px;
    opacity: 0;
    transition: opacity 0.3s;
  }
  .copy-msg.show { opacity: 1; }

  /* Распределение оценок — это кадр для видео */
  .dist {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 3px;
    height: 70px;
    margin: 18px 0 4px;
  }
  .dist-col { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; height: 100%; }
  .dist-bar {
    background: rgba(255,255,255,0.85);
    border-radius: 3px 3px 0 0;
    min-height: 2px;
    transition: height 0.4s ease;
  }
  .dist-labels { display: flex; justify-content: space-between; gap: 3px; font-size: 0.65rem; opacity: 0.7; }
  .dist-labels span { flex: 1; text-align: center; }
  .extra { font-size: 0.9rem; opacity: 0.85; margin-top: 10px; }
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

    <div class="dist" id="dist"></div>
    <div class="dist-labels" id="dist-labels"></div>
    <div class="extra" id="extra"></div>

    <button onclick="copyTrackLink()">Скопировать ссылку</button>
    <div class="copy-msg" id="copy-msg">Ссылка скопирована!</div>

    <button class="secondary" onclick="startNew()">Новая сессия</button>

    <div class="hint">
      Средняя появляется каждые 10 оценок<br>
      Отказы не влияют на среднюю
    </div>
  </div>
</div>

<script>
let currentSession = localStorage.getItem('currentSession') || null;
let pollInterval = null;

// рисуем подписи под столбиками один раз
const labelsEl = document.getElementById('dist-labels');
for (let i = 1; i <= 10; i++) {
  const s = document.createElement('span');
  s.textContent = i;
  labelsEl.appendChild(s);
}

if (currentSession) {
  document.getElementById('no-session').style.display = 'none';
  document.getElementById('active-session').style.display = 'block';
  showQR(currentSession);
  updateStats();
  pollInterval = setInterval(updateStats, 1500);
}

function startNew() {
  fetch('/new_session')
    .then(r => r.json())
    .then(data => {
      currentSession = data.session_id;
      localStorage.setItem('currentSession', currentSession);
      document.getElementById('no-session').style.display = 'none';
      document.getElementById('active-session').style.display = 'block';
      showQR(currentSession);
      if (pollInterval) clearInterval(pollInterval);
      updateStats();
      pollInterval = setInterval(updateStats, 1500);
    })
    .catch(err => alert('Ошибка: ' + err));
}

function showQR(sessionId) {
  const rateUrl = window.location.origin + '/rate/' + sessionId;
  document.getElementById('qrcode').innerHTML = '';
  new QRCode(document.getElementById('qrcode'), {
    text: rateUrl,
    width: 200,
    height: 200,
    colorDark: "#000000",
    colorLight: "#ffffff",
    correctLevel: QRCode.CorrectLevel.H
  });
}

function copyTrackLink() {
  if (!currentSession) return;
  const link = window.location.origin + '/track/' + currentSession;
  navigator.clipboard.writeText(link).then(() => {
    const msg = document.getElementById('copy-msg');
    msg.classList.add('show');
    setTimeout(() => msg.classList.remove('show'), 2000);
  }).catch(() => prompt("Скопируй ссылку:", link));
}

function drawDistribution(dist) {
  const el = document.getElementById('dist');
  el.innerHTML = '';
  const values = [];
  for (let i = 1; i <= 10; i++) values.push(dist[i] || 0);
  const max = Math.max(1, ...values);

  values.forEach(v => {
    const col = document.createElement('div');
    col.className = 'dist-col';
    const bar = document.createElement('div');
    bar.className = 'dist-bar';
    bar.style.height = (v / max * 100) + '%';
    bar.style.opacity = v === 0 ? 0.25 : 1;
    col.appendChild(bar);
    el.appendChild(col);
  });
}

function updateStats() {
  if (!currentSession) return;
  fetch('/stats/' + currentSession)
    .then(r => r.json())
    .then(data => {
      document.getElementById('bar').style.width = ((data.count % 10) / 10 * 100) + '%';
      document.getElementById('count-text').textContent = data.count + ' ' + pluralize(data.count);
      document.getElementById('refusal-text').textContent = 'Отказов: ' + data.refusals;

      if (data.revealed_average !== null) {
        document.getElementById('average').textContent = data.revealed_average.toFixed(2);
        let status = 'Средняя на ' + data.revealed_count + ' оценках';
        if (data.count > data.revealed_count) {
          status += ' · ещё ' + data.to_next_reveal + ' до обновления';
        }
        document.getElementById('status').textContent = status;

        document.getElementById('extra').textContent =
          'Медиана ' + data.revealed_median +
          ' · десяток: ' + data.tens +
          ' · ниже 7: ' + data.below_seven;
      } else {
        document.getElementById('average').textContent = '—';
        document.getElementById('status').textContent = 'Ещё ' + data.to_next_reveal + ' до первой средней';
        document.getElementById('extra').textContent = '';
      }

      drawDistribution(data.distribution);
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
  * { box-sizing: border-box; }
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
    padding: 26px 16px;
    max-width: 380px;
    width: 100%;
  }
  h1 { margin: 0 0 10px; font-size: 1.4rem; }
  .desc { font-size: 0.95rem; opacity: 0.9; line-height: 1.45; margin-bottom: 8px; }
  .nudge {
    font-size: 0.85rem;
    line-height: 1.4;
    background: rgba(0,0,0,0.18);
    border-radius: 12px;
    padding: 10px 12px;
    margin-bottom: 16px;
  }

  .scale { display: flex; flex-direction: column; gap: 7px; margin-bottom: 14px; }
  .rate-btn {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    background: white;
    border: none;
    border-radius: 13px;
    padding: 11px 14px;
    cursor: pointer;
    text-align: left;
    font-family: inherit;
  }
  .rate-btn:active { transform: scale(0.985); }
  .rate-btn .num {
    flex: 0 0 30px;
    font-size: 1.3rem;
    font-weight: 800;
    color: #5b21b6;
    text-align: center;
  }
  .rate-btn .label {
    font-size: 0.9rem;
    line-height: 1.25;
    color: #2c2140;
    font-weight: 500;
  }

  .refuse-btn {
    background: transparent; border: 2px solid rgba(255,255,255,0.45); color: white;
    padding: 12px; border-radius: 14px; font-size: 0.95rem; width: 100%; cursor: pointer;
    font-family: inherit;
  }
  .message { display: none; font-size: 1.15rem; padding: 12px 0 8px; line-height: 1.4; }
  .copy-btn {
    display: none;
    background: white; color: #5b21b6; border: none;
    padding: 12px 20px; font-size: 0.95rem; font-weight: 600;
    border-radius: 50px; cursor: pointer; margin-top: 10px; width: 100%;
    font-family: inherit;
  }
  .copy-msg { font-size: 0.85rem; margin-top: 8px; opacity: 0; transition: opacity 0.3s; }
  .copy-msg.show { opacity: 1; }
  .live-stats { margin-top: 22px; padding-top: 18px; border-top: 1px solid rgba(255,255,255,0.25); }
  .avg-big { font-size: 2.3rem; font-weight: 800; margin: 8px 0 4px; }
  .avg-sub { font-size: 0.95rem; opacity: 0.9; }
</style>
</head>
<body>
<div class="card">
  <h1>Насколько я в твоём типаже?</h1>

  <div class="desc">
    Это социальный эксперимент.<br>
    Полностью анонимно — я не узнаю, кто что поставил.
  </div>

  <div class="nudge">
    Пожалуйста, не ставь 10 из вежливости.<br>
    <b>5 — это нормально, а не обидно.</b>
  </div>

  <div id="form">
    <div class="scale">
      {% for value, label in scale %}
      <button class="rate-btn" onclick="send({{ value }})">
        <span class="num">{{ value }}</span>
        <span class="label">{{ label }}</span>
      </button>
      {% endfor %}
    </div>
    <button class="refuse-btn" id="refuse-btn" onclick="refuse()">Не хочу оценивать</button>
  </div>

  <div class="message" id="message"></div>
  <button class="copy-btn" id="copy-btn" onclick="copyTrackLink()">Скопировать ссылку</button>
  <div class="copy-msg" id="copy-msg">Ссылка скопирована!</div>

  <div class="live-stats">
    <div class="avg-big" id="girl-average">—</div>
    <div class="avg-sub" id="girl-status">Средняя появится после 10 оценок</div>
    <div class="avg-sub" id="girl-count" style="margin-top:6px; opacity:0.8;"></div>
  </div>
</div>

<script>
const sessionId = "{{ session_id }}";
const storageKey = "rated_" + sessionId;

if (localStorage.getItem(storageKey)) {
  document.getElementById('form').style.display = 'none';
  document.getElementById('message').style.display = 'block';
  document.getElementById('message').textContent = 'Вы уже участвовали с этого устройства';
  document.getElementById('copy-btn').style.display = 'block';
}

function send(score) {
  if (localStorage.getItem(storageKey)) return;
  fetch('/submit/' + sessionId, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({score: score})
  }).then(() => {
    localStorage.setItem(storageKey, '1');
    document.getElementById('form').style.display = 'none';
    document.getElementById('message').style.display = 'block';
    document.getElementById('message').textContent = 'Спасибо! Оценка отправлена';
    document.getElementById('copy-btn').style.display = 'block';
    updateGirlStats();
  });
}

function refuse() {
  if (localStorage.getItem(storageKey)) return;
  fetch('/refuse/' + sessionId, { method: 'POST' })
    .then(() => {
      localStorage.setItem(storageKey, '1');
      document.getElementById('form').style.display = 'none';
      document.getElementById('message').style.display = 'block';
      document.getElementById('message').textContent = 'Отказ учтён';
      document.getElementById('copy-btn').style.display = 'block';
      updateGirlStats();
    });
}

function copyTrackLink() {
  const link = window.location.origin + '/track/' + sessionId;
  navigator.clipboard.writeText(link).then(() => {
    const msg = document.getElementById('copy-msg');
    msg.classList.add('show');
    setTimeout(() => msg.classList.remove('show'), 2000);
  }).catch(() => prompt("Скопируй ссылку:", link));
}

function updateGirlStats() {
  fetch('/stats/' + sessionId)
    .then(r => r.json())
    .then(data => {
      document.getElementById('girl-count').textContent =
        data.count + ' оценок • ' + data.refusals + ' отказов';

      if (data.revealed_average !== null) {
        document.getElementById('girl-average').textContent = data.revealed_average.toFixed(2);
        let status = 'Текущая средняя (на ' + data.revealed_count + ')';
        if (data.count > data.revealed_count) {
          status += ' · ещё ' + data.to_next_reveal + ' до обновления';
        }
        document.getElementById('girl-status').textContent = status;
      } else {
        document.getElementById('girl-average').textContent = '—';
        document.getElementById('girl-status').textContent =
          'Ещё ' + data.to_next_reveal + ' до открытия средней';
      }
    });
}

updateGirlStats();
setInterval(updateGirlStats, 2000);
</script>
</body>
</html>
"""


TRACK_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Результаты оценки</title>
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
    padding: 20px;
    text-align: center;
  }
  .card {
    background: rgba(255,255,255,0.15);
    backdrop-filter: blur(12px);
    border-radius: 24px;
    padding: 36px 28px;
    max-width: 380px;
    width: 100%;
  }
  h1 { margin: 0 0 12px; font-size: 1.6rem; }
  .avg { font-size: 3.2rem; font-weight: 800; margin: 16px 0 8px; }
  .sub { font-size: 1.1rem; opacity: 0.9; margin: 6px 0; }
  button {
    background: white; color: #5b21b6; border: none;
    padding: 14px 24px; font-size: 1rem; font-weight: 600;
    border-radius: 50px; cursor: pointer; margin-top: 20px; width: 100%;
    font-family: inherit;
  }
  .copy-msg { font-size: 0.9rem; margin-top: 10px; opacity: 0; transition: opacity 0.3s; }
  .copy-msg.show { opacity: 1; }
</style>
</head>
<body>
<div class="card">
  <h1>Результаты оценки</h1>
  <div class="avg" id="average">—</div>
  <div class="sub" id="status">Загрузка...</div>
  <div class="sub" id="count"></div>
  <div class="sub" id="refusals"></div>
  <button onclick="copyTrackLink()">Скопировать ссылку</button>
  <div class="copy-msg" id="copy-msg">Ссылка скопирована!</div>
</div>

<script>
const sessionId = "{{ session_id }}";

function copyTrackLink() {
  const link = window.location.href;
  navigator.clipboard.writeText(link).then(() => {
    const msg = document.getElementById('copy-msg');
    msg.classList.add('show');
    setTimeout(() => msg.classList.remove('show'), 2000);
  }).catch(() => prompt("Скопируй ссылку:", link));
}

function update() {
  fetch('/stats/' + sessionId)
    .then(r => r.json())
    .then(data => {
      document.getElementById('count').textContent = data.count + ' оценок';
      document.getElementById('refusals').textContent = data.refusals + ' отказов';

      if (data.revealed_average !== null) {
        document.getElementById('average').textContent = data.revealed_average.toFixed(2);
        let status = 'Средняя на ' + data.revealed_count + ' оценках';
        if (data.count > data.revealed_count) {
          status += ' · ещё ' + data.to_next_reveal + ' до обновления';
        }
        document.getElementById('status').textContent = status;
      } else {
        document.getElementById('average').textContent = '—';
        document.getElementById('status').textContent = 'Ещё ' + data.to_next_reveal + ' до открытия';
      }
    });
}

update();
setInterval(update, 3000);
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
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (session_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (session_id,)
            )
    return jsonify({'session_id': session_id})


@app.route('/rate/<session_id>')
def rate(session_id):
    return render_template_string(RATE_HTML, session_id=session_id, scale=SCALE)


@app.route('/track/<session_id>')
def track(session_id):
    return render_template_string(TRACK_HTML, session_id=session_id)


@app.route('/submit/<session_id>', methods=['POST'])
def submit(session_id):
    data = request.get_json(silent=True) or {}
    score = data.get('score')
    if not isinstance(score, (int, float)) or not (1 <= int(score) <= 10):
        return jsonify({'ok': False, 'error': 'bad score'}), 400

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ratings (session_id, score) VALUES (%s, %s)",
                (session_id, int(score))
            )
    return jsonify({'ok': True})


@app.route('/refuse/<session_id>', methods=['POST'])
def refuse(session_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO refusals (session_id) VALUES (%s)", (session_id,))
    return jsonify({'ok': True})


@app.route('/stats/<session_id>')
def stats(session_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT score FROM ratings WHERE session_id = %s ORDER BY id",
                (session_id,)
            )
            scores = [row['score'] for row in cur.fetchall()]

            cur.execute(
                "SELECT COUNT(*) as cnt FROM refusals WHERE session_id = %s",
                (session_id,)
            )
            ref_count = cur.fetchone()['cnt']

    count = len(scores)

    # Средняя считается только по "открытым" десяткам — так она переживает
    # перезагрузку страницы и не может показать отрицательный остаток.
    revealed_count = (count // REVEAL_STEP) * REVEAL_STEP
    revealed = scores[:revealed_count]

    payload = {
        'count': count,
        'refusals': ref_count,
        'revealed_count': revealed_count,
        'to_next_reveal': REVEAL_STEP - (count % REVEAL_STEP),
        'revealed_average': None,
        'revealed_median': None,
        'tens': 0,
        'below_seven': 0,
        'distribution': {str(i): 0 for i in range(1, 11)},
    }

    if revealed:
        payload['revealed_average'] = round(statistics.mean(revealed), 2)
        payload['revealed_median'] = statistics.median(revealed)
        payload['tens'] = revealed.count(10)
        payload['below_seven'] = sum(1 for s in revealed if s < 7)
        payload['distribution'] = {str(i): revealed.count(i) for i in range(1, 11)}

    return jsonify(payload)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
