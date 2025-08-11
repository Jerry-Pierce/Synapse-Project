# app.py
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta
import json
import os
import random
import glob
import string
import uuid

app = Flask(__name__)
app.secret_key = 'supersecretkey_for_synapse'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- 상수 정의 ---
USERS_FILE = 'users.json'
SHOP_ITEMS = {
    'item001': {'name': 'Gold Profile Badge', 'price': 100, 'icon': '🥇'},
    'item002': {'name': 'Silver Profile Badge', 'price': 50, 'icon': '🥈'},
    'item003': {'name': 'Bronze Profile Badge', 'price': 10, 'icon': '🥉'},
    'item004': {'name': 'Cool Website Theme', 'price': 200, 'icon': '🎨'}
}
DAILY_LOGIN_REWARD = 5

# MMORPG 게임 상태
game_world = {
    'players': {},  # {session_id: {username, x, y, level, exp, hp, last_seen}}
    'monsters': {},  # {monster_id: {x, y, hp, type}}
    'items': {},  # {item_id: {x, y, type}}
    'duels': {},  # {duel_id: {player1_id, player2_id, status, arena_pos}}
    'duel_requests': {}  # {request_id: {from_player, to_player, timestamp}}
}

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
        default_player_data = {'tickets': 0, 'score': 0, 'items': [], 'equipped_badge': None, 'last_login_date': None, 'level': 1, 'exp': 0, 'hp': 100}
        player_data = load_data(path, default_player_data)
        for key, value in default_player_data.items():
            if key not in player_data:
                player_data[key] = value
        return player_data
    return {'tickets': 0, 'score': 0, 'items': [], 'equipped_badge': None, 'last_login_date': None, 'level': 1, 'exp': 0, 'hp': 100}

def save_user_player_data(player_data):
    path = get_user_data_path('player')
    if path: save_data(player_data, path)

# --- MMORPG 게임 함수들 ---
def spawn_monsters():
    """몬스터 생성"""
    # 일반 몬스터 5마리 유지
    normal_monsters = [m for m in game_world['monsters'].values() if m.get('monster_type') != 'boss']
    while len(normal_monsters) < 5:
        monster_id = str(uuid.uuid4())
        game_world['monsters'][monster_id] = {
            'x': random.randint(50, 750),
            'y': random.randint(50, 550),
            'hp': 30,
            'max_hp': 30,
            'type': random.choice(['👹', '👾', '🤖']),
            'monster_type': 'normal',
            'target_player': None,  # 타겟 플레이어
            'detection_range': 150,  # 감지 범위 (넓혀짐)
            'attack_range': 40,  # 공격 범위
            'move_speed': 4.0,  # 이동 속도 (더 빠르게)
            'last_move': 0,  # 마지막 이동 시간
            'last_attack': 0  # 마지막 공격 시간
        }
        normal_monsters.append(game_world['monsters'][monster_id])
    
    # 보스 몬스터 1마리 유지
    boss_monsters = [m for m in game_world['monsters'].values() if m.get('monster_type') == 'boss']
    if len(boss_monsters) < 1:
        spawn_boss_monster()

def spawn_boss_monster():
    """보스 몬스터 생성"""
    boss_id = str(uuid.uuid4())
    game_world['monsters'][boss_id] = {
        'x': random.randint(100, 700),
        'y': random.randint(100, 500),
        'hp': 150,
        'max_hp': 150,
        'type': '🐲',  # 드래곤 보스
        'monster_type': 'boss',
        'last_attack': 0,
        'attack_pattern': 0,
        'target_player': None,  # 타겟 플레이어
        'detection_range': 200,  # 감지 범위 (더 넓게)
        'attack_range': 60,  # 공격 범위
        'move_speed': 5.0,  # 이동 속도 (플레이어보다 더 빠르게)
        'last_move': 0  # 마지막 이동 시간
    }

def spawn_items():
    """아이템 생성"""
    if len(game_world['items']) < 3:
        item_id = str(uuid.uuid4())
        game_world['items'][item_id] = {
            'x': random.randint(50, 750),
            'y': random.randint(50, 550),
            'type': random.choice(['💎', '⚔️', '🛡️', '💰'])
        }

