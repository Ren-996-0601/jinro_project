from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from role_presets import ROLE_PRESETS

from game_logic import (
    get_night_time_left, get_day_time_left, get_vote_time_left,
    force_kaitou_swap, force_vote, kaitou_exchange,
    tally_votes, determine_result
)

import random, string, time
from collections import Counter

app = Flask(__name__)
app.secret_key = 'your_secret_key'

COMMUNITIES = ['test_com']  # テスト用コミュニティ名
users = []
rooms = {}  # room_id: {"members": [usernames], "gm": username, "role_presets": preset, "community": community_name}

# トップページルート
@app.route('/')
def index():
    return render_template('index.html')

# ログイン画面ルート（仮実装、後で詳細を作成）
@app.route('/login', methods=['GET', 'POST'])
def login():
    msg = ''
    if request.method == 'POST':
        community = request.form['community']
        username = request.form['username']
        password = request.form['password']
        user = next((u for u in users if u['community'] == community and u['username'] == username and u['password'] == password), None)
        if user:
            session['community'] = community
            session['username'] = username
            return redirect(url_for('create_or_join'))
        else:
            msg = '認証に失敗しました。'
    return render_template('login.html', msg=msg)

# ユーザー登録
@app.route('/register', methods=['GET', 'POST'])
def register():
    msg = ''
    if request.method == 'POST':
        community = request.form['community']
        username = request.form['username']
        password = request.form['password']
        if community not in COMMUNITIES:
            msg = '存在しないコミュニティコードです。'
        elif any(u['username'] == username and u['community'] == community for u in users):
            msg = 'このコミュニティ内でそのユーザー名は既に使われています。'
        else:
            users.append({'community': community, 'username': username, 'password': password})
            session['community'] = community
            session['username'] = username
            return redirect(url_for('create_or_join'))
    return render_template('register.html', msg=msg)

# ルーム作成・参加選択
@app.route('/create_or_join')
def create_or_join():
    if 'username' not in session:
        return redirect(url_for('register'))
    return render_template('create_or_join.html')

# ルーム作成
@app.route('/create_room', methods=['GET', 'POST'])
def create_room():
    if 'username' not in session:
        return redirect(url_for('register'))
    if request.method == 'POST':
        room_id = ''.join(random.choices(string.digits, k=4))
        selected_role_name = request.form['role_presets']
        # 選択された配役データを取得
        selected_preset = next((preset for preset in ROLE_PRESETS if preset['name'] == selected_role_name), None)
        if not selected_preset:
            return "配役が不正です", 400
        
        rooms[room_id] = {
            "members": [session['username']],
            "gm": session['username'],
            "role_presets": selected_preset,
            "community": session['community'],
            "max_players": selected_preset['num_players'],
            "phase": "waiting",  # ← ゲーム開始前は "waiting"
            "night_actions": {},    # 各プレイヤーの夜アクション結果を記録
            "red_chat": [], # 人狼の赤チャットメッセージ
        }

        session['room_id'] = room_id
        return redirect(url_for('room', room_id=room_id))
    return render_template('create_room.html', role_presets=ROLE_PRESETS)

# ルーム参加
@app.route('/join_room', methods=['GET', 'POST'])
def join_room():
    msg = ''
    if 'username' not in session:
        return redirect(url_for('register'))
    if request.method == 'POST':
        room_id = request.form['room_id']
        if room_id in rooms:
            room = rooms[room_id]
            if len(room['members']) >= room['max_players']:
                msg = 'この部屋は定員に達しています。'
            elif session['username'] not in room['members']:
                room['members'].append(session['username'])
                session['room_id'] = room_id
                return redirect(url_for('room', room_id=room_id, from_='post'))
            else:
                session['room_id'] = room_id
                return redirect(url_for('room', room_id=room_id, from_='post'))
        else:
            msg = 'そのルームは存在しません。'
    return render_template('join_room.html', msg=msg)

