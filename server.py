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
TICK_RATE = 1.0 / 30.0 
CLIENT_TIMEOUT = 10.0
SUPERPOWER_CHECK_INTERVAL = 15.0
SUPERPOWER_COOLDOWN = 15.0

# --- Game Constants ---
WIDTH, HEIGHT = 1000, 700
BULLET_SPEED = 800
PLAYER_RADIUS = 17
PLAYER_SIZE = PLAYER_RADIUS * 2
BULLET_RADIUS = 6
PLAYER_HEALTH = 100
BULLET_DAMAGE = 10
SUPERPOWER_BULLET_DAMAGE = 50
RESPAWN_TIME = 3.0
SHOOT_COOLDOWN = 0.2
KILL_SCORE = 100
PLAYER_MAX_SPEED = 300 

# --- Powerup & Hazard Constants ---
POWERUP_SPAWN_CHANCE = 0.002
MAX_POWERUPS = 3
POWERUP_TYPES = {
    'health': {'color': (102, 187, 106), 'value': 30},
    'speed': {'color': (66, 165, 245), 'duration': 5.0},
    'damage': {'color': (239, 83, 80), 'duration': 8.0}
}
HAZARD_INTERVAL = 20.0
HAZARD_DURATION = 5.0

# --- Server State ---
players = {}
bullets = []
powerups = []
walls = []
events_queue = []
player_id_counter = 0
sockets_map = {}
client_last_seen = {}
game_stats = {'kills': defaultdict(int), 'deaths': defaultdict(int), 'streaks': defaultdict(int)}
last_superpower_grant_time = 0
last_hazard_time = 0

# --- Colors ---
AVAILABLE_COLORS = [
    (239, 83, 80), (236, 64, 122), (171, 71, 188), (126, 87, 194),
    (92, 107, 192), (66, 165, 245), (41, 182, 246), (38, 198, 218),
    (38, 166, 154), (102, 187, 106), (174, 213, 129), (255, 238, 88)
]
SUPERPOWER_BULLET_COLOR = (255, 238, 88)

def receive_data(sock):
    try:
        raw_msglen=sock.recv(4)
        if not raw_msglen: return None
        msglen=struct.unpack('!I',raw_msglen)[0]
        if msglen>4096: return None
        data=b''
        while len(data)<msglen:data+=sock.recv(msglen-len(data))
        return pickle.loads(data)
    except(struct.error, pickle.UnpicklingError, ConnectionAbortedError, ConnectionResetError, socket.timeout, BlockingIOError):
        return None

def send_data(sock, data):
    try:
        packed_data = pickle.dumps(data)
        sock.sendall(struct.pack('!I', len(packed_data)) + packed_data)
        return True
    except (ConnectionResetError, BrokenPipeError, OSError):
        return False

def get_new_player_color():
    return AVAILABLE_COLORS[len(players) % len(AVAILABLE_COLORS)]

def check_for_comeback_power():
    global last_superpower_grant_time
    SCORE_DIFFERENCE_THRESHOLD = KILL_SCORE * 2
    if time.time() - last_superpower_grant_time < SUPERPOWER_COOLDOWN or len(players) < 2: return

    for p in players.values(): p['superpower_ready'] = False
    scores = {pid: game_stats['kills'].get(pid, 0) for pid in players.keys()}
    lowest_score, highest_score = min(scores.values()), max(scores.values())

    if lowest_score >= highest_score or (highest_score - lowest_score < SCORE_DIFFERENCE_THRESHOLD): return

    last_place_players = [pid for pid, score in scores.items() if score == lowest_score]
    if last_place_players:
        target_pid = random.choice(last_place_players)
        if target_pid in players:
            players[target_pid]['superpower_ready'] = True
            last_superpower_grant_time = time.time()
            print(f"✨ Granted superpower to Player {target_pid}")

def check_rect_collision(rect1, rect2):
    return (rect1['x'] < rect2['x'] + rect2['width'] and
            rect1['x'] + rect1['width'] > rect2['x'] and
            rect1['y'] < rect2['y'] + rect2['height'] and
            rect1['height'] + rect1['y'] > rect2['y'])

