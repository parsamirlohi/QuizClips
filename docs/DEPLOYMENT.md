# Deploying to a server

This is how the live site is run: one small Ubuntu server (AWS Lightsail, 2 vCPUs and 2 GB of RAM), the app as a `systemd` service, and Caddy in front for HTTPS. Any Linux VPS works the same way.

## 1. The server

- Ubuntu 24.04, at least 2 vCPUs and 2 GB of RAM (4 GB is more comfortable).
- Give it a static IP and open ports 22, 80 and 443 in the firewall.
- Point a domain (or a free DuckDNS name) at the IP with an `A` record.

## 2. Install

```bash
sudo apt update && sudo apt -y upgrade
sudo apt install -y python3-pip python3-venv git ffmpeg caddy
git clone https://github.com/parsamirlohi/QuizClips.git
cd QuizClips
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
```

Add a swap file so a rendering spike slows the server down instead of crashing it:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 3. Settings

Create `.env` (see `.env.example` and [CONFIGURATION.md](CONFIGURATION.md)). Typical server values:

```
PIXABAY_API_KEY=...
GEMINI_API_KEY=...
QC_HOST=127.0.0.1
TRUST_PROXY=1
LIMIT_SITE_DAILY=100
FOOTAGE_WORKERS=3
X264_PRESET=ultrafast
```

Set `QC_PASSWORD` as well to put a login box in front of the whole site. Never commit `.env`.

## 4. Run it as a service

`/etc/systemd/system/quizclips.service`:

```ini
[Unit]
Description=Quizclips
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/QuizClips
ExecStart=/home/ubuntu/QuizClips/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now quizclips
```

## 5. HTTPS with Caddy

`/etc/caddy/Caddyfile` (the braces must be on their own lines):

```
your-domain.example {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl restart caddy
```

Caddy gets and renews the certificate by itself.

## Updating

Changes reach the site only when you pull them, so you can test locally first:

```bash
cd ~/QuizClips && git pull && sudo systemctl restart quizclips
```

## Performance

Rendering is CPU-bound. On 2 shared vCPUs a 5-question video (about 106 seconds long) took about 3.7 minutes to build, against roughly a minute on a laptop. More CPU is the only real fix.
