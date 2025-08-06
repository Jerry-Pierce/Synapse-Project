# app.py
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta
import json
import os
import random
import glob
import string

app = Flask(__name__)
app.secret_key = 'supersecretkey_for_synapse'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# --- 상수 정의 ---
USERS_FILE = 'users.json'
SHOP_ITEMS = {
    'item001': {'name': 'Gold Profile Badge', 'price': 100, 'icon': '🥇'},
    'item002': {'name': 'Silver Profile Badge', 'price': 50, 'icon': '🥈'},
    'item003': {'name': 'Bronze Profile Badge', 'price': 10, 'icon': '🥉'},
    'item004': {'name': 'Cool Website Theme', 'price': 200, 'icon': '🎨'}
}
DAILY_LOGIN_REWARD = 5

with open('translations.json', 'r', encoding='utf-8') as f:
    translations = json.load(f)

# --- 데이터 관리 함수 ---
def load_data(filename, default_data):
    if not os.path.exists(filename): return default_data
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content: return default_data
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError): return default_data

def save_data(data, filename):
    with open(filename, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)

# --- 유저 데이터 관리 ---
def get_user_data_path(data_type):
    if 'username' in session:
        return f"data_{session['username']}_{data_type}.json"
    return None

def load_user_goals():
    path = get_user_data_path('goals')
    if not path: return []
    goals = load_data(path, [])
    today_str = str(date.today())
    for goal in goals:
        if goal.get('type') == 'recurring' and goal.get('last_completed') != today_str:
            goal['status'] = 'In Progress'
    save_data(goals, path)
    return goals

def save_user_goals(goals):
    path = get_user_data_path('goals')
    if path: save_data(goals, path)

def load_user_player_data():
    path = get_user_data_path('player')
    if path:
        default_player_data = {'tickets': 0, 'score': 0, 'items': [], 'equipped_badge': None, 'last_login_date': None}
        player_data = load_data(path, default_player_data)
        for key, value in default_player_data.items():
            if key not in player_data:
                player_data[key] = value
        return player_data
    return {'tickets': 0, 'score': 0, 'items': [], 'equipped_badge': None, 'last_login_date': None}

def save_user_player_data(player_data):
    path = get_user_data_path('player')
    if path: save_data(player_data, path)


# --- 유저 인증 경로 ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    lang = session.get('lang', 'en')
    t = translations[lang]
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_data(USERS_FILE, {})
        if username in users:
            flash('Username already exists!', 'error')
            return redirect(url_for('register'))
        users[username] = generate_password_hash(password)
        save_data(users, USERS_FILE)
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', t=t)

@app.route('/login', methods=['GET', 'POST'])
def login():
    lang = session.get('lang', 'en')
    t = translations[lang]
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember = 'remember' in request.form
        users = load_data(USERS_FILE, {})
        if username in users and check_password_hash(users[username], password):
            session['username'] = username
            session.permanent = remember
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'error')
    return render_template('login.html', t=t)

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/set_language/<lang>')
def set_language(lang):
    session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    lang = session.get('lang', 'en')
    t = translations[lang]
    if request.method == 'POST':
        username = request.form['username']
        users = load_data(USERS_FILE, {})
        if username in users:
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            users[username] = generate_password_hash(temp_password)
            save_data(users, USERS_FILE)
            flash(f'Your temporary password is: {temp_password}. Please log in and change it immediately.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Username not found.', 'error')
            return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html', t=t)


# --- 페이지 렌더링 경로 ---
def get_common_render_data():
    player_data = load_user_player_data() if 'username' in session else None
    theme = 'dark-theme' if player_data and 'item004' in player_data.get('items', []) else 'light-theme'
    equipped_badge_icon = SHOP_ITEMS.get(player_data.get('equipped_badge', ''), {}).get('icon') if player_data else None
    lang = session.get('lang', 'en')
    t = translations[lang]
    return {
        'player_data': player_data,
        'theme': theme,
        'equipped_badge_icon': equipped_badge_icon,
        't': t
    }

@app.route('/')
def index():
    if 'username' not in session:
        common_data = get_common_render_data()
        return render_template('welcome.html', **common_data)
    common_data = get_common_render_data()
    player_data = common_data['player_data']
    today_str = str(date.today())
    if player_data.get('last_login_date') != today_str:
        player_data['tickets'] += DAILY_LOGIN_REWARD
        player_data['last_login_date'] = today_str
        save_user_player_data(player_data)
        flash(f'Daily Login Bonus! You received {DAILY_LOGIN_REWARD} tickets. 🎟️', 'success')
    goals = load_user_goals()
    return render_template('index.html', goal_list=goals, tickets=player_data['tickets'], today=today_str, **common_data)

@app.route('/game_room')
def game_room():
    common_data = get_common_render_data()
    if not common_data or 'username' not in session: return redirect(url_for('login'))
    return render_template('game_room.html', **common_data)

