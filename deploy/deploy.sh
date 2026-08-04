#!/usr/bin/env bash
# Build the frontend, ship everything to EC2 (tar over ssh - no rsync needed
# on Windows/Git Bash), restart the service. Run from the repo root.
#
# One-time server setup (over ssh):
#   sudo dnf install -y python3.11                       # AL2023 ships 3.9 as python3
#   # after the first deploy:
#   cd /home/ec2-user/anacity/backend
#   python3.11 -m venv venv && venv/bin/pip install -r requirements.txt
#   nano .env                                            # ANTHROPIC_API_KEY=... (typed by hand, never shipped)
#   chmod 600 .env
#   sudo cp ../deploy/anacity.service /etc/systemd/system/
#   sudo systemctl daemon-reload && sudo systemctl enable --now anacity
#   # open TCP 8000 in the instance security group (EC2 console -> inbound rules)

set -euo pipefail

KEY="/c/Users/Aamruth Venkatesh/aws-migration/transcriber-key.pem"
HOST="ec2-user@3.213.109.62"
DEST="/home/ec2-user/anacity"

echo "==> building frontend"
(cd frontend && npm run build)

echo "==> shipping to $HOST"
# server-side .env is untouched: it's excluded here and tar only overwrites what it carries
tar czf - \
  --exclude='backend/venv' --exclude='__pycache__' \
  --exclude='.pytest_cache' --exclude='backend/.env' \
  backend deploy EXPLANATION.md README.md frontend/dist \
  | ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$HOST" \
      "mkdir -p $DEST && tar xzf - -C $DEST"

echo "==> installing any new python deps + restarting"
ssh -i "$KEY" "$HOST" \
  "cd $DEST/backend && venv/bin/pip install -q -r requirements.txt && sudo systemctl restart anacity && sleep 2 && systemctl is-active anacity"

echo "==> live at http://3.213.109.62:8000"