# ルーム画面
@app.route('/room/<room_id>', methods=['GET', 'POST'])
def room(room_id):
    if 'username' not in session or 'room_id' not in session:
        return redirect(url_for('register'))
    if room_id not in rooms:
        html = """
        <!doctype html>
        <meta charset="utf-8">
        <p>接続中…（サーバの状態を確認しています）</p>
        <script>
            setTimeout(function(){ location.replace(location.href); }, 1000);
        </script>
        """
        return html, 200

    room = rooms[room_id]
    roles = room.get('roles', {})
    username = session['username']
    is_gm = (username == room['gm'])
    msg = ''

    # ゲーム開始ボタンが押されたとき（GMのみ）
    if request.method == 'POST' and is_gm and room['phase'] == "waiting":
        if len(room['members']) != room['max_players']:
            msg = f"参加者が{room['max_players']}人ちょうど集まっていないとゲームを開始できません。"
        else:
            # 役職配布処理
            preset = room['role_presets']   # 選択された配役プリセット
            roles_list = preset['roles'][:]
            random.shuffle(roles_list)
            members = room['members']
            assigned_roles = {}
            for i, member in enumerate(members):
                assigned_roles[member] = roles_list[i]
            room['roles'] = assigned_roles
            room['extra_roles'] = roles_list[len(members):]
            room['phase'] = "night"
            msg = 'ゲームが開始されました。'
            roles = room['roles']
            room['night_start_time'] = time.time()  # 現在のUNIX時刻
            room['night_time'] = preset.get('night_time', 30)  # role_presets.pyから取得
            room['is_peace_village'] = all(role != "人狼" for role in room['roles'].values())
            return redirect(url_for('room', room_id=room_id, from_='post'))

    room.setdefault('transition_locked', False)
    
    # 夜フェーズ終了チェック
    if room['phase'] == "night":
        if get_night_time_left(room) <= 0 and not room['transition_locked']:
            room['transition_locked'] = True
            try:
                room['phase'] = "day"
                room['day_start_time'] = time.time()
                room['day_time'] = room['role_presets'].get('day_time', 60)
            finally:
                room['transition_locked'] = False
    
    # 昼フェーズ終了チェック
    if room['phase'] == "day" and get_day_time_left(room) <= 0 and not room['transition_locked']:
        room['transition_locked'] = True
        try:
            room['phase'] = "vote"
            room['vote_start_time'] = time.time()
            room['vote_time'] = room['role_presets'].get('vote_time', 60)
            room['votes'] = {}
        finally:
            room['transition_locked'] = False
    
    # 投票フェーズ終了チェック
    if room['phase'] == "vote" and get_vote_time_left(room) <= 0 and not room['transition_locked']:
        room['transition_locked'] = True
        try:
            force_kaitou_swap(room)
            # ここで集計や結果表示用データを作成してもOK
            # 怪盗の交換処理
            for kaitou, target in room.get('kaitou_swaps', {}).items():
                kaitou_exchange(room, kaitou, target)
            force_vote(room)
            tally_votes(room)
            determine_result(room)
            room['phase'] = "result"
        finally:
            room['transition_locked'] = False
        
    if request.method == 'POST' and room['phase'] == "night":
        roles = room.get('roles', {})  # 念のため再取得
        action = request.form.get('action')
        # 赤チャット
        if action == "red_chat" and roles.get(username, "") == "人狼":
            msg_text = request.form['red_chat_message']
            room['red_chat'].append({'sender':username, 'text':msg_text})
            msg = "赤チャットを送信しました。"
        # 占い師の占い
        elif action == "fortune" and roles.get(username, "") == "占い師":
            target = request.form['fortune_target']
            if target == "extra":
                result = " / ".join(room['extra_roles'])
            else:
                result = f"{target}の役職は「{roles.get(target, '不明')}」"
            room['night_actions'][username] = result
            return redirect(url_for('room', room_id=room_id, from_='post'))
        # 怪盗の交換
        elif action == "kaitou" and roles.get(username, "") == "怪盗":
            target = request.form['kaitou_target']
            # 交換情報を記録（rolesは変更しない）
            room.setdefault('kaitou_swaps', {})[username] = target
            # 交換相手の役職を怪盗に通知
            swapped_role = roles.get(target, "不明")
            result = f"{target}とカードを交換し、あなたの役職は「{swapped_role}」になりました。"
            room['night_actions'][username] = result
            return redirect(url_for('room', room_id=room_id, from_='post'))
    
    # 投票処理
    if request.method == "POST" and room['phase'] == "vote":
        action = request.form.get("action")
        if action == "vote":
            voter = session['username']
            target = request.form.get("vote_target")
            if voter not in room['votes']:
                room['votes'][voter] = target
                flash(f"{target}に投票しました。")
            else:
                flash("既に投票済みです。")
        # POST-Redirect-GETでメッセージを保持
        return redirect(url_for('room', room_id=room_id, from_='post'))

    night_time_left = get_night_time_left(room)
    day_time_left = get_day_time_left(room)
    vote_time_left = get_vote_time_left(room) if room['phase'] == "vote" else 0
    return render_template(
        'room.html',
        room_id=room_id,
        members=room['members'],
        is_gm=is_gm,
        roles=room.get('roles'),  # ← .get()で安全に取得
        extra_roles=room.get('extra_roles', []),
        msg=msg,
        max_players=room['max_players'],
        phase=room['phase'],
        night_actions=room.get('night_actions', {}),
        red_chat=room.get('red_chat', []),
        night_time_left=night_time_left,
        day_time_left=day_time_left,
        vote_time_left=vote_time_left,
        votes=room.get('votes', {}),
        vote_counts=room.get('vote_counts', {}),
        executed=room.get('executed', []),
        result_msg=room.get('result_msg', ''),
        winners=room.get('winners', []),
        losers=room.get('losers', []),
    )

@app.route('/room/<room_id>/red_chat', methods=['GET'])
def get_red_chat(room_id):
    room = rooms.get(room_id)
    if not room:
        return jsonify({'error': 'room not found'}), 404
    # ここではチャット内容だけ返す
    return jsonify(room.get('red_chat', []))

@app.route('/room/<room_id>/red_chat', methods=['POST'])
def post_red_chat(room_id):
    room = rooms.get(room_id)
    if not room:
        return jsonify({'error': 'room not found'}), 404
    data = request.get_json()
    username = session.get('username')
    text = data.get('message', '').strip()
    if not username or not text:
        return jsonify({'error': 'invalid'}), 400
    # チャットを保存
    room.setdefault('red_chat', []).append({'sender': username, 'text': text})
    return jsonify({'result': 'ok'})

@app.route('/room/<room_id>/status', methods=['GET'])
def room_status(room_id):
    """
    部屋の存在と現在のフェーズ、残り時間を返す軽量API
    """
    room = rooms.get(room_id)
    if not room:
        return jsonify({'ok': False, 'error': 'room not found'}), 404
    return jsonify({
        'ok': True,
        'phase': room['phase'],
        'night_time_left': get_night_time_left(room),
        'day_time_left': get_day_time_left(room),
        'vote_time_left': get_vote_time_left(room) if room['phase'] == 'vote' else 0
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