# --- 듀얼 시스템 함수들 ---
def create_duel_request(from_player_id, to_player_id):
    """듀얼 신청 생성"""
    request_id = str(uuid.uuid4())
    game_world['duel_requests'][request_id] = {
        'from_player': from_player_id,
        'to_player': to_player_id,
        'timestamp': date.today().isoformat(),
        'from_username': game_world['players'][from_player_id]['username'],
        'to_username': game_world['players'][to_player_id]['username']
    }
    return request_id

def accept_duel_request(request_id):
    """듀얼 신청 수락"""
    if request_id not in game_world['duel_requests']:
        return False
    
    request = game_world['duel_requests'][request_id]
    player1_id = request['from_player']
    player2_id = request['to_player']
    
    # 듀얼 생성
    duel_id = str(uuid.uuid4())
    game_world['duels'][duel_id] = {
        'player1_id': player1_id,
        'player2_id': player2_id,
        'status': 'active',
        'arena_pos': {'x': 400, 'y': 300},  # 아레나 중앙
        'start_time': date.today().isoformat()
    }
    
    # 플레이어들을 아레나로 이동
    game_world['players'][player1_id]['x'] = 350
    game_world['players'][player1_id]['y'] = 300
    game_world['players'][player1_id]['in_duel'] = duel_id
    
    game_world['players'][player2_id]['x'] = 450
    game_world['players'][player2_id]['y'] = 300
    game_world['players'][player2_id]['in_duel'] = duel_id
    
    # 요청 삭제
    del game_world['duel_requests'][request_id]
    return duel_id

def end_duel(duel_id, winner_id=None):
    """듀얼 종료"""
    if duel_id not in game_world['duels']:
        return False
    
    duel = game_world['duels'][duel_id]
    player1_id = duel['player1_id']
    player2_id = duel['player2_id']
    
    # 플레이어들 듀얼 상태 해제
    if player1_id in game_world['players']:
        game_world['players'][player1_id].pop('in_duel', None)
        game_world['players'][player1_id]['hp'] = 100  # HP 회복
    
    if player2_id in game_world['players']:
        game_world['players'][player2_id].pop('in_duel', None)
        game_world['players'][player2_id]['hp'] = 100  # HP 회복
    
    # 듀얼 삭제
    del game_world['duels'][duel_id]
    return True

# --- 몬스터 AI 시스템 ---
def update_monster_ai():
    """몬스터 AI 업데이트"""
    import time
    current_time = time.time()
    
    for monster_id, monster in game_world['monsters'].items():
        # 가장 가까운 플레이어 찾기
        closest_player = None
        closest_distance = float('inf')
        
        for player_id, player in game_world['players'].items():
            # 듀얼 중인 플레이어는 제외
            if player.get('in_duel'):
                continue
                
            distance = ((monster['x'] - player['x']) ** 2 + (monster['y'] - player['y']) ** 2) ** 0.5
            
            if distance < closest_distance:
                closest_distance = distance
                closest_player = {'id': player_id, 'data': player}
        
        # 감지 범위 내에 플레이어가 있는지 확인
        if closest_player and closest_distance <= monster['detection_range']:
            monster['target_player'] = closest_player['id']
            
            # 공격 범위 내라면 공격
            if closest_distance <= monster['attack_range']:
                if current_time - monster.get('last_attack', 0) > 2.0:  # 2초 쿨다운
                    attack_player(monster_id, closest_player['id'])
                    monster['last_attack'] = current_time
            else:
                # 추적 이동
                if current_time - monster.get('last_move', 0) > 0.016:  # 약 60fps로 이동 (매우 부드럽게)
                    move_monster_towards_player(monster, closest_player['data'])
                    monster['last_move'] = current_time
        else:
            # 타겟 해제
            monster['target_player'] = None

