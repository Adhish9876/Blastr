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
SHOOT_COOLDOWN = 0.3
UPDATE_RATE = 60
INTERPOLATION_DELAY = 0.05
PLAYER_SIZE = 30
SCREEN_PADDING = PLAYER_SIZE // 2 # Padding from screen edges

# --- Command-line argument for server IP ---
if len(sys.argv) > 1:
    HOST = sys.argv[1]

# --- Pygame Initialization ---
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption('Blastr! - A Multiplayer Arena Shooter')
clock = pygame.time.Clock()

# --- Load Assets and Fonts ---
try:
    font_main = pygame.font.SysFont("Segoe UI", 50, bold=True)
    font_medium = pygame.font.SysFont("Segoe UI", 32)
    font_small = pygame.font.SysFont("Segoe UI", 24)
    font_ui = pygame.font.SysFont("Segoe UI", 18)
    font_helper = pygame.font.SysFont("Segoe UI", 16) # NEW: Font for helper text
except:
    font_main = pygame.font.Font(None, 48)
    font_medium = pygame.font.Font(None, 32)
    font_small = pygame.font.Font(None, 24)
    font_ui = pygame.font.Font(None, 20)
    font_helper = pygame.font.Font(None, 18)

font_title = pygame.font.SysFont("Segoe UI Black", 96)

try:
    background_image = pygame.image.load('background.jpg').convert()
    background_image = pygame.transform.scale(background_image, (WIDTH, HEIGHT))
except pygame.error:
    background_image = pygame.Surface((WIDTH, HEIGHT))
    background_image.fill((19, 21, 40))

# --- Networking ---
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
player_id = None

def receive_data(sock):
    try:
        sock.settimeout(0.01)
        raw_msglen = sock.recv(4)
        if not raw_msglen: return None
        msglen = struct.unpack('!I', raw_msglen)[0]
        if msglen > 8192: return None
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
    try:
        packed_data = pickle.dumps(data)
        sock.sendall(struct.pack('!I', len(packed_data)) + packed_data)
        return True
    except (ConnectionResetError, BrokenPipeError, OSError):
        global connection_lost
        connection_lost = True
        return False

# --- Game State Variables ---
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
input_box = pygame.Rect(WIDTH / 2 - 175, HEIGHT / 2 - 70, 350, 50)
input_active = False

# --- Enhanced Button Class ---
class Button:
    def __init__(self, rect, text, color, hover_color, shadow_color, font):
        self.rect = pygame.Rect(rect)
        self.shadow_rect = pygame.Rect(rect)
        self.shadow_rect.y += 5
        self.text = text
        self.color = color
        self.hover_color = hover_color
        self.shadow_color = shadow_color
        self.font = font
        self.is_hovered = False
        self.y_offset = 0

    def draw(self, screen):
        current_color = self.hover_color if self.is_hovered else self.color
        if self.is_hovered and pygame.mouse.get_pressed()[0]: self.y_offset = 5
        else: self.y_offset = 0
        shadow_pos = self.shadow_rect.copy(); shadow_pos.y = self.rect.y + 5 - self.y_offset
        pygame.draw.rect(screen, self.shadow_color, shadow_pos, border_radius=12)
        main_pos = self.rect.copy(); main_pos.y -= self.y_offset
        pygame.draw.rect(screen, current_color, main_pos, border_radius=12)
        text_surf = self.font.render(self.text, True, (255, 255, 255))
        text_rect = text_surf.get_rect(center=main_pos.center)
        screen.blit(text_surf, text_rect)

    def check_hover(self, mouse_pos): self.is_hovered = self.rect.collidepoint(mouse_pos)
    def is_clicked(self, event): return self.is_hovered and event.type == MOUSEBUTTONDOWN and event.button == 1

# --- Core Game Logic ---
def connect_to_server():
    global player_id, game_screen, connection_lost, client
    try:
        print(f"🔌 Connecting to server at {HOST}:{PORT}...")
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((HOST, PORT))
        initial_data = receive_data(client)
        if not initial_data or 'id' not in initial_data: raise Exception("Failed to receive player ID.")
        player_id = initial_data['id']
        send_data(client, {'id': player_id, 'action': 'set_name', 'name': player_name})
        print(f"🎮 You are Player #{player_id} ({player_name})")
        game_screen = 'playing'
        connection_lost = False
    except Exception as e:
        print(f"❌ Failed to connect: {e}"); game_screen = 'main_menu'; connection_lost = True

# --- Drawing Functions ---
def draw_text(text, font, color, pos, shadow=True, left_align=False, center_align=False):
    shadow_surf = font.render(text, True, (0,0,0,100)) if shadow else None
    text_surf = font.render(text, True, color)
    if left_align: text_rect = text_surf.get_rect(midleft=pos)
    elif center_align: text_rect = text_surf.get_rect(center=pos)
    else: text_rect = text_surf.get_rect(topleft=pos)
    if shadow: screen.blit(shadow_surf, (text_rect.x+2, text_rect.y+2))
    screen.blit(text_surf, text_rect)

