"""Run once with:  python set_key.py
Asks for your video API key and saves it to the .env file next to this script."""
from pathlib import Path

env_file = Path(__file__).resolve().parent / ".env"

print("Which site is your key from?")
print("  1) Pixabay")
print("  2) Pexels")
choice = input("Type 1 or 2: ").strip()
name = "PEXELS_API_KEY" if choice == "2" else "PIXABAY_API_KEY"
site = "Pexels" if choice == "2" else "Pixabay"

key = input(f"Paste your {site} API key and press Enter: ").strip().strip('"').strip("'")
if not key:
    raise SystemExit("No key entered, nothing was saved.")

lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
lines = [ln for ln in lines if not ln.startswith(name + "=")] + [f"{name}={key}"]
env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

print(f"Saved to {env_file}")
print("Now run:  python app.py")
