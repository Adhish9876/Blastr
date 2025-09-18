import socket
import pickle
import sys
import select
import math
import random
import time
import struct
from collections import defaultdict

# --- Server Constants ---
HOST = '0.0.0.0'
PORT = 5557
TICK_RATE = 1.0 / 60.0
CLIENT_TIMEOUT = 10.0
SUPERPOWER_CHECK_INTERVAL = 10.0 # Seconds to check for last place

# --- Game Constants ---
WIDTH, HEIGHT = 1000, 700
BULLET_SPEED = 800 # Per second
PLAYER_RADIUS = 17
BULLET_RADIUS = 6
PLAYER_HEALTH = 100
BULLET_DAMAGE = 10
SUPERPOWER_BULLET_DAMAGE = 50 # --- NEW: Damage for superpower bullets ---
RESPAWN_TIME = 3.0
SHOOT_COOLDOWN = 0.2
KILL_SCORE = 100

# --- Server State ---
players = {}
bullets = []
player_id_counter = 0
sockets_map = {} # Maps player_id to socket
client_last_seen = {}
game_stats = {'kills': defaultdict(int), 'deaths': defaultdict(int)}

# --- Available Colors ---
AVAILABLE_COLORS = [
    (239, 83, 80), (236, 64, 122), (171, 71, 188), (126, 87, 194),
    (92, 107, 192), (66, 165, 245), (41, 182, 246), (38, 198, 218),
    (38, 166, 154), (102, 187, 106), (174, 213, 129), (255, 238, 88)
]

def receive_data(sock):
    """Receives data with a 4-byte length header."""
    try:
        raw_msglen = sock.recv(4)
        if not raw_msglen: return None
        msglen = struct.unpack('!I', raw_msglen)[0]
        if msglen > 4096: return None
        data = b''
        while len(data) < msglen:
            packet = sock.recv(msglen - len(data))
            if not packet: return None
            data += packet
        return pickle.loads(data)
    except (struct.error, pickle.UnpicklingError, ConnectionAbortedError,
            ConnectionResetError, socket.timeout, BlockingIOError):
        return None

def send_data(sock, data):
    """Packs and sends data with a 4-byte length header."""
    try:
        packed_data = pickle.dumps(data)
        sock.sendall(struct.pack('!I', len(packed_data)) + packed_data)
        return True
    except (ConnectionResetError, BrokenPipeError, OSError):
        return False

def get_new_player_color():
    """Cycles through available colors for new players."""
    return AVAILABLE_COLORS[len(players) % len(AVAILABLE_COLORS)]

def check_for_comeback_power():
    """Checks for the player in last place and grants them a superpower."""
    if len(players) < 2: return

    for p in players.values():
        p['superpower_ready'] = False

    active_pids = [pid for pid in players.keys() if pid in game_stats['kills']]
    if not active_pids: return

    # Find the player with the lowest score
    scores = {pid: game_stats['kills'][pid] for pid in active_pids}
    if not scores: return
    
    lowest_score = min(scores.values())
    highest_score = max(scores.values())
    
    if lowest_score >= highest_score: return

    last_place_players = [pid for pid, score in scores.items() if score == lowest_score]
    
    if last_place_players:
        target_pid = random.choice(last_place_players)
        if target_pid in players:
            players[target_pid]['superpower_ready'] = True
            print(f"✨ Granted superpower to Player {target_pid} ({players[target_pid]['name']})")


def game_loop(dt):
    """Main logic update loop for the game."""
    global bullets
    current_time = time.time()

    for bullet in bullets[:]:
        bullet['x'] += math.cos(bullet['angle']) * BULLET_SPEED * dt
        bullet['y'] += math.sin(bullet['angle']) * BULLET_SPEED * dt

        if not (0 < bullet['x'] < WIDTH and 0 < bullet['y'] < HEIGHT):
            if bullet in bullets: bullets.remove(bullet)
            continue

        for pid, player in players.items():
            if player['health'] <= 0 or pid == bullet.get('owner_id'):
                continue
            dist = math.hypot(bullet['x'] - player['x'], bullet['y'] - player['y'])
            if dist < PLAYER_RADIUS + BULLET_RADIUS:
                # --- MODIFIED: Use custom bullet damage if available, otherwise default ---
                damage_to_deal = bullet.get('damage', BULLET_DAMAGE)
                player['health'] -= damage_to_deal
                
                if player['health'] <= 0:
                    player['health'] = 0
                    player['death_time'] = current_time
                    game_stats['deaths'][pid] += 1
                    if bullet['owner_id'] in players: # Ensure killer is still connected
                        game_stats['kills'][bullet['owner_id']] += KILL_SCORE
                if bullet in bullets: bullets.remove(bullet)
                break
    
    for player in players.values():
        if player['health'] <= 0 and 'death_time' in player:
            if current_time - player.get('death_time', 0) >= RESPAWN_TIME:
                player['health'] = PLAYER_HEALTH
                player['x'] = random.randint(50, WIDTH - 50)
                player['y'] = random.randint(50, HEIGHT - 50)
                player.pop('death_time', None)

