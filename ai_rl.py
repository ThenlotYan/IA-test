"""
ai_rl.py - IA par APPRENTISSAGE PAR RENFORCEMENT (Q-learning tabulaire)
pour Croassy / Froggy Road. Python pur, aucune dépendance.

Principe
--------
L'agent ne connaît pas les règles : il apprend par essai-erreur.
  * OBSERVATION : une vue égocentrique compacte (état) :
        - sa case et les cases voisines (devant, devant x2, gauche/droite, derrière)
          codées en 12 classes : herbe libre, obstacle, route dégagée / à surveiller /
          dangereuse / mortelle (selon le temps avant impact du véhicule ou du train),
          tronc / bord de tronc, eau (avec le temps avant l'arrivée du prochain tronc),
          avertissement de train ; la direction où contourner un mur d'arbres ;
        - le temps avant d'être attrapé par l'aigle et le risque d'être emporté hors de la rivière.
  * ACTIONS : avancer, gauche, droite, attendre, reculer (les coups impossibles,
    comme un arbre devant, sont masqués).
  * FONCTION Q : table factorisée. Chaque action a sa propre petite table qui ne
    regarde que les cases utiles à ce coup (ex. "avancer" : case devant, case
    d'après, aigle). Les tables sont minuscules, donc l'agent généralise vite.
  * RÉCOMPENSES : +1 par nouvelle rangée gagnée, +0.5 par pièce,
    -0.05 par tour (pour ne pas traîner), -10 à la mort.
  * APPRENTISSAGE : mise à jour de Q-learning à chaque décision
        Q(s,a) <- Q(s,a) + alpha * ( r + gamma * max_a' Q(s',a') - Q(s,a) )
    avec une politique epsilon-greedy dont epsilon diminue avec les épisodes.
La table Q est sauvegardée dans rl_qtable.json (à côté de ce fichier) :
l'agent reprend donc son apprentissage à chaque lancement.

Interface identique à l'ancienne IA : choose(game) / record(score) / save().
"""
import json
import random
import time
from collections import deque
from pathlib import Path

WRAP = 22.0                 # période des véhicules / troncs (comme dans le jeu)
COL_MAX = 4                 # colonnes jouables : -4 .. 4
STEP = 0.20                 # durée entre deux décisions (s)
ACTIONS = ((0, 1), (-1, 0), (1, 0), (0, 0), (0, -1))    # avancer, gauche, droite, attendre, reculer
INF = float("inf")

ALPHA, GAMMA = 0.10, 0.95
R_ROW, R_COIN, R_TIME, R_DEATH = 1.0, 0.5, 0.05, -10.0
EPS_START, EPS_MIN, EPS_DECAY = 0.30, 0.02, 0.9995
QFILE = Path(__file__).resolve().parent / "rl_qtable.json"

# classes de cases
GROUND, BLOCK, CLEAR, CAUTION, WARNING, DEADLY, LOG, WATER, LOGEDGE, RAILWARN, SOON, MID = range(12)
_COMPACT = {GROUND: 0, CLEAR: 0, LOG: 0, BLOCK: 1, CAUTION: 2, WARNING: 2, LOGEDGE: 2,
            RAILWARN: 2, SOON: 2, MID: 3, DEADLY: 3, WATER: 3}


def _pd(a, b):
    return ((a - b + WRAP / 2) % WRAP) - WRAP / 2


def _bucket(t):
    return DEADLY if t < 0.3 else WARNING if t < 0.7 else CAUTION if t < 1.3 else CLEAR