@app.route('/shop')
def shop():
    common_data = get_common_render_data()
    if not common_data or 'username' not in session: return redirect(url_for('login'))
    return render_template('shop.html', items=SHOP_ITEMS, player_score=common_data['player_data']['score'], player_items=common_data['player_data']['items'], **common_data)

@app.route('/profile')
def profile():
    common_data = get_common_render_data()
    if not common_data or 'username' not in session: return redirect(url_for('login'))
    player_data = common_data['player_data']
    owned_badges = {item_id: SHOP_ITEMS[item_id] for item_id in player_data['items'] if 'Badge' in SHOP_ITEMS[item_id]['name']}
    return render_template('profile.html', player=player_data, badges=owned_badges, **common_data)

@app.route('/guess_the_number')
def guess_the_number():
    common_data = get_common_render_data()
    if not common_data or 'username' not in session: return redirect(url_for('login'))
    if 'answer' not in session:
        session['answer'] = random.randint(1, 100)
    return render_template('guess_the_number.html', tickets=common_data['player_data']['tickets'], message=session.get('message', 'Guess a number between 1 and 100!'), **common_data)

@app.route('/memory_game')
def memory_game():
    common_data = get_common_render_data()
    if not common_data or 'username' not in session: return redirect(url_for('login'))
    return render_template('memory_game.html', tickets=common_data['player_data']['tickets'], **common_data)

@app.route('/leaderboard')
def leaderboard():
    common_data = get_common_render_data()
    if not common_data or 'username' not in session: return redirect(url_for('login'))
    all_players = []
    for player_file in glob.glob('data_*_player.json'):
        username = player_file.split('_')[1]
        player_info = load_data(player_file, {})
        all_players.append({'username': username, 'score': player_info.get('score', 0)})
    sorted_players = sorted(all_players, key=lambda p: p['score'], reverse=True)
    return render_template('leaderboard.html', players=sorted_players, **common_data)

@app.route('/dashboard')
def dashboard():
    common_data = get_common_render_data()
    if not common_data or 'username' not in session: return redirect(url_for('login'))
    player_data = common_data['player_data']
    goals = load_user_goals()
    total_goals = len(goals)
    completed_goals = len([g for g in goals if g['status'] == 'Completed'])
    completion_rate = int((completed_goals / total_goals) * 100) if total_goals > 0 else 0
    stats = {
        'score': player_data.get('score', 0),
        'tickets': player_data.get('tickets', 0),
        'total_goals': total_goals,
        'completed_goals': completed_goals,
        'completion_rate': completion_rate
    }
    chart_labels = []
    chart_data = []
    today = date.today()
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_str = str(day)
        chart_labels.append(day.strftime('%m/%d'))
        completed_on_day = 0
        for goal in goals:
            if goal.get('completion_date') == day_str:
                completed_on_day += 1
        chart_data.append(completed_on_day)
    return render_template('dashboard.html', stats=stats, chart_labels=chart_labels, chart_data=chart_data, **common_data)

@app.route('/settings')
def settings():
    common_data = get_common_render_data()
    if not common_data or 'username' not in session: return redirect(url_for('login'))
    return render_template('settings.html', **common_data)


# --- 데이터 처리 경로 ---
@app.route('/add_goal', methods=['POST'])
def add_goal():
    if 'username' not in session: return jsonify({'success': False, 'error': 'Not logged in'})
    goals = load_user_goals()
    goal_text = request.form['goal']
    is_recurring = 'is_recurring' in request.form
    deadline = request.form.get('deadline')
    new_goal = {'text': goal_text, 'status': 'In Progress'}
    if is_recurring:
        new_goal['type'] = 'recurring'
        new_goal['last_completed'] = None
    if deadline:
        new_goal['deadline'] = deadline
    goals.append(new_goal)
    save_user_goals(goals)
    return jsonify({'success': True, 'goals': goals})

@app.route('/delete/<int:goal_id>', methods=['POST'])
def delete_goal(goal_id):
    if 'username' not in session: return jsonify({'success': False, 'error': 'Not logged in'})
    goals = load_user_goals()
    if 0 <= goal_id < len(goals):
        goals.pop(goal_id)
        save_user_goals(goals)
    return jsonify({'success': True, 'goals': goals})

@app.route('/toggle/<int:goal_id>', methods=['POST'])
def toggle_status(goal_id):
    if 'username' not in session: return jsonify({'success': False, 'error': 'Not logged in'})
    goals = load_user_goals()
    player_data = load_user_player_data()
    if 0 <= goal_id < len(goals):
        goal = goals[goal_id]
        today_str = str(date.today())
        if goal['status'] == 'In Progress':
            goal['status'] = 'Completed'
            player_data['tickets'] += 1
            if goal.get('type') == 'recurring':
                goal['last_completed'] = today_str
            else:
                goal['completion_date'] = today_str
        else:
            if goal.get('type') != 'recurring':
                goal['status'] = 'In Progress'
                if player_data['tickets'] > 0: player_data['tickets'] -= 1
                if 'completion_date' in goal:
                    del goal['completion_date']
        save_user_goals(goals)
        save_user_player_data(player_data)
    return jsonify({'success': True, 'goals': goals, 'tickets': player_data['tickets']})

