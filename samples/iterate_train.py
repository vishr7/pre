"""Minimal PRE Iterate training script: takes each search parameter as a flag, writes <out>/metrics.json."""
import argparse, json, math, os, random

parser = argparse.ArgumentParser()
parser.add_argument("--lr", type=float, required=True)
parser.add_argument("--batch_size", type=int, required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()
random.seed(int(os.environ.get("PRE_TRIAL_SEED", "0")))

for epoch in range(1, 6):
    # Toy objective that peaks near lr=3e-3 and prefers smaller batches; replace with real training.
    acc = (0.95 - abs(math.log10(args.lr) + 2.5) * 0.08 - args.batch_size / 640 + random.uniform(-0.005, 0.005)) * epoch / 5
    print(json.dumps({"epoch": epoch, "val_accuracy": round(acc, 4)}), flush=True)

with open(os.path.join(args.out, "metrics.json"), "w") as f:
    json.dump({"val_accuracy": acc}, f)
