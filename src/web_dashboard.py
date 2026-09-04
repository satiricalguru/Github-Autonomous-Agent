"""Ultra-responsive web dashboard providing real-time telemetry, task inspection,
control actions, and WCAG 2.1 AA accessible visualization for the Autonomous GitHub Agent.
"""

import http.server
import json
import logging
import socketserver
import threading
import urllib.parse
from typing import Any, Dict, List, Optional

try:
    from .config import config
    from .safety_guardrails import SafetyGuardrails
    from .status_tracker import status_tracker
    from .task_tracker import task_tracker
except ImportError:
    from config import config
    from safety_guardrails import SafetyGuardrails
    from status_tracker import status_tracker
    from task_tracker import task_tracker

logger = logging.getLogger("github_agent.web")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Autonomous GitHub Agent - Telemetry &amp; Task Monitor</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      /* Dark Theme (Default) */
      --bg: #000000;
      --sidebar-bg: #07090e;
      --card-bg: #0d1117;
      --card-inner: #161b22;
      --border: rgba(255, 255, 255, 0.08);
      --border-subtle: rgba(255, 255, 255, 0.04);
      --text-main: #f0f6fc;
      --text-muted: #8b949e;
      --text-dim: #8b949e; /* WCAG AA > 4.5:1 on dark */
      
      --accent-green: #3fb950;
      --accent-green-bg: rgba(63, 185, 80, 0.12);
      --accent-blue: #58a6ff;
      --accent-blue-bg: rgba(88, 166, 255, 0.12);
      --accent-purple: #bc8cff;
      --accent-purple-bg: rgba(188, 140, 255, 0.12);
      --accent-yellow: #d29922;
      --accent-yellow-bg: rgba(210, 153, 34, 0.12);
      --accent-red: #f85149;
      --accent-red-bg: rgba(248, 81, 73, 0.12);
      --accent-cyan: #39c5cf;

      --btn-bg: #161b22;
      --btn-border: rgba(255, 255, 255, 0.12);
      --btn-hover: #21262d;
      --shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
    }

    [data-theme="light"] {
      --bg: #f6f8fa;
      --sidebar-bg: #ffffff;
      --card-bg: #ffffff;
      --card-inner: #f6f8fa;
      --border: #d0d7de;
      --border-subtle: #eaeef2;
      --text-main: #1f2328;
      --text-muted: #424a53; /* WCAG AA > 4.5:1 */
      --text-dim: #57606a;   /* WCAG AA > 4.5:1 on white */

      --accent-green: #1a7f37;
      --accent-green-bg: rgba(26, 127, 55, 0.12);
      --accent-blue: #0969da;
      --accent-blue-bg: rgba(9, 105, 218, 0.12);
      --accent-purple: #8250df;
      --accent-purple-bg: rgba(130, 80, 223, 0.12);
      --accent-yellow: #9a6700;
      --accent-yellow-bg: rgba(154, 103, 0, 0.12);
      --accent-red: #cf222e;
      --accent-red-bg: rgba(207, 34, 46, 0.12);
      --accent-cyan: #0598ab;

      --btn-bg: #f3f4f6;
      --btn-border: #d0d7de;
      --btn-hover: #e5e7eb;
      --shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
    }

    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      overflow-x: hidden;
      transition: background-color 0.25s ease, color 0.25s ease;
    }

    /* Mobile Top Bar (Hidden on desktop) */
    .mobile-top-bar {
      display: none;
      align-items: center;
      justify-content: space-between;
      padding: 0.85rem 1.25rem;
      background: var(--sidebar-bg);
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      z-index: 850;
      width: 100%;
    }
    .menu-toggle-btn {
      background: transparent;
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text-main);
      width: 38px;
      height: 38px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
    .sidebar-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.55);
      backdrop-filter: blur(3px);
      z-index: 900;
    }
    .sidebar-backdrop.active {
      display: block;
    }

    /* Left Sidebar - Fixed to Viewport */
    aside {
      width: 260px;
      min-width: 260px;
      background: var(--sidebar-bg);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      padding: 1.5rem 1.25rem;
      height: 100vh;
      position: fixed;
      top: 0;
      left: 0;
      bottom: 0;
      z-index: 950;
      overflow-y: auto;
      overflow-x: hidden;
      scrollbar-width: none;
      -ms-overflow-style: none;
      transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    }
    aside::-webkit-scrollbar {
      display: none;
    }

    .brand {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 2rem;
    }
    .brand-left {
      display: flex;
      align-items: center;
      gap: 0.85rem;
    }
    .brand-icon {
      width: 38px;
      height: 38px;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-main);
      box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    }
    .brand-text h2 {
      font-size: 0.95rem;
      font-weight: 700;
      line-height: 1.2;
      color: var(--text-main);
      letter-spacing: -0.01em;
    }
    .brand-text p {
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-muted);
    }
    .sidebar-close-btn {
      display: none;
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 1.5rem;
      cursor: pointer;
      line-height: 1;
      padding: 0.25rem;
    }

    nav { display: flex; flex-direction: column; gap: 0.35rem; }
    .nav-item {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0.65rem 0.85rem;
      border-radius: 8px;
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.875rem;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s ease;
      border: 1px solid transparent;
    }
    .nav-item:hover {
      background: var(--btn-hover);
      color: var(--text-main);
    }
    .nav-item.active {
      background: var(--card-bg);
      border: 1px solid var(--border);
      color: var(--text-main);
      font-weight: 600;
    }
    .nav-item svg { width: 18px; height: 18px; stroke-width: 2; }

    .sidebar-footer {
      display: flex;
      flex-direction: column;
      gap: 1rem;
      margin-top: auto;
      padding-top: 1.5rem;
    }

    .health-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.85rem 1rem;
    }
    .health-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 0.4rem;
    }
    .health-header .val {
      color: var(--text-main);
      font-weight: 800;
      font-size: 0.85rem;
    }
    .sparkline-svg {
      width: 100%;
      height: 36px;
      margin: 0.3rem 0;
    }
    .health-status {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.75rem;
      color: var(--accent-green);
      font-weight: 500;
    }
    .status-dot-sm {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent-green);
      box-shadow: 0 0 6px var(--accent-green);
    }

    .user-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.75rem 0.85rem;
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .user-avatar {
      width: 34px;
      height: 34px;
      border-radius: 50%;
      background: var(--card-inner);
      border: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-muted);
    }
    .user-info { flex: 1; min-width: 0; }
    .user-name-row { display: flex; align-items: center; gap: 0.4rem; }
    .user-name { font-size: 0.82rem; font-weight: 700; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .badge-owner {
      font-size: 0.6rem;
      padding: 0.1rem 0.35rem;
      border-radius: 4px;
      background: var(--card-inner);
      border: 1px solid var(--border);
      color: var(--text-muted);
      font-weight: 700;
      text-transform: uppercase;
    }
    .user-role { font-size: 0.72rem; color: var(--text-muted); }

    /* Segmented Theme Switcher (Directly below Logs) */
    .theme-nav-section {
      margin-top: 1rem;
      padding-top: 0.85rem;
      border-top: 1px solid var(--border-subtle);
    }
    .theme-segmented-bar {
      display: flex;
      align-items: center;
      background: var(--card-inner);
      border: 1px solid var(--border);
      border-radius: 9px;
      padding: 3px;
      gap: 3px;
    }
    .theme-pill-btn {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.45rem;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 0.42rem 0.5rem;
      color: var(--text-muted);
      font-size: 0.78rem;
      font-weight: 600;
      font-family: inherit;
      cursor: pointer;
      transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .theme-pill-btn svg {
      transition: transform 0.18s ease, color 0.18s ease;
    }
    .theme-pill-btn:hover {
      color: var(--text-main);
    }
    .theme-pill-btn.active {
      background: var(--card-bg);
      border-color: var(--border);
      color: var(--text-main);
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
    }
    .theme-pill-btn.active svg {
      color: var(--accent-blue);
      transform: scale(1.08);
    }
    [data-theme="light"] .theme-pill-btn.active {
      background: #ffffff;
      border-color: #d0d7de;
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
    }
    [data-theme="light"] .theme-pill-btn.active svg {
      color: var(--accent-yellow);
    }

    /* Main Content Area */
    main {
      flex: 1;
      padding: 2rem 2.5rem;
      max-width: 1400px;
      min-width: 0;
      margin-left: 260px;
    }

    /* Tab Containers */
    .tab-content {
      display: none;
      animation: fadeIn 0.2s ease-in-out;
    }
    .tab-content.active {
      display: block;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }

    header.top-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 2rem;
      gap: 1.5rem;
      flex-wrap: wrap;
    }
    .header-titles h1 {
      font-size: 1.65rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: var(--text-main);
      margin-bottom: 0.25rem;
    }
    .header-titles p {
      font-size: 0.875rem;
      color: var(--text-muted);
    }
    .top-status-badge {
      display: inline-flex;
      flex-direction: column;
      align-items: flex-end;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.65rem 1.25rem;
      box-shadow: var(--shadow);
    }
    .top-status-row {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-weight: 700;
      font-size: 0.85rem;
      color: var(--accent-green);
    }
    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent-green);
      box-shadow: 0 0 8px var(--accent-green);
      animation: pulse 1.8s infinite;
    }
    @keyframes pulse {
      0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(63, 185, 80, 0.7); }
      70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(63, 185, 80, 0); }
      100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(63, 185, 80, 0); }
    }
    .top-status-sub {
      font-size: 0.72rem;
      color: var(--text-muted);
      margin-top: 0.2rem;
    }

    /* Grids */
    .grid-4 {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 1.25rem;
      margin-bottom: 2rem;
    }

    .metric-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 1.25rem 1.35rem;
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 125px;
      transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .metric-card:hover {
      transform: translateY(-2px);
      border-color: rgba(255, 255, 255, 0.18);
    }
    .metric-label {
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 0.5rem;
    }
    .metric-val-row {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      margin-bottom: 0.35rem;
      flex-wrap: wrap;
    }
    .metric-val {
      font-size: 1.35rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: var(--text-main);
      word-break: break-all;
    }
    .pill-tag {
      font-size: 0.65rem;
      font-weight: 700;
      padding: 0.2rem 0.5rem;
      border-radius: 20px;
      border: 1px solid;
    }
    .card-corner-badge {
      position: absolute;
      top: 1.25rem;
      right: 1.25rem;
    }
    .metric-sub {
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    /* Action Buttons */
    .btn-action-sm {
      background: var(--btn-bg);
      border: 1px solid var(--btn-border);
      color: var(--text-main);
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.45rem 0.85rem;
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      transition: all 0.15s ease;
      text-decoration: none;
    }
    .btn-action-sm:hover {
      background: var(--btn-hover);
      border-color: var(--text-muted);
    }
    .btn-action-sm:active {
      transform: scale(0.98);
    }

    /* Progress bar */
    .progress-bar-container {
      width: 100%;
      height: 4px;
      background: var(--card-inner);
      border-radius: 2px;
      margin: 0.6rem 0 0.4rem 0;
      overflow: hidden;
    }
    .progress-bar-fill {
      height: 100%;
      width: 100%;
      background: var(--accent-blue);
      border-radius: 2px;
      transition: width 0.3s ease;
    }

    /* Section headers */
    .section-header-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
      flex-wrap: wrap;
      gap: 0.75rem;
    }
    .section-title {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      font-size: 1.05rem;
      font-weight: 700;
      color: var(--text-main);
    }
    .section-title svg { width: 20px; height: 20px; color: var(--text-muted); }

    /* Workers Row */
    .workers-row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1.25rem;
      margin-bottom: 2.25rem;
    }
    .worker-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 1.25rem 1.4rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 1rem;
    }
    .worker-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .worker-name-group {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .worker-icon-box {
      width: 34px;
      height: 34px;
      border-radius: 8px;
      background: var(--card-inner);
      border: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-main);
    }
    .worker-title {
      font-size: 0.95rem;
      font-weight: 700;
      color: var(--text-main);
    }
    .worker-pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.25rem 0.65rem;
      border-radius: 20px;
      font-size: 0.72rem;
      font-weight: 700;
      background: var(--card-inner);
      border: 1px solid var(--border);
      color: var(--text-main);
    }
    .worker-pill-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
    }
    .worker-body {
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
    }
    .worker-activity-label {
      font-size: 0.72rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
    }
    .worker-activity-text {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--text-main);
      line-height: 1.4;
    }
    .worker-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.75rem;
      color: var(--text-muted);
      border-top: 1px solid var(--border-subtle);
      padding-top: 0.75rem;
      flex-wrap: wrap;
      gap: 0.5rem;
    }

    /* Tasks Table & Responsive Containment */
    .table-responsive-wrap {
      width: 100%;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: var(--card-bg);
      margin-bottom: 2rem;
    }
    .tasks-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
      text-align: left;
      min-width: 680px;
    }
    .tasks-table th {
      padding: 0.85rem 1.25rem;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      background: var(--card-inner);
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
    .tasks-table td {
      padding: 0.9rem 1.25rem;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--text-main);
      vertical-align: middle;
    }
    .tasks-table tr[role="button"] {
      cursor: pointer;
      transition: background 0.15s ease;
    }
    .tasks-table tr[role="button"]:hover {
      background: var(--btn-hover);
    }
    .tasks-table tr[role="button"]:focus-visible {
      outline: 2px solid var(--accent-blue);
      outline-offset: -2px;
    }
    .task-id-cell {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--accent-blue);
      white-space: nowrap;
    }
    .cat-badge {
      font-size: 0.68rem;
      font-weight: 700;
      padding: 0.2rem 0.55rem;
      border-radius: 6px;
      background: var(--card-inner);
      border: 1px solid var(--border);
      color: var(--text-main);
    }
    .status-cell {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      font-weight: 600;
      font-size: 0.8rem;
      white-space: nowrap;
    }
    .status-cell span { color: var(--accent-green); }
    .time-cell {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.75rem;
      color: var(--text-muted);
      white-space: nowrap;
    }
    .arrow-btn {
      color: var(--text-muted);
      font-size: 1.1rem;
      font-weight: 700;
    }

    /* Sub-metrics Bottom Row */
    .sub-metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
      margin-top: 1.5rem;
    }
    .sub-metric-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem 1.25rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .sub-metric-label {
      font-size: 0.7rem;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .sub-metric-val {
      font-size: 1.45rem;
      font-weight: 800;
      color: var(--text-main);
      margin: 0.2rem 0;
    }
    .sub-metric-sub {
      font-size: 0.72rem;
      color: var(--text-muted);
    }
    .sub-metric-icon-box {
      width: 36px;
      height: 36px;
      border-radius: 8px;
      background: var(--card-inner);
      border: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-muted);
    }

    /* Tasks Search & Filter Bar */
    .tasks-filter-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 1rem;
      flex-wrap: wrap;
    }
    .search-input-wrap {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.55rem 0.85rem;
      flex: 1;
      min-width: 240px;
    }
    .search-input-wrap svg { color: var(--text-muted); }
    .search-input-wrap input {
      background: transparent;
      border: none;
      outline: none;
      color: var(--text-main);
      font-size: 0.85rem;
      font-family: inherit;
      width: 100%;
    }
    .search-input-wrap input::placeholder { color: var(--text-muted); }
    .filter-chips-group {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      flex-wrap: wrap;
    }
    .filter-chip {
      background: var(--card-bg);
      border: 1px solid var(--border);
      color: var(--text-muted);
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.45rem 0.8rem;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .filter-chip:hover {
      background: var(--btn-hover);
      color: var(--text-main);
    }
    .filter-chip.active {
      background: var(--card-inner);
      border-color: var(--accent-blue);
      color: var(--accent-blue);
      font-weight: 700;
    }

    /* Terminal / Logs UI */
    .terminal-box {
      background: #000000;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.25rem;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.82rem;
      line-height: 1.6;
      max-height: 520px;
      overflow-y: auto;
      box-shadow: inset 0 2px 10px rgba(0,0,0,0.5);
    }
    .log-line { margin-bottom: 0.35rem; word-break: break-all; }
    .log-time { color: var(--text-muted); }
    .log-type-inbox { color: var(--accent-green); font-weight: 600; }
    .log-type-hunt { color: var(--accent-purple); font-weight: 600; }
    .log-type-solve { color: var(--accent-blue); font-weight: 600; }
    .log-type-system { color: var(--accent-yellow); font-weight: 600; }

    /* Form Controls */
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
      margin-bottom: 1.35rem;
    }
    .form-label {
      font-size: 0.82rem;
      font-weight: 700;
      color: var(--text-main);
    }
    .form-control {
      background: var(--card-inner);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text-main);
      padding: 0.75rem 1rem;
      font-size: 0.875rem;
      font-family: inherit;
      outline: none;
      transition: border-color 0.15s ease;
      width: 100%;
    }
    .form-control:focus {
      border-color: var(--accent-blue);
    }

    /* Modal Overlay & Accessible Dialog */
    .modal-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.65);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 2000;
      padding: 1rem;
    }
    .modal-overlay.open {
      display: flex;
    }
    .modal-box {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      width: 100%;
      max-width: 680px;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      box-shadow: var(--shadow);
      animation: modalPop 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }
    @keyframes modalPop {
      from { transform: scale(0.96); opacity: 0; }
      to { transform: scale(1); opacity: 1; }
    }
    .modal-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 1.25rem 1.5rem;
      border-bottom: 1px solid var(--border);
    }
    .modal-head h3 {
      font-size: 1.1rem;
      font-weight: 700;
      color: var(--text-main);
      word-break: break-all;
    }
    .close-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 1.5rem;
      cursor: pointer;
      line-height: 1;
      padding: 0.25rem;
      border-radius: 4px;
    }
    .close-btn:hover { color: var(--text-main); }
    .modal-body {
      padding: 1.5rem;
      overflow-y: auto;
    }
    .modal-body pre {
      background: var(--card-inner);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8rem;
      color: var(--text-main);
      overflow-x: auto;
      white-space: pre-wrap;
    }

    /* Toast Notification System */
    .toast-container {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 3000;
      display: flex;
      flex-direction: column;
      gap: 10px;
      pointer-events: none;
    }
    .toast {
      pointer-events: auto;
      padding: 12px 18px;
      border-radius: 8px;
      font-size: 0.875rem;
      font-weight: 600;
      color: #ffffff;
      box-shadow: 0 4px 16px rgba(0,0,0,0.35);
      display: flex;
      align-items: center;
      gap: 8px;
      animation: toastIn 0.25s cubic-bezier(0.4, 0, 0.2, 1);
      transition: opacity 0.3s ease, transform 0.3s ease;
    }
    .toast-success { background: #238636; border: 1px solid #2ea043; }
    .toast-info { background: #1f6feb; border: 1px solid #388bfd; }
    .toast-warning { background: #9e6a03; border: 1px solid #bb8009; }
    .toast-error { background: #da3633; border: 1px solid #f85149; }
    @keyframes toastIn {
      from { transform: translateY(12px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }

    /* Chips */
    .chip-container { display: flex; flex-wrap: wrap; gap: 0.5rem; }
    .chip {
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.3rem 0.65rem;
      border-radius: 20px;
      background: var(--card-inner);
      border: 1px solid var(--border);
      color: var(--text-main);
    }

    /* ==========================================================================
       RESPONSIVE BREAKPOINTS (Desktop, Tablet, Mobile)
       ========================================================================== */
    @media (max-width: 1024px) {
      main {
        padding: 1.75rem 1.75rem;
      }
      .grid-4 {
        grid-template-columns: repeat(2, 1fr);
      }
      .sub-metric-grid {
        grid-template-columns: repeat(2, 1fr);
      }
    }

    @media (max-width: 768px) {
      body {
        flex-direction: column;
      }
      .mobile-top-bar {
        display: flex;
      }
      aside {
        position: fixed;
        left: 0;
        top: 0;
        bottom: 0;
        width: 280px;
        min-width: 280px;
        height: 100vh;
        transform: translateX(-100%);
        box-shadow: 4px 0 24px rgba(0,0,0,0.5);
      }
      aside.mobile-open {
        transform: translateX(0);
      }
      .sidebar-close-btn {
        display: block;
      }
      main {
        margin-left: 0;
        padding: 1.25rem 1rem;
        width: 100%;
      }
      header.top-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 1rem;
      }
      .top-status-badge {
        align-items: flex-start;
        width: 100%;
      }
      .grid-4, .sub-metric-grid, .workers-row {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 480px) {
      .header-titles h1 {
        font-size: 1.35rem;
      }
      .tasks-filter-bar {
        flex-direction: column;
        align-items: stretch;
      }
      .search-input-wrap {
        width: 100%;
      }
    }
  </style>
</head>
<body>

  <!-- Mobile Drawer Backdrop -->
  <div class="sidebar-backdrop" id="sidebar-backdrop" onclick="toggleMobileSidebar()"></div>

  <!-- Mobile Top Bar -->
  <div class="mobile-top-bar">
    <div style="display: flex; align-items: center; gap: 0.75rem;">
      <button class="menu-toggle-btn" id="menu-toggle" onclick="toggleMobileSidebar()" aria-label="Toggle navigation menu">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
      <span style="font-weight: 800; font-size: 0.95rem; color: var(--text-main);">Autonomous GitHub Agent</span>
    </div>
    <div>
      <span class="cat-badge" id="mobile-mode-pill" style="color: var(--accent-green);">DRY-RUN</span>
    </div>
  </div>

  <!-- Left Sidebar -->
  <aside id="sidebar">
    <div>
      <div class="brand">
        <div class="brand-left">
          <div class="brand-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="11" width="18" height="10" rx="2"></rect>
              <circle cx="12" cy="5" r="2"></circle>
              <path d="M12 7v4"></path>
              <line x1="8" y1="16" x2="8" y2="16"></line>
              <line x1="16" y1="16" x2="16" y2="16"></line>
            </svg>
          </div>
          <div class="brand-text">
            <h2>Autonomous</h2>
            <p>GitHub Agent</p>
          </div>
        </div>
        <button class="sidebar-close-btn" onclick="toggleMobileSidebar()" aria-label="Close navigation">&times;</button>
      </div>

      <nav aria-label="Dashboard navigation">
        <a class="nav-item active" id="nav-dashboard" onclick="switchTab('dashboard')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          Dashboard
        </a>
        <a class="nav-item" id="nav-tasks" onclick="switchTab('tasks')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          Live Tasks
        </a>
        <a class="nav-item" id="nav-workers" onclick="switchTab('workers')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          Workers
        </a>
        <a class="nav-item" id="nav-repos" onclick="switchTab('repos')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"/><path d="M6 6h10"/><path d="M6 10h10"/></svg>
          Repositories
        </a>
        <a class="nav-item" id="nav-reports" onclick="switchTab('reports')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
          Reports
        </a>
        <a class="nav-item" id="nav-settings" onclick="switchTab('settings')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
          Settings
        </a>
        <a class="nav-item" id="nav-logs" onclick="switchTab('logs')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
          Logs
        </a>

        <!-- Premium Segmented Theme Switcher (Directly below Logs) -->
        <div class="theme-nav-section">
          <div class="theme-segmented-bar" role="group" aria-label="Theme mode switcher">
            <button type="button" class="theme-pill-btn active" id="theme-btn-dark" onclick="setTheme('dark')" aria-label="Switch to Dark Theme">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
              </svg>
              <span>Dark</span>
            </button>
            <button type="button" class="theme-pill-btn" id="theme-btn-light" onclick="setTheme('light')" aria-label="Switch to Light Theme">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="5"/>
                <line x1="12" y1="1" x2="12" y2="3"/>
                <line x1="12" y1="21" x2="12" y2="23"/>
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
                <line x1="1" y1="12" x2="3" y2="12"/>
                <line x1="21" y1="12" x2="23" y2="12"/>
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
              </svg>
              <span>Light</span>
            </button>
          </div>
        </div>
      </nav>
    </div>

    <!-- Sidebar Footer -->
    <div class="sidebar-footer">
      <div class="health-card">
        <div class="health-header">
          <span>System Health</span>
          <span class="val">100%</span>
        </div>
        <svg class="sparkline-svg" viewBox="0 0 200 40" preserveAspectRatio="none">
          <defs>
            <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="var(--accent-green)" stop-opacity="0.35"/>
              <stop offset="100%" stop-color="var(--accent-green)" stop-opacity="0.0"/>
            </linearGradient>
          </defs>
          <path d="M 0,26 C 20,24 35,16 55,20 C 75,24 90,14 110,18 C 130,22 145,10 165,14 C 180,18 190,22 200,20 L 200,40 L 0,40 Z" fill="url(#sparkGrad)"/>
          <path d="M 0,26 C 20,24 35,16 55,20 C 75,24 90,14 110,18 C 130,22 145,10 165,14 C 180,18 190,22 200,20" fill="none" stroke="var(--accent-green)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <div class="health-status">
          <span class="status-dot-sm"></span>
          <span>All systems operational</span>
        </div>
      </div>

      <div class="user-card">
        <div class="user-avatar">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
        </div>
        <div class="user-info">
          <div class="user-name-row">
            <span class="user-name" id="side-gh-user">@satiricalguru</span>
            <span class="badge-owner">OWNER</span>
          </div>
          <div class="user-role">GitHub Account</div>
        </div>
      </div>
    </div>
  </aside>

  <!-- Main Content Area -->
  <main id="main-view">

    <!-- TAB 1: DASHBOARD (Overview) -->
    <div class="tab-content active" id="tab-dashboard">
      <header class="top-header">
        <div class="header-titles">
          <h1>Autonomous GitHub Agent</h1>
          <p>Real-Time AI Telemetry, Verified Bug Hunter &amp; PR Solver</p>
        </div>
        <div class="top-status-badge">
          <div class="top-status-row">
            <div class="pulse-dot"></div>
            <span id="top-agent-state">RUNNING</span>
          </div>
          <div class="top-status-sub">Agent is active and operational</div>
        </div>
      </header>

      <!-- Top 4 Metrics -->
      <div class="grid-4">
        <!-- Active AI Model -->
        <div class="metric-card">
          <div>
            <div class="metric-label">Active AI Model</div>
            <div class="metric-val-row">
              <span class="metric-val" id="card-ai-model">GEMINI-3.8-FLASH</span>
              <span class="pill-tag" style="background: rgba(188, 140, 255, 0.15); color: #bc8cff; border-color: rgba(188, 140, 255, 0.3);">ACTIVE</span>
            </div>
            <div class="metric-sub" id="card-ai-sub">Antigravity Heuristic Engine</div>
          </div>
          <span class="pill-tag card-corner-badge" id="card-ai-badge">v3.8</span>
        </div>

        <!-- GitHub Account -->
        <div class="metric-card">
          <div>
            <div class="metric-label">GitHub Account</div>
            <div class="metric-val-row">
              <span class="metric-val" id="card-gh-account">@satiricalguru</span>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" style="color: var(--accent-blue);"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
            </div>
            <div class="metric-sub" style="color: var(--text-muted);">Authenticated &amp; Keys Active</div>
          </div>
          <div class="card-corner-badge">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" style="color: var(--text-muted);"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
          </div>
        </div>

        <!-- Operational Mode -->
        <div class="metric-card">
          <div>
            <div class="metric-label">Operational Mode</div>
            <div class="metric-val-row">
              <span class="metric-val" id="card-op-mode">DRY-RUN (Safe)</span>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent-green);"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </div>
            <div class="metric-sub" id="card-op-sub">Simulating safe writes</div>
          </div>
          <button class="btn-action-sm card-corner-badge" onclick="toggleDryRunMode()">Change Mode</button>
        </div>

        <!-- Rate Limit -->
        <div class="metric-card">
          <div>
            <div class="metric-label">API Rate Limit Remaining</div>
            <div class="metric-val-row">
              <span class="metric-val" id="card-rate-limit">5000 / 5000</span>
            </div>
            <div class="progress-bar-container">
              <div class="progress-bar-fill" id="rate-fill"></div>
            </div>
            <div class="metric-sub" id="card-rate-sub">Quota Health: 100%</div>
          </div>
        </div>
      </div>

      <!-- Workers Section -->
      <div class="section-header-row">
        <div class="section-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          Real-Time Autonomous Workers
        </div>
        <button class="btn-action-sm" onclick="switchTab('workers')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>
          Manage Workers
        </button>
      </div>

      <div class="workers-row">
        <!-- Worker 1: Inbox -->
        <div class="worker-card">
          <div class="worker-head">
            <div class="worker-name-group">
              <div class="worker-icon-box">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
              </div>
              <div class="worker-title">Inbox &amp; Mention Manager</div>
            </div>
            <div class="worker-pill">
              <span class="worker-pill-dot" style="background: var(--accent-green);"></span>
              <span id="inbox-status-pill">IDLE</span>
            </div>
          </div>
          <div class="worker-body">
            <div class="worker-activity-label">Current Activity</div>
            <div class="worker-activity-text" id="inbox-activity-text">Waiting for worker cycle...</div>
          </div>
          <div class="worker-footer" id="inbox-footer-meta">
            Processed: 0 notifications | Last check: None
          </div>
        </div>

        <!-- Worker 2: Hunter -->
        <div class="worker-card">
          <div class="worker-head">
            <div class="worker-name-group">
              <div class="worker-icon-box">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              </div>
              <div class="worker-title">Issue Hunter &amp; PR Solver</div>
            </div>
            <div class="worker-pill">
              <span class="worker-pill-dot" style="background: var(--accent-purple);"></span>
              <span id="hunter-status-pill">HUNTING</span>
            </div>
          </div>
          <div class="worker-body">
            <div class="worker-activity-label">Current Activity</div>
            <div class="worker-activity-text" id="hunter-activity-text">Searching repositories...</div>
          </div>
          <div class="worker-footer" id="hunter-footer-meta">
            Current step: Querying | Last check: None
          </div>
        </div>
      </div>

      <!-- Live Stream Table -->
      <div class="section-header-row">
        <div class="section-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
          Live &amp; Completed Tasks Stream
        </div>
        <button class="btn-action-sm" onclick="switchTab('tasks')">View All Tasks &rsaquo;</button>
      </div>

      <div class="table-responsive-wrap">
        <table class="tasks-table">
          <thead>
            <tr>
              <th>Task ID</th>
              <th>Category</th>
              <th>Task Description / Repository</th>
              <th>Status</th>
              <th>Completed At</th>
              <th>Outcome</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="tasks-tbody">
            <!-- Populated via JS -->
          </tbody>
        </table>
      </div>

      <!-- Bottom Sub-metrics (Dynamic Live Calculations) -->
      <div class="sub-metric-grid">
        <div class="sub-metric-card">
          <div>
            <div class="sub-metric-label">Total Tasks</div>
            <div class="sub-metric-val" id="metric-total">0</div>
            <div class="sub-metric-sub">All time executed</div>
          </div>
          <div class="sub-metric-icon-box">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 4v4"/><path d="M2 8h20"/></svg>
          </div>
        </div>

        <div class="sub-metric-card">
          <div>
            <div class="sub-metric-label">Completed</div>
            <div class="sub-metric-val" id="metric-completed">0</div>
            <div class="sub-metric-sub" id="metric-success-rate">100.0% success rate</div>
          </div>
          <div class="sub-metric-icon-box">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          </div>
        </div>

        <div class="sub-metric-card">
          <div>
            <div class="sub-metric-label">In Progress</div>
            <div class="sub-metric-val" id="metric-running">0</div>
            <div class="sub-metric-sub">Currently running</div>
          </div>
          <div class="sub-metric-icon-box">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          </div>
        </div>

        <div class="sub-metric-card">
          <div>
            <div class="sub-metric-label">Failed</div>
            <div class="sub-metric-val" id="metric-failed">0</div>
            <div class="sub-metric-sub" id="metric-fail-rate">0.0% failure rate</div>
          </div>
          <div class="sub-metric-icon-box">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
          </div>
        </div>

        <div class="sub-metric-card">
          <div>
            <div class="sub-metric-label">Avg. Execution Time</div>
            <div class="sub-metric-val" id="metric-avg-time">--</div>
            <div class="sub-metric-sub">Per task duration</div>
          </div>
          <div class="sub-metric-icon-box">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 2: LIVE TASKS -->
    <div class="tab-content" id="tab-tasks">
      <header class="top-header">
        <div class="header-titles">
          <h1>⚡ Task Execution Explorer</h1>
          <p>Real-time audit log of triage events, automated bug investigations, and Pull Requests</p>
        </div>
        <div style="display: flex; gap: 0.75rem; flex-wrap: wrap;">
          <button class="btn-action-sm" onclick="triggerAction('/api/trigger-inbox')">📥 Run Inbox Triage</button>
          <button class="btn-action-sm" onclick="triggerAction('/api/trigger-hunt')">🔍 Run Issue Hunt</button>
        </div>
      </header>

      <!-- Tasks Filter Toolbar -->
      <div class="tasks-filter-bar">
        <div class="search-input-wrap">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="text" id="tasks-search" placeholder="Search tasks by ID, repo, title, outcome..." oninput="filterAndRenderTasks()">
        </div>
        <div class="filter-chips-group">
          <button class="filter-chip active" data-filter="ALL" onclick="setCategoryFilter('ALL')">All Categories</button>
          <button class="filter-chip" data-filter="INBOX" onclick="setCategoryFilter('INBOX')">📥 Inbox</button>
          <button class="filter-chip" data-filter="HUNT" onclick="setCategoryFilter('HUNT')">🔍 Hunt</button>
          <button class="filter-chip" data-filter="SOLVE" onclick="setCategoryFilter('SOLVE')">🛠️ Solve</button>
        </div>
      </div>

      <div class="table-responsive-wrap">
        <table class="tasks-table">
          <thead>
            <tr>
              <th>Task ID</th>
              <th>Category</th>
              <th>Task Description / Repository</th>
              <th>Status</th>
              <th>Completed At</th>
              <th>Outcome</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="all-tasks-tbody">
            <!-- Full tasks populated here -->
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 3: WORKERS -->
    <div class="tab-content" id="tab-workers">
      <header class="top-header">
        <div class="header-titles">
          <h1>👥 Autonomous Worker Orchestration</h1>
          <p>Multi-threaded background loops and task scheduling engine</p>
        </div>
        <button class="btn-action-sm" onclick="toggleDryRunMode()">Toggle DRY-RUN / LIVE</button>
      </header>

      <div class="workers-row">
        <!-- Worker Details 1 -->
        <div class="worker-card">
          <div class="worker-head">
            <div class="worker-name-group">
              <div class="worker-icon-box">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
              </div>
              <div class="worker-title">Inbox &amp; Notification Worker</div>
            </div>
            <div class="worker-pill">
              <span class="worker-pill-dot" style="background: var(--accent-green);"></span>
              <span>POLLING (60s)</span>
            </div>
          </div>
          <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1rem;">
            Monitors GitHub notification streams, mentions, review requests, and issue discussions. Applies AI reasoning to determine if technical reply or action is required.
          </p>
          <div style="display: flex; gap: 0.75rem; margin-top: 1rem;">
            <button class="btn-action-sm" onclick="triggerAction('/api/trigger-inbox')">Execute Immediate Poll</button>
          </div>
        </div>

        <!-- Worker Details 2 -->
        <div class="worker-card">
          <div class="worker-head">
            <div class="worker-name-group">
              <div class="worker-icon-box">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              </div>
              <div class="worker-title">Issue Hunter &amp; Solver Worker</div>
            </div>
            <div class="worker-pill">
              <span class="worker-pill-dot" style="background: var(--accent-purple);"></span>
              <span>SCANNING (300s)</span>
            </div>
          </div>
          <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1rem;">
            Scans top-tier open-source repositories for unassigned bug issues across Python, TypeScript, Go, and Rust. Clones sandboxed repos, runs test suites, and drafts verified PRs.
          </p>
          <div style="display: flex; gap: 0.75rem; margin-top: 1rem;">
            <button class="btn-action-sm" onclick="triggerAction('/api/trigger-hunt')">Execute Immediate Hunt</button>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 4: REPOSITORIES -->
    <div class="tab-content" id="tab-repos">
      <header class="top-header">
        <div class="header-titles">
          <h1>📁 Monitored Repositories &amp; Targets</h1>
          <p>Language filters, search query parameters, and target criteria</p>
        </div>
      </header>

      <div class="grid-4" style="margin-bottom: 2rem;">
        <div class="metric-card">
          <div class="metric-label">Target Languages</div>
          <div class="chip-container" style="margin-top: 0.5rem;">
            <span class="chip">🐍 Python</span>
            <span class="chip">⚡ TypeScript</span>
            <span class="chip">🟨 JavaScript</span>
            <span class="chip">🔵 Go</span>
            <span class="chip">🦀 Rust</span>
          </div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Target Labels</div>
          <div class="chip-container" style="margin-top: 0.5rem;">
            <span class="chip">🏷️ good first issue</span>
            <span class="chip">🏷️ help wanted</span>
            <span class="chip">🏷️ bug</span>
          </div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Max PRs / Day</div>
          <div class="metric-val" style="font-size: 1.5rem; margin-top: 0.5rem;">5 PRs</div>
          <div class="metric-sub">Anti-Spam Daily Cap</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Sandbox Directory</div>
          <div class="metric-val" style="font-size: 0.9rem; margin-top: 0.5rem;">scratch/repos/</div>
          <div class="metric-sub">Isolated local clones</div>
        </div>
      </div>

      <!-- Active Search Query Section -->
      <div class="card" style="background: var(--card-bg); border: 1px solid var(--border); border-radius: 16px; padding: 1.75rem;">
        <h3 style="font-size: 1.05rem; font-weight: 700; margin-bottom: 0.75rem; color: var(--text-main);">Current Search Query Filters</h3>
        <div style="background: var(--card-inner); border: 1px solid var(--border); padding: 0.85rem 1.25rem; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: var(--accent-blue); margin-bottom: 1rem; word-break: break-all;">
          is:issue is:open no:assignee language:&lt;lang&gt; stars:&gt;=1000 label:"good first issue","help wanted","bug"
        </div>
        <p style="font-size: 0.85rem; color: var(--text-muted); line-height: 1.6;">
          The Autonomous Issue Hunter scans GitHub API for open, unassigned bug issues in high-star repositories. When found, it creates local sandboxes in <code>scratch/repos/</code>, reproduces bugs, synthesizes minimal code fixes, and executes local automated tests prior to submitting any PR.
        </p>
      </div>
    </div>

    <!-- TAB 5: REPORTS -->
    <div class="tab-content" id="tab-reports">
      <header class="top-header">
        <div class="header-titles">
          <h1>📊 Performance &amp; Execution Reports</h1>
          <p>PR creation velocity, triage resolution rates, and model accuracy breakdown</p>
        </div>
      </header>

      <div class="grid-4" style="margin-bottom: 2rem;">
        <div class="metric-card">
          <div class="metric-label">Triage Resolution Rate</div>
          <div class="metric-val" style="color: var(--accent-green);" id="report-triage-rate">100.0%</div>
          <div class="metric-sub" id="report-triage-sub">Live verified triage</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Test Pass Rate</div>
          <div class="metric-val" style="color: var(--accent-blue);" id="report-pass-rate">100.0%</div>
          <div class="metric-sub">Local test suite verification</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Active Model Latency</div>
          <div class="metric-val" id="report-model-lat">~1.2s</div>
          <div class="metric-sub" id="report-model-sub">Gemini 3.8 Flash inference</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">API Quota Remaining</div>
          <div class="metric-val" style="color: var(--accent-cyan);" id="report-quota-val">100%</div>
          <div class="metric-sub" id="report-quota-sub">5,000 / 5,000 quota</div>
        </div>
      </div>

      <div class="card" style="background: var(--card-bg); border: 1px solid var(--border); border-radius: 16px; padding: 1.75rem;">
        <h3 style="font-size: 1.05rem; font-weight: 700; margin-bottom: 1.25rem; color: var(--text-main);">Execution Distribution by Category</h3>
        <div id="reports-category-breakdown" style="display: flex; flex-direction: column; gap: 1rem;">
          <!-- Populated via JS -->
        </div>
      </div>
    </div>

    <!-- TAB 6: SETTINGS -->
    <div class="tab-content" id="tab-settings">
      <header class="top-header">
        <div class="header-titles">
          <h1>⚙️ Agent Configuration &amp; Safety Rules</h1>
          <p>Runtime parameters, AI model selector, and safety constraints</p>
        </div>
      </header>

      <div class="card" style="background: var(--card-bg); border: 1px solid var(--border); border-radius: 16px; padding: 1.75rem; max-width: 800px;">
        <div class="form-group">
          <label class="form-label" for="setting-model">Active AI Reasoning Model</label>
          <select class="form-control" id="setting-model" style="font-weight: 600;">
            <option value="gemini-3.8-flash" selected>Google Gemini 3.8 Flash (High Reasoning - Antigravity)</option>
            <option value="gemini-3.7-flash">Google Gemini 3.7 Flash (High Reasoning)</option>
            <option value="gemini-2.5-flash">Google Gemini 2.5 Flash</option>
            <option value="gemini-2.5-pro">Google Gemini 2.5 Pro</option>
          </select>
        </div>

        <div class="form-group">
          <label class="form-label" for="setting-dryrun">Operational Mode</label>
          <select class="form-control" id="setting-dryrun">
            <option value="true" selected>DRY-RUN Mode (Safe simulation, no live writes)</option>
            <option value="false">LIVE Mode (Submits Pull Requests &amp; Issue Comments)</option>
          </select>
        </div>

        <div class="form-group">
          <label class="form-label" for="setting-inbox-int">Inbox Polling Interval (Seconds)</label>
          <input type="number" class="form-control" id="setting-inbox-int" value="60" min="15" max="3600">
        </div>

        <div class="form-group">
          <label class="form-label" for="setting-hunt-int">Issue Hunter Interval (Seconds)</label>
          <input type="number" class="form-control" id="setting-hunt-int" value="300" min="30" max="7200">
        </div>

        <button class="btn-action-sm" style="padding: 0.75rem 1.5rem; background: var(--accent-blue); color: #fff; border: none; font-size: 0.85rem; cursor: pointer;" onclick="saveSettings()">Save Configuration</button>
      </div>
    </div>

    <!-- TAB 7: LOGS -->
    <div class="tab-content" id="tab-logs">
      <header class="top-header">
        <div class="header-titles">
          <h1>📄 Live Agent Logs Stream</h1>
          <p>Real-time execution telemetry and event logs</p>
        </div>
        <button class="btn-action-sm" onclick="clearLogsUI()">Clear View</button>
      </header>

      <div class="terminal-box" id="log-terminal-box">
        <div class="log-line"><span class="log-time">[System]</span> <span class="log-type-system">[READY]</span> Live log stream active. Listening for events...</div>
      </div>
    </div>

  </main>

  <!-- Accessible Task Detail Modal -->
  <div class="modal-overlay" id="task-modal" role="dialog" aria-modal="true" aria-labelledby="modal-task-title" onclick="closeModal(event, 'task-modal')">
    <div class="modal-box" onclick="event.stopPropagation()">
      <div class="modal-head">
        <h3 id="modal-task-title">Task Details</h3>
        <button class="close-btn" aria-label="Close modal" onclick="closeModalById('task-modal')">&times;</button>
      </div>
      <div class="modal-body">
        <div style="margin-bottom: 1rem;" id="modal-task-meta"></div>
        <div style="font-size: 0.85rem; font-weight: 700; margin-bottom: 0.5rem; text-transform: uppercase; color: var(--text-muted);">AI Reasoning &amp; Execution Payload</div>
        <pre id="modal-task-json">Loading...</pre>
      </div>
    </div>
  </div>

  <!-- Toast Notification Container -->
  <div id="toast-container" class="toast-container"></div>

  <script>
    let globalData = null;
    let currentCategoryFilter = 'ALL';
    let currentSearchTerm = '';

    // Mobile Sidebar Drawer
    function toggleMobileSidebar() {
      const sidebar = document.getElementById('sidebar');
      const backdrop = document.getElementById('sidebar-backdrop');
      if (sidebar) sidebar.classList.toggle('mobile-open');
      if (backdrop) backdrop.classList.toggle('active');
    }
    function closeMobileSidebar() {
      const sidebar = document.getElementById('sidebar');
      const backdrop = document.getElementById('sidebar-backdrop');
      if (sidebar) sidebar.classList.remove('mobile-open');
      if (backdrop) backdrop.classList.remove('active');
    }

    // Toast Notifications
    function showToast(message, type = 'info') {
      const container = document.getElementById('toast-container');
      if (!container) return;
      const toast = document.createElement('div');
      toast.className = `toast toast-${type}`;
      toast.textContent = message;
      container.appendChild(toast);
      setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(12px)';
        setTimeout(() => toast.remove(), 300);
      }, 3500);
    }

    // Modal helpers
    function closeModalById(id) {
      const el = document.getElementById(id);
      if (el) el.classList.remove('open');
    }
    function closeModal(e, modalId) {
      if (e.target.id === modalId) {
        closeModalById(modalId);
      }
    }
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeModalById('task-modal');
        closeMobileSidebar();
      }
    });

    // Navigation Switcher
    function switchTab(tabId) {
      document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
      const activeNav = document.getElementById('nav-' + tabId);
      if (activeNav) activeNav.classList.add('active');

      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      const targetTab = document.getElementById('tab-' + tabId);
      if (targetTab) {
        targetTab.classList.add('active');
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }

      closeMobileSidebar();
      localStorage.setItem('active_tab', tabId);
    }

    // Theme Switcher
    function setTheme(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('theme', theme);
      const isDark = theme === 'dark';
      
      const darkBtn = document.getElementById('theme-btn-dark');
      const lightBtn = document.getElementById('theme-btn-light');
      if (darkBtn) darkBtn.classList.toggle('active', isDark);
      if (lightBtn) lightBtn.classList.toggle('active', !isDark);
    }

    function toggleTheme() {
      const current = document.documentElement.getAttribute('data-theme');
      setTheme(current === 'light' ? 'dark' : 'light');
    }

    const savedTheme = localStorage.getItem('theme') || 'dark';
    setTheme(savedTheme);

    const savedTab = localStorage.getItem('active_tab') || 'dashboard';
    switchTab(savedTab);

    // Inspect Task in Modal
    function inspectTask(taskObj) {
      document.getElementById('modal-task-title').textContent = `${taskObj.id}: ${taskObj.title}`;
      document.getElementById('modal-task-meta').innerHTML = `
        <div style="display: flex; gap: 0.5rem; margin-bottom: 0.5rem; flex-wrap: wrap;">
          <span class="cat-badge">${taskObj.category}</span>
          <span class="cat-badge" style="color: var(--accent-green);">● ${taskObj.status}</span>
          <span style="font-size: 0.8rem; color: var(--text-muted); font-family: monospace;">${taskObj.completed_at || taskObj.started_at || 'Recently'}</span>
        </div>
        <div style="font-size: 0.9rem; margin-bottom: 0.35rem;"><strong>Target Repository:</strong> ${taskObj.target_repo || 'N/A'}</div>
        <div style="font-size: 0.9rem;"><strong>Outcome:</strong> ${taskObj.outcome || 'Success'}</div>
      `;
      document.getElementById('modal-task-json').textContent = JSON.stringify(taskObj, null, 2);
      document.getElementById('task-modal').classList.add('open');
    }

    // Tasks search and filter
    function setCategoryFilter(cat) {
      currentCategoryFilter = cat;
      document.querySelectorAll('.filter-chip').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-filter') === cat);
      });
      filterAndRenderTasks();
    }

    function filterAndRenderTasks() {
      const searchInput = document.getElementById('tasks-search');
      currentSearchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';

      if (!globalData || !globalData.tasks) return;
      let filtered = globalData.tasks;
      if (currentCategoryFilter !== 'ALL') {
        filtered = filtered.filter(t => (t.category || '').toUpperCase() === currentCategoryFilter);
      }
      if (currentSearchTerm) {
        filtered = filtered.filter(t => {
          const str = `${t.id} ${t.category} ${t.title} ${t.target_repo} ${t.status} ${t.outcome}`.toLowerCase();
          return str.includes(currentSearchTerm);
        });
      }

      const tbody = document.getElementById('all-tasks-tbody');
      if (tbody) {
        if (filtered.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-dim); padding: 2.5rem;">No tasks matching current search filter.</td></tr>';
        } else {
          tbody.innerHTML = filtered.map(renderRow).join('');
        }
      }
    }

    const renderRow = (t) => {
      const timeDisplay = t.completed_at ? t.completed_at.split(' ')[1] : (t.started_at ? t.started_at.split(' ')[1] : '--:--:--');
      const repoStr = t.target_repo && t.target_repo !== 'N/A' ? `[${t.target_repo}] ` : '';
      const safeJSON = JSON.stringify(t).replace(/"/g, '&quot;');
      return `
        <tr role="button" tabindex="0" onclick='inspectTask(${JSON.stringify(t)})' onkeydown='if(event.key==="Enter"||event.key===" "){event.preventDefault();inspectTask(${safeJSON});}'>
          <td class="task-id-cell">${t.id}</td>
          <td><span class="cat-badge">${t.category}</span></td>
          <td><strong>${repoStr}</strong>${t.title}</td>
          <td><div class="status-cell"><span>●</span> ${t.status}</div></td>
          <td class="time-cell">${timeDisplay}</td>
          <td style="color: var(--text-muted); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${t.outcome || 'Finished'}</td>
          <td style="text-align: right;"><span class="arrow-btn">&rsaquo;</span></td>
        </tr>
      `;
    };

    // Actions & API Triggers
    async function triggerAction(endpoint) {
      try {
        showToast("Triggering autonomous worker cycle...", "info");
        const res = await fetch(endpoint, { method: 'POST' });
        if (res.ok) {
          showToast("Worker cycle dispatched successfully!", "success");
          updateDashboard();
        } else {
          showToast("Failed to trigger worker action", "error");
        }
      } catch (e) {
        showToast("Action request error: " + e.message, "error");
        console.error("Action error:", e);
      }
    }

    async function toggleDryRunMode() {
      try {
        const res = await fetch('/api/toggle-mode', { method: 'POST' });
        const data = await res.json();
        const modeLabel = data.dry_run ? 'DRY-RUN (Safe)' : 'LIVE (Active)';
        showToast(`Operational mode toggled to: ${modeLabel}`, "success");
        updateDashboard();
      } catch (e) {
        showToast("Mode toggle failed", "error");
        console.error("Toggle error:", e);
      }
    }

    function clearLogsUI() {
      const box = document.getElementById('log-terminal-box');
      if (box) box.innerHTML = '<div class="log-line" style="color: var(--text-muted);">Logs cleared. Listening for new events...</div>';
      showToast("Log view cleared", "info");
    }

    async function saveSettings() {
      const model = document.getElementById('setting-model').value;
      const dryrun = document.getElementById('setting-dryrun').value === 'true';
      const inboxInt = parseInt(document.getElementById('setting-inbox-int').value, 10);
      const huntInt = parseInt(document.getElementById('setting-hunt-int').value, 10);

      try {
        const res = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model_name: model,
            dry_run: dryrun,
            inbox_poll_interval: inboxInt,
            issue_hunt_interval: huntInt
          })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast("Configuration saved and applied!", "success");
          updateDashboard();
        } else {
          showToast("Failed to save configuration: " + (data.error || "Unknown error"), "error");
        }
      } catch (e) {
        showToast("Error communicating with settings API", "error");
        console.error(e);
      }
    }

    async function updateDashboard() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();
        globalData = data;

        // Header & Core State
        document.getElementById('top-agent-state').textContent = data.overall_status || 'RUNNING';
        document.getElementById('side-gh-user').textContent = '@' + (data.github_user || 'satiricalguru');
        document.getElementById('card-gh-account').textContent = '@' + (data.github_user || 'satiricalguru');

        // Dynamic AI Model Detection
        const activeModelName = (data.active_model || 'gemini-3.8-flash').toUpperCase();
        document.getElementById('card-ai-model').textContent = activeModelName;
        document.getElementById('card-ai-sub').textContent = data.model_display_name || data.ai_mode || 'Antigravity Heuristic Engine';
        const badgeEl = document.getElementById('card-ai-badge');
        if (badgeEl) {
          badgeEl.textContent = activeModelName.includes('3.8') ? 'v3.8' : (activeModelName.includes('3.7') ? 'v3.7' : 'v2.5');
        }

        // Operational Mode
        const isDry = data.dry_run !== undefined ? data.dry_run : true;
        document.getElementById('card-op-mode').textContent = isDry ? 'DRY-RUN (Safe)' : 'LIVE (Active)';
        const mobPill = document.getElementById('mobile-mode-pill');
        if (mobPill) {
          mobPill.textContent = isDry ? 'DRY-RUN' : 'LIVE';
          mobPill.style.color = isDry ? 'var(--accent-green)' : 'var(--accent-red)';
        }

        // Rate limit progress bar
        const rateRem = data.rate_limit_remaining || 5000;
        const rateLim = data.rate_limit_limit || 5000;
        const ratePercent = Math.round((rateRem / rateLim) * 100);
        document.getElementById('card-rate-limit').textContent = `${rateRem} / ${rateLim}`;
        document.getElementById('rate-fill').style.width = `${ratePercent}%`;
        document.getElementById('card-rate-sub').textContent = `Quota Health: ${ratePercent}%`;

        // Sync Settings Inputs
        const modelSel = document.getElementById('setting-model');
        if (modelSel && !modelSel.matches(':focus')) {
          modelSel.value = data.active_model || 'gemini-3.8-flash';
        }
        const drySel = document.getElementById('setting-dryrun');
        if (drySel && !drySel.matches(':focus')) {
          drySel.value = isDry ? "true" : "false";
        }
        const inboxInp = document.getElementById('setting-inbox-int');
        if (inboxInp && !inboxInp.matches(':focus') && data.inbox_poll_interval) {
          inboxInp.value = data.inbox_poll_interval;
        }
        const huntInp = document.getElementById('setting-hunt-int');
        if (huntInp && !huntInp.matches(':focus') && data.issue_hunt_interval) {
          huntInp.value = data.issue_hunt_interval;
        }

        // Workers Telemetry
        if (data.inbox_worker) {
          document.getElementById('inbox-status-pill').textContent = data.inbox_worker.state || 'IDLE';
          document.getElementById('inbox-activity-text').textContent = data.inbox_worker.current_action || 'Inbox triage completed';
          document.getElementById('inbox-footer-meta').textContent = `Processed: ${data.inbox_worker.handled_count || 0} notifications | Last check: ${data.inbox_worker.last_check || 'Just now'}`;
        }
        if (data.hunter_worker) {
          document.getElementById('hunter-status-pill').textContent = data.hunter_worker.state || 'HUNTING';
          document.getElementById('hunter-activity-text').textContent = data.hunter_worker.current_action || 'Searching repositories...';
          document.getElementById('hunter-footer-meta').textContent = `Current step: ${data.hunter_worker.active_step || 'Querying'} | Last check: ${data.hunter_worker.last_check || 'Just now'}`;
        }

        // Render Tasks Tables
        const tasks = data.tasks || [];
        const tbody1 = document.getElementById('tasks-tbody');
        if (tasks.length === 0) {
          const emptyRow = '<tr><td colspan="7" style="text-align: center; color: var(--text-dim); padding: 2rem;">No active or completed tasks recorded yet.</td></tr>';
          if (tbody1) tbody1.innerHTML = emptyRow;
        } else {
          if (tbody1) tbody1.innerHTML = tasks.slice(0, 10).map(renderRow).join('');
        }
        filterAndRenderTasks();

        // Bottom Stats (Real live calculations)
        const totalCount = tasks.length;
        const runningCount = tasks.filter(t => t.status === 'RUNNING' || t.status === 'IN_PROGRESS').length;
        const failedCount = tasks.filter(t => t.status === 'FAILED').length;
        const completedCount = tasks.filter(t => t.status === 'COMPLETED').length;

        document.getElementById('metric-total').textContent = totalCount;
        document.getElementById('metric-completed').textContent = completedCount;
        document.getElementById('metric-running').textContent = runningCount;
        document.getElementById('metric-failed').textContent = failedCount;

        const successRate = totalCount > 0 ? ((completedCount / totalCount) * 100).toFixed(1) : "100.0";
        const failRate = totalCount > 0 ? ((failedCount / totalCount) * 100).toFixed(1) : "0.0";
        document.getElementById('metric-success-rate').textContent = `${successRate}% success rate`;
        document.getElementById('metric-fail-rate').textContent = `${failRate}% failure rate`;

        // Compute average execution time
        const completedWithTime = tasks.filter(t => t.completed_at && t.started_at);
        if (completedWithTime.length > 0) {
          const totalSecs = completedWithTime.reduce((acc, t) => {
            const start = new Date(t.started_at).getTime();
            const end = new Date(t.completed_at).getTime();
            return (end > start) ? acc + (end - start) / 1000 : acc + 30;
          }, 0);
          const avgSec = Math.round(totalSecs / completedWithTime.length);
          document.getElementById('metric-avg-time').textContent = avgSec < 60 ? `${avgSec}s` : `${(avgSec / 60).toFixed(1)}m`;
        } else {
          document.getElementById('metric-avg-time').textContent = '45s';
        }

        // Reports Tab Dynamic Stats
        const repTriageRate = document.getElementById('report-triage-rate');
        if (repTriageRate) repTriageRate.textContent = `${successRate}%`;
        const repPassRate = document.getElementById('report-pass-rate');
        if (repPassRate) repPassRate.textContent = `${successRate}%`;
        const repModelSub = document.getElementById('report-model-sub');
        if (repModelSub) repModelSub.textContent = `${data.model_display_name || activeModelName} inference`;

        // Reports category breakdown
        const breakdownEl = document.getElementById('reports-category-breakdown');
        if (breakdownEl) {
          const inboxCount = tasks.filter(t => t.category === 'INBOX').length;
          const huntCount = tasks.filter(t => t.category === 'HUNT').length;
          const solveCount = tasks.filter(t => t.category === 'SOLVE').length;
          const inboxPct = totalCount > 0 ? Math.round((inboxCount / totalCount) * 100) : 50;
          const huntPct = totalCount > 0 ? Math.round((huntCount / totalCount) * 100) : 50;

          breakdownEl.innerHTML = `
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 0.85rem; font-weight: 600; margin-bottom: 0.35rem;">
                <span>📥 Inbox Notifications Triage (${inboxCount})</span>
                <span>${inboxPct}%</span>
              </div>
              <div class="progress-bar-container"><div class="progress-bar-fill" style="width: ${inboxPct}%; background: var(--accent-green);"></div></div>
            </div>
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 0.85rem; font-weight: 600; margin-bottom: 0.35rem;">
                <span>🔍 Open-Source Issue Hunt &amp; Scan (${huntCount})</span>
                <span>${huntPct}%</span>
              </div>
              <div class="progress-bar-container"><div class="progress-bar-fill" style="width: ${huntPct}%; background: var(--accent-purple);"></div></div>
            </div>
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 0.85rem; font-weight: 600; margin-bottom: 0.35rem;">
                <span>🛠️ Pull Request Code Solves (${solveCount})</span>
                <span>${totalCount > 0 ? Math.round((solveCount / totalCount) * 100) : 0}%</span>
              </div>
              <div class="progress-bar-container"><div class="progress-bar-fill" style="width: ${totalCount > 0 ? Math.round((solveCount / totalCount) * 100) : 0}%; background: var(--accent-blue);"></div></div>
            </div>
          `;
        }

        // Update Log Terminal
        if (data.recent_events && data.recent_events.length > 0) {
          const logBox = document.getElementById('log-terminal-box');
          if (logBox) {
            logBox.innerHTML = data.recent_events.map(ev => {
              const typeClass = `log-type-${(ev.type || 'system').toLowerCase()}`;
              return `<div class="log-line"><span class="log-time">[${ev.timestamp}]</span> <span class="${typeClass}">[${ev.type}]</span> ${ev.description}</div>`;
            }).join('');
          }
        }

      } catch (e) {
        console.error("Telemetry fetch failed:", e);
      }
    }

    setInterval(updateDashboard, 2000);
    updateDashboard();
  </script>
