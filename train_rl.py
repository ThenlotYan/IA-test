"""
train_rl.py - entraîne l'IA (Q-learning) SANS affichage, beaucoup plus vite que dans le jeu.

    python3 train_rl.py                  # 20 minutes max, reprend rl_qtable.json s'il existe
    python3 train_rl.py --minutes 5      # durée max
    python3 train_rl.py --episodes 3000  # ou nombre d'épisodes max
    python3 train_rl.py --fresh          # repart de zéro (efface la table Q)

La table apprise est écrite dans rl_qtable.json : le jeu la recharge automatiquement.
"""
import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pygame

import Croassy_Road as game


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--episodes", type=int, default=10 ** 9)
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()

    pygame.init()
    screen = pygame.display.set_mode((game.W, game.H))
    game.SAVE_FILE = Path(os.devnull)
    G = game.Game(screen)
    G.snd, G.save = {}, (lambda: None)           # ni son, ni sauvegarde du jeu pendant l'entraînement
    if a.fresh:
        G.ai.q, G.ai.episodes, G.ai.best = {}, 0, 0
        G.ai.scores.clear()
    G.ai_on = True
    G.reset("play")
    ai, t0, last = G.ai, time.time(), G.ai.episodes
    start = ai.episodes
    print("départ : épisode %d, %d états" % (ai.episodes, len(ai.q)))
    try:
        while time.time() - t0 < a.minutes * 60 and ai.episodes - start < a.episodes:
            G.update(0.05)
            if ai.episodes - last >= 200:
                last = ai.episodes
                print("épisode %5d | moy.100 %6.1f | record %4d | eps %.2f | %d états | %.0fs"
                      % (ai.episodes, ai.mean_score, ai.best, ai.epsilon, len(ai.q), time.time() - t0))
    except KeyboardInterrupt:
        pass
    ai.save()
    print("sauvegardé : %s (%d états, %d épisodes)" % (ai.qfile, len(ai.q), ai.episodes))


if __name__ == "__main__":
    main()
