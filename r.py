#!/usr/bin/env python3
"""One batch slice: fetch the pack, render frames, return the result. Quiet by design."""
import json, os, subprocess, sys, tarfile, time, urllib.parse, urllib.request

J = json.load(open('job.json')); I = int(sys.argv[1]); W = '/tmp/w'; Q = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
_T = {'t': '', 'e': 0}


def tok():
    if time.time() > _T['e'] - 120:
        b = urllib.parse.urlencode({'client_id': os.environ['GDRIVE_CLIENT_ID'], 'client_secret': os.environ['GDRIVE_CLIENT_SECRET'],
                                    'refresh_token': os.environ['GDRIVE_REFRESH_TOKEN'], 'grant_type': 'refresh_token'}).encode()
        d = json.load(urllib.request.urlopen('https://oauth2.googleapis.com/token', b, timeout=60))
        _T.update(t=d['access_token'], e=time.time() + int(d.get('expires_in', 3600)))
    return {'Authorization': 'Bearer ' + _T['t']}


def req(url, data=None, h=None, m=None, tries=6):
    for k in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, data, {**tok(), **(h or {})}, method=m), timeout=600)
        except Exception:
            if k == tries - 1: raise
            time.sleep(2 ** k)


def fetch(fid, dst):
    r = req(f'https://www.googleapis.com/drive/v3/files/{fid}?alt=media&supportsAllDrives=true')
    with open(dst, 'wb') as w:
        for c in iter(lambda: r.read(1 << 22), b''): w.write(c)


def send(path, name, parent):
    meta = json.dumps({'name': name, 'parents': [parent]}).encode(); n = os.path.getsize(path)
    loc = req('https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true', meta,
              {'Content-Type': 'application/json; charset=UTF-8', 'X-Upload-Content-Length': str(n)}, 'POST').headers['Location']
    req(loc, open(path, 'rb').read(), {'Content-Length': str(n)}, 'PUT')


def frames(p):
    r = subprocess.run(['npx', 'remotion', 'ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v', '-show_entries',
                        'stream=nb_read_packets', '-of', 'csv=p=0', p], cwd=W, capture_output=True, text=True)
    try: return int(r.stdout.strip().strip(',').split(',')[0])
    except ValueError: return -1


def main():
    os.makedirs(W, exist_ok=True); fetch(J['p'], '/tmp/p.tgz'); tarfile.open('/tmp/p.tgz').extractall(W)
    M = json.load(open(f'{W}/meta.json'))
    subprocess.run(['npm', 'ci', '--no-audit', '--no-fund'], cwd=W, check=True, **Q)
    subprocess.run(['npx', '-y', f'playwright@{M["pw"]}', 'install', '--with-deps', 'chromium-headless-shell'], cwd=W, check=True, **Q)
    exe = os.path.expanduser(f'~/.cache/ms-playwright/{M["shell"]}/chrome-headless-shell-linux64/chrome-headless-shell')
    a = I * M['step']; b = min(M['n'] - 1, a + M['step'] - 1); out = f'{W}/{I}.mp4'
    for k in range(3):
        cmd = ['npx', 'remotion', 'render', 'b', 'Story', out, '--props=' + open(f'{W}/props.json').read(), f'--frames={a}-{b}', '--muted',
               f'--crf={M["crf"]}', f'--concurrency={max(1, M["conc"] - k)}', '--timeout=120000', '--log=error', f'--browser-executable={exe}']
        if subprocess.run(cmd, cwd=W, **Q).returncode == 0 and frames(out) == b - a + 1: break
    else: sys.exit(1)
    send(out, f'{I}.mp4', J['o'])


try: main(); print('ok')
except SystemExit: print('fail'); sys.exit(1)
except Exception: print('fail'); sys.exit(1)
