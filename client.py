import pygame
import socket
import pickle
import math
import sys
import time
import struct
import random
import json
import os
from collections import deque
from pygame.locals import *

# --- Game Constants ---
ORIGINAL_WIDTH, ORIGINAL_HEIGHT = 1000, 700
FPS = 60
HOST = '127.0.0.1'
PORT = 5557
SHOOT_COOLDOWN = 0.2
INTERPOLATION_DELAY = 0.1 
PLAYER_SIZE = 30
SCREEN_PADDING = PLAYER_SIZE // 2
RESPAWN_TIME = 3.0
SAVE_FILE = 'blastr_progress.json'

if len(sys.argv) > 1: HOST = sys.argv[1]

# --- Pygame Init ---
pygame.init()
screen = pygame.display.set_mode((ORIGINAL_WIDTH, ORIGINAL_HEIGHT))
pygame.display.set_caption('Blastr! - An Addictive Arena Shooter')
clock = pygame.time.Clock()
pygame.mouse.set_visible(True)
pygame.mixer.init()

# Dynamic screen scaling
current_width, current_height = ORIGINAL_WIDTH, ORIGINAL_HEIGHT
scale_factor = 1.0

def get_scaled_pos(x, y):
    return int(x * scale_factor), int(y * scale_factor)

def get_scaled_size(size):
    return int(size * scale_factor)

# --- Sound Effects (Placeholder - you can add actual sound files) ---
sounds = {
    'shoot': None, 'hit': None, 'powerup': None, 'death': None, 'level_up': None
}

# --- Fonts & Assets ---
try:
    font_main, font_medium, font_small, font_ui, font_tiny, font_super, font_killstreak = [pygame.font.SysFont("Segoe UI Black", s) for s in [50, 32, 24, 18, 16, 40, 60]]
    font_title = pygame.font.SysFont("Segoe UI Black", 96)
    font_tiny = pygame.font.SysFont("Segoe UI", 14)
except:
    font_main,font_medium,font_small,font_ui,font_tiny,font_super,font_killstreak,font_title,font_tiny = [pygame.font.Font(None,s) for s in [48,32,24,20,18,42,62,96,14]]

# --- Player Progress System ---
class PlayerProgress:
    def __init__(self):
        self.level = 1
        self.xp = 0
        self.xp_to_next = 100
        self.total_kills = 0
        self.total_deaths = 0
        self.total_powerups = 0
        self.games_played = 0
        self.best_killstreak = 0
        self.achievements = set()
        self.unlocked_titles = set(['Rookie'])
        self.current_title = 'Rookie'
        self.playtime = 0
        self.last_session_start = time.time()
        self.load_progress()
    
    def add_xp(self, amount):
        self.xp += amount
        leveled_up = False
        while self.xp >= self.xp_to_next:
            self.xp -= self.xp_to_next
            self.level += 1
            self.xp_to_next = int(100 * (1.2 ** (self.level - 1)))
            leveled_up = True
            self.check_level_achievements()
        return leveled_up
    
    def check_achievements(self, event_type, data=None):
        new_achievements = []
        
        if event_type == 'kill':
            if self.total_kills == 10 and 'First Blood' not in self.achievements:
                new_achievements.append('First Blood')
            elif self.total_kills == 100 and 'Centurion' not in self.achievements:
                new_achievements.append('Centurion')
            elif self.total_kills == 500 and 'Executioner' not in self.achievements:
                new_achievements.append('Executioner')
        
        elif event_type == 'killstreak':
            streak = data
            if streak >= 5 and 'Rampage' not in self.achievements:
                new_achievements.append('Rampage')
            elif streak >= 10 and 'Unstoppable' not in self.achievements:
                new_achievements.append('Unstoppable')
        
        elif event_type == 'survival':
            survival_time = data
            if survival_time >= 300 and 'Survivor' not in self.achievements:
                new_achievements.append('Survivor')
        
        elif event_type == 'level':
            if self.level >= 10 and 'Veteran' not in self.achievements:
                new_achievements.append('Veteran')
                self.unlocked_titles.add('Veteran')
        
        for achievement in new_achievements:
            self.achievements.add(achievement)
        
        return new_achievements
    
    def check_level_achievements(self):
        if self.level >= 5 and 'Apprentice' not in self.unlocked_titles:
            self.unlocked_titles.add('Apprentice')
        elif self.level >= 10 and 'Veteran' not in self.unlocked_titles:
            self.unlocked_titles.add('Veteran')
        elif self.level >= 20 and 'Expert' not in self.unlocked_titles:
            self.unlocked_titles.add('Expert')
        elif self.level >= 50 and 'Master' not in self.unlocked_titles:
            self.unlocked_titles.add('Master')
        elif self.level >= 100 and 'Legend' not in self.unlocked_titles:
            self.unlocked_titles.add('Legend')
    
    def save_progress(self):
        self.playtime += time.time() - self.last_session_start
        data = {
            'level': self.level, 'xp': self.xp, 'xp_to_next': self.xp_to_next,
            'total_kills': self.total_kills, 'total_deaths': self.total_deaths,
            'total_powerups': self.total_powerups, 'games_played': self.games_played,
            'best_killstreak': self.best_killstreak, 'achievements': list(self.achievements),
            'unlocked_titles': list(self.unlocked_titles), 'current_title': self.current_title,
            'playtime': self.playtime
        }
        try:
            with open(SAVE_FILE, 'w') as f:
                json.dump(data, f)
        except:
            pass
    
    def load_progress(self):
        try:
            if os.path.exists(SAVE_FILE):
                with open(SAVE_FILE, 'r') as f:
                    data = json.load(f)
                self.level = data.get('level', 1)
                self.xp = data.get('xp', 0)
                self.xp_to_next = data.get('xp_to_next', 100)
                self.total_kills = data.get('total_kills', 0)
                self.total_deaths = data.get('total_deaths', 0)
                self.total_powerups = data.get('total_powerups', 0)
                self.games_played = data.get('games_played', 0)
                self.best_killstreak = data.get('best_killstreak', 0)
                self.achievements = set(data.get('achievements', []))
                self.unlocked_titles = set(data.get('unlocked_titles', ['Rookie']))
                self.current_title = data.get('current_title', 'Rookie')
                self.playtime = data.get('playtime', 0)
        except:
            pass

