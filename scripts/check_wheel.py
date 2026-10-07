"""Install a wheel outside the checkout and verify its real dashboard assets."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

wheel = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="github-agent-wheel-") as directory:
    root = Path(directory)
    target = root / "installed"
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(wheel)], check=True)
    env = dict(os.environ, PYTHONPATH=str(target), GITHUB_AGENT_NO_GH="true", GITHUB_TOKEN="",
               GEMINI_API_KEY="", AI_PROVIDER="gemini", SCRATCH_DIR=str(root / "state"))
    code = '''
from pathlib import Path
import httpx
from src import web_dashboard
assert "installed" in str(Path(web_dashboard.__file__).resolve())
assert web_dashboard.FRONTEND_DIR.name == "_frontend"
server = web_dashboard.start_web_server(0)
try:
 base = f"http://127.0.0.1:{server.server_address[1]}"
 with httpx.Client(base_url=base, trust_env=False) as client:
  for path, needle in [("/", "Open dashboard"), ("/dashboard", "settingsForm"), ("/js/field.js", "AgentField"), ("/classic", "settingsForm"), ("/dist/app.js", "MissionControlApp"), ("/dist/dom.js", "escapeHtml"), ("/css/layout.css", "mobile-open")]:
   response = client.get(path)
   assert response.status_code == 200 and needle in response.text, path
  assert client.get("/api/status").json()["status"] == "STOPPED"
 print("Installed wheel: dashboard HTML, JavaScript, CSS, and API passed")
finally:
 server.shutdown()
 server.server_close()
'''
    subprocess.run([sys.executable, "-c", code], cwd=root, env=env, check=True)