def move_monster_towards_player(monster, player):
    """몬스터가 플레이어 쪽으로 이동"""
    dx = player['x'] - monster['x']
    dy = player['y'] - monster['y']
    
    # 정규화
    distance = (dx ** 2 + dy ** 2) ** 0.5
    if distance > 0:
        dx /= distance
        dy /= distance
        
        # 이동 (프레임당 이동량을 작게 하여 부드럽게)
        frame_speed = monster['move_speed'] * 0.3  # 프레임당 실제 이동량
        monster['x'] += dx * frame_speed
        monster['y'] += dy * frame_speed
        
        # 경계 체크
        monster['x'] = max(25, min(775, monster['x']))
        monster['y'] = max(25, min(575, monster['y']))

def attack_player(monster_id, player_id):
    """몬스터가 플레이어를 공격"""
    if monster_id not in game_world['monsters'] or player_id not in game_world['players']:
        return
    
    monster = game_world['monsters'][monster_id]
    player = game_world['players'][player_id]
    
    # 데미지 계산
    if monster.get('monster_type') == 'boss':
        damage = random.randint(8, 15)
    else:
        damage = random.randint(3, 8)
    
    # 플레이어 HP 감소
    player['hp'] -= damage
    if player['hp'] < 0:
        player['hp'] = 0
    
    # 몬스터 공격 이벤트 발생
    socketio.emit('player_damaged_by_monster', {
        'player_id': player_id,
        'monster_id': monster_id,
        'monster_type': monster['type'],
        'damage': damage,
        'hp': player['hp']
    }, room='game_world')

# 게임 초기화
spawn_monsters()
spawn_items()

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

@app.route('/mmorpg_game')
def mmorpg_game():
    common_data = get_common_render_data()
    if not common_data or 'username' not in session: return redirect(url_for('login'))
    return render_template('mmorpg_game.html', **common_data)

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
    
    # 활동 내역 생성
    activities = [
        {
            'icon': 'star',
            'description': f'Earned {player_data["score"]} total points',
            'time': 'All time'
        },
        {
            'icon': 'ticket',
            'description': f'Collected {player_data["tickets"]} tickets',
            'time': 'All time'
        },
        {
            'icon': 'sword',
            'description': f'Reached level {player_data["level"]}',
            'time': 'Current'
        }
    ]
    
    # 통계 계산
    goals = load_user_goals()
    total_goals = len(goals)
    completed_goals = len([g for g in goals if g['status'] == 'Completed'])
    completion_rate = int((completed_goals / total_goals) * 100) if total_goals > 0 else 0
    
    stats = {
        'score': player_data['score'],
        'tickets': player_data['tickets'],
        'total_goals': total_goals,
        'completed_goals': completed_goals,
        'completion_rate': completion_rate
    }
    
    # 가입일 추가
    player_data['join_date'] = player_data.get('join_date', 'Unknown')
    
    return render_template('profile.html', 
                         player=player_data,
                         badges=owned_badges,
                         activities=activities,
                         stats=stats,
                         **common_data)

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

@app.route('/calendar')
def calendar():
    common_data = get_common_render_data()
    if not common_data or 'username' not in session: return redirect(url_for('login'))
    return render_template('calendar.html', **common_data)

@app.route('/get_calendar_events')
def get_calendar_events():
    if 'username' not in session:
        return jsonify([])
    try:
        goals = load_user_goals()
        events = []
        for i, goal in enumerate(goals):
            if 'deadline' in goal:
                events.append({
                    'id': str(i),
                    'title': goal['text'],
                    'start': goal['deadline'],
                    'backgroundColor': '#28a745' if goal['status'] == 'Completed' else '#007bff',
                    'allDay': True
                })
        print(f"Sending {len(events)} events")  # 디버깅용 로그
        return jsonify(events)
    except Exception as e:
        print(f"Error in get_calendar_events: {str(e)}")  # 디버깅용 로그
        return jsonify([])

@app.route('/add_calendar_goal', methods=['POST'])
def add_calendar_goal():
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    data = request.get_json()
    goals = load_user_goals()
    new_goal = {
        'text': data['title'],
        'status': 'In Progress',
        'deadline': data['date']
    }
    if data['isRecurring']:
        new_goal['type'] = 'recurring'
        new_goal['last_completed'] = None
    goals.append(new_goal)
    save_user_goals(goals)
    return jsonify({
        'success': True,
        'goal': {
            'id': str(len(goals) - 1),
            'title': data['title'],
            'date': data['date']
        }
    })