# --- Networking ---
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
player_id = None

def receive_data(sock):
    try:
        raw_msglen = sock.recv(4);
        if not raw_msglen: return None
        msglen = struct.unpack('!I', raw_msglen)[0]
        if msglen > 16384: return None
        data = b''
        while len(data) < msglen: data += sock.recv(msglen - len(data))
        return pickle.loads(data)
    except (struct.error, pickle.UnpicklingError, ConnectionAbortedError, ConnectionResetError, socket.timeout, BlockingIOError):
        return None

def send_data(sock, data):
    try:
        sock.sendall(struct.pack('!I', len(p := pickle.dumps(data))) + p); return True
    except (ConnectionResetError, BrokenPipeError, OSError):
        global connection_lost; connection_lost = True; return False

# --- Game State & FX ---
progress = PlayerProgress()
game_screen = 'main_menu'; running = True
predicted_pos = {'x': ORIGINAL_WIDTH/2, 'y': ORIGINAL_HEIGHT/2}; server_snapshots = deque(maxlen=60)
player_display_positions = {}; my_player_health = 100; my_player_max_health = 100
scoreboard_data = {}; connection_lost = False; player_name = "Player"+str(random.randint(100,999))
input_box = pygame.Rect(ORIGINAL_WIDTH/2-175, ORIGINAL_HEIGHT/2-70, 350, 50); input_active = False
last_shot_time = 0; superpower_available = False
screen_shake = 0; particles = []; announcements = []; level_up_announcements = []
starfield = [(random.randint(0,ORIGINAL_WIDTH), random.randint(0,ORIGINAL_HEIGHT), random.randint(1,3), random.uniform(0.1, 0.5)) for _ in range(200)]
show_info_panel = False; show_progress_panel = False; show_achievements_panel = False
fullscreen = False; current_killstreak = 0; game_start_time = None; survival_time = 0

# --- Enhanced Particle Effects ---
class EnhancedParticle:
    def __init__(self, x, y, color, life, size, velocity=None, particle_type='normal'):
        self.x, self.y, self.color, self.life, self.max_life = x, y, color, life, life
        self.size, self.particle_type = size, particle_type
        if velocity:
            self.vx, self.vy = velocity
        else:
            self.vx, self.vy = random.uniform(-2,2), random.uniform(-3,-1)
        self.gravity = 0.05 if particle_type == 'normal' else 0.02
        self.fade = particle_type == 'glow'
    
    def update(self):
        self.x += self.vx; self.y += self.vy
        if self.particle_type != 'float':
            self.vy += self.gravity
        self.life -= 1; self.size -= 0.1
        
        if self.particle_type == 'float':
            self.vx *= 0.98; self.vy *= 0.98
    
    def draw(self, s):
        if self.size > 0:
            if self.fade:
                alpha = int(255 * (self.life / self.max_life))
                color_with_alpha = (*self.color, alpha)
                glow_surf = pygame.Surface((int(self.size*4), int(self.size*4)), pygame.SRCALPHA)
                pygame.draw.circle(glow_surf, color_with_alpha, (int(self.size*2), int(self.size*2)), int(self.size))
                s.blit(glow_surf, (int(self.x - self.size*2), int(self.y - self.size*2)))
            else:
                pygame.draw.circle(s, self.color, (int(self.x), int(self.y)), int(self.size))

class Announcement:
    def __init__(self, text, color=(255,255,255), duration=2.5, size='normal'):
        self.text, self.start_time, self.duration = text, time.time(), duration
        self.color = color
        self.font = font_super if size == 'large' else font_main if size == 'medium' else font_medium
    
    def draw(self, s, index):
        age = time.time()-self.start_time
        if age < self.duration:
            alpha = max(0, 255*(1-(age/self.duration)**2))
            ts=self.font.render(self.text,1,self.color);ts.set_alpha(alpha)
            y_pos = 20 + (index * 60)
            s.blit(ts,ts.get_rect(topright=(current_width - 20, y_pos)))

# --- Helper Classes ---
class Button:
    def __init__(self, r, t, c, h, s, f):
        self.rect, self.text, self.color, self.hover, self.shadow, self.font = pygame.Rect(r),t,c,h,s,f
        self.s_rect = pygame.Rect(r); self.s_rect.y += 5; self.is_hovered, self.y_off = False,0
    
    def draw(self, s):
        # Scale button for current resolution
        scaled_rect = pygame.Rect(
            int(self.rect.x * scale_factor),
            int(self.rect.y * scale_factor),
            int(self.rect.width * scale_factor),
            int(self.rect.height * scale_factor)
        )
        scaled_shadow = pygame.Rect(scaled_rect)
        scaled_shadow.y += int(5 * scale_factor)
        
        self.y_off = int(5 * scale_factor) if self.is_hovered and pygame.mouse.get_pressed()[0] else 0
        
        shadow_pos = scaled_shadow.copy()
        shadow_pos.y = scaled_rect.y + int(5 * scale_factor) - self.y_off
        main_pos = scaled_rect.copy()
        main_pos.y -= self.y_off
        
        pygame.draw.rect(s, self.shadow, shadow_pos, border_radius=int(12*scale_factor))
        pygame.draw.rect(s, self.hover if self.is_hovered else self.color, main_pos, border_radius=int(12*scale_factor))
        
        text_surface = self.font.render(self.text, 1, (255,255,255))
        s.blit(text_surface, text_surface.get_rect(center=main_pos.center))
    
    def check_hover(self, m):
        scaled_rect = pygame.Rect(
            int(self.rect.x * scale_factor),
            int(self.rect.y * scale_factor),
            int(self.rect.width * scale_factor),
            int(self.rect.height * scale_factor)
        )
        self.is_hovered = scaled_rect.collidepoint(m)
    
    def is_clicked(self, e):
        return self.is_hovered and e.type == MOUSEBUTTONDOWN and e.button == 1