def draw_main_menu():
    screen.blit(background_image, (0, 0))
    draw_text("BLASTR!", font_title, (255, 255, 255), (WIDTH/2, HEIGHT/4), center_align=True)
    draw_text("Enter your name and join the fight!", font_small, (200, 200, 220), (WIDTH/2, HEIGHT/4 + 80), center_align=True)
    border_color = (66, 165, 245) if input_active else (90, 90, 110)
    pygame.draw.rect(screen, (20, 20, 35), input_box, border_radius=8)
    pygame.draw.rect(screen, border_color, input_box, 2, border_radius=8)
    text_surface = font_medium.render(player_name, True, (255, 255, 255))
    screen.blit(text_surface, (input_box.x + 15, input_box.y + 8))
    if connection_lost: draw_text("Failed to connect to the server.", font_small, (239, 83, 80), (WIDTH/2, HEIGHT - 50), center_align=True)

def draw_playing_ui(health, max_health):
    health_ratio = health / max_health
    bar_pos, bar_size = (20, HEIGHT - 50), (250, 25)
    pygame.draw.rect(screen, (20, 20, 35), (*bar_pos, *bar_size), border_radius=8)
    health_color = (102, 187, 106) if health_ratio > 0.6 else (255, 238, 88) if health_ratio > 0.3 else (239, 83, 80)
    if health_ratio > 0: pygame.draw.rect(screen, health_color, (bar_pos[0], bar_pos[1], bar_size[0] * health_ratio, bar_size[1]), border_radius=8)
    pygame.draw.rect(screen, (90, 90, 110), (*bar_pos, *bar_size), 2, border_radius=8)
    draw_text(f"{int(health)} / {max_health}", font_ui, (255,255,255), (bar_pos[0] + bar_size[0]/2, bar_pos[1] + bar_size[1]/2), center_align=True)
    draw_text(f"FPS: {clock.get_fps():.0f}", font_ui, (200,200,220), (WIDTH-50, 15), center_align=True)
    # --- NEW: Draw helper text ---
    draw_text("TAB - Leaderboard", font_helper, (255,255,255,150), (20, 20), shadow=False)
    draw_text("ESC - Exit Game", font_helper, (255,255,255,150), (20, 40), shadow=False)

