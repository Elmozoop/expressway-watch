#!/bin/bash
# Netlify build step: turn the link-preview image into a full URL
# so a link shared on WhatsApp, LinkedIn or Slack shows docs/og.jpg

set -e

# The site URL on Netlify (set in Netlify dashboard -> Site configuration -> Environment variables)
# If not set, fall back to the default Netlify URL pattern
SITE_URL="${SITE_URL:-https://${NETLIFY_SITE_NAME}.netlify.app}"

# Update og:image in index.html to be an absolute URL
if [ -f "index.html" ]; then
  # Replace relative og.jpg with absolute URL
  sed -i "s|content=\"og.jpg\"|content=\"${SITE_URL}/og.jpg\"|g" index.html
  echo "Updated og:image to ${SITE_URL}/og.jpg"
fi

echo "Netlify build step completed"
