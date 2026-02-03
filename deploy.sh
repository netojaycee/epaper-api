#!/bin/bash
# deploy.sh - Automated deployment script for DigitalOcean
# Usage: bash deploy.sh your-domain.com

if [ $# -eq 0 ]; then
    echo "Usage: bash deploy.sh yourdomain.com"
    exit 1
fi

DOMAIN=$1
APP_USER="appuser"
APP_DIR="/home/${APP_USER}/epaper-api"
APP_PORT=8000

echo "================================================"
echo "FastAPI Deployment to DigitalOcean"
echo "Domain: $DOMAIN"
echo "================================================"

# Update system
echo "Step 1: Updating system packages..."
sudo apt update && sudo apt upgrade -y && sudo apt autoremove -y

# Install dependencies
echo "Step 2: Installing system dependencies..."
sudo apt install -y python3.11 python3.11-venv python3-pip python3-dev \
    build-essential libxml2-dev libxslt1-dev nginx certbot \
    python3-certbot-nginx git ufw

# Configure firewall
echo "Step 3: Configuring firewall..."
sudo ufw --force enable
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status

# Verify installations
echo "Step 4: Verifying installations..."
echo "Python: $(python3.11 --version)"
echo "Nginx: $(nginx -v 2>&1)"
echo "Certbot: $(certbot --version)"
echo "Git: $(git --version)"

# Create/Update application
if [ ! -d "$APP_DIR" ]; then
    echo "Step 5: Cloning application..."
    # This assumes you have the repo pushed to GitHub
    # Modify the URL to your actual repository
    # su - $APP_USER -c "git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git $APP_DIR"
    echo "ERROR: Please manually clone your repo to $APP_DIR"
    exit 1
else
    echo "Step 5: Application directory found. Skipping clone..."
fi

# Setup Python environment
echo "Step 6: Setting up Python virtual environment..."
sudo -u $APP_USER bash -c "cd $APP_DIR && python3.11 -m venv venv && source venv/bin/activate && pip install --upgrade pip && pip install ."

# Create Nginx configuration
echo "Step 7: Configuring Nginx..."
sudo tee /etc/nginx/sites-available/epaper-api > /dev/null <<EOF
upstream fastapi_app {
    server 127.0.0.1:${APP_PORT};
}

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} www.${DOMAIN};
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN} www.${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    location / {
        proxy_pass http://fastapi_app;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;

        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        client_max_body_size 100M;
    }
}
EOF

# Enable Nginx site
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/epaper-api /etc/nginx/sites-enabled/

# Test and start Nginx (HTTP only for now)
echo "Step 8: Starting Nginx..."
sudo nginx -t && sudo systemctl start nginx && sudo systemctl enable nginx

# Setup SSL
echo "Step 9: Setting up SSL certificate..."
echo "NOTE: Make sure DNS is pointing to this server before continuing"
read -p "Is DNS configured for ${DOMAIN}? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo certbot certonly --nginx -d ${DOMAIN} -d www.${DOMAIN} --non-interactive --agree-tos -m admin@${DOMAIN}
    
    # Update Nginx with SSL config
    sudo systemctl reload nginx
    echo "✓ SSL certificate installed"
else
    echo "Please configure DNS first, then run: sudo certbot certonly --nginx -d ${DOMAIN} -d www.${DOMAIN}"
fi

# Create .env file on server
echo "Step 11: Creating .env configuration file..."
sudo tee ${APP_DIR}/.env > /dev/null <<'ENVEOF'
# Application
APP_ENV=production
DEBUG=false

# Server
HOST=127.0.0.1
PORT=8000
WORKERS=4

# File uploads
MAX_UPLOAD_SIZE_MB=100
TEMP_DIR=/tmp/epaper-uploads

# Ollama (AI Parser)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=mistral

# WordPress Configuration
# ⚠️  UPDATE THESE WITH YOUR ACTUAL VALUES ⚠️
WORDPRESS_URL=http://your-wordpress-site.com/wp-json/wp/v2/posts
WORDPRESS_USERNAME=admin
WORDPRESS_PASSWORD=your_app_password_here
WORDPRESS_CATEGORIES_URL=http://your-wordpress-site.com/wp-json/wp/v2/categories?per_page=100
WORDPRESS_AUTHORS_URL=http://your-wordpress-site.com/wp-json/wp/v2/users?per_page=100
WORDPRESS_ENABLE_POSTING=false

# Logging
LOG_LEVEL=INFO
LOG_FILE=

# Security
REQUIRE_AUTH=false
API_KEY=
ENVEOF

# Fix permissions on .env
sudo chown ${APP_USER}:${APP_USER} ${APP_DIR}/.env
sudo chmod 600 ${APP_DIR}/.env
echo "✓ .env created at ${APP_DIR}/.env"
echo ""
echo "⚠️  IMPORTANT: Edit the .env file with your WordPress credentials:"
echo "   nano ${APP_DIR}/.env"
echo ""

# Update systemd service to load .env
echo "Step 12: Updating systemd service to use .env..."
sudo tee /etc/systemd/system/epaper-api.service > /dev/null <<EOF
[Unit]
Description=FastAPI IDML News Extractor
After=network.target

[Service]
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/uvicorn main:app --host 127.0.0.1 --port ${APP_PORT} --workers 4

Restart=always
RestartSec=10

StandardOutput=journal
StandardError=journal
SyslogIdentifier=epaper-api

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable epaper-api
sudo systemctl start epaper-api

echo ""
echo "================================================"
echo "✓ Deployment Complete!"
echo "================================================"
echo ""
echo "Your application is running at:"
echo "  https://${DOMAIN}"
echo ""
echo "IMPORTANT: Configure WordPress credentials:"
echo "  ssh appuser@${DOMAIN}"
echo "  nano ${APP_DIR}/.env"
echo ""
echo "Then restart the service:"
echo "  sudo systemctl restart epaper-api"
echo ""
echo "Useful commands:"
echo "  View logs: sudo journalctl -u epaper-api -f"
echo "  Status: sudo systemctl status epaper-api"
echo "  Restart: sudo systemctl restart epaper-api"
echo "  Edit config: nano ${APP_DIR}/.env"
echo ""
echo "Next steps:"
echo "  1. SSH to server: ssh appuser@${DOMAIN}"
echo "  2. Edit .env with WordPress credentials: nano ${APP_DIR}/.env"
echo "  3. Restart service: sudo systemctl restart epaper-api"
echo "  4. Monitor logs: sudo journalctl -u epaper-api -f"
echo ""