def draw_player(pos, color, name, is_local_player=False):
    x, y = int(pos['x']), int(pos['y'])
    pygame.draw.circle(screen, (0,0,0,50), (x, y+2), PLAYER_SIZE // 2)
    pygame.draw.circle(screen, color, (x, y), PLAYER_SIZE // 2)
    highlight_color = tuple(min(255, c+50) for c in color)
    pygame.draw.circle(screen, highlight_color, (x-3, y-3), (PLAYER_SIZE // 2) - 8)
    name_color = (200, 220, 255) if is_local_player else (255, 255, 255)
    draw_text(name, font_ui, name_color, (x, y - 25), center_align=True)

def draw_scoreboard():
    if not server_snapshots: return
    player_data = server_snapshots[-1].get('players', {})
    sorted_players = sorted(scoreboard_data.items(), key=lambda item: item[1], reverse=True)
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); overlay.fill((19, 21, 40, 220)); screen.blit(overlay, (0, 0))
    draw_text("SCOREBOARD", font_main, (255, 255, 255), (WIDTH/2, 100), center_align=True)
    y_offset = 180
    for i, (pid, kills) in enumerate(sorted_players[:10]):
        name = player_data.get(pid, {}).get('name', 'Unknown')
        row_color = (255, 238, 88) if pid == player_id else (220, 220, 220)
        draw_text(f"#{i+1}", font_medium, row_color, (WIDTH/2 - 250, y_offset), left_align=True)
        draw_text(name, font_medium, row_color, (WIDTH/2 - 150, y_offset), left_align=True)
        draw_text(str(kills), font_medium, row_color, (WIDTH/2 + 250, y_offset), center_align=True)
        y_offset += 40

# --- Button Instances ---
play_button = Button((WIDTH/2 - 125, HEIGHT/2, 250, 60), "PLAY", (38, 166, 154), (46, 204, 113), (26, 110, 100), font_main)
quit_button = Button((WIDTH/2 - 125, HEIGHT/2 + 80, 250, 60), "QUIT", (239, 83, 80), (241, 108, 105), (150, 40, 40), font_main)
respawn_button = Button((WIDTH/2 - 125, HEIGHT/2 + 50, 250, 60), "RESPAWN", (66, 165, 245), (92, 180, 255), (30, 100, 180), font_main)

# --- Main Game Loop ---
while running:
    dt = clock.tick(FPS) / 1000.0
    mouse_pos = pygame.mouse.get_pos()
    
    for event in pygame.event.get():
        if event.type == QUIT: running = False
        # --- NEW: Handle ESCAPE key to exit ---
        if event.type == KEYDOWN and event.key == K_ESCAPE: running = False
            
        if game_screen == 'main_menu':
            play_button.check_hover(mouse_pos); quit_button.check_hover(mouse_pos)
            if play_button.is_clicked(event): game_screen = 'connecting'
            if quit_button.is_clicked(event): running = False
            if event.type == MOUSEBUTTONDOWN: input_active = input_box.collidepoint(event.pos)
            if event.type == KEYDOWN and input_active:
                if event.key == K_BACKSPACE: player_name = player_name[:-1]
                elif len(player_name) < 15: player_name += event.unicode
        elif game_screen == 'dead':
            respawn_button.check_hover(mouse_pos)
            if respawn_button.is_clicked(event): send_data(client, {'id': player_id, 'action': 'respawn'})

    if game_screen == 'connecting':
        screen.blit(background_image, (0, 0)); draw_text("Connecting...", font_main, (255, 255, 255), (WIDTH/2, HEIGHT/2), center_align=True)
        pygame.display.flip(); connect_to_server()
    elif game_screen == 'main_menu':
        draw_main_menu(); play_button.draw(screen); quit_button.draw(screen)
    elif game_screen in ['playing', 'dead']:
        if connection_lost: game_screen = 'main_menu'; continue
        
        game_data = receive_data(client)
        if game_data and 'players' in game_data:
            game_data['timestamp'] = time.time()
            server_snapshots.append(game_data); scoreboard_data = game_data.get('stats', {})

        if len(server_snapshots) >= 2:
            render_time = time.time() - INTERPOLATION_DELAY
            s_after, s_before = server_snapshots[-1], server_snapshots[-2]
            if (time_diff := s_after['timestamp'] - s_before['timestamp']) > 0:
                t = max(0.0, min(1.0, (render_time - s_before['timestamp']) / time_diff))
                for pid in s_after['players']:
                    if pid != player_id and pid in s_before['players']:
                        b, a = s_before['players'][pid], s_after['players'][pid]
                        player_display_positions[pid] = {'x': b['x'] + (a['x'] - b['x']) * t, 'y': b['y'] + (a['y'] - b['y']) * t}

        if server_snapshots and player_id in (latest := server_snapshots[-1])['players']:
            my_player_health = latest['players'][player_id]['health']
            if my_player_health <= 0 and game_screen == 'playing': game_screen = 'dead'
            elif my_player_health > 0 and game_screen == 'dead': game_screen = 'playing'
        
        keys = pygame.key.get_pressed()
        if game_screen == 'playing':
            if pygame.mouse.get_pressed()[0]: send_data(client, {'id': player_id, 'action': 'shoot', 'angle': math.atan2(mouse_pos[1] - predicted_pos['y'], mouse_pos[0] - predicted_pos['x'])})
            predicted_pos['x'] += (mouse_pos[0] - predicted_pos['x']) * 0.2
            predicted_pos['y'] += (mouse_pos[1] - predicted_pos['y']) * 0.2
            predicted_pos['x'] = max(SCREEN_PADDING, min(WIDTH - SCREEN_PADDING, predicted_pos['x']))
            predicted_pos['y'] = max(SCREEN_PADDING, min(HEIGHT - SCREEN_PADDING, predicted_pos['y']))
            send_data(client, {'id': player_id, 'action': 'move', 'pos': (predicted_pos['x'], predicted_pos['y'])})

        screen.blit(background_image, (0,0))
        pygame.draw.rect(screen, (90, 90, 110, 50), (0, 0, WIDTH, HEIGHT), 4, border_radius=1)
        
        if server_snapshots:
            latest = server_snapshots[-1]
            for b in latest['bullets']: pygame.draw.circle(screen, (255, 238, 88), (int(b['x']), int(b['y'])), 5)
            for pid, p_data in latest['players'].items():
                if p_data['health'] > 0:
                    pos = predicted_pos if pid == player_id else player_display_positions.get(pid, p_data)
                    draw_player(pos, p_data['color'], p_data['name'], pid == player_id)

        draw_playing_ui(my_player_health, my_player_max_health)
        
        if keys[K_TAB]: draw_scoreboard()

        if game_screen == 'dead':
            s = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA); s.fill((20, 20, 35, 200)); screen.blit(s, (0, 0))
            draw_text("YOU WERE BLASTED!", font_main, (239, 83, 80), (WIDTH/2, HEIGHT/2 - 50), center_align=True)
            respawn_button.draw(screen)

    pygame.display.flip()

# --- Cleanup ---
client.close()
pygame.quit()
sys.exit()