# --- Functions ---
def connect_to_server():
    global player_id, game_screen, connection_lost, client, game_start_time
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0)
        client.connect((HOST, PORT))
        if not (d:=receive_data(client)) or 'id' not in d: raise Exception("No ID.")
        player_id = d['id']; send_data(client, {'id':player_id,'action':'set_name','name':f"{player_name}"})
        client.setblocking(False)
        game_screen, connection_lost = 'playing', False
        game_start_time = time.time()
        progress.games_played += 1
        print(f"🎮 Connected as Player #{player_id}")
    except Exception as e:
        print(f"❌ Connect failed: {e}"); game_screen, connection_lost = 'main_menu', True

def toggle_fullscreen():
    global fullscreen, screen, current_width, current_height, scale_factor
    fullscreen = not fullscreen
    if fullscreen:
        # Get the current display size
        display_info = pygame.display.Info()
        screen = pygame.display.set_mode((display_info.current_w, display_info.current_h), pygame.FULLSCREEN)
        current_width, current_height = display_info.current_w, display_info.current_h
    else:
        screen = pygame.display.set_mode((ORIGINAL_WIDTH, ORIGINAL_HEIGHT))
        current_width, current_height = ORIGINAL_WIDTH, ORIGINAL_HEIGHT
    
    # Calculate scale factor for UI elements
    scale_factor = min(current_width / ORIGINAL_WIDTH, current_height / ORIGINAL_HEIGHT)

def draw_text(t, f, c, p, sh=True, l=False, ce=False, scale=True):
    if scale:
        pos = get_scaled_pos(p[0], p[1]) if isinstance(p, tuple) else p
    else:
        pos = p
    
    ts = f.render(t, True, c)
    if l:
        tr = ts.get_rect(midleft=pos)
    elif ce:
        tr = ts.get_rect(center=pos)
    else:
        tr = ts.get_rect(topleft=pos)
    
    if sh:
        shadow_offset = get_scaled_size(2) if scale else 2
        screen.blit(f.render(t, True, (0,0,0,100)), (tr.x+shadow_offset, tr.y+shadow_offset))
    screen.blit(ts, tr)

def draw_progress_bar(x, y, width, height, progress_ratio, bg_color, fill_color):
    scaled_x, scaled_y = get_scaled_pos(x, y)
    scaled_width, scaled_height = get_scaled_size(width), get_scaled_size(height)
    
    # Background
    pygame.draw.rect(screen, bg_color, (scaled_x, scaled_y, scaled_width, scaled_height), border_radius=int(4*scale_factor))
    # Fill
    if progress_ratio > 0:
        fill_width = int(scaled_width * progress_ratio)
        pygame.draw.rect(screen, fill_color, (scaled_x, scaled_y, fill_width, scaled_height), border_radius=int(4*scale_factor))
    # Border
    pygame.draw.rect(screen, (90,90,110), (scaled_x, scaled_y, scaled_width, scaled_height), int(2*scale_factor), border_radius=int(4*scale_factor))

def draw_enhanced_starfield():
    for i, (x, y, size, speed) in enumerate(starfield):
        new_y = (y + speed) % current_height
        starfield[i] = (x, new_y, size, speed)
        
        # Add twinkling effect
        twinkle = 0.7 + 0.3 * math.sin(time.time() * 2 + i * 0.1)
        alpha = int(255 * twinkle)
        color = (alpha, alpha, alpha)
        
        scaled_size = max(1, int(size * scale_factor))
        pygame.draw.circle(screen, color, (int(x * scale_factor), int(new_y)), scaled_size)