class RLAgent:
    def __init__(self, qfile=QFILE):
        self.qfile = Path(qfile)
        self.q = {}
        self.episodes = 0
        self.best = 0
        self.scores = deque(maxlen=100)
        self.learning = True        # False = mode "jouer" : greedy, sans apprentissage
        self.next_t = 0.0
        self.prev = None            # (état, action) précédent
        self._world = None
        self._maxy = 0
        self._coins = 0
        self.last_ms = 0.0
        self.load()

    # ------------------------------------------------------------------
    # Statistiques / persistance
    # ------------------------------------------------------------------
    @property
    def epsilon(self):
        return max(EPS_MIN, EPS_START * EPS_DECAY ** self.episodes) if self.learning else 0.0

    @property
    def mean_score(self):
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    def load(self):
        try:
            d = json.loads(self.qfile.read_text())
            self.q = {tuple(int(c) for c in k.split(",")): v for k, v in d["q"].items()}
            self.episodes, self.best = int(d.get("episodes", 0)), int(d.get("best", 0))
            self.scores.extend(d.get("scores", []))
        except Exception:
            pass

    def save(self):
        try:
            d = {"q": {",".join(map(str, k)): round(v, 4) for k, v in self.q.items()},
                 "episodes": self.episodes, "best": self.best, "scores": list(self.scores)}
            self.qfile.write_text(json.dumps(d, separators=(",", ":")))
        except Exception as e:      # ne jamais planter le jeu, mais le dire
            print("ai_rl : sauvegarde impossible :", e)

    # ------------------------------------------------------------------
    # Interface avec le jeu
    # ------------------------------------------------------------------
    def record(self, score):
        """Appelé à la fin d'un épisode (mort) : dernière mise à jour + stats."""
        if self.learning and self.prev is not None:
            self._update(self.prev, R_DEATH, None)
        self.prev = None
        self.scores.append(score)
        self.best = max(self.best, score)
        self.episodes += 1
        self.next_t = 0.0
        if self.learning and self.episodes % 100 == 0:
            self.save()

    def choose(self, game):
        """Renvoie (dx, dy), (0, 0) pour attendre, ou None si pas de décision maintenant."""
        p = game.p
        if p.hop or game.state != "play" or game.paused or game.t < self.next_t:
            return None
        self.next_t = game.t + STEP
        t0 = time.perf_counter()
        if game.world is not self._world:               # nouvel épisode
            self._world, self.prev = game.world, None
            self._maxy, self._coins = p.max_y, game.run_coins
        keys, legal = self._observe(game)
        if self.learning and self.prev is not None:
            pk = self.prev
            r = ((p.max_y - self._maxy) * R_ROW + (game.run_coins - self._coins) * R_COIN - R_TIME)
            self._update(pk, r, (keys, legal))
        self._maxy, self._coins = p.max_y, game.run_coins
        a = self._policy(keys, legal)
        self.prev = keys[a]
        self.last_ms = (time.perf_counter() - t0) * 1000
        return ACTIONS[a]

    # ------------------------------------------------------------------
    # Q-learning
    # ------------------------------------------------------------------
    def _q(self, key):
        return self.q.get(key, 0.0)

    def _policy(self, keys, legal):
        if random.random() < self.epsilon:
            if 0 in legal and random.random() < 0.5:    # exploration orientée : avancer
                return 0
            return random.choice(legal)
        vals = {x: self._q(keys[x]) for x in legal}
        best = max(vals.values())
        return random.choice([x for x in legal if vals[x] >= best - 1e-9])

    def _update(self, key, r, nxt):
        """Q(s,a) <- Q(s,a) + alpha * (r + gamma * max Q(s',a') - Q(s,a))"""
        target = r
        if nxt is not None:
            keys2, legal2 = nxt
            target += GAMMA * max(self._q(keys2[x]) for x in legal2)
        old = self.q.get(key, 0.0)
        self.q[key] = old + ALPHA * (target - old)

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------
    def _observe(self, game):
        p, rows = game.p, game.world.rows
        x, y = p.x, int(round(p.y))
        c0 = self._cell(rows, y, x, 0)
        u1 = self._cell(rows, y + 1, x, 0)
        u2 = self._cell(rows, y + 2, x, 0)
        l1, r1 = self._cell(rows, y + 1, x, -1), self._cell(rows, y + 1, x, 1)
        l0, r0 = self._cell(rows, y, x, -1), self._cell(rows, y, x, 1)
        d1 = self._cell(rows, y - 1, x, 0)
        t_eagle = (y - (game.cam_y - 1.0)) / max(game.creep(), 0.05)   # secondes avant l'aigle
        eb = 0 if t_eagle < 1.0 else 1 if t_eagle < 2.0 else 2 if t_eagle < 3.5 else 3 if t_eagle < 6.0 else 4
        row = rows.get(y)
        drift = 0
        if row is not None and row.kind == "river":
            v = row.dir * row.speed
            if v * x > 0 and (5.4 - abs(x)) / row.speed < 2.0:
                drift = 1
        cm = _COMPACT
        pl = pr = 3                    # direction où contourner un obstacle devant
        if u1 == BLOCK:
            gl = next((k for k in range(1, 5) if self._cell(rows, y + 1, x, -k) != BLOCK), 9)
            gr = next((k for k in range(1, 5) if self._cell(rows, y + 1, x, k) != BLOCK), 9)
            pl, pr = (1, 0) if gl < gr else (0, 1) if gr < gl else (2, 2)
        keys = {                       # une petite table par action (Q factorisée)
            0: (0, u1, cm[u2], eb),                     # avancer
            1: (1, l0, cm[c0], cm[l1], pl, eb),         # gauche
            2: (2, r0, cm[c0], cm[r1], pr, eb),         # droite
            3: (3, c0, cm[u1], eb, drift),              # attendre
            4: (4, d1, cm[c0]),                         # reculer
        }
        legal = [3]
        if u1 != BLOCK:
            legal.insert(0, 0)
        if l0 != BLOCK:
            legal.append(1)
        if r0 != BLOCK:
            legal.append(2)
        if d1 != BLOCK:
            legal.append(4)
        return keys, sorted(legal)

    def _cell(self, rows, y, x, dx):
        row = rows.get(y)
        if row is None:
            return BLOCK
        k = row.kind
        xx = (x if k == "river" else float(round(x))) + dx
        if dx and abs(xx) > COL_MAX + 0.5:
            return BLOCK
        if k == "grass":
            return BLOCK if round(xx) in row.trees else GROUND
        if k == "road":
            return _bucket(self._ttc_road(row, xx))
        if k == "river":
            return self._log_code(row, xx)
        if k == "pads":
            return LOG if round(xx) in row.pads else WATER
        if k == "rail":
            return self._rail_code(row, xx)
        return GROUND

    @staticmethod
    def _ttc_road(row, xx):
        """Temps (s) avant qu'un véhicule touche la colonne xx."""
        best = INF
        vel = row.dir * row.speed
        for v in row.items:
            pos, w = row.shift + v["off"], v["len"] / 2 + 0.3
            if abs(_pd(xx, pos)) < w:
                return 0.0
            s = ((xx - w) - pos) % WRAP if vel > 0 else (pos - (xx + w)) % WRAP
            t = s / row.speed
            if t < best:
                best = t
        return best

    @staticmethod
    def _log_code(row, xx):
        base = row.shift + row.dir * row.speed * 0.15
        best, arrive = -INF, INF
        v = row.dir * row.speed
        for c, ln in row.logs:
            m = ln / 2 + 0.1 - abs(_pd(xx, base + c))
            if m > best:
                best = m
            h = ln / 2 - 0.25                        # zone "solide" du tronc
            r0 = _pd(xx, row.shift + c)
            t = 0.0 if abs(r0) <= h else (((r0 - h) % WRAP) / v if v > 0 else ((-h - r0) % WRAP) / -v)
            if t < arrive:
                arrive = t
        if best > 0.35:
            return LOG
        if best > 0:
            return LOGEDGE
        return SOON if arrive < 0.5 else MID if arrive < 1.2 else WATER

    @staticmethod
    def _rail_code(row, xx):
        if row.state == "idle":
            return CLEAR
        if row.state == "warn":
            return RAILWARN
        f = row.front
        if row.dir > 0:
            if f >= xx + 16.3:
                return CLEAR
            t = 0.0 if f > xx - 0.3 else (xx - 0.3 - f) / 30.0
        else:
            if f <= xx - 16.3:
                return CLEAR
            t = 0.0 if f < xx + 0.3 else (f - (xx + 0.3)) / 30.0
        return _bucket(t)
