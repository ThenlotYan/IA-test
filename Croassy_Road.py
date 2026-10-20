#!/usr/bin/env python3
"""
FROGGY ROAD - jeu "traverse la route sans te faire écraser" en pygame.
Rendu isométrique en voxels (cubes à 3 faces), caméra qui suit le joueur.

Mécaniques : sauts case par case, routes (voitures/camions), rivières (troncs,
nénuphars), voies ferrées (train annoncé par des feux), arbres, pièces,
caméra qui avance toute seule (l'aigle t'attrape si tu traînes), score sauvegardé.

Contrôles :  flèches / ZQSD / WASD  (ESPACE = avancer)
             P = pause, R = rejouer, ECHAP = quitter
             C = changer de personnage (écran titre, déblocage avec les pièces)

Installation :  sudo apt install python3-pygame     (ou)   pip install pygame-ce
Lancement    :  python3 Croassy_Road.py
"""
import json
import math
import random
import sys
from pathlib import Path

import pygame

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------
W, H = 660, 760
S = 44.0                    # taille d'une unité monde (px)
A = S * 0.866               # projection isométrique : décalage horizontal / unité
B = S * 0.5                 # projection isométrique : décalage vertical / unité
LEAD = 2.0                  # le joueur est affiché LEAD rangées devant la caméra
OX = W / 2 - LEAD * A
OY = H * 0.60 + LEAD * B
FPS = 60
HOP_T = 0.13                # durée d'un saut (s)
WRAP = 22.0                 # période des véhicules / troncs (cases)
COL_MAX = 4                 # colonnes jouables : -4 .. 4
Z_BOT = -50                 # bas des dalles de terrain
LOG_H = 9                   # hauteur des troncs au-dessus de l'eau
SAVE_FILE = Path.home() / ".froggy_road.json"

ZT = {"grass": 10, "road": 4, "river": -2, "pads": -2, "rail": 5}
GRASS_C = [(132, 208, 84), (120, 194, 74)]
ROAD_C = [(94, 98, 110), (86, 90, 102)]
WATER_C = [(88, 184, 240), (78, 172, 232)]
RAIL_C = (158, 148, 136)
LOG_C = (146, 100, 60)
PAD_C = (72, 172, 86)
CAR_COLORS = [(228, 70, 70), (70, 130, 230), (244, 204, 64), (84, 194, 114),
              (236, 236, 240), (166, 96, 206), (244, 144, 56)]
TRAILERS = [(232, 232, 238), (96, 156, 226), (240, 184, 64), (124, 204, 144)]
FOLIAGE = [(76, 168, 66), (60, 150, 78), (100, 184, 64)]
WINDOW = (52, 72, 104)
SKINS = [
    dict(name="Grenouille", price=0, body=(242, 138, 50), foot=(212, 104, 30), belly=(255, 228, 164), acc=None),
    dict(name="Lapin", price=25, body=(236, 236, 244), foot=(196, 196, 210), belly=(255, 190, 208), acc="ears"),
    dict(name="Canard", price=50, body=(252, 218, 70), foot=(240, 150, 40), belly=(255, 244, 170), acc="beak"),
    dict(name="Robot", price=80, body=(150, 170, 196), foot=(104, 120, 146), belly=(210, 226, 244), acc="ant"),
]


def shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def pd(a, b):
    """Distance signée sur la boucle de période WRAP."""
    return ((a - b + WRAP / 2) % WRAP) - WRAP / 2


def make_sounds():
    """Petits bruitages générés à la volée (aucun fichier audio nécessaire)."""
    import array
    try:
        pygame.mixer.init(22050, -16, 1)
        n_rate = 22050

        def tone(f0, f1, dur, vol=0.35, noise=0.0):
            n, ph, a = int(n_rate * dur), 0.0, array.array("h")
            for i in range(n):
                k = i / n
                ph += 2 * math.pi * (f0 + (f1 - f0) * k) / n_rate
                v = math.sin(ph) * (1 - noise) + random.uniform(-1, 1) * noise
                a.append(int(v * (1 - k) ** 1.5 * vol * 32767))
            return pygame.mixer.Sound(buffer=a.tobytes())
        return dict(hop=tone(300, 620, .09), coin=tone(880, 1480, .16, .3),
                    splat=tone(200, 50, .25, .5, .6), splash=tone(600, 120, .35, .4, .8),
                    eagle=tone(900, 300, .4, .3), buy=tone(500, 1000, .25, .3))
    except Exception:
        return {}


DIFF_RANGE = 250.0          # rangées pour atteindre la difficulté maximale
LEVEL_STEP = 25             # une rangée-palier "Niveau N" toutes les 25 rangées


def difficulty(y):
    """Difficulté 0..1 qui croît avec la distance (progression douce)."""
    t = min(1.0, max(0.0, y) / DIFF_RANGE)
    return t * t * (3 - 2 * t) * 0.35 + t * 0.65


def creep_speed(max_y):
    """Vitesse de l'aigle (avancée de la caméra, rangées/s)."""
    return 0.30 + 0.60 * difficulty(max_y)


def ground_z(row):
    if row is None:
        return 0
    if row.kind == "river":
        return ZT["river"] + LOG_H
    if row.kind == "pads":
        return ZT["pads"] + 2
    return ZT[row.kind]


def ground_color(row):
    k = row.kind
    if k == "grass":
        return GRASS_C[row.y % 2]
    if k == "road":
        return ROAD_C[row.y % 2]
    if k == "rail":
        return RAIL_C
    if k == "river":
        return LOG_C
    return PAD_C