@app.route('/toggle_calendar_goal/<goal_id>', methods=['POST'])
def toggle_calendar_goal(goal_id):
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    goals = load_user_goals()
    goal_id = int(goal_id)
    if 0 <= goal_id < len(goals):
        goal = goals[goal_id]
        goal['status'] = 'Completed' if goal['status'] == 'In Progress' else 'In Progress'
        save_user_goals(goals)
        return jsonify({
            'success': True,
            'completed': goal['status'] == 'Completed'
        })
    return jsonify({'success': False, 'error': 'Goal not found'})

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
            player_data['exp'] += 10  # MMORPG 경험치 추가
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
    default_player_data = {'tickets': 0, 'score': 0, 'items': [], 'equipped_badge': None, 'last_login_date': None, 'level': 1, 'exp': 0, 'hp': 100}
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

# --- WebSocket 이벤트 핸들러들 ---
@socketio.on('connect')
def on_connect():
    if 'username' in session:
        player_data = load_user_player_data()
        session_id = request.sid
        
        # 게임 월드에 플레이어 추가
        game_world['players'][session_id] = {
            'username': session['username'],
            'x': random.randint(100, 700),
            'y': random.randint(100, 500),
            'level': player_data.get('level', 1),
            'exp': player_data.get('exp', 0),
            'hp': player_data.get('hp', 100),
            'last_seen': date.today().isoformat()
        }
        
        join_room('game_world')
        
        # 현재 게임 상태를 새 플레이어에게 전송
        emit('game_state', {
            'players': game_world['players'],
            'monsters': game_world['monsters'],
            'items': game_world['items']
        })
        
        # 다른 플레이어들에게 새 플레이어 알림
        emit('player_joined', {
            'session_id': session_id,
            'player': game_world['players'][session_id]
        }, room='game_world', include_self=False)

@socketio.on('disconnect')
def on_disconnect():
    session_id = request.sid
    if session_id in game_world['players']:
        # 다른 플레이어들에게 플레이어 떠남 알림
        emit('player_left', {'session_id': session_id}, room='game_world')
        
        # 게임 월드에서 플레이어 제거
        del game_world['players'][session_id]
        leave_room('game_world')

@socketio.on('player_move')
def on_player_move(data):
    session_id = request.sid
    if session_id in game_world['players']:
        # 플레이어 위치 업데이트
        game_world['players'][session_id]['x'] = data['x']
        game_world['players'][session_id]['y'] = data['y']
        
        # 다른 플레이어들에게 위치 업데이트 전송
        emit('player_moved', {
            'session_id': session_id,
            'x': data['x'],
            'y': data['y']
        }, room='game_world', include_self=False)

@socketio.on('attack_monster')
def on_attack_monster(data):
    monster_id = data['monster_id']
    session_id = request.sid
    
    if monster_id in game_world['monsters'] and session_id in game_world['players']:
        monster = game_world['monsters'][monster_id]
        player = game_world['players'][session_id]
        
        # 몬스터 데미지 (보스는 더 적은 데미지)
        if monster.get('monster_type') == 'boss':
            damage = random.randint(3, 8)  # 보스는 더 강함
        else:
            damage = random.randint(5, 15)
        monster['hp'] -= damage
        
        if monster['hp'] <= 0:
            # 몬스터 처치 - 경험치와 점수 획득 (보스는 더 많은 보상)
            if monster.get('monster_type') == 'boss':
                exp_gained = random.randint(50, 75)  # 보스 보상
                score_gained = random.randint(20, 30)
            else:
                exp_gained = random.randint(15, 25)
                score_gained = random.randint(3, 8)
            
            player['exp'] += exp_gained
            
            # 레벨업 체크
            if player['exp'] >= player['level'] * 100:
                player['level'] += 1
                player['exp'] = 0
                player['hp'] = 100  # 레벨업시 HP 회복
                
                emit('level_up', {
                    'new_level': player['level']
                }, room=session_id)
            
            # 플레이어 데이터 저장
            if 'username' in session:
                player_data = load_user_player_data()
                player_data['level'] = player['level']
                player_data['exp'] = player['exp']
                player_data['hp'] = player['hp']
                player_data['score'] += score_gained
                save_user_player_data(player_data)
            
            # 몬스터 제거
            del game_world['monsters'][monster_id]
            
            # 새 몬스터 생성
            spawn_monsters()
            
            # 모든 플레이어에게 업데이트 전송
            emit('monster_killed', {
                'monster_id': monster_id,
                'killer': player['username'],
                'exp_gained': exp_gained,
                'score_gained': score_gained
            }, room='game_world')
            
        else:
            # 몬스터가 살아있음 - 데미지만 전송
            emit('monster_damaged', {
                'monster_id': monster_id,
                'damage': damage,
                'hp': monster['hp']
            }, room='game_world')

