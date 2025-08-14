import time, random
from collections import Counter

from utils import is_werewolf_side, is_villager_side

def get_night_time_left(room):
    now = time.time()
    start = room.get('night_start_time', now)
    seconds = room.get('night_time', 30)
    left = int(start + seconds - now)
    return max(left, 0)

def get_day_time_left(room):
    now = time.time()
    start = room.get('day_start_time', now)
    seconds = room.get('day_time', 60)
    left = int(start + seconds - now)
    return max(left, 0)

def get_vote_time_left(room):
    now = time.time()
    start = room.get('vote_start_time', now)
    seconds = room.get('vote_time', 60)
    left = int(start + seconds - now)
    return max(left, 0)

# 怪盗が交換しなかった場合の自動交換
def force_kaitou_swap(room):
    roles = room.get('roles', {})
    kaitou_swaps = room.setdefault('kaitou_swaps', {})
    members = list(room['members'])
    for kaitou_name, role in roles.items():
        if role == "怪盗" and kaitou_name not in kaitou_swaps:
            # 自分以外を交換先候補に
            candidates = [m for m in members if m != kaitou_name]
            if candidates:
                target = random.choice(candidates)
                kaitou_swaps[kaitou_name] = target
                print(f"[自動処理] 怪盗 {kaitou_name} は {target} と強制的に交換されました。")

# プレイヤーが投票しなかった場合の自動投票
def force_vote(room):
    votes = room.setdefault('votes', {})
    members = list(room['members'])
    for voter in members:
        if voter not in votes:
            # 自分以外を投票先候補に
            candidates = [m for m in members if m != voter]
            if candidates:
                target = random.choice(candidates)
                votes[voter] = target
                print(f"[自動処理] {voter} は {target} に強制的に投票されました。")

def kaitou_exchange(room, kaitou_name, target_name):
    roles = room['roles']
    kaitou_role = roles[kaitou_name]
    target_role = roles[target_name]

    if target_role == "村人":
        roles[kaitou_name] = "白怪盗"
        roles[target_name] = "村人"
    elif target_role == "占い師":
        roles[kaitou_name] = "白怪盗"
        roles[target_name] = "占い師"
    elif target_role == "人狼":
        roles[kaitou_name] = "人狼(元怪盗)"
        roles[target_name] = "元人狼"
    elif target_role == "狂人":
        roles[kaitou_name] = "狂人(元怪盗)"
        roles[target_name] = "元狂人"

def tally_votes(room):
    votes = room.get('votes', {})
    vote_counts = Counter(votes.values())

    # 全員の得票数をroomに保存（得票数が0の人も含める）
    all_members = room['members']
    all_vote_counts = {member: vote_counts.get(member, 0) for member in all_members}
    room['vote_counts'] = all_vote_counts

    if not vote_counts:
        executed = []
    elif len(set(vote_counts.values())) == 1 and len(vote_counts) == len(all_members) and list(vote_counts.values())[0] == 1:
        # 全員1票ずつで最多得票者なし
        executed = []
    else:
        max_votes = max(vote_counts.values())
        executed = [name for name, cnt in vote_counts.items() if cnt == max_votes]
    room['executed'] = executed # 結果表示用

def determine_result(room):
    roles = room['roles']
    is_peace = room['is_peace_village']
    executed = room.get('executed', [])

    # 処刑者の役職リスト
    executed_roles = [roles[name] for name in executed]

    # 勝利条件
    if is_peace:
        if not executed:
            result_msg = "全員勝利です"
            winner_side = "ALL"
        else:
            result_msg = "全員敗北です"
            winner_side = "NONE"
    else:
        if any(role in ("人狼", "人狼(元怪盗)") for role in executed_roles):
            result_msg = "村人陣営の勝利です"
            winner_side = "村人"
        else:
            result_msg = "人狼陣営の勝利です"
            winner_side = "人狼"
    room['result_msg'] = result_msg
    room['winner_side'] = winner_side

    # 勝者・敗者リスト作成
    winner_names = [name for name, role in roles.items()
                    if (winner_side == "村人" and is_villager_side(role)) or
                       (winner_side == "人狼" and is_werewolf_side(role)) or
                       (winner_side == "ALL")]
    loser_names = [name for name in roles if name not in winner_names]

    room['winners'] = [(name, roles[name]) for name in winner_names]
    room['losers'] = [(name, roles[name]) for name in loser_names]