def update_hazards(dt, current_time):
    global last_hazard_time, walls
    if current_time - last_hazard_time > HAZARD_INTERVAL and not walls:
        last_hazard_time = current_time
        side = random.choice(['v', 'h'])
        speed = 250
        if side == 'v':
            wall = {'x': -20, 'y': random.randint(0, int(HEIGHT*0.3)), 'width': 20, 'height': int(HEIGHT*0.4), 'vx': speed, 'vy': 0, 'color': (255,0,100)}
            if random.random() > 0.5:
                wall['x'] = WIDTH; wall['vx'] = -speed
        else:
            wall = {'x': random.randint(0, int(WIDTH*0.3)), 'y': -20, 'width': int(WIDTH*0.4), 'height': 20, 'vx': 0, 'vy': speed, 'color': (255,0,100)}
            if random.random() > 0.5:
                wall['y'] = HEIGHT; wall['vy'] = -speed
        wall['spawn_time'] = current_time
        walls.append(wall)

    for w in walls[:]:
        w['x'] += w['vx'] * dt; w['y'] += w['vy'] * dt
        if current_time - w['spawn_time'] > HAZARD_DURATION: walls.remove(w); continue
        for pid, p in players.items():
            player_rect = {'x': p['x']-PLAYER_RADIUS, 'y': p['y']-PLAYER_RADIUS, 'width': PLAYER_SIZE, 'height': PLAYER_SIZE}
            if p['health'] > 0 and check_rect_collision(w, player_rect):
                p['health'] = 0; p['death_time'] = current_time
                game_stats['deaths'][pid] += 1; game_stats['streaks'][pid] = 0
                events_queue.append({'type': 'death', 'player_id': pid, 'pos': (p['x'], p['y']), 'color': p['color']})

def update_powerups():
    if len(powerups) < MAX_POWERUPS and random.random() < POWERUP_SPAWN_CHANCE:
        p_type = random.choice(list(POWERUP_TYPES.keys()))
        powerups.append({'x': random.randint(50,WIDTH-50), 'y': random.randint(50,HEIGHT-50), 'type': p_type, **POWERUP_TYPES[p_type]})
    
    for p in powerups[:]:
        for pid, player in players.items():
            if player['health'] > 0 and math.hypot(p['x']-player['x'], p['y']-player['y']) < PLAYER_RADIUS + 15:
                if p['type'] == 'health': player['health'] = min(PLAYER_HEALTH, player['health'] + p['value'])
                else: player[f"{p['type']}_boost"] = time.time() + p['duration']
                events_queue.append({'type':'powerup_collect', 'pos':(p['x'],p['y']), 'color':p['color']})
                powerups.remove(p); break

def game_loop(dt):
    current_time = time.time()
    update_hazards(dt, current_time)
    update_powerups()

    for bullet in bullets[:]:
        speed_multiplier = 1.5 if bullet.get('is_fast') else 1
        bullet['x'] += math.cos(bullet['angle']) * BULLET_SPEED * dt * speed_multiplier
        bullet['y'] += math.sin(bullet['angle']) * BULLET_SPEED * dt * speed_multiplier

        if not (0 < bullet['x'] < WIDTH and 0 < bullet['y'] < HEIGHT):
            if bullet in bullets: bullets.remove(bullet); continue

        for pid, player in players.items():
            if player['health'] <= 0 or pid == bullet.get('owner_id'): continue
            if math.hypot(bullet['x']-player['x'],bullet['y']-player['y']) < PLAYER_RADIUS+BULLET_RADIUS:
                owner = players.get(bullet['owner_id'])
                damage_multiplier = 2.0 if owner and owner.get('damage_boost',0)>current_time else 1.0
                damage = bullet.get('damage',BULLET_DAMAGE) * damage_multiplier
                player['health'] -= damage
                events_queue.append({'type':'hit','pos':(bullet['x'],bullet['y']),'color':bullet.get('color'),'target_id':pid})

                if player['health'] <= 0:
                    player['health']=0;player['death_time']=current_time
                    game_stats['deaths'][pid] += 1; game_stats['streaks'][pid] = 0
                    events_queue.append({'type':'death','player_id':pid,'pos':(player['x'],player['y']),'color':player['color']})
                    if owner:
                        events_queue.append({'type':'kill', 'killer_id': bullet['owner_id']})
                        game_stats['kills'][bullet['owner_id']] += KILL_SCORE; game_stats['streaks'][bullet['owner_id']] += 1
                        if (streak := game_stats['streaks'][bullet['owner_id']]) >= 2:
                            events_queue.append({'type':'kill_streak', 'name':owner['name'], 'streak':streak})
                        check_for_comeback_power()

                if bullet in bullets: bullets.remove(bullet); break
    
    for player in players.values():
        if player['health'] <= 0 and 'death_time' in player and current_time-player.get('death_time',0)>=RESPAWN_TIME:
            player['health']=PLAYER_HEALTH;player['x']=random.randint(50,WIDTH-50);player['y']=random.randint(50,HEIGHT-50)
            player.pop('death_time', None); player.pop('speed_boost', None); player.pop('damage_boost', None)