def main():
    global player_id_counter
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setblocking(False)
    server.bind((HOST, PORT))
    server.listen(10)
    print(f"🚀 Blastr! Server started on {HOST}:{PORT}")
    inputs = [server]
    last_tick_time = time.time()
    last_superpower_check_time = time.time()

    while True:
        try:
            readable, _, exceptional = select.select(inputs, [], inputs, 0.01)
            current_time = time.time()
            dt = current_time - last_tick_time
            if dt >= TICK_RATE:
                game_loop(dt)
                last_tick_time = current_time

                if current_time - last_superpower_check_time > SUPERPOWER_CHECK_INTERVAL:
                    check_for_comeback_power()
                    last_superpower_check_time = current_time
                
                if players:
                    game_state = {'players': players, 'bullets': bullets, 'stats': game_stats['kills']}
                    for pid, sock in list(sockets_map.items()):
                        if not send_data(sock, game_state):
                           exceptional.append(sock)

            for sock in readable:
                if sock is server:
                    conn, addr = server.accept()
                    conn.setblocking(False)
                    inputs.append(conn)
                    print(f"🎮 New player connected from {addr}")
                    player_id = player_id_counter; player_id_counter += 1
                    sockets_map[player_id] = conn
                    client_last_seen[player_id] = time.time()
                    players[player_id] = {
                        'x': random.randint(50, WIDTH - 50), 'y': random.randint(50, HEIGHT - 50),
                        'health': PLAYER_HEALTH, 'color': get_new_player_color(),
                        'name': f"Player {player_id}", 'last_shot': 0, 'superpower_ready': False
                    }
                    send_data(conn, {'id': player_id})
                    print(f"✅ Player {player_id} spawned.")
                else:
                    pid_to_remove = next((pid for pid, s in sockets_map.items() if s == sock), None)
                    message = receive_data(sock)
                    if message and pid_to_remove is not None:
                        client_last_seen[pid_to_remove] = time.time()
                        player = players.get(pid_to_remove)
                        if not player: continue

                        action = message.get('action')
                        if action == 'move': player['x'], player['y'] = message['pos']
                        elif action == 'shoot' and player['health'] > 0 and time.time() - player['last_shot'] >= SHOOT_COOLDOWN:
                            player['last_shot'] = time.time()
                            bullets.append({'x': player['x'], 'y': player['y'], 'angle': message['angle'], 'owner_id': pid_to_remove})
                        elif action == 'set_name':
                            name = message['name'].strip()
                            if 1 <= len(name) <= 15:
                                players[pid_to_remove]['name'] = name
                                print(f"ℹ️ Player {pid_to_remove} is now {name}")
                        # --- MODIFIED: Add a damage key to superpower bullets ---
                        elif action == 'activate_superpower' and player.get('superpower_ready'):
                            player['superpower_ready'] = False
                            print(f"💥 Player {pid_to_remove} used their superpower!")
                            for i in range(16):
                                angle = math.radians(i * (360/16))
                                bullets.append({'x': player['x'], 'y': player['y'], 'angle': angle, 'owner_id': pid_to_remove, 'damage': SUPERPOWER_BULLET_DAMAGE})
                            for i in range(16):
                                angle = math.radians(i * (360/16) + 11.25)
                                bullets.append({'x': player['x'], 'y': player['y'], 'angle': angle, 'owner_id': pid_to_remove, 'damage': SUPERPOWER_BULLET_DAMAGE})
                        elif action == 'respawn' and player['health'] <= 0:
                             if 'death_time' not in player: player['death_time'] = time.time()
                    else:
                        exceptional.append(sock)

            for sock in exceptional:
                pid_to_remove = next((pid for pid, s in sockets_map.items() if s == sock), None)
                if pid_to_remove is not None:
                    print(f"❌ Player {pid_to_remove} disconnected.")
                    players.pop(pid_to_remove, None); sockets_map.pop(pid_to_remove, None)
                    client_last_seen.pop(pid_to_remove, None); game_stats['kills'].pop(pid_to_remove, None)
                if sock in inputs: inputs.remove(sock)
                sock.close()

            for pid in list(client_last_seen.keys()):
                if time.time() - client_last_seen[pid] > CLIENT_TIMEOUT:
                    if (sock := sockets_map.get(pid)): exceptional.append(sock)
        except Exception as e:
            print(f"💥 Server error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()

