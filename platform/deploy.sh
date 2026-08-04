#!/bin/bash
set -euo pipefail

echo "=== SmartTrader 7CAS - Deploiement Production ==="
echo ""

# Check .env exists
if [ ! -f .env ]; then
    echo "ERREUR: Fichier .env manquant."
    echo "Copiez .env.example en .env et remplissez les valeurs:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    exit 1
fi

source .env

# Validate required vars
if [ "${SECRET_KEY:-CHANGEZ_MOI}" = "CHANGEZ_MOI_avec_une_cle_aleatoire_de_64_caracteres" ]; then
    echo "ERREUR: Changez SECRET_KEY dans .env"
    exit 1
fi

if [ -z "${ADMIN_PASSWORD:-}" ]; then
    echo "ERREUR: ADMIN_PASSWORD requis dans .env"
    exit 1
fi

DOMAIN="${DOMAIN:-localhost}"

echo "1/4 - Construction de l'image Docker..."
docker compose build

echo "2/4 - Obtention du certificat SSL..."
if [ "$DOMAIN" != "localhost" ] && [ ! -d "certbot/conf/live/smarttrader" ]; then
    mkdir -p certbot/conf certbot/www

    # Temporary nginx for ACME challenge
    docker compose up -d nginx
    sleep 2

    docker compose run --rm certbot certonly \
        --webroot --webroot-path=/var/www/certbot \
        --email "${ADMIN_EMAIL:-admin@$DOMAIN}" \
        --agree-tos --no-eff-email \
        --cert-name smarttrader \
        -d "$DOMAIN"

    docker compose down
    echo "   Certificat SSL obtenu pour $DOMAIN"
else
    echo "   SSL: certificat existant ou mode localhost"
fi

echo "3/4 - Demarrage des services..."
docker compose up -d

echo "4/4 - Verification..."
sleep 3
if docker compose ps | grep -q "healthy\|running"; then
    echo ""
    echo "=== Deploiement reussi ==="
    echo ""
    echo "  URL:   https://$DOMAIN"
    echo "  Admin: $ADMIN_USERNAME / [mot de passe dans .env]"
    echo ""
    echo "Commandes utiles:"
    echo "  docker compose logs -f        # Voir les logs"
    echo "  docker compose restart web     # Redemarrer l'app"
    echo "  docker compose down            # Arreter tout"
    echo ""
else
    echo "ATTENTION: Verifiez les logs avec: docker compose logs"
fi