# --------------------------------------------------------------------------
# Éléments dessinés en espace écran
# --------------------------------------------------------------------------
def draw_coin(s, cx, cy, t):
    wd = max(3, abs(math.cos(t * 5)) * 14)
    pygame.draw.ellipse(s, (196, 138, 20), (cx - wd / 2 - 2, cy - 12, wd + 4, 24))
    pygame.draw.ellipse(s, (255, 214, 62), (cx - wd / 2, cy - 10, wd, 20))
    if wd > 8:
        pygame.draw.ellipse(s, (255, 240, 150), (cx - wd / 4, cy - 5, wd / 2, 10))


def draw_eagle(s, x, y, t):
    flap = math.sin(t * 20)
    wing = (92, 62, 38)
    pygame.draw.polygon(s, wing, [(x - 8, y), (x - 95, y - 34 + flap * 22), (x - 70, y + 6), (x - 30, y + 16)])
    pygame.draw.polygon(s, wing, [(x + 8, y), (x + 95, y - 34 + flap * 22), (x + 70, y + 6), (x + 30, y + 16)])
    pygame.draw.ellipse(s, (122, 82, 48), (x - 24, y - 12, 48, 58))
    pygame.draw.circle(s, (246, 246, 246), (int(x), int(y - 14)), 15)
    pygame.draw.polygon(s, (250, 190, 40), [(x - 6, y - 10), (x + 6, y - 10), (x, y + 6)])
    pygame.draw.circle(s, (20, 20, 20), (int(x - 6), int(y - 18)), 2)
    pygame.draw.circle(s, (20, 20, 20), (int(x + 6), int(y - 18)), 2)
    pygame.draw.polygon(s, (250, 190, 40), [(x - 10, y + 44), (x - 4, y + 44), (x - 7, y + 56)])
    pygame.draw.polygon(s, (250, 190, 40), [(x + 4, y + 44), (x + 10, y + 44), (x + 7, y + 56)])


# --------------------------------------------------------------------------
# Monde
# --------------------------------------------------------------------------
class Row:
    def __init__(self, y, kind, seed, direction):
        self.y = y
        self.kind = kind
        self.seed = seed
        self.dir = direction
        self.speed = 0.0
        self.shift = 0.0
        self.trees = {}
        self.coins = set()
        self.pads = set()
        self.items = []     # véhicules
        self.logs = []      # (centre, longueur)
        self.state = "idle"
        self.timer = 0.0
        self.front = 0.0
        self.idle = (2.0, 5.0)     # pause entre deux trains (s)
        self.warn = 1.4            # durée de l'avertissement (s)

    def train_extent(self):
        a = self.front
        b = self.front - self.dir * 16
        return min(a, b), max(a, b)

    def update(self, dt, rng):
        if self.kind in ("road", "river"):
            self.shift += self.dir * self.speed * dt
        elif self.kind == "rail":
            self.timer -= dt
            if self.state == "idle" and self.timer <= 0:
                self.state, self.timer = "warn", self.warn
            elif self.state == "warn" and self.timer <= 0:
                self.state = "pass"
                self.front = -34.0 if self.dir > 0 else 34.0
            elif self.state == "pass":
                self.front += self.dir * 30 * dt
                if (self.dir > 0 and self.front > 42) or (self.dir < 0 and self.front < -42):
                    self.state, self.timer = "idle", rng.uniform(*self.idle)


class World:
    EASY = {"grass": 3.0, "road": 4.0, "river": 2.2, "rail": 1.0, "pads": 1.0}
    HARD = {"grass": 1.1, "road": 4.6, "river": 3.4, "rail": 1.9, "pads": 1.4}
    LIMITS = {"grass": 2, "road": 4, "river": 3, "rail": 1, "pads": 3}

    def __init__(self):
        self.rng = random.Random()
        self.rows = {}
        self.last, self.run = "grass", 0
        for y in range(-16, 2):
            self.rows[y] = self.make(y, "grass", start=True)
        self.top = 2

    def pick(self):
        r = self.rng
        d = difficulty(self.top)
        kinds = list(self.EASY)
        weights = [self.EASY[k] + (self.HARD[k] - self.EASY[k]) * d for k in kinds]
        while True:
            k = r.choices(kinds, weights)[0]
            if k == self.last and self.run >= self.LIMITS[k]:
                continue
            return k

    def make(self, y, kind, start=False):
        r = self.rng
        row = Row(y, kind, r.randint(0, 999), r.choice((-1, 1)))
        d = difficulty(y)
        m = 1 + 0.9 * d                      # multiplicateur de vitesse
        if kind == "grass":
            for c in range(-COL_MAX, COL_MAX + 1):
                if c == 0 and y <= 1:
                    continue
                p = (0.1 if y < -1 else 0.0) if start else 0.2 + 0.12 * d
                if r.random() < p:
                    row.trees[c] = (r.randint(1, 3), r.randint(0, 2))
            if not start and r.random() < 0.12 - 0.06 * d:
                free = [c for c in range(-COL_MAX, COL_MAX + 1) if c not in row.trees]
                if free:
                    row.coins.add(r.choice(free))
        elif kind == "road":
            row.speed = r.uniform(1.6, 3.8) * m
            n = min(5, 2 + int(round(2 * d)) + r.choice((0, 1)))     # 2-3 au début, 4-5 plus loin
            jit = 1.2 - 0.5 * d
            sp, o = WRAP / n, r.uniform(0, WRAP)
            for i in range(n):
                truck = r.random() < min(0.15 + 0.30 * d, 0.45 if n < 5 else 0.3)
                row.items.append(dict(off=(o + i * sp + r.uniform(-jit, jit)) % WRAP,
                                      len=3.2 if truck else 1.5, truck=truck,
                                      color=r.choice(CAR_COLORS), color2=r.choice(TRAILERS)))
        elif kind == "river":
            row.speed = r.uniform(0.7, 1.6) * m
            pos, centers = r.uniform(0, 2), []
            while pos < WRAP - 3:
                ln = r.choice((2, 2, 3, 3, 4) if r.random() > d else (2, 2, 2, 3))
                centers.append([pos + ln / 2, ln])
                pos += ln + r.uniform(1.0 + 0.7 * d, 2.2 + 0.9 * d)
            scale = WRAP / pos
            row.logs = [(c * scale, ln) for c, ln in centers]
        elif kind == "pads":
            prev = self.rows.get(y - 1)
            if prev is not None and prev.kind == "pads":
                cols = set(prev.pads)
                for c in range(-COL_MAX, COL_MAX + 1):
                    if r.random() < 0.25:
                        cols.add(c)
            else:
                cols = {c for c in range(-COL_MAX, COL_MAX + 1) if r.random() < 0.55}
                while len(cols) < 3:
                    cols.add(r.randint(-COL_MAX, COL_MAX))
            row.pads = cols
        elif kind == "rail":
            row.timer = r.uniform(0.5, 3.5)
            row.idle = (max(0.6, 2.0 - 1.4 * d), max(1.6, 5.0 - 3.0 * d))
            row.warn = max(0.9, 1.4 - 0.5 * d)
        return row

    def generate(self, y_max):
        while self.top <= y_max:
            k = self.pick()
            self.run = self.run + 1 if k == self.last else 1
            self.last = k
            self.rows[self.top] = self.make(self.top, k)
            self.top += 1

    def prune(self, y_min):
        for y in [y for y in self.rows if y < y_min]:
            del self.rows[y]