def main():
    global player_id_counter, last_superpower_grant_time
    server=socket.socket(socket.AF_INET,socket.SOCK_STREAM);server.setblocking(False);server.bind((HOST,PORT));server.listen(10)
    print(f"🚀 Blastr! Server started on {HOST}:{PORT}")
    inputs=[server];last_tick_time=time.time();last_superpower_check_time=time.time();last_superpower_grant_time=time.time()

    while True:
        try:
            readable,_,exceptional=select.select(inputs,[],inputs,0.01)
            current_time=time.time(); dt=current_time-last_tick_time
            if dt >= TICK_RATE:
                game_loop(dt); last_tick_time = current_time
                if current_time-last_superpower_check_time>SUPERPOWER_CHECK_INTERVAL:
                    check_for_comeback_power(); last_superpower_check_time=current_time
                if players:
                    public_players = {}
                    for pid, p in players.items():
                        player_data = {'x': p['x'], 'y': p['y'], 'color': p['color'], 'health': p['health'], 'name': p['name'], 'superpower_ready': p.get('superpower_ready', False)}
                        if 'death_time' in p:
                            player_data['death_time'] = p['death_time']
                        public_players[pid] = player_data

                    game_state={'players':public_players,'bullets':bullets,'stats':game_stats['kills'],'events':events_queue,'powerups':powerups, 'walls':walls}
                    for pid,sock in list(sockets_map.items()):
                        if not send_data(sock,game_state): exceptional.append(sock)
                    events_queue.clear()
            
            for sock in readable:
                if sock is server:
                    conn,addr=server.accept();conn.setblocking(False);inputs.append(conn);print(f"🎮 New from {addr}")
                    pid=player_id_counter;player_id_counter+=1;sockets_map[pid]=conn;client_last_seen[pid]=time.time()
                    players[pid]={'x':random.randint(50,WIDTH-50),'y':random.randint(50,HEIGHT-50),'health':PLAYER_HEALTH,'color':get_new_player_color(),'name':f"Player {pid}",'last_shot':0}
                    send_data(conn,{'id':pid});print(f"✅ Player {pid} spawned.")
                else:
                    pid=next((p for p,s in sockets_map.items() if s==sock),None)
                    msg=receive_data(sock)
                    if msg and pid is not None and (player:=players.get(pid)):
                        client_last_seen[pid]=time.time()
                        action=msg.get('action')
                        if action=='move':
                            speed = PLAYER_MAX_SPEED * (1.5 if player.get('speed_boost', 0) > time.time() else 1.0)
                            max_dist = speed * TICK_RATE 
                            dx, dy = msg['pos'][0] - player['x'], msg['pos'][1] - player['y']
                            dist = math.hypot(dx, dy)
                            if dist > max_dist:
                                player['x'] += (dx/dist) * max_dist
                                player['y'] += (dy/dist) * max_dist
                            else:
                                player['x'], player['y'] = msg['pos']
                        elif action=='shoot' and player['health']>0 and time.time()-player['last_shot']>=SHOOT_COOLDOWN:
                            player['last_shot']=time.time();bullets.append({'x':player['x'],'y':player['y'],'angle':msg['angle'],'owner_id':pid,'color':player['color']})
                        elif action=='set_name':
                            if 1<=(len(n:=msg['name'].strip()))<=30:players[pid]['name']=n;print(f"ℹ️ Player {pid} is now {n}")
                        elif action=='activate_superpower' and player.get('superpower_ready'):
                            player['superpower_ready']=False; print(f"💥 Player {pid} used superpower!")
                            for i in range(32):
                                angle=math.radians(i*(360/16) + (0 if i<16 else 11.25))
                                bullets.append({'x':player['x'],'y':player['y'],'angle':angle,'owner_id':pid,'damage':SUPERPOWER_BULLET_DAMAGE,'color':SUPERPOWER_BULLET_COLOR,'is_fast':True})
                        elif action=='respawn' and player['health']<=0 and 'death_time' not in player: player['death_time']=time.time()
                    else: exceptional.append(sock)

            for sock in exceptional:
                if (pid:=next((p for p,s in sockets_map.items() if s==sock),None)) is not None:
                    print(f"❌ Player {pid} disconnected.");players.pop(pid,None);sockets_map.pop(pid,None);client_last_seen.pop(pid,None);game_stats['kills'].pop(pid,None);game_stats['streaks'].pop(pid,None)
                if sock in inputs:inputs.remove(sock);sock.close()

            for pid in list(client_last_seen.keys()):
                if time.time()-client_last_seen[pid]>CLIENT_TIMEOUT and (sock:=sockets_map.get(pid)):exceptional.append(sock)
        except Exception as e:
            print(f"💥 Server error: {e}"); time.sleep(1)

if __name__ == "__main__":
    main()

