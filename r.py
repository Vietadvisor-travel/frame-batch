#!/usr/bin/env python3
"""One batch slice: fetch the pack, render frames, return the result. Quiet by design."""
import json, os, subprocess, sys, tarfile, time, urllib.error, urllib.parse, urllib.request

J = json.load(open('job.json')); I = int(sys.argv[1]); W = '/tmp/w'; Q = dict(stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
STAGE = ['start']


def sh(cmd, **k):
    r = subprocess.run(cmd, cwd=W, **Q, **k)
    if r.returncode: raise RuntimeError(f'exit {r.returncode}: ' + r.stderr.decode('utf-8', 'replace')[-300:].replace(W, '.'))
    return r
_T = {'t': '', 'e': 0}


def tok():
    if time.time() > _T['e'] - 120:
        v = {k: os.environ.get('GDRIVE_' + k, '').strip().split('=', 1)[-1].strip().strip('"') for k in ('CLIENT_ID', 'CLIENT_SECRET', 'REFRESH_TOKEN')}
        b = urllib.parse.urlencode({'client_id': v['CLIENT_ID'], 'client_secret': v['CLIENT_SECRET'], 'refresh_token': v['REFRESH_TOKEN'], 'grant_type': 'refresh_token'}).encode()
        try: d = json.load(urllib.request.urlopen('https://oauth2.googleapis.com/token', b, timeout=60))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f'login {e.code} ' + json.loads(e.read() or b'{}').get('error', '') + ' lengths ' + ','.join(str(len(x)) for x in v.values()))
        _T.update(t=d['access_token'], e=time.time() + int(d.get('expires_in', 3600)))
    return {'Authorization': 'Bearer ' + _T['t']}


def req(url, data=None, h=None, m=None, tries=6):
    for k in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, data, {**tok(), **(h or {})}, method=m), timeout=600)
        except RuntimeError: raise
        except urllib.error.HTTPError as e:
            if k == tries - 1 or e.code in (400, 401, 403, 404): raise RuntimeError(f'drive {e.code}')
            time.sleep(2 ** k)
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
    os.makedirs(W, exist_ok=True); STAGE[0] = 'fetch'; fetch(J['p'], '/tmp/p.tgz'); tarfile.open('/tmp/p.tgz').extractall(W)
    M = json.load(open(f'{W}/meta.json'))
    STAGE[0] = 'deps'; sh(['npm', 'ci', '--no-audit', '--no-fund'])
    STAGE[0] = 'browser'; sh(['npx', '-y', f'playwright@{M["pw"]}', 'install', '--with-deps', 'chromium-headless-shell'])
    exe = os.path.expanduser(f'~/.cache/ms-playwright/{M["shell"]}/chrome-headless-shell-linux64/chrome-headless-shell')
    a = I * M['step']; b = min(M['n'] - 1, a + M['step'] - 1); out = f'{W}/{I}.mp4'
    STAGE[0] = 'render'
    for k in range(3):
        cmd = ['npx', 'remotion', 'render', 'b', 'Story', out, '--props=' + open(f'{W}/props.json').read(), f'--frames={a}-{b}', '--muted',
               f'--crf={M["crf"]}', f'--concurrency={max(1, M["conc"] - k)}', '--timeout=120000', '--log=error', f'--browser-executable={exe}']
        r = subprocess.run(cmd, cwd=W, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode == 0 and frames(out) == b - a + 1: break
    else:
        slug = json.load(open(f'{W}/props.json')).get('slug', '#')
        raise RuntimeError(('exe ok ' if os.path.exists(exe) else 'no exe ') + r.stdout.decode('utf-8', 'replace')[-400:].replace(W, '.').replace(slug, 'x'))
    STAGE[0] = 'send'; send(out, f'{I}.mp4', J['o'])


try: main(); print('ok')
except SystemExit: print('fail', STAGE[0]); sys.exit(1)
except Exception as e: print('fail', STAGE[0], type(e).__name__, str(e)[-300:] if STAGE[0] in ('deps', 'browser') or isinstance(e, RuntimeError) else ''); sys.exit(1)
