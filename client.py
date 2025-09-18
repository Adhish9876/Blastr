import pygame
import socket
import pickle
import math
import sys
import time
import struct
import random
from collections import deque
from pygame.locals import *

# --- Game Constants ---
WIDTH, HEIGHT = 1000, 700
FPS = 60
HOST = '127.0.0.1'
PORT = 5557
SHOOT_COOLDOWN = 0.3 # Client-side prediction cooldown
UPDATE_RATE = 60
INTERPOLATION_DELAY = 0.05
PLAYER_SIZE = 30
SCREEN_PADDING = PLAYER_SIZE // 2

# --- Command-line argument ---
if len(sys.argv) > 1:
    HOST = sys.argv[1]

# --- Pygame Init ---
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption('Blastr! - A Multiplayer Arena Shooter')
clock = pygame.time.Clock()

# --- Fonts ---
try:
    font_main = pygame.font.SysFont("Segoe UI", 50, bold=True)
    font_medium = pygame.font.SysFont("Segoe UI", 32)
    font_small = pygame.font.SysFont("Segoe UI", 24)
    font_ui = pygame.font.SysFont("Segoe UI", 18)
    font_helper = pygame.font.SysFont("Segoe UI", 16)
    font_super = pygame.font.SysFont("Segoe UI Black", 40) # NEW: Font for superpower alert
except: # Fallback fonts
    font_main, font_medium, font_small, font_ui, font_helper, font_super = [pygame.font.Font(None, s) for s in [48, 32, 24, 20, 18, 42]]

font_title = pygame.font.SysFont("Segoe UI Black", 96)

# --- Assets ---
try:
    background_image = pygame.image.load('background.jpg').convert()
    background_image = pygame.transform.scale(background_image, (WIDTH, HEIGHT))
except pygame.error:
    background_image = pygame.Surface((WIDTH, HEIGHT)); background_image.fill((19, 21, 40))

# --- Networking ---
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
player_id = None

def receive_data(sock):
    try:
        raw_msglen = sock.recv(4)
        if not raw_msglen: return None
        msglen = struct.unpack('!I', raw_msglen)[0]
        if msglen > 16384: return None # Increased buffer for more bullets
        data = b''
        while len(data) < msglen: data += sock.recv(msglen - len(data))
        return pickle.loads(data)
    except (struct.error, pickle.UnpicklingError, ConnectionAbortedError, ConnectionResetError, socket.timeout, BlockingIOError):
        return None

def send_data(sock, data):
    try:
        sock.sendall(struct.pack('!I', len(p := pickle.dumps(data))) + p)
        return True
    except (ConnectionResetError, BrokenPipeError, OSError):
        global connection_lost; connection_lost = True; return False

# --- Game State ---
game_screen = 'main_menu'
running = True
predicted_pos = {'x': WIDTH / 2, 'y': HEIGHT / 2}
server_snapshots = deque(maxlen=60)
player_display_positions = {}
my_player_health = 100
my_player_max_health = 100
scoreboard_data = {}
connection_lost = False
player_name = "Player" + str(random.randint(100, 999))
input_box = pygame.Rect(WIDTH/2-175, HEIGHT/2-70, 350, 50)
input_active = False
last_shot_time = 0
superpower_available = False # NEW: State for superpower

# --- UI Classes ---
class Button:
    def __init__(self, rect, text, color, hover, shadow, font):
        self.rect, self.text, self.color, self.hover, self.shadow, self.font = pygame.Rect(rect), text, color, hover, shadow, font
        self.shadow_rect = pygame.Rect(rect); self.shadow_rect.y += 5
        self.is_hovered, self.y_offset = False, 0
    def draw(self, screen):
        self.y_offset = 5 if self.is_hovered and pygame.mouse.get_pressed()[0] else 0
        shadow_pos = self.shadow_rect.copy(); shadow_pos.y = self.rect.y + 5 - self.y_offset
        main_pos = self.rect.copy(); main_pos.y -= self.y_offset
        pygame.draw.rect(screen, self.shadow, shadow_pos, border_radius=12)
        pygame.draw.rect(screen, self.hover if self.is_hovered else self.color, main_pos, border_radius=12)
        screen.blit(self.font.render(self.text, True, (255,255,255)), self.font.render(self.text, True, (255,255,255)).get_rect(center=main_pos.center))
    def check_hover(self, m): self.is_hovered = self.rect.collidepoint(m)
    def is_clicked(self, e): return self.is_hovered and e.type == MOUSEBUTTONDOWN and e.button == 1

# --- Game Logic ---
def connect_to_server():
    global player_id, game_screen, connection_lost, client
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((HOST, PORT))
        if not (initial_data := receive_data(client)) or 'id' not in initial_data: raise Exception("No ID.")
        player_id = initial_data['id']
        send_data(client, {'id': player_id, 'action': 'set_name', 'name': player_name})
        game_screen, connection_lost = 'playing', False
        print(f"🎮 Connected as Player #{player_id} ({player_name})")
    except Exception as e:
        print(f"❌ Connect failed: {e}"); game_screen, connection_lost = 'main_menu', True