@app.route('/play_clicker_game', methods=['POST'])
def play_clicker_game():
    if 'username' not in session: return jsonify({'success': False, 'message': 'Not logged in!'})
    player_data = load_user_player_data()
    if player_data['tickets'] > 0:
        player_data['tickets'] -= 1
        player_data['score'] += 1
        save_user_player_data(player_data)
        return jsonify({'success': True, 'tickets': player_data['tickets'], 'score': player_data['score']})
    else:
        return jsonify({'success': False, 'message': 'Not enough tickets!'})

@app.route('/guess', methods=['POST'])
def guess():
    if 'username' not in session: return redirect(url_for('login'))
    player_data = load_user_player_data()
    lang = session.get('lang', 'en')
    t = translations[lang]
    if player_data['tickets'] > 0:
        player_data['tickets'] -= 1
        guess = int(request.form['guess'])
        answer = session.get('answer', 50)
        if guess < answer: session['message'] = f"Too low! You guessed {guess}."
        elif guess > answer: session['message'] = f"Too high! You guessed {guess}."
        else:
            session['message'] = f"You got it! The number was {answer}. (+10 Score Bonus!)"
            player_data['score'] += 10
            session.pop('answer', None)
        save_user_player_data(player_data)
    else:
        session['message'] = "Not enough tickets to guess!"
    return redirect(url_for('guess_the_number'))

@app.route('/memory_game_reward', methods=['POST'])
def memory_game_reward():
    if 'username' not in session: return jsonify({'success': False, 'message': 'Not logged in!'})
    player_data = load_user_player_data()
    player_data['score'] += 5
    save_user_player_data(player_data)
    return jsonify({'success': True, 'score': player_data['score']})

@app.route('/spend_ticket', methods=['POST'])
def spend_ticket():
    if 'username' not in session: return jsonify({'success': False, 'message': 'Not logged in!'})
    player_data = load_user_player_data()
    tickets_to_spend = request.json.get('tickets', 1)
    if player_data['tickets'] >= tickets_to_spend:
        player_data['tickets'] -= tickets_to_spend
        save_user_player_data(player_data)
        return jsonify({'success': True, 'tickets': player_data['tickets']})
    else:
        return jsonify({'success': False, 'message': 'Not enough tickets!'})

@app.route('/buy_item/<item_id>', methods=['POST'])
def buy_item(item_id):
    if 'username' not in session: return redirect(url_for('login'))
    player_data = load_user_player_data()
    if item_id in SHOP_ITEMS:
        item = SHOP_ITEMS[item_id]
        if item_id not in player_data['items'] and player_data['score'] >= item['price']:
            player_data['score'] -= item['price']
            player_data['items'].append(item_id)
            save_user_player_data(player_data)
    return redirect(url_for('shop'))

@app.route('/get_ad_reward', methods=['POST'])
def get_ad_reward():
    if 'username' not in session: return jsonify({'success': False, 'message': 'Not logged in!'})
    player_data = load_user_player_data()
    player_data['tickets'] += 1
    save_user_player_data(player_data)
    return jsonify({'success': True, 'tickets': player_data['tickets']})

@app.route('/equip_badge/<item_id>', methods=['POST'])
def equip_badge(item_id):
    if 'username' not in session: return redirect(url_for('login'))
    player_data = load_user_player_data()
    if item_id in player_data['items'] and 'Badge' in SHOP_ITEMS[item_id]['name']:
        player_data['equipped_badge'] = item_id
        save_user_player_data(player_data)
    return redirect(url_for('profile'))

@app.route('/reset_progress', methods=['POST'])
def reset_progress():
    if 'username' not in session: return redirect(url_for('login'))
    default_player_data = {'tickets': 0, 'score': 0, 'items': [], 'equipped_badge': None, 'last_login_date': None}
    save_user_player_data(default_player_data)
    flash('Your game progress has been reset!', 'success')
    return redirect(url_for('settings'))

@app.route('/change_password', methods=['POST'])
def change_password():
    if 'username' not in session: return redirect(url_for('login'))
    current_password = request.form['current_password']
    new_password = request.form['new_password']
    confirm_password = request.form['confirm_password']
    users = load_data(USERS_FILE, {})
    username = session['username']
    if not check_password_hash(users[username], current_password):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('settings'))
    if new_password != confirm_password:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('settings'))
    users[username] = generate_password_hash(new_password)
    save_data(users, USERS_FILE)
    flash('Password changed successfully!', 'success')
    return redirect(url_for('settings'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