def draw_main_menu():
    draw_enhanced_starfield()
    
    # Title with glow effect
    title_y = get_scaled_size(ORIGINAL_HEIGHT//4)
    for offset in range(5, 0, -1):
        alpha = 50 - offset * 8
        glow_surf = font_title.render("BLASTR!", True, (66, 165, 245, alpha))
        title_rect = glow_surf.get_rect(center=(current_width//2, title_y))
        screen.blit(glow_surf, (title_rect.x + offset, title_rect.y + offset))
    
    draw_text("BLASTR!", font_title, (255,255,255), (current_width//2, title_y), ce=True, scale=False)
    draw_text("An Addictive Arena Shooter", font_small, (200,200,220), (current_width//2, title_y + get_scaled_size(80)), ce=True, scale=False)
    
    # Player info
    level_text = f"Level {progress.level} {progress.current_title}"
    draw_text(level_text, font_medium, (255, 238, 88), (current_width//2, title_y + get_scaled_size(120)), ce=True, scale=False)
    
    # XP Bar
    # xp_bar_y = title_y + get_scaled_size(150)
    # draw_progress_bar(current_width//2 - 150, xp_bar_y, 300, 20, progress.xp / progress.xp_to_next, (40,40,60), (66, 165, 245))
    # draw_text(f"XP: {progress.xp}/{progress.xp_to_next}", font_ui, (255,255,255), (current_width//2, xp_bar_y + get_scaled_size(10)), ce=True, scale=False)
    
    # Input box
    scaled_input_box = pygame.Rect(
        get_scaled_pos(input_box.x, input_box.y)[0],
        get_scaled_pos(input_box.x, input_box.y)[1],
        get_scaled_size(input_box.width),
        get_scaled_size(input_box.height)
    )
    pygame.draw.rect(screen, (20,20,35), scaled_input_box, border_radius=int(8*scale_factor))
    pygame.draw.rect(screen, (66,165,245) if input_active else (90,90,110), scaled_input_box, int(2*scale_factor), border_radius=int(8*scale_factor))
    
    name_surface = font_medium.render(player_name, 1, (255,255,255))
    screen.blit(name_surface, (scaled_input_box.x + get_scaled_size(15), scaled_input_box.y + get_scaled_size(8)))
    
    # Stats
    stats_y = current_height - get_scaled_size(120)
    draw_text(f"Games: {progress.games_played} | K/D: {progress.total_kills}/{progress.total_deaths}", font_small, (150,150,170), (current_width//2, stats_y), ce=True, scale=False)
    draw_text(f"Best Streak: {progress.best_killstreak} | Playtime: {int(progress.playtime//3600)}h {int((progress.playtime%3600)//60)}m", font_small, (150,150,170), (current_width//2, stats_y + get_scaled_size(25)), ce=True, scale=False)
    
    if connection_lost:
        draw_text("Failed to connect.", font_small, (239,83,80), (current_width//2, current_height - get_scaled_size(50)), ce=True, scale=False)

def draw_info_screen(is_loading):
    overlay = pygame.Surface((current_width, current_height), pygame.SRCALPHA)
    overlay.fill((19, 21, 40, 235 if is_loading else 220))
    screen.blit(overlay, (0,0))
    
    draw_text("HOW TO PLAY", font_main, (255,255,255), (current_width//2, get_scaled_size(80)), ce=True, scale=False)
    
    box_width, box_height = get_scaled_size(280), get_scaled_size(400)
    start_x = (current_width - (box_width * 3 + get_scaled_size(40) * 2)) // 2
    
    info_sections = {
        "POWER-UPS": [
            ((102, 187, 106), "HEALTH", "Restores 30 health."),
            ((66, 165, 245), "SPEED", "Short movement speed boost."),
            ((239, 83, 80), "DAMAGE", "Short bullet damage boost.")
        ],
        "HAZARDS": [
            ((255, 0, 100), "LASER WALL", "Instantly lethal. Dodge it at all costs!")
        ],
        "SUPERPOWER": [
            ((255, 238, 88), "COMEBACK", "When you're far behind, press [F] to unleash a bullet storm!")
        ]
    }
    
    for i, (title, items) in enumerate(info_sections.items()):
        box_x = start_x + i * (box_width + get_scaled_size(40))
        box_rect = pygame.Rect(box_x, get_scaled_size(150), box_width, box_height)
        
        pygame.draw.rect(overlay, (25, 30, 50, 200), box_rect, border_radius=int(15*scale_factor))
        pygame.draw.rect(overlay, (100, 110, 140, 200), box_rect, int(2*scale_factor), border_radius=int(15*scale_factor))
        
        draw_text(title, font_medium, (255, 238, 88), (box_rect.centerx, get_scaled_size(185)), ce=True, scale=False)
        
        y_offset = get_scaled_size(240)
        for color, item_title, desc in items:
            if item_title == "LASER WALL":
                icon_rect = pygame.Rect(box_x + get_scaled_size(30), y_offset + get_scaled_size(15), get_scaled_size(40), get_scaled_size(10))
                pygame.draw.rect(screen, color, icon_rect, border_radius=int(3*scale_factor))
            elif item_title == "COMEBACK":
                center_x, center_y = box_x + get_scaled_size(50), y_offset + get_scaled_size(20)
                for size in [get_scaled_size(25), get_scaled_size(20), get_scaled_size(15)]:
                    alpha = 50 + size * 2
                    glow_surf = pygame.Surface((size*2, size*2), pygame.SRCALPHA)
                    pygame.draw.circle(glow_surf, (*color, alpha), (size, size), size)
                    screen.blit(glow_surf, (center_x - size, center_y - size))
                pygame.draw.circle(screen, color, (center_x, center_y), get_scaled_size(15))
                pygame.draw.circle(screen, (255, 255, 255), (center_x - get_scaled_size(3), center_y - get_scaled_size(3)), get_scaled_size(8))
            else:
                icon_rect = pygame.Rect(box_x + get_scaled_size(30), y_offset, get_scaled_size(40), get_scaled_size(40))
                pygame.draw.rect(screen, color, icon_rect, border_radius=int(8*scale_factor))
                pygame.draw.rect(screen, (255, 255, 255, 100), icon_rect, int(2*scale_factor), border_radius=int(8*scale_factor))

            text_y = y_offset + get_scaled_size(8) if item_title != "COMEBACK" else y_offset + get_scaled_size(8)
            draw_text(item_title, font_small, (255, 255, 255), (box_x + get_scaled_size(85), text_y), l=True, scale=False)
            
            # Text wrapping
            words = desc.split(' ')
            line = ""
            line_y = text_y + get_scaled_size(25)
            for word in words:
                test_line = line + word + " "
                if font_ui.size(test_line)[0] > box_width - get_scaled_size(100):
                    draw_text(line, font_ui, (200, 200, 220), (box_x + get_scaled_size(85), line_y), l=True, scale=False)
                    line = word + " "
                    line_y += get_scaled_size(20)
                else:
                    line = test_line
            draw_text(line, font_ui, (200, 200, 220), (box_x + get_scaled_size(85), line_y), l=True, scale=False)
            
            y_offset += get_scaled_size(100)

def draw_progress_screen():
    overlay = pygame.Surface((current_width, current_height), pygame.SRCALPHA)
    overlay.fill((19, 21, 40, 220))
    screen.blit(overlay, (0,0))
    
    draw_text("PLAYER PROGRESS", font_main, (255,255,255), (current_width//2, get_scaled_size(80)), ce=True, scale=False)
    
    # Level and XP
    level_y = get_scaled_size(150)
    draw_text(f"Level {progress.level} {progress.current_title}", font_medium, (255, 238, 88), (current_width//2, level_y), ce=True, scale=False)
    draw_progress_bar(current_width//2 - get_scaled_size(200), level_y + get_scaled_size(40), 400, 25, progress.xp / progress.xp_to_next, (40,40,60), (66, 165, 245))
    draw_text(f"XP: {progress.xp}/{progress.xp_to_next}", font_ui, (255,255,255), (current_width//2, level_y + get_scaled_size(52)), ce=True, scale=False)
    
    # Statistics
    stats_y = get_scaled_size(250)
    stats = [
        ("Total Kills", progress.total_kills, (102, 187, 106)),
        ("Total Deaths", progress.total_deaths, (239, 83, 80)),
        ("K/D Ratio", f"{progress.total_kills/max(1,progress.total_deaths):.2f}", (255, 238, 88)),
        ("Best Killstreak", progress.best_killstreak, (66, 165, 245)),
        ("Games Played", progress.games_played, (200, 200, 220)),
        ("Power-ups Collected", progress.total_powerups, (255, 165, 0))
    ]
    
    for i, (label, value, color) in enumerate(stats):
        x = current_width//4 + (i % 2) * current_width//2
        y = stats_y + (i // 2) * get_scaled_size(60)
        draw_text(label, font_small, (200, 200, 220), (x, y), ce=True, scale=False)
        draw_text(str(value), font_medium, color, (x, y + get_scaled_size(25)), ce=True, scale=False)
    
    # Available Titles
    titles_y = get_scaled_size(450)
    draw_text("UNLOCKED TITLES", font_small, (255, 238, 88), (current_width//2, titles_y), ce=True, scale=False)
    
    title_list = list(progress.unlocked_titles)
    for i, title in enumerate(title_list):
        color = (255, 238, 88) if title == progress.current_title else (200, 200, 220)
        x = current_width//2 - len(title_list) * get_scaled_size(80) + i * get_scaled_size(160)
        draw_text(title, font_ui, color, (x, titles_y + get_scaled_size(30)), ce=True, scale=False)

def draw_achievements_screen():
    overlay = pygame.Surface((current_width, current_height), pygame.SRCALPHA)
    overlay.fill((19, 21, 40, 220))
    screen.blit(overlay, (0,0))
    
    draw_text("ACHIEVEMENTS", font_main, (255,255,255), (current_width//2, get_scaled_size(80)), ce=True, scale=False)
    
    achievement_list = [
        ("First Blood", "Get your first kill", "First Blood" in progress.achievements),
        ("Centurion", "Reach 100 total kills", "Centurion" in progress.achievements),
        ("Executioner", "Reach 500 total kills", "Executioner" in progress.achievements),
        ("Rampage", "Get a 5 kill streak", "Rampage" in progress.achievements),
        ("Unstoppable", "Get a 10 kill streak", "Unstoppable" in progress.achievements),
        ("Survivor", "Survive for 5 minutes in one game", "Survivor" in progress.achievements),
        ("Veteran", "Reach level 10", "Veteran" in progress.achievements),
    ]
    
    start_y = get_scaled_size(150)
    for i, (name, desc, unlocked) in enumerate(achievement_list):
        y = start_y + i * get_scaled_size(70)
        color = (255, 238, 88) if unlocked else (100, 100, 120)
        
        # Achievement icon
        icon_rect = pygame.Rect(current_width//2 - get_scaled_size(300), y, get_scaled_size(50), get_scaled_size(50))
        if unlocked:
            pygame.draw.rect(screen, (255, 238, 88), icon_rect, border_radius=int(8*scale_factor))
            pygame.draw.rect(screen, (255, 255, 255), icon_rect, int(2*scale_factor), border_radius=int(8*scale_factor))
            draw_text("★", font_medium, (19, 21, 40), (icon_rect.centerx, icon_rect.centery), ce=True, scale=False)
        else:
            pygame.draw.rect(screen, (50, 50, 70), icon_rect, border_radius=int(8*scale_factor))
            pygame.draw.rect(screen, (100, 100, 120), icon_rect, int(2*scale_factor), border_radius=int(8*scale_factor))
            draw_text("?", font_medium, (100, 100, 120), (icon_rect.centerx, icon_rect.centery), ce=True, scale=False)
        
        # Achievement text
        draw_text(name, font_small, color, (current_width//2 - get_scaled_size(230), y + get_scaled_size(5)), l=True, scale=False)
        draw_text(desc, font_ui, (150, 150, 170), (current_width//2 - get_scaled_size(230), y + get_scaled_size(30)), l=True, scale=False)

def draw_playing_ui(health, max_health):
    # Health bar
    hr = health/max_health
    bar_rect = (get_scaled_size(20), current_height - get_scaled_size(50))
    bar_size = (get_scaled_size(250), get_scaled_size(25))
    
    pygame.draw.rect(screen, (20,20,35), (*bar_rect, *bar_size), border_radius=int(8*scale_factor))
    hc = (102,187,106) if hr > 0.6 else (255,238,88) if hr > 0.3 else (239,83,80)
    
    if hr > 0:
        pygame.draw.rect(screen, hc, (bar_rect[0], bar_rect[1], int(bar_size[0]*hr), bar_size[1]), border_radius=int(8*scale_factor))
    
    pygame.draw.rect(screen, (90,90,110), (*bar_rect, *bar_size), int(2*scale_factor), border_radius=int(8*scale_factor))
    
    health_text_pos = (bar_rect[0] + bar_size[0]//2, bar_rect[1] + bar_size[1]//2)
    draw_text(f"{int(health)}/{max_health}", font_ui, (255,255,255), health_text_pos, ce=True, scale=False)
    
    # Level and XP in top right
    level_text = f"Lv.{progress.level} ({progress.xp}/{progress.xp_to_next})"
    draw_text(level_text, font_ui, (255, 238, 88), (current_width - get_scaled_size(10), get_scaled_size(15)), l=False, ce=False, scale=False)
    
    # XP bar in top right
    xp_bar_rect = (current_width - get_scaled_size(220), get_scaled_size(35))
    xp_bar_size = (get_scaled_size(200), get_scaled_size(8))
    draw_progress_bar(xp_bar_rect[0], xp_bar_rect[1], xp_bar_size[0], xp_bar_size[1], progress.xp / progress.xp_to_next, (40,40,60), (66, 165, 245))
    
    # FPS and controls
    draw_text(f"FPS: {clock.get_fps():.0f}", font_ui, (200,200,220), (current_width - get_scaled_size(50), current_height - get_scaled_size(40)), ce=True, scale=False)
    
    control_text = "TAB-Scores | P-Progress | A-Achievements | I-Info"
    draw_text(control_text, font_tiny, (255,255,255,150), (get_scaled_size(20), get_scaled_size(20)), sh=False, scale=False)
    draw_text("ESC-Exit | F11-Fullscreen", font_tiny, (255,255,255,150), (get_scaled_size(20), get_scaled_size(40)), sh=False, scale=False)
    
    # Current killstreak
    if current_killstreak > 1:
        streak_text = f"KILLSTREAK: {current_killstreak}"
        streak_color = (255, 238, 88) if current_killstreak < 5 else (255, 100, 100)
        draw_text(streak_text, font_medium, streak_color, (current_width//2, get_scaled_size(100)), ce=True, scale=False)
    
    # Survival time
    # if game_start_time:
    #     survival_time = time.time() - game_start_time
    #     minutes = int(survival_time // 60)
    #     seconds = int(survival_time % 60)
    #     time_text = f"TIME: {minutes:02d}:{seconds:02d}"
    #     draw_text(time_text, font_ui, (200, 200, 220), (current_width//2, get_scaled_size(70)), ce=True, scale=False)
    
    # Superpower indicator
    if superpower_available:
        alpha = 128 + 127*math.sin(time.time()*5)
        glow_text = font_super.render("PRESS [F] - COMEBACK READY!", 1, (255,238,88))
        glow_text.set_alpha(alpha)
        text_rect = glow_text.get_rect(center=(current_width//2, current_height - get_scaled_size(60)))
        screen.blit(glow_text, text_rect)

def draw_player(pos, color, name, is_local):
    scaled_size = get_scaled_size(PLAYER_SIZE)
    x, y = int(pos['x'] * scale_factor), int(pos['y'] * scale_factor)
    
    pygame.draw.circle(screen, color, (x, y), scaled_size//2)
    pygame.draw.circle(screen, tuple(min(255, c+50) for c in color), (x-int(3*scale_factor), y-int(3*scale_factor)), (scaled_size//2)-int(8*scale_factor))
    
    name_color = (200, 220, 255) if is_local else (255, 255, 255)
    draw_text(name, font_ui, name_color, (x, y - get_scaled_size(25)), ce=True, scale=False)

def draw_scoreboard():
    if not server_snapshots: return
    pd = server_snapshots[-1].get('players', {})
    sp = sorted(scoreboard_data.items(), key=lambda i: i[1], reverse=True)
    
    overlay = pygame.Surface((current_width, current_height), pygame.SRCALPHA)
    overlay.fill((19, 21, 40, 220))
    screen.blit(overlay, (0, 0))
    
    draw_text("LEADERBOARD", font_main, (255,255,255), (current_width//2, get_scaled_size(100)), ce=True, scale=False)
    
    for i, (pid, kills) in enumerate(sp[:10]):
        name = pd.get(pid, {}).get('name', '?')
        row_color = (255, 238, 88) if pid == player_id else (220, 220, 220)
        
        y_pos = get_scaled_size(180) + i * get_scaled_size(40)
        draw_text(f"#{i+1}", font_medium, row_color, (current_width//2 - get_scaled_size(250), y_pos), l=True, scale=False)
        draw_text(name, font_medium, row_color, (current_width//2 - get_scaled_size(150), y_pos), l=True, scale=False)
        draw_text(str(kills), font_medium, row_color, (current_width//2 + get_scaled_size(250), y_pos), ce=True, scale=False)

# Create scaled buttons
def create_buttons():
    button_width, button_height = 250, 60
    button_spacing = 80
    center_x, center_y = ORIGINAL_WIDTH//2, ORIGINAL_HEIGHT//2
    
    play_btn = Button((center_x - button_width//2, center_y, button_width, button_height), "PLAY", (38,166,154), (46,204,113), (26,110,100), font_medium)
    quit_btn = Button((center_x - button_width//2, center_y + button_spacing, button_width, button_height), "QUIT", (239,83,80), (241,108,105), (150,40,40), font_medium)
    start_game_btn = Button((center_x - button_width//2, ORIGINAL_HEIGHT - 120, button_width, button_height), "START GAME", (38,166,154), (46,204,113), (26,110,100), font_medium)
    
    return play_btn, quit_btn, start_game_btn

def handle_game_events(events):
    global current_killstreak, progress, level_up_announcements, particles
    
    for ev in events:
        if ev['type'] == 'hit':
            # Enhanced hit particles
            for _ in range(8):
                particles.append(EnhancedParticle(ev['pos'][0], ev['pos'][1], ev['color'], 20, random.randint(3,6), particle_type='glow'))
            if ev['target_id'] == player_id:
                global screen_shake
                screen_shake = 15
        
        elif ev['type'] == 'kill':
            if ev['killer_id'] == player_id:
                current_killstreak += 1
                progress.total_kills += 1
                xp_gained = 10 + (current_killstreak - 1) * 5
                
                if progress.add_xp(xp_gained):
                    level_up_announcements.append(Announcement(f"LEVEL UP! Now Level {progress.level}", (255, 238, 88), 3.0, 'large'))
                
                # Check achievements
                new_achievements = progress.check_achievements('kill')
                new_achievements.extend(progress.check_achievements('killstreak', current_killstreak))
                
                for achievement in new_achievements:
                    announcements.append(Announcement(f"ACHIEVEMENT: {achievement}!", (255, 238, 88), 3.0, 'medium'))
                
                if current_killstreak > progress.best_killstreak:
                    progress.best_killstreak = current_killstreak
        
        elif ev['type'] == 'death':
            if ev['player_id'] == player_id:
                current_killstreak = 0
                progress.total_deaths += 1
                # Death particles
                for _ in range(30):
                    particles.append(EnhancedParticle(ev['pos'][0], ev['pos'][1], (239, 83, 80), 40, random.randint(4,10), particle_type='normal'))
        
        elif ev['type'] == 'kill_streak':
            streak_texts = {2:"DOUBLE KILL!", 3:"TRIPLE KILL!", 4:"MEGA KILL!", 5:"ULTRA KILL!"}
            streak_text = streak_texts.get(ev['streak'], "RAMPAGE!")
            announcements.append(Announcement(f"{ev['name']} - {streak_text}", (255, 100, 100), 2.5))
        
        elif ev['type'] == 'powerup_collect':
            progress.total_powerups += 1
            progress.add_xp(5)  # Small XP for collecting power-ups
            # Powerup particles
            for _ in range(15):
                particles.append(EnhancedParticle(ev['pos'][0], ev['pos'][1], ev['color'], 25, random.randint(2,5), particle_type='float'))

def main():
    global game_screen, running, player_name, input_active, last_shot_time, superpower_available
    global screen_shake, particles, announcements, level_up_announcements, show_info_panel
    global show_progress_panel, show_achievements_panel, connection_lost, client, player_id
    global predicted_pos, server_snapshots, player_display_positions, my_player_health
    global my_player_max_health, scoreboard_data, fullscreen, screen, current_killstreak
    global game_start_time, survival_time, progress
    
    play_btn, quit_btn, start_game_btn = create_buttons()
    
    while running:
        dt = clock.tick(FPS) / 1000.0
        m_pos = pygame.mouse.get_pos()
        
        # Handle events
        for e in pygame.event.get():
            if e.type == QUIT or (e.type == KEYDOWN and e.key == K_ESCAPE):
                running = False
            
            if e.type == KEYDOWN:
                if e.key == K_F11:
                    toggle_fullscreen()
            
            # Menu handling
            if game_screen == 'main_menu':
                play_btn.check_hover(m_pos)
                quit_btn.check_hover(m_pos)
                
                if play_btn.is_clicked(e):
                    game_screen = 'loading'
                if quit_btn.is_clicked(e):
                    running = False
                
                # Name input
                scaled_input_box = pygame.Rect(
                    get_scaled_pos(input_box.x, input_box.y)[0],
                    get_scaled_pos(input_box.x, input_box.y)[1],
                    get_scaled_size(input_box.width),
                    get_scaled_size(input_box.height)
                )
                
                if e.type == MOUSEBUTTONDOWN:
                    input_active = scaled_input_box.collidepoint(e.pos)
                
                if e.type == KEYDOWN and input_active:
                    if e.key == K_BACKSPACE:
                        player_name = player_name[:-1]
                    elif len(player_name) < 15 and e.unicode.isprintable():
                        player_name += e.unicode
            
            elif game_screen == 'loading':
                start_game_btn.check_hover(m_pos)
                if start_game_btn.is_clicked(e):
                    game_screen = 'connecting'
            
            elif game_screen in ['playing', 'dead']:
                if e.type == KEYDOWN:
                    if e.key == K_i:
                        show_info_panel = not show_info_panel
                        show_progress_panel = False
                        show_achievements_panel = False
                    elif e.key == K_p:
                        show_progress_panel = not show_progress_panel
                        show_info_panel = False
                        show_achievements_panel = False
                    elif e.key == K_a:
                        show_achievements_panel = not show_achievements_panel
                        show_info_panel = False
                        show_progress_panel = False
        
        # Clear screen
        screen.fill((19, 21, 40))
        
        # Game state rendering
        if game_screen == 'loading':
            draw_info_screen(is_loading=True)
            start_game_btn.draw(screen)
        
        elif game_screen == 'connecting':
            draw_text("Connecting...", font_main, (255,255,255), (current_width//2, current_height//2), ce=True, scale=False)
            pygame.display.flip()
            connect_to_server()
        
        elif game_screen == 'main_menu':
            draw_main_menu()
            play_btn.draw(screen)
            quit_btn.draw(screen)
        
        elif game_screen in ['playing', 'dead']:
            if connection_lost:
                progress.save_progress()
                game_screen = 'main_menu'
                continue
            
            # Receive server data
            while True:
                gd = receive_data(client)
                if gd is None:
                    break
                
                if 'players' in gd:
                    gd['timestamp'] = time.time()
                    server_snapshots.append(gd)
                    scoreboard_data = gd.get('stats', {})
                    
                    # Handle events
                    if 'events' in gd:
                        handle_game_events(gd['events'])
            
            # Player interpolation
            if len(server_snapshots) >= 2:
                s_a, s_b = server_snapshots[-1], server_snapshots[-2]
                if (td := s_a['timestamp'] - s_b['timestamp']) > 0:
                    t = max(0.0, min(1.0, (time.time() - INTERPOLATION_DELAY - s_b['timestamp']) / td))
                    for pid in s_a['players']:
                        if pid != player_id and pid in s_b['players']:
                            b, a = s_b['players'][pid], s_a['players'][pid]
                            player_display_positions[pid] = {
                                'x': b['x'] + (a['x'] - b['x']) * t,
                                'y': b['y'] + (a['y'] - b['y']) * t
                            }
            
            # Update player state
            death_time = None
            if server_snapshots and player_id in (latest := server_snapshots[-1])['players']:
                my_player_data = latest['players'][player_id]
                my_player_health = my_player_data['health']
                superpower_available = my_player_data.get('superpower_ready', False)
                death_time = my_player_data.get('death_time')
                
                new_screen = 'dead' if my_player_health <= 0 and game_screen == 'playing' else 'playing' if my_player_health > 0 and game_screen == 'dead' else game_screen
                game_screen = new_screen
            
            # Input handling
            keys = pygame.key.get_pressed()
            if game_screen == 'playing':
                # Shooting
                if (pygame.mouse.get_pressed()[0] or keys[K_SPACE]) and time.time() - last_shot_time > SHOOT_COOLDOWN:
                    last_shot_time = time.time()
                    angle = math.atan2(m_pos[1] - predicted_pos['y'] * scale_factor, m_pos[0] - predicted_pos['x'] * scale_factor)
                    send_data(client, {'id': player_id, 'action': 'shoot', 'angle': angle})
                
                # Superpower
                if keys[K_f] and superpower_available:
                    send_data(client, {'id': player_id, 'action': 'activate_superpower'})
                    superpower_available = False
                
                # Movement prediction
                target_x = m_pos[0] / scale_factor
                target_y = m_pos[1] / scale_factor
                predicted_pos['x'] += (target_x - predicted_pos['x']) * 0.2
                predicted_pos['y'] += (target_y - predicted_pos['y']) * 0.2
                predicted_pos['x'] = max(SCREEN_PADDING, min(ORIGINAL_WIDTH - SCREEN_PADDING, predicted_pos['x']))
                predicted_pos['y'] = max(SCREEN_PADDING, min(ORIGINAL_HEIGHT - SCREEN_PADDING, predicted_pos['y']))
                
                send_data(client, {'id': player_id, 'action': 'move', 'pos': (predicted_pos['x'], predicted_pos['y'])})
            
            # Screen shake
            screen_offset = (0, 0)
            if screen_shake > 0:
                screen_offset = (
                    random.randint(-screen_shake, screen_shake),
                    random.randint(-screen_shake, screen_shake)
                )
                screen_shake -= 1
            
            # Draw game world
            draw_enhanced_starfield()
            
            # Update and draw particles
            for p in particles[:]:
                p.update()
                p.draw(screen)
                if p.life <= 0:
                    particles.remove(p)
            
            # Draw game objects
            if server_snapshots:
                latest = server_snapshots[-1]
                
                # Draw players
                for pid, p_data in latest['players'].items():
                    if p_data['health'] > 0:
                        pos = predicted_pos if pid == player_id else player_display_positions.get(pid, p_data)
                        adjusted_pos = {'x': pos['x'] + screen_offset[0]/scale_factor, 'y': pos['y'] + screen_offset[1]/scale_factor}
                        draw_player(adjusted_pos, p_data['color'], p_data['name'], pid == player_id)
                
                # Draw bullets
                for b in latest['bullets']:
                    color = b.get('color', (255, 238, 88))
                    x = int((b['x'] + screen_offset[0]/scale_factor) * scale_factor)
                    y = int((b['y'] + screen_offset[1]/scale_factor) * scale_factor)
                    pygame.draw.circle(screen, color, (x, y), get_scaled_size(5))
                
                # Draw power-ups
                for p in latest.get('powerups', []):
                    color = p.get('color', (255, 255, 255))
                    x = int((p['x'] - 10 + screen_offset[0]/scale_factor) * scale_factor)
                    y = int((p['y'] - 10 + screen_offset[1]/scale_factor) * scale_factor)
                    size = get_scaled_size(20)
                    pygame.draw.rect(screen, color, (x, y, size, size), border_radius=int(4*scale_factor))
                
                # Draw walls/hazards
                for w in latest.get('walls', []):
                    x = int((w['x'] + screen_offset[0]/scale_factor) * scale_factor)
                    y = int((w['y'] + screen_offset[1]/scale_factor) * scale_factor)
                    width = int(w['width'] * scale_factor)
                    height = int(w['height'] * scale_factor)
                    pygame.draw.rect(screen, w['color'], (x, y, width, height))
            
            # Check survival time for achievements
            if game_start_time:
                survival_time = time.time() - game_start_time
                new_achievements = progress.check_achievements('survival', survival_time)
                for achievement in new_achievements:
                    announcements.append(Announcement(f"ACHIEVEMENT: {achievement}!", (255, 238, 88), 3.0, 'medium'))
            
            # Draw UI
            draw_playing_ui(my_player_health, my_player_max_health)
            
            # Draw announcements
            for i, announcement in enumerate(level_up_announcements + announcements):
                announcement.draw(screen, i)
            
            # Clean up old announcements
            level_up_announcements = [a for a in level_up_announcements if time.time() - a.start_time < a.duration]
            announcements = [a for a in announcements if time.time() - a.start_time < a.duration]
            
            # Draw overlays
            if keys[K_TAB]:
                draw_scoreboard()
            
            if show_info_panel:
                draw_info_screen(is_loading=False)
            
            if show_progress_panel:
                draw_progress_screen()
            
            if show_achievements_panel:
                draw_achievements_screen()
            
            # Death screen
            if game_screen == 'dead':
                overlay = pygame.Surface((current_width, current_height), pygame.SRCALPHA)
                overlay.fill((20, 20, 35, 200))
                screen.blit(overlay, (0, 0))
                
                draw_text("YOU WERE BLASTED!", font_main, (239, 83, 80), (current_width//2, current_height//2 - get_scaled_size(80)), ce=True, scale=False)
                
                if death_time:
                    time_left = RESPAWN_TIME - (time.time() - death_time)
                    if time_left > 0:
                        draw_text(f"RESPAWNING IN {math.ceil(time_left)}", font_main, (255, 255, 255), (current_width//2, current_height//2), ce=True, scale=False)
        
        pygame.display.flip()
    
    # Save progress before quitting
    progress.save_progress()
    if client:
        client.close()
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()