# --- Drawing Functions ---
def draw_text(text, font, color, pos, sh=True, l=False, c=False):
    ts = font.render(text, True, color)
    if l: tr = ts.get_rect(midleft=pos)
    elif c: tr = ts.get_rect(center=pos)
    else: tr = ts.get_rect(topleft=pos)
    if sh: screen.blit(font.render(text, True, (0,0,0,100)), (tr.x+2, tr.y+2))
    screen.blit(ts, tr)

def draw_main_menu():
    screen.blit(background_image, (0, 0))
    draw_text("BLASTR!", font_title, (255,255,255), (WIDTH/2, HEIGHT/4), c=True)
    draw_text("Enter name and join the fight!", font_small, (200,200,220), (WIDTH/2, HEIGHT/4+80), c=True)
    bc = (66,165,245) if input_active else (90,90,110)
    pygame.draw.rect(screen, (20,20,35), input_box, border_radius=8); pygame.draw.rect(screen, bc, input_box, 2, border_radius=8)
    screen.blit(font_medium.render(player_name, True, (255,255,255)), (input_box.x+15, input_box.y+8))
    if connection_lost: draw_text("Failed to connect.", font_small, (239,83,80), (WIDTH/2, HEIGHT-50), c=True)

def draw_playing_ui(health, max_health):
    hr, br, bs = health/max_health, (20, HEIGHT-50), (250, 25)
    pygame.draw.rect(screen, (20,20,35), (*br, *bs), border_radius=8)
    hc = (102,187,106) if hr > 0.6 else (255,238,88) if hr > 0.3 else (239,83,80)
    if hr > 0: pygame.draw.rect(screen, hc, (br[0], br[1], bs[0]*hr, bs[1]), border_radius=8)
    pygame.draw.rect(screen, (90,90,110), (*br, *bs), 2, border_radius=8)
    draw_text(f"{int(health)}/{max_health}", font_ui, (255,255,255), (br[0]+bs[0]/2, br[1]+bs[1]/2), c=True)
    draw_text(f"FPS: {clock.get_fps():.0f}", font_ui, (200,200,220), (WIDTH-50, 15), c=True)
    draw_text("TAB-Leaderboard", font_helper, (255,255,255,150), (20,20), sh=False); draw_text("ESC-Exit", font_helper, (255,255,255,150), (20,40), sh=False)
    # --- NEW: Draw superpower alert ---
    if superpower_available:
        alpha = 128 + 127 * math.sin(time.time() * 5) # Pulsing alpha
        draw_text("PRESS [F] - SUPERPOWER READY!", font_super, (255, 238, 88, alpha), (WIDTH/2, HEIGHT - 60), c=True)