# --------------------------------------------------------------------------
# Jeu
# --------------------------------------------------------------------------
class Player:
    def __init__(self):
        self.x = 0.0
        self.y = 0
        self.max_y = 0
        self.lift = 0.0
        self.hop = None
        self.queue = None
        self.face = (0, 1)


class Game:
    def __init__(self, screen):
        self.screen = screen
        self.f_big = pygame.font.Font(None, 96)
        self.f_mid = pygame.font.Font(None, 52)
        self.f_small = pygame.font.Font(None, 30)
        self.best, self.coins = 0, 0
        self.owned, self.skin_i = {SKINS[0]["name"]}, 0
        self.snd = make_sounds()
        self.load()
        self.t = 0.0
        self.paused = False
        self.reset("title")

    # ---- sauvegarde ----
    def load(self):
        try:
            d = json.loads(SAVE_FILE.read_text())
            self.best, self.coins = int(d.get("best", 0)), int(d.get("coins", 0))
            self.owned |= set(d.get("owned", []))
            self.skin_i = int(d.get("skin", 0)) % len(SKINS)
        except Exception:
            pass

    def save(self):
        try:
            SAVE_FILE.write_text(json.dumps({"best": self.best, "coins": self.coins,
                                              "owned": sorted(self.owned), "skin": self.skin_i}))
        except Exception:
            pass

    def shutdown(self):
        self.save()

    # ---- état ----
    def reset(self, state="play"):
        self.world = World()
        self.p = Player()
        if state == "title":
            self.p.face = (0, -1)
        self.parts, self.land_t = [], -9.0
        self.level, self.lvl_t = 1, -9.0
        self.cam_x = 0.0
        self.cam_y = -LEAD
        self.started = False
        self.state = state
        self.dead = None
        self.dead_t = 0.0
        self.dead_gz = 0.0
        self.run_coins = 0
        self.world.generate(30)

    # ---- effets ----
    def creep(self):
        return creep_speed(self.p.max_y)

    def play(self, name):
        snd = self.snd.get(name)
        if snd:
            snd.play()

    def skin_now(self):
        sk = SKINS[self.skin_i]
        return sk if (self.state == "title" or sk["name"] in self.owned) else SKINS[0]

    def next_skin(self):
        self.skin_i = (self.skin_i + 1) % len(SKINS)
        sk = SKINS[self.skin_i]
        if sk["name"] not in self.owned and self.coins >= sk["price"]:
            self.coins -= sk["price"]
            self.owned.add(sk["name"])
            self.play("buy")
        self.save()

    def burst(self, x, y, z, col, n, spd=2.0, up=90, life=0.6):
        for _ in range(n):
            a, v = random.uniform(0, 6.283), random.uniform(.3, 1) * spd
            self.parts.append([x, y, z, math.cos(a) * v, math.sin(a) * v,
                               random.uniform(.4, 1) * up, 0.0, life * random.uniform(.6, 1), col])

    def hop_squash(self):
        p = self.p
        if p.hop:
            sn = math.sin(math.pi * min(1.0, p.hop[4]))
            return 1 + 0.28 * sn, 1 - 0.14 * sn
        k = max(0.0, 1 - (self.t - self.land_t) / 0.14)
        return 1 - 0.22 * k + 0.02 * math.sin(self.t * 3), 1 + 0.12 * k

    def die(self, kind):
        if self.state == "dead":
            return
        self.dead_gz = self.player_z()
        self.state, self.dead, self.dead_t = "dead", kind, 0.0
        p, bc = self.p, self.skin_now()["body"]
        if kind == "squash":
            self.burst(p.x, p.y, self.dead_gz + 10, bc, 14)
            self.burst(p.x, p.y, self.dead_gz + 10, (255, 255, 255), 8)
            self.play("splat")
        elif kind == "drown":
            self.burst(p.x, p.y, self.dead_gz, (200, 236, 252), 20, up=140)
            self.play("splash")
        else:
            self.play("eagle")
        self.best = max(self.best, int(self.p.max_y))
        self.save()

    # ---- entrées ----
    def key(self, k):
        if k == pygame.K_ESCAPE:
            self.shutdown()
            pygame.quit()
            sys.exit()
        if k == pygame.K_p and self.state == "play":
            self.paused = not self.paused
            return
        if k == pygame.K_r:
            self.reset("play")
            return
        if k == pygame.K_c and self.state == "title":
            self.next_skin()
            return
        mv = None
        if k in (pygame.K_UP, pygame.K_w, pygame.K_z, pygame.K_SPACE):
            mv = (0, 1)
        elif k in (pygame.K_DOWN, pygame.K_s):
            mv = (0, -1)
        elif k in (pygame.K_LEFT, pygame.K_a, pygame.K_q):
            mv = (-1, 0)
        elif k in (pygame.K_RIGHT, pygame.K_d):
            mv = (1, 0)
        if self.state == "title" and (mv or k == pygame.K_RETURN):
            self.state = "play"
        elif self.state == "dead":
            if self.dead_t > 0.8 and (k in (pygame.K_SPACE, pygame.K_RETURN) or mv):
                self.reset("play")
            return
        if mv and self.state == "play" and not self.paused:
            self.try_hop(*mv)

    def try_hop(self, dx, dy):
        p = self.p
        if p.hop:
            p.queue = (dx, dy)
            return
        p.face = (dx, dy)
        ty = p.y + dy
        row = self.world.rows.get(ty)
        if row is None:
            return
        if dy != 0:
            tx = p.x if row.kind == "river" else float(round(p.x))
        else:
            tx = p.x + dx
        if abs(tx) > COL_MAX + 0.5:
            return
        if row.kind == "grass" and round(tx) in row.trees:
            return
        p.hop = [p.x, p.y, tx, ty, 0.0]
        self.started = True
        self.play("hop")

    # ---- logique ----
    def on_log(self, row, x):
        for c, ln in row.logs:
            if abs(pd(x, row.shift + c)) <= ln / 2 + 0.1:
                return True
        return False

    def land(self):
        p = self.p
        row = self.world.rows.get(round(p.y))
        if row is None:
            return
        p.max_y = max(p.max_y, p.y)
        self.land_t = self.t
        if row.kind in ("grass", "road", "rail"):
            self.burst(p.x, p.y, ground_z(row), shade(ground_color(row), 1.2), 5, 1.0, 45, .35)
        if row.kind == "pads" and round(p.x) not in row.pads:
            self.die("drown")
        elif row.kind == "river" and not self.on_log(row, p.x):
            self.die("drown")
        elif row.kind == "grass" and round(p.x) in row.coins:
            row.coins.discard(round(p.x))
            self.coins += 1
            self.run_coins += 1
            self.burst(p.x, p.y, ground_z(row) + 14, (255, 214, 62), 8, 1.2, 110, .5)
            self.play("coin")

    def update(self, dt):
        self.t += dt
        for q in self.parts:
            q[0] += q[3] * dt
            q[1] += q[4] * dt
            q[2] += q[5] * dt
            q[5] -= 380 * dt
            q[6] += dt
        self.parts = [q for q in self.parts if q[6] < q[7]]
        w = self.world
        for r in w.rows.values():
            r.update(dt, w.rng)
        if self.state == "dead":
            self.dead_t += dt
            return
        if self.state != "play" or self.paused:
            return
        p = self.p
        if p.hop:
            h = p.hop
            h[4] += dt / HOP_T
            f = min(1.0, h[4])
            p.x = h[0] + (h[2] - h[0]) * f
            p.y = h[1] + (h[3] - h[1]) * f
            p.lift = math.sin(math.pi * f) * 24
            if h[4] >= 1:
                p.x, p.y, p.hop, p.lift = h[2], h[3], None, 0.0
                self.land()
                if p.queue and self.state == "play":
                    mv, p.queue = p.queue, None
                    self.try_hop(*mv)
        else:
            row = w.rows.get(round(p.y))
            if row is not None and row.kind == "river":
                if not self.on_log(row, p.x):
                    self.die("drown")
                else:
                    p.x += row.dir * row.speed * dt
                    if abs(p.x) > 5.4:
                        self.die("drown")
        if self.state != "play":
            return
        row = w.rows.get(round(p.y))
        if row is not None:
            if row.kind == "road":
                for v in row.items:
                    if abs(pd(p.x, row.shift + v["off"])) < v["len"] / 2 + 0.3:
                        self.die("squash")
                        return
            elif row.kind == "rail" and row.state == "pass":
                lo, hi = row.train_extent()
                if lo - 0.3 < p.x < hi + 0.3:
                    self.die("squash")
                    return
        lvl = 1 + int(p.max_y // LEVEL_STEP)
        if lvl > self.level:
            self.level, self.lvl_t = lvl, self.t
            self.play("buy")
        # caméra
        if self.started:
            creep = self.creep()
            target = p.max_y - LEAD
            c = self.cam_y + creep * dt
            if target > self.cam_y:
                c = max(c, self.cam_y + (target - self.cam_y) * min(1.0, 5 * dt))
            self.cam_y = c
        self.cam_x += (p.x - self.cam_x) * min(1.0, 4 * dt)
        if p.y < self.cam_y - 1.0:
            self.die("eagle")
            return
        w.generate(int(self.cam_y) + 30)
        w.prune(int(self.cam_y) - 16)

    # ---- projection / primitives ----
    def P(self, x, y, z):
        return (OX + ((x - self.cam_x) + (y - self.cam_y)) * A,
                OY + ((x - self.cam_x) - (y - self.cam_y)) * B - z)

    def xrange_(self, y, pad=90):
        lo = self.cam_x + (-pad - OX) / A - (y - self.cam_y)
        hi = self.cam_x + (W + pad - OX) / A - (y - self.cam_y)
        return lo, hi

    def cube(self, x0, x1, y0, y1, z0, z1, col):
        s, P = self.screen, self.P
        pygame.draw.polygon(s, shade(col, 0.84), [P(x0, y0, z0), P(x1, y0, z0), P(x1, y0, z1), P(x0, y0, z1)])
        pygame.draw.polygon(s, shade(col, 0.66), [P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)])
        pygame.draw.polygon(s, col, [P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)])

    def top_poly(self, x0, x1, y0, y1, z, col):
        P = self.P
        pygame.draw.polygon(self.screen, col, [P(x0, y0, z), P(x1, y0, z), P(x1, y1, z), P(x0, y1, z)])

    def face_b(self, x0, x1, y, z0, z1, col):
        P = self.P
        pygame.draw.polygon(self.screen, col, [P(x0, y, z0), P(x1, y, z0), P(x1, y, z1), P(x0, y, z1)])

    def face_a(self, x, y0, y1, z0, z1, col):
        P = self.P
        pygame.draw.polygon(self.screen, col, [P(x, y0, z0), P(x, y1, z0), P(x, y1, z1), P(x, y0, z1)])

    def slab(self, xa, xb, y0, y1, zt, col):
        P, s = self.P, self.screen
        pygame.draw.polygon(s, shade(col, 0.74), [P(xa, y0, Z_BOT), P(xb, y0, Z_BOT), P(xb, y0, zt), P(xa, y0, zt)])
        self.top_poly(xa, xb, y0, y1, zt, col)

    # ---- objets ----
    def tree_at(self, row, c):
        if abs(c) <= COL_MAX:
            return row.trees.get(c)
        h = ((c * 73856093) ^ (row.seed * 19349663) ^ (row.y * 83492791)) & 0xFFFF
        if abs(c) == COL_MAX + 1 or h / 65535.0 < 0.5:
            return (1 + (h >> 3) % 3, (h >> 5) % 3)
        return None

    def draw_tree(self, x, y, z0, layers, tint):
        cube = self.cube
        if tint == 2 and layers == 1:                 # rocher
            cube(x - .32, x + .32, y - .32, y + .32, z0, z0 + 11, (152, 156, 164))
            cube(x - .18, x + .18, y - .18, y + .18, z0 + 11, z0 + 18, (170, 174, 182))
            return
        cube(x - .13, x + .13, y - .13, y + .13, z0, z0 + 10, (122, 86, 54))
        if tint == 1:                                  # sapin
            z = z0 + 8
            for half, hh in ((.44, 14), (.33, 14), (.2, 14)):
                cube(x - half, x + half, y - half, y + half, z, z + hh, (50, 128, 80))
                z += hh
            return
        col = FOLIAGE[tint]
        z = z0 + 10
        for i in range(layers):
            half = .44 - .06 * i
            cube(x - half, x + half, y - half, y + half, z, z + 17, col)
            z += 17

    def draw_vehicle(self, x, y, d, v, zt):
        cube = self.cube
        if not v["truck"]:
            col = v["color"]
            for wx in (-0.45, 0.45):
                cube(x + wx - .15, x + wx + .15, y - .41, y + .41, zt, zt + 6, (30, 30, 36))
            cube(x - .75, x + .75, y - .36, y + .36, zt + 3, zt + 13, col)
            xc = x - d * 0.1
            cube(xc - .4, xc + .4, y - .32, y + .32, zt + 13, zt + 20, WINDOW)
            cube(xc - .43, xc + .43, y - .35, y + .35, zt + 20, zt + 23, col)
            xe = x + .75
            lamp = (255, 238, 150) if d > 0 else (230, 50, 50)
            for yy in (-.26, .16):
                self.face_a(xe, y + yy, y + yy + .10, zt + 6, zt + 9, lamp)
        else:
            front = x + d * 1.6
            xcab = front - d * 0.5
            xt = x - d * 0.55
            for wx in (-1.1, -0.2, 1.2):
                cube(x + wx - .15, x + wx + .15, y - .43, y + .43, zt, zt + 6, (30, 30, 36))
            cube(xt - 1.05, xt + 1.05, y - .42, y + .42, zt + 3, zt + 31, v["color2"])
            cube(xcab - .5, xcab + .5, y - .4, y + .4, zt + 3, zt + 21, v["color"])
            self.face_b(xcab - .36, xcab + .36, y - .4, zt + 12, zt + 19, WINDOW)
            if d > 0:
                self.face_a(xcab + .5, y - .30, y + .30, zt + 12, zt + 19, WINDOW)
                self.face_a(xcab + .5, y - .34, y - .22, zt + 5, zt + 8, (255, 238, 150))
            else:
                self.face_a(xt + 1.05, y - .30, y + .30, zt + 10, zt + 14, (230, 50, 50))

    def draw_log(self, x, ln, y, bob):
        z = ZT["river"] + bob
        self.cube(x - ln / 2, x + ln / 2, y - .4, y + .4, z - 6, z + LOG_H, LOG_C)
        self.cube(x + ln / 2, x + ln / 2 + .05, y - .34, y + .34, z - 4, z + LOG_H - 2, (218, 180, 124))

    def draw_frog(self, x, y, z0, sq=1.0, wide=1.0, face=(0, 1)):
        """Héros : petite grenouille cubique orange (personnage original)."""
        cube = self.cube
        fx, fy = face
        px, py = abs(fy), abs(fx)
        hw = 0.33 * wide
        h = 22 * sq
        sk = self.skin_now()
        body, foot, belly = sk["body"], sk["foot"], sk["belly"]
        for sgn in (-1, 1):                            # pieds
            cx_ = x + fx * 0.34 + px * sgn * 0.19
            cy_ = y + fy * 0.34 + py * sgn * 0.19
            cube(cx_ - .11, cx_ + .11, cy_ - .11, cy_ + .11, z0, z0 + max(1, 5 * sq), foot)
        cube(x - hw, x + hw, y - hw, y + hw, z0 + 3, z0 + 3 + h, body)
        ztop = z0 + 3 + h
        if sq > 0.5:                                   # bande sombre sur le dos
            self.top_poly(x - .09, x + .09, y - hw + .06, y + hw - .06, ztop, (214, 100, 28))
        if fx == 1:                                    # ventre vers la caméra
            self.face_a(x + hw, y - hw + .08, y + hw - .08, z0 + 5, z0 + 3 + h * 0.55, belly)
        elif fy == -1:
            self.face_b(x - hw + .08, x + hw - .08, y - hw, z0 + 5, z0 + 3 + h * 0.55, belly)
        eh = max(2, 9 * sq)
        for sgn in (-1, 1):                            # yeux
            ex = x + fx * 0.19 + px * sgn * 0.17
            ey = y + fy * 0.19 + py * sgn * 0.17
            cube(ex - .115, ex + .115, ey - .115, ey + .115, ztop, ztop + eh, (252, 252, 252))
            if sq > 0.5:
                if fx == 1:
                    self.face_a(ex + .115, ey - .05, ey + .05, ztop + 2, ztop + 7, (24, 24, 34))
                elif fy == -1:
                    self.face_b(ex - .05, ex + .05, ey - .115, ztop + 2, ztop + 7, (24, 24, 34))
        if sk["acc"] == "ears":                        # oreilles de lapin
            for sgn in (-1, 1):
                ex, ey = x + px * sgn * .17 - fx * .06, y + py * sgn * .17 - fy * .06
                cube(ex - .07, ex + .07, ey - .07, ey + .07, ztop, ztop + 15 * sq, body)
                cube(ex - .03, ex + .03, ey - .03, ey + .03, ztop + 1, ztop + 12 * sq, belly)
        elif sk["acc"] == "beak":                      # bec de canard
            bx, by = x + fx * .4, y + fy * .4
            cube(bx - .11, bx + .11, by - .11, by + .11, ztop - 11 * sq, ztop - 5 * sq, foot)
        elif sk["acc"] == "ant":                       # antenne de robot
            cube(x - .04, x + .04, y - .04, y + .04, ztop, ztop + 11 * sq, (200, 60, 60))
            cube(x - .09, x + .09, y - .09, y + .09, ztop + 11 * sq, ztop + 16 * sq, (255, 90, 90))

    def player_z(self):
        p = self.p
        rows = self.world.rows
        if p.hop:
            h = p.hop
            f = min(1.0, h[4])
            z0, z1 = ground_z(rows.get(h[1])), ground_z(rows.get(h[3]))
            return z0 + (z1 - z0) * f
        return ground_z(rows.get(round(p.y)))

    def draw_player(self):
        p = self.p
        row = self.world.rows.get(round(p.y))
        gz = self.player_z()
        if self.state == "dead":
            gz = self.dead_gz
            if self.dead == "squash":
                self.draw_frog(p.x, p.y, gz, 0.14, 1.5, p.face)
                return
            if self.dead == "drown":
                sink = min(1.0, self.dead_t / 0.6)
                zw = ZT["river"] if (row and row.kind == "river") else ZT["pads"]
                cut = self.P(p.x + 0.3, p.y - 0.3, zw)[1]
                self.screen.set_clip((0, 0, W, int(cut)))
                if sink < 1:
                    self.draw_frog(p.x, p.y, gz - sink * 30, 1.0, 1.0, p.face)
                self.screen.set_clip(None)
                for i in range(3):
                    r = (self.dead_t * 1.1 + i * 0.33) % 1.0
                    cx, cy = self.P(p.x, p.y, zw)
                    pygame.draw.ellipse(self.screen, (214, 238, 252),
                                        (cx - r * 56, cy - r * 28, r * 112, r * 56), 2)
                return
        if row is not None:
            r_ = max(0.18, 0.33 - p.lift * 0.005)
            gc = shade(ground_color(row), 0.78)
            self.top_poly(p.x - r_, p.x + r_, p.y - r_, p.y + r_, gz, gc)
        sq, wd = self.hop_squash()
        self.draw_frog(p.x, p.y, gz + p.lift, sq, wd, p.face)

    # ---- rendu des rangées ----
    def copies(self, base, lo, hi):
        b = base % WRAP
        k0 = math.ceil((lo - b) / WRAP)
        k1 = math.floor((hi - b) / WRAP)
        return [b + k * WRAP for k in range(k0, k1 + 1)]

    def draw_row(self, row, with_player):
        t = self.t
        y = row.y
        lo, hi = self.xrange_(y)
        k = row.kind
        zt = ZT[k]
        xa, xb = lo - 6, hi + 6
        y0, y1 = y - .5, y + .5
        items = []
        if k == "grass":
            self.slab(xa, xb, y0, y1, zt, GRASS_C[y % 2])
            for c in range(math.floor(lo) - 1, math.ceil(hi) + 2):
                tr = self.tree_at(row, c)
                if tr:
                    items.append((c, "tree", (c, tr)))
                elif abs(c) <= COL_MAX + 3 and (c * 31 + row.seed * 17) % 9 == 0:
                    items.append((c, "tuft", c))
            for c in row.coins:
                items.append((c, "coin", c))
        elif k == "road":
            self.slab(xa, xb, y0, y1, zt, ROAD_C[y % 2])
            above = self.world.rows.get(y + 1)
            if above is not None and above.kind == "road":
                for xd in range(math.floor(lo / 2) * 2, math.ceil(hi) + 2, 2):
                    self.top_poly(xd, xd + 1.0, y1 - .05, y1 + .05, zt, (232, 232, 236))
            for v in row.items:
                for xv in self.copies(row.shift + v["off"], lo - 3, hi + 3):
                    items.append((xv, "veh", (xv, v)))
        elif k in ("river", "pads"):
            self.slab(xa, xb, y0, y1, zt, WATER_C[y % 2])
            for i in range(9):
                xw = lo - 4 + ((i * 7.3 + row.seed * 0.37 + t * 0.9 * (1 if i % 2 else -1)) % (hi - lo + 8))
                yw = y - .32 + ((i * 0.23 + row.seed * 0.011) % 0.64)
                self.top_poly(xw, xw + 0.9, yw, yw + .07, zt, (176, 224, 248))
            if k == "pads":
                for c in row.pads:
                    items.append((c, "pad", c))
            else:
                for c, ln in row.logs:
                    for xv in self.copies(row.shift + c, lo - 5, hi + 5):
                        items.append((xv, "log", (xv, ln, c)))
        elif k == "rail":
            self.slab(xa, xb, y0, y1, zt, RAIL_C)
            for xs in range(math.floor(lo * 2) - 1, math.ceil(hi * 2) + 2):
                xs /= 2.0
                self.cube(xs - .09, xs + .09, y - .42, y + .42, zt, zt + 2, (124, 88, 58))
            self.cube(xa, xb, y - .30, y - .22, zt + 2, zt + 4, (204, 204, 214))
            self.cube(xa, xb, y + .22, y + .30, zt + 2, zt + 4, (204, 204, 214))
            items.append((-4.8, "pole", None))
            if row.state == "pass":
                for i in range(8):
                    items.append((row.front - row.dir * (1 + 2 * i), "train", (i, row.front - row.dir * (1 + 2 * i))))
        if with_player:
            items.append((self.p.x, "player", None))
        items.sort(key=lambda it: it[0])
        for xk, kind, data in items:
            if kind == "tree":
                c, (layers, tint) = data
                self.top_poly(c - .38, c + .75, y - .4, y + .4, zt, shade(GRASS_C[y % 2], 0.8))
                self.draw_tree(c, y, zt, layers, tint)
            elif kind == "tuft":
                c = data
                col = (252, 252, 252) if (c + row.seed) % 2 else (252, 226, 90)
                self.cube(c - .06 + .2, c + .06 + .2, y - .06, y + .06, zt, zt + 4, col)
            elif kind == "coin":
                cx, cy = self.P(data, y, zt + 20 + math.sin(t * 3 + data) * 3)
                draw_coin(self.screen, cx, cy, t)
            elif kind == "veh":
                ln_ = 1.7 if data[1]["truck"] else 0.85
                self.top_poly(data[0] - ln_, data[0] + ln_ + .3, y - .42, y + .42, zt, shade(ROAD_C[y % 2], 0.7))
                self.draw_vehicle(data[0], y, row.dir, data[1], zt)
            elif kind == "log":
                xv, ln, c = data
                self.top_poly(xv - ln / 2, xv + ln / 2 + .25, y - .4, y + .4, zt, shade(WATER_C[y % 2], 0.8))
                self.draw_log(xv, ln, y, math.sin(t * 2 + c) * 1.2)
            elif kind == "pad":
                c = data
                self.cube(c - .4, c + .4, y - .4, y + .4, zt - 1, zt + 2, PAD_C)
                if (c * 5 + row.seed) % 4 == 0:
                    self.cube(c - .1, c + .1, y - .1, y + .1, zt + 2, zt + 7, (255, 150, 190))
            elif kind == "pole":
                self.cube(xk - .06, xk + .06, y - .44, y - .32, zt, zt + 40, (96, 96, 108))
                self.cube(xk - .16, xk + .16, y - .46, y - .30, zt + 40, zt + 56, (34, 34, 42))
                on1 = row.state == "warn" and int(t * 6) % 2 == 0
                on2 = row.state == "warn" and int(t * 6) % 2 == 1
                self.face_b(xk - .12, xk - .02, y - .46, zt + 44, zt + 52, (255, 70, 70) if on1 else (96, 34, 34))
                self.face_b(xk + .02, xk + .12, y - .46, zt + 44, zt + 52, (255, 70, 70) if on2 else (96, 34, 34))
            elif kind == "train":
                i, c = data
                col = (206, 52, 52) if i == 0 else [(72, 112, 192), (232, 192, 62), (92, 162, 112)][i % 3]
                self.cube(c - .97, c + .97, y - .42, y + .42, zt + 2, zt + 36, col)
                self.face_b(c - .8, c + .8, y - .42, zt + 20, zt + 30, WINDOW)
                if i == 0:
                    front_x = c + row.dir * .97
                    if row.dir > 0:
                        self.face_a(front_x, y - .34, y + .34, zt + 6, zt + 12, (255, 238, 140))
            elif kind == "player":
                self.draw_player()

    def text(self, txt, font, pos, color=(255, 255, 255), anchor="center"):
        img = font.render(txt, True, color)
        out = font.render(txt, True, (20, 24, 30))
        w, h = img.get_width(), img.get_height()
        if anchor == "center":
            x, y = pos[0] - w / 2, pos[1] - h / 2
        elif anchor == "right":
            x, y = pos[0] - w, pos[1]
        elif anchor == "top":
            x, y = pos[0] - w / 2, pos[1]
        else:
            x, y = pos
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2), (-2, -2)):
            self.screen.blit(out, (x + ox, y + oy))
        self.screen.blit(img, (x, y))

    def draw(self):
        s = self.screen
        s.fill((104, 176, 74))
        w, p = self.world, self.p
        prow = round(p.y)
        eagle = self.state == "dead" and self.dead == "eagle"
        for y in range(int(self.cam_y) + 22, int(self.cam_y) - 15, -1):
            row = w.rows.get(y)
            if row is None:
                continue
            self.draw_row(row, y == prow and not eagle)
        if eagle:
            tt, gz = self.dead_t, self.dead_gz
            row = w.rows.get(prow)
            if tt < 0.45:
                f = tt / 0.45
                r_ = 0.3 + 1.0 * f
                if row is not None:
                    self.top_poly(p.x - r_, p.x + r_, p.y - r_, p.y + r_, gz, shade(ground_color(row), 0.74))
                self.draw_frog(p.x, p.y, gz, 1.0, 1.0, p.face)
                ex, ey = self.P(p.x, p.y, gz + 34)
                draw_eagle(s, ex, -80 + (ey - 30 + 80) * f, self.t)
            else:
                rise = (tt - 0.45) * 700
                self.draw_frog(p.x, p.y, gz + rise, 1.0, 1.0, p.face)
                ex, ey = self.P(p.x, p.y, gz + rise + 34)
                draw_eagle(s, ex, ey - 30, self.t)
        if self.state == "play" and self.occluded():
            ghost = pygame.Surface((W, H), pygame.SRCALPHA)
            real, self.screen = self.screen, ghost
            self.draw_frog(p.x, p.y, self.player_z() + p.lift, 1.0, 1.0, p.face)
            self.screen = real
            ghost.set_alpha(135)
            real.blit(ghost, (0, 0))
        for q in self.parts:
            sx, sy = self.P(q[0], q[1], q[2])
            r = max(1, int(5 * (1 - q[6] / q[7]) + 1))
            pygame.draw.rect(s, q[8], (sx - r, sy - r, 2 * r, 2 * r))
        self.draw_hud()

    def occluded(self):
        """Vrai si un arbre d'une rangée plus proche peut cacher la grenouille."""
        p = self.p
        for dy in (1, 2):
            row = self.world.rows.get(round(p.y) - dy)
            if row is not None and row.kind == "grass":
                for c in row.trees:
                    if abs(c - p.x) <= 1.3 and row.trees[c][0] >= 1:
                        return True
        return False

    def draw_hud(self):
        s = self.screen
        if self.state in ("play", "dead"):
            self.text(str(int(self.p.max_y)), self.f_big, (18, 8), anchor="left")
        self.text("Meilleur : %d" % self.best, self.f_small, (20, 78), anchor="left")
        draw_coin(s, W - 28, 28, self.t)
        self.text(str(self.coins), self.f_mid, (W - 46, 10), anchor="right")
        if self.state in ("play", "dead"):
            self.text("Niveau %d" % self.level, self.f_small, (W // 2, 10), (255, 240, 120), anchor="top")
        if self.state == "play" and self.t - self.lvl_t < 1.6:
            self.text("NIVEAU %d !" % self.level, self.f_mid, (W // 2, 300), (255, 240, 120))
        if self.state == "title":
            ov = pygame.Surface((W, H), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 90))
            s.blit(ov, (0, 0))
            self.text("FROGGY ROAD", self.f_big, (W // 2, 170), (255, 240, 120))
            self.text("Traverse sans te faire écraser !", self.f_mid, (W // 2, 244))
            sk = SKINS[self.skin_i]
            lock = "" if sk["name"] in self.owned else "  -  verrouillé : %d pièces" % sk["price"]
            self.text("C : personnage  >  %s%s" % (sk["name"], lock), self.f_small, (W // 2, 590),
                      (255, 220, 80) if not lock else (255, 140, 140))
            self.text("ESPACE ou flèches pour commencer", self.f_mid, (W // 2, 640))
            self.text("Flèches / ZQSD / WASD  -  P pause  -  R rejouer", self.f_small, (W // 2, 690))
        elif self.state == "dead" and self.dead_t > (1.3 if self.dead == "eagle" else 0.8):
            ov = pygame.Surface((W, H), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 120))
            s.blit(ov, (0, 0))
            self.text("PERDU !", self.f_big, (W // 2, 230), (255, 110, 110))
            self.text("Score : %d" % int(self.p.max_y), self.f_mid, (W // 2, 320))
            self.text("Meilleur : %d" % self.best, self.f_mid, (W // 2, 368))
            if self.run_coins:
                self.text("+%d pièce(s)" % self.run_coins, self.f_small, (W // 2, 412), (255, 220, 80))
            self.text("ESPACE pour rejouer", self.f_mid, (W // 2, 500))
        elif self.paused:
            self.text("PAUSE", self.f_big, (W // 2, H // 2))


def main():
    pygame.init()
    pygame.display.set_caption("Froggy Road")
    try:
        screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
    except (pygame.error, AttributeError):
        screen = pygame.display.set_mode((W, H))
    clock = pygame.time.Clock()
    game = Game(screen)
    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                game.shutdown()
                pygame.quit()
                sys.exit()
            elif e.type == pygame.KEYDOWN:
                game.key(e.key)
        game.update(dt)
        game.draw()
        pygame.display.flip()


if __name__ == "__main__":
    main()