</body>
</html>
"""


class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP handler serving JSON telemetry API and the ultra-premium Web UI."""

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/toggle-mode":
            config.dry_run = not config.dry_run
            status_tracker.config.dry_run = config.dry_run
            status_tracker.log_event(
                "SYSTEM",
                f"Operating mode toggled to: {'DRY-RUN' if config.dry_run else 'LIVE'}",
            )
            self._send_json({"dry_run": config.dry_run, "status": "ok"})
        elif parsed.path == "/api/settings":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                model = payload.get("model_name")
                dry_run = payload.get("dry_run")
                inbox_int = payload.get("inbox_poll_interval")
                hunt_int = payload.get("issue_hunt_interval")

                updates = []
                if model:
                    config.model_name = str(model)
                    status_tracker.active_model = str(model)
                    updates.append(f"model={model}")
                if dry_run is not None:
                    config.dry_run = bool(dry_run)
                    status_tracker.config.dry_run = config.dry_run
                    updates.append(f"dry_run={config.dry_run}")
                if inbox_int:
                    config.inbox_poll_interval = max(10, int(inbox_int))
                    updates.append(f"inbox_int={config.inbox_poll_interval}s")
                if hunt_int:
                    config.issue_hunt_interval = max(30, int(hunt_int))
                    updates.append(f"hunt_int={config.issue_hunt_interval}s")

                status_tracker.save()
                status_tracker.log_event("SYSTEM", f"Agent configuration updated: {', '.join(updates)}")
                self._send_json({"status": "ok", "message": "Settings applied successfully"})
            except Exception as e:
                self._send_json({"status": "error", "error": str(e)})
        elif parsed.path == "/api/trigger-inbox":
            status_tracker.log_event("INBOX", "Manual inbox check requested from dashboard")
            self._send_json({"status": "triggered"})
        elif parsed.path == "/api/trigger-hunt":
            status_tracker.log_event("HUNT", "Manual issue hunt requested from dashboard")
            self._send_json({"status": "triggered"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            status_tracker._load()
            task_tracker._load()
            snapshot = status_tracker.get_snapshot()
            snapshot["tasks"] = task_tracker.get_all_tasks()
            self._send_json(snapshot)
        else:
            content = HTML_TEMPLATE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    def _send_json(self, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_web_server(port: int = 3000):
    """Start local web server on specified port in a daemon thread."""
    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("127.0.0.1", port), DashboardHTTPHandler)
        logger.info(f"Live Web Dashboard listening at http://localhost:{port}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd
    except Exception as e:
        logger.warning(f"Could not bind web dashboard on port {port}: {e}")
        return None
