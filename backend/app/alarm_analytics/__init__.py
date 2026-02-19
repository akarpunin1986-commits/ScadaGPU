"""Alarm Analytics — isolated module for detailed alarm analysis.

Detects individual alarm bits (0->1 transitions), captures metrics snapshots,
performs root-cause analysis, and exposes results via REST API + frontend modal.

Integration points:
  1. main.py: import router + start detector
  2. scada-v5.html: <script src="/alarm_modal.js">
"""