def draw_player(pos, color, name, is_local=False):
    x, y = int(pos['x']), int(pos['y'])
    pygame.draw.circle(screen, (0,0,0,50), (x,y+2), PLAYER_SIZE//2)
    pygame.draw.circle(screen, color, (x,y), PLAYER_SIZE//2)
    pygame.draw.circle(screen, tuple(min(255,c+50) for c in color), (x-3,y-3), (PLAYER_SIZE//2)-8)
    draw_text(name, font_ui, (200,220,255) if is_local else (255,255,255), (x,y-25), c=True)

def draw_scoreboard():
    if not server_snapshots: return
    pd = server_snapshots[-1].get('players', {})
    sp = sorted(scoreboard_data.items(), key=lambda i: i[1], reverse=True)
    ov = pygame.Surface((WIDTH,HEIGHT), pygame.SRCALPHA); ov.fill((19,21,40,220)); screen.blit(ov, (0,0))
    draw_text("SCOREBOARD", font_main, (255,255,255), (WIDTH/2, 100), c=True)
    for i, (pid, kills) in enumerate(sp[:10]):
        name, rc = pd.get(pid,{}).get('name','?'), (255,238,88) if pid==player_id else (220,220,220)
        draw_text(f"#{i+1}", font_medium, rc, (WIDTH/2-250, 180+i*40), l=True)
        draw_text(name, font_medium, rc, (WIDTH/2-150, 180+i*40), l=True)
        draw_text(str(kills), font_medium, rc, (WIDTH/2+250, 180+i*40), c=True)

# --- UI Instances ---
play_btn = Button((WIDTH/2-125, HEIGHT/2, 250,60), "PLAY", (38,166,154), (46,204,113), (26,110,100), font_main)
quit_btn = Button((WIDTH/2-125, HEIGHT/2+80, 250,60), "QUIT", (239,83,80), (241,108,105), (150,40,40), font_main)
respawn_btn = Button((WIDTH/2-125, HEIGHT/2+50, 250,60), "RESPAWN", (66,165,245), (92,180,255), (30,100,180), font_main)

# --- Main Game Loop ---
while running:
    dt, mouse_pos = clock.tick(FPS)/1000.0, pygame.mouse.get_pos()
    for e in pygame.event.get():
        if e.type == QUIT or (e.type == KEYDOWN and e.key == K_ESCAPE): running = False
        if game_screen == 'main_menu':
            play_btn.check_hover(mouse_pos); quit_btn.check_hover(mouse_pos)
            if play_btn.is_clicked(e): game_screen = 'connecting'
            if quit_btn.is_clicked(e): running = False
            if e.type == MOUSEBUTTONDOWN: input_active = input_box.collidepoint(e.pos)
            if e.type == KEYDOWN and input_active:
                if e.key == K_BACKSPACE: player_name = player_name[:-1]
                elif len(player_name) < 15: player_name += e.unicode
        elif game_screen == 'dead':
            respawn_btn.check_hover(mouse_pos)
            if respawn_btn.is_clicked(e): send_data(client, {'id': player_id, 'action': 'respawn'})

    if game_screen == 'connecting':
        screen.blit(background_image, (0,0)); draw_text("Connecting...", font_main, (255,255,255), (WIDTH/2, HEIGHT/2), c=True)
        pygame.display.flip(); connect_to_server()
    elif game_screen == 'main_menu':
        draw_main_menu(); play_btn.draw(screen); quit_btn.draw(screen)
    elif game_screen in ['playing', 'dead']:
        if connection_lost: game_screen = 'main_menu'; continue
        if (gd := receive_data(client)) and 'players' in gd:
            gd['timestamp'] = time.time(); server_snapshots.append(gd); scoreboard_data = gd.get('stats', {})
        if len(server_snapshots) >= 2:
            s_after, s_before = server_snapshots[-1], server_snapshots[-2]
            if (td := s_after['timestamp']-s_before['timestamp']) > 0:
                t = max(0.0, min(1.0, (time.time()-INTERPOLATION_DELAY-s_before['timestamp'])/td))
                for pid in s_after['players']:
                    if pid!=player_id and pid in s_before['players']:
                        b,a=s_before['players'][pid], s_after['players'][pid]
                        player_display_positions[pid] = {'x':b['x']+(a['x']-b['x'])*t, 'y':b['y']+(a['y']-b['y'])*t}
        if server_snapshots and player_id in (l:=server_snapshots[-1])['players']:
            my_player_health = l['players'][player_id]['health']
            superpower_available = l['players'][player_id].get('superpower_ready', False)
            if my_player_health <= 0 and game_screen == 'playing': game_screen = 'dead'
            elif my_player_health > 0 and game_screen == 'dead': game_screen = 'playing'
        
        keys = pygame.key.get_pressed()
        if game_screen == 'playing':
            # --- MODIFIED: Shoot with spacebar or mouse ---
            is_shooting = pygame.mouse.get_pressed()[0] or keys[K_SPACE]
            if is_shooting and time.time() - last_shot_time > SHOOT_COOLDOWN:
                last_shot_time = time.time()
                send_data(client, {'id':player_id, 'action':'shoot', 'angle':math.atan2(mouse_pos[1]-predicted_pos['y'], mouse_pos[0]-predicted_pos['x'])})
            # --- NEW: Activate superpower with F key ---
            if keys[K_f] and superpower_available:
                send_data(client, {'id': player_id, 'action': 'activate_superpower'})
                superpower_available = False # Prevent spamming

            predicted_pos['x'] += (mouse_pos[0]-predicted_pos['x'])*0.2
            predicted_pos['y'] += (mouse_pos[1]-predicted_pos['y'])*0.2
            predicted_pos['x'] = max(SCREEN_PADDING, min(WIDTH-SCREEN_PADDING, predicted_pos['x']))
            predicted_pos['y'] = max(SCREEN_PADDING, min(HEIGHT-SCREEN_PADDING, predicted_pos['y']))
            send_data(client, {'id':player_id, 'action':'move', 'pos':(predicted_pos['x'], predicted_pos['y'])})

        screen.blit(background_image, (0,0))
        pygame.draw.rect(screen, (90,90,110,50), (0,0,WIDTH,HEIGHT), 4, border_radius=1)
        if server_snapshots:
            latest = server_snapshots[-1]
            for b in latest['bullets']: pygame.draw.circle(screen, (255,238,88), (int(b['x']), int(b['y'])), 5)
            for pid, p_data in latest['players'].items():
                if p_data['health'] > 0:
                    pos = predicted_pos if pid == player_id else player_display_positions.get(pid, p_data)
                    draw_player(pos, p_data['color'], p_data['name'], pid==player_id)
        
        draw_playing_ui(my_player_health, my_player_max_health)
        if keys[K_TAB]: draw_scoreboard()
        if game_screen == 'dead':
            s = pygame.Surface((WIDTH,HEIGHT), pygame.SRCALPHA); s.fill((20,20,35,200)); screen.blit(s, (0,0))
            draw_text("YOU WERE BLASTED!", font_main, (239,83,80), (WIDTH/2, HEIGHT/2-50), c=True)
            respawn_btn.draw(screen)

    pygame.display.flip()

client.close(); pygame.quit(); sys.exit()


# --- NEW: Superpower activation ---