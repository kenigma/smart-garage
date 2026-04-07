#!/usr/bin/env bash
# setup-tunnel.sh — Set up a persistent Cloudflare Tunnel so the garage app
# is reachable at a public HTTPS URL (e.g. https://garage.yourdomain.com).
#
# Prerequisites:
#   1. Your domain is added to Cloudflare (free plan) and nameservers updated at GoDaddy.
#   2. Run this script on the Pi as the pi user (not root).
#
# Usage: bash deploy/setup-tunnel.sh

set -e

echo "=== Step 1: Install cloudflared ==="
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt install -y cloudflared

echo ""
echo "=== Step 2: Authenticate with Cloudflare ==="
echo "A browser window will open — log in and authorise the tunnel."
cloudflared tunnel login

echo ""
echo "=== Step 3: Create the tunnel ==="
cloudflared tunnel create smart-garage
# Note the tunnel ID printed above — you'll need it for the config file.

echo ""
echo "=== Step 4: Create config file ==="
TUNNEL_ID=$(cloudflared tunnel list | awk '/smart-garage/ {print $1}')
CONFIG_DIR="$HOME/.cloudflared"
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_DIR/config.yml" <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${CONFIG_DIR}/${TUNNEL_ID}.json
ingress:
  - service: http://localhost:8000
EOF
echo "Config written to $CONFIG_DIR/config.yml"

echo ""
echo "=== Step 5: Route your domain ==="
echo "Replace 'garage.yourdomain.com' with your actual subdomain:"
read -rp "Hostname (e.g. garage.yourdomain.com): " HOSTNAME
cloudflared tunnel route dns smart-garage "$HOSTNAME"
# Update the ingress in config.yml to include the hostname
sed -i "s|- service: http://localhost:8000|- hostname: ${HOSTNAME}\n  service: http://localhost:8000\n- service: http_status:404|" "$CONFIG_DIR/config.yml"
echo "Updated $CONFIG_DIR/config.yml with hostname $HOSTNAME"

echo ""
echo "=== Step 6: Install and start as systemd service ==="
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

echo ""
echo "=== Done ==="
echo "Your garage app should now be accessible at https://${HOSTNAME}"
echo "Add this to your .env: PUBLIC_URL=https://${HOSTNAME}"
