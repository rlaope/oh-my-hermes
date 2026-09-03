#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
import sys
BASE=Path(__file__).resolve().parent; sys.path.insert(0,str(BASE/"lib"))
from common import load_object, write_json
from statistics import analyze

def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument("--baseline",type=Path,required=True); p.add_argument("--optimized",type=Path,required=True); p.add_argument("--bootstrap-repetitions",type=int,default=10000); p.add_argument("--seed",type=int,default=20260813); p.add_argument("--manifest",type=Path,default=BASE/"manifest.json"); p.add_argument("--output",type=Path,required=True); a=p.parse_args(argv)
 if a.bootstrap_repetitions<100: p.error("bootstrap repetitions must be at least 100")
 report=analyze(a.baseline,a.optimized,a.bootstrap_repetitions,a.seed,load_object(a.manifest)); write_json(a.output,report); print(json.dumps(report,sort_keys=True,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())