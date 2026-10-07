"""One command rebuilds everything: python pipeline/run_all.py [--data DIR] [--simulate]"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def run(*args):
    print("->", " ".join(args))
    subprocess.check_call([sys.executable, *args], cwd=ROOT)


ap = argparse.ArgumentParser()
ap.add_argument("--data", default="data/raw/sim", help="folder of Cricsheet-format JSON files")
ap.add_argument("--simulate", action="store_true", help="generate simulated matches first")
ap.add_argument("--source", default=None, help="label shown on the site: 'simulated' or 'Cricsheet'")
a = ap.parse_args()
if a.simulate:
    run("pipeline/simulate.py", "--out", a.data)
src = a.source or ("simulated" if "sim" in a.data else "Cricsheet")
run("pipeline/ingest.py", "--data", a.data)
run("pipeline/train.py", "--source", src)
