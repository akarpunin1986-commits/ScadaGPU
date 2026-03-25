#!/bin/bash
# AI API routes through WireGuard VPN
# All Cloudflare ranges (OpenAI uses Cloudflare CDN)
ip route add 104.16.0.0/12 dev wg0 2>/dev/null
ip route add 172.64.0.0/13 dev wg0 2>/dev/null
ip route add 162.158.0.0/15 dev wg0 2>/dev/null
ip route add 141.101.64.0/18 dev wg0 2>/dev/null
# Anthropic
ip route add 160.79.104.0/24 dev wg0 2>/dev/null
logger "vpn-ai-routes: AI API routes via wg0 applied"