@socketio.on('collect_item')
def on_collect_item(data):
    item_id = data['item_id']
    session_id = request.sid
    
    if item_id in game_world['items'] and session_id in game_world['players']:
        item = game_world['items'][item_id]
        player = game_world['players'][session_id]
        
        # 아이템 효과 적용
        if item['type'] == '💎':
            score_bonus = 20
        elif item['type'] == '⚔️':
            score_bonus = 15
        elif item['type'] == '🛡️':
            player['hp'] = min(100, player['hp'] + 25)  # HP 회복
            score_bonus = 10
        elif item['type'] == '💰':
            score_bonus = 25
        
        # 플레이어 데이터 업데이트
        if 'username' in session:
            player_data = load_user_player_data()
            player_data['score'] += score_bonus
            if item['type'] == '🛡️':
                player_data['hp'] = player['hp']
            save_user_player_data(player_data)
        
        # 아이템 제거
        del game_world['items'][item_id]
        
        # 새 아이템 생성
        spawn_items()
        
        # 모든 플레이어에게 업데이트 전송
        emit('item_collected', {
            'item_id': item_id,
            'collector': player['username'],
            'item_type': item['type'],
            'score_bonus': score_bonus
        }, room='game_world')

@socketio.on('chat_message')
def on_chat_message(data):
    session_id = request.sid
    if session_id in game_world['players']:
        player = game_world['players'][session_id]
        
        # 채팅 메시지를 모든 플레이어에게 전송
        emit('chat_message', {
            'username': player['username'],
            'message': data['message']
        }, room='game_world')

# --- 듀얼 시스템 웹소켓 이벤트들 ---
@socketio.on('request_duel')
def on_request_duel(data):
    session_id = request.sid
    target_username = data['target_username']
    
    if session_id not in game_world['players']:
        return
    
    # 대상 플레이어 찾기
    target_player_id = None
    for player_id, player in game_world['players'].items():
        if player['username'] == target_username:
            target_player_id = player_id
            break
    
    if not target_player_id:
        emit('duel_error', {'message': '플레이어를 찾을 수 없습니다.'})
        return
    
    if target_player_id == session_id:
        emit('duel_error', {'message': '자신에게는 듀얼 신청할 수 없습니다.'})
        return
    
    # 이미 듀얼 중인지 확인
    if game_world['players'][session_id].get('in_duel'):
        emit('duel_error', {'message': '이미 듀얼 중입니다.'})
        return
    
    if game_world['players'][target_player_id].get('in_duel'):
        emit('duel_error', {'message': '상대방이 이미 듀얼 중입니다.'})
        return
    
    # 듀얼 요청 생성
    request_id = create_duel_request(session_id, target_player_id)
    
    # 신청자에게 알림
    emit('duel_request_sent', {
        'target_username': target_username,
        'request_id': request_id
    })
    
    # 대상자에게 알림
    emit('duel_request_received', {
        'from_username': game_world['players'][session_id]['username'],
        'request_id': request_id
    }, room=target_player_id)

