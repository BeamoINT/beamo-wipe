import subprocess,tempfile,time,json,urllib.request,websocket,base64
from pathlib import Path
out=Path("docs/evidence/stop-erase-94")
import http.server,threading
server=http.server.ThreadingHTTPServer(("127.0.0.1",0),http.server.SimpleHTTPRequestHandler)
threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory() as profile:
 p=subprocess.Popen(["google-chrome","--headless=new","--no-first-run","--no-default-browser-check","--disable-background-networking","--disable-component-update","--disable-extensions","--disable-sync","--disable-gpu","--no-sandbox","--disable-dev-shm-usage","--remote-allow-origins=*","--remote-debugging-port=0","--user-data-dir="+profile,"about:blank"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(100):
   portfile=Path(profile)/"DevToolsActivePort"
   if portfile.exists(): break
   time.sleep(.1)
  port=portfile.read_text().splitlines()[0]
  tabs=json.load(urllib.request.urlopen(f"http://localhost:{port}/json"))
  tabs=[tab for tab in tabs if tab["type"]=="page"]
  ws=websocket.create_connection(tabs[0]["webSocketDebuggerUrl"],timeout=10)
  ident=0
  def call(method,params={}):
   global ident
   ident+=1;ws.send(json.dumps(dict(id=ident,method=method,params=params)))
   while True:
    r=json.loads(ws.recv())
    if r.get("id")==ident:
     assert "error" not in r,r
     return r.get("result",{})
  def js(expression):
   r=call("Runtime.evaluate",dict(expression=expression,returnByValue=True))
   assert "exceptionDetails" not in r,r
   return r["result"].get("value")
  call("Page.enable")
  call("Page.bringToFront")
  call("Emulation.setDeviceMetricsOverride",dict(width=1024,height=740,deviceScaleFactor=1,mobile=False))
  url=f"http://127.0.0.1:{server.server_port}/web-preview/index.html"
  call("Page.navigate",dict(url=url+"#s=working&disk=0&pct=42"))
  for _ in range(100):
   if js('typeof draw === "function"'): break
   time.sleep(.1)
  assert js('screen')=="working", (js('screen'), js('document.body.innerText'))
  js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent==="Stop erase").click()')
  assert js('screen')=="stop_confirm"
  assert js('document.activeElement.textContent')=="Keep erasing"
  assert "cannot restore" in js('document.body.innerText')
  js('document.activeElement.click()')
  assert js('screen')=="working"
  js('screen="stop_confirm";draw()')
  js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent==="Yes, stop erasing").click()')
  assert js('screen')=="stopping"
  time.sleep(1.6)
  assert js('screen')=="stopped"
  # Actual sample completion continues while reading confirmation.
  js('startWork();screen="stop_confirm";draw()')
  time.sleep(4)
  assert js('screen')=="done"
  print("PASS: browser interaction assertions including completion while confirming.",flush=True)
  for state in ("working","stop_confirm","stopping","stopped","stop_unconfirmed"):
   js(f'screen="{state}";draw()')
   time.sleep(.2)
   js("window.scrollTo(0,0)")
   size=call("Page.getLayoutMetrics")["cssContentSize"]
   r=call("Page.captureScreenshot",dict(captureBeyondViewport=True,clip=dict(x=0,y=0,width=size["width"],height=size["height"],scale=1)))
   (out/f"after-browser-{state}.png").write_bytes(base64.b64decode(r["data"]))
  print("PASS: browser stop control, safe focus, keep erasing, stopping/stopped, completion while confirming; five renders at 1024px width (full page capture).")
 finally:
  p.terminate();p.wait(timeout=10)