@socketio.on('accept_duel')
def on_accept_duel(data):
    session_id = request.sid
    request_id = data['request_id']
    
    if session_id not in game_world['players']:
        return
    
    if request_id not in game_world['duel_requests']:
        emit('duel_error', {'message': '듀얼 요청을 찾을 수 없습니다.'})
        return
    
    request = game_world['duel_requests'][request_id]
    if request['to_player'] != session_id:
        emit('duel_error', {'message': '권한이 없습니다.'})
        return
    
    # 듀얼 시작
    duel_id = accept_duel_request(request_id)
    if duel_id:
        # 양쪽 플레이어에게 듀얼 시작 알림
        emit('duel_started', {
            'duel_id': duel_id,
            'opponent': game_world['players'][request['from_player']]['username']
        }, room=session_id)
        
        emit('duel_started', {
            'duel_id': duel_id,
            'opponent': game_world['players'][session_id]['username']
        }, room=request['from_player'])
        
        # 모든 플레이어에게 게임 상태 업데이트
        emit('game_state', {
            'players': game_world['players'],
            'monsters': game_world['monsters'],
            'items': game_world['items'],
            'duels': game_world['duels']
        }, room='game_world')

@socketio.on('decline_duel')
def on_decline_duel(data):
    session_id = request.sid
    request_id = data['request_id']
    
    if request_id not in game_world['duel_requests']:
        return
    
    request = game_world['duel_requests'][request_id]
    if request['to_player'] != session_id:
        return
    
    # 신청자에게 거절 알림
    emit('duel_declined', {
        'from_username': game_world['players'][session_id]['username']
    }, room=request['from_player'])
    
    # 요청 삭제
    del game_world['duel_requests'][request_id]

@socketio.on('attack_player')
def on_attack_player(data):
    session_id = request.sid
    target_player_id = data['target_player_id']
    
    if session_id not in game_world['players'] or target_player_id not in game_world['players']:
        return
    
    attacker = game_world['players'][session_id]
    target = game_world['players'][target_player_id]
    
    # 듀얼 중인지 확인
    if not attacker.get('in_duel') or attacker.get('in_duel') != target.get('in_duel'):
        emit('duel_error', {'message': '듀얼 중이 아닙니다.'})
        return
    
    # 데미지 계산
    damage = random.randint(15, 25)
    target['hp'] -= damage
    
    if target['hp'] <= 0:
        target['hp'] = 0
        # 듀얼 종료
        duel_id = attacker['in_duel']
        end_duel(duel_id, session_id)
        
        # 승리/패배 알림
        emit('duel_ended', {
            'winner': attacker['username'],
            'loser': target['username'],
            'result': 'victory'
        }, room=session_id)
        
        emit('duel_ended', {
            'winner': attacker['username'],
            'loser': target['username'],
            'result': 'defeat'
        }, room=target_player_id)
        
        # 승리 보상
        if 'username' in session:
            player_data = load_user_player_data()
            player_data['score'] += 50  # 듀얼 승리 보상
            save_user_player_data(player_data)
    else:
        # 데미지 알림
        emit('player_damaged', {
            'attacker': attacker['username'],
            'target': target['username'],
            'damage': damage,
            'hp': target['hp']
        }, room='game_world')
    
    # 게임 상태 업데이트
    emit('game_state', {
        'players': game_world['players'],
        'monsters': game_world['monsters'],
        'items': game_world['items'],
        'duels': game_world['duels']
            }, room='game_world')

# --- 몬스터 AI 업데이트 소켓 이벤트 ---
@socketio.on('monster_ai_update')
def on_monster_ai_update():
    update_monster_ai()
    
    # 모든 플레이어에게 업데이트된 게임 상태 전송
    emit('game_state', {
        'players': game_world['players'],
        'monsters': game_world['monsters'],
        'items': game_world['items'],
        'duels': game_world['duels']
    }, room='game_world')

@socketio.on('player_damaged')
def on_player_damaged(data):
    # 플레이어가 몬스터에게 데미지를 받았을 때
    emit('player_damaged_event', {
        'player_id': data['player_id'],
        'damage': data['damage'],
        'hp': data['hp']
    }, room='game_world')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)