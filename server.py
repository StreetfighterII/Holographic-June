import os, sqlite3, json, hmac, urllib.request, urllib.error
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, session

app=Flask(__name__, static_folder='static')
app.secret_key=os.environ.get('SESSION_SECRET','dev-only-change-me')
DB=Path(os.environ.get('JUNE_DB','june_memory.sqlite3'))

def db():
 c=sqlite3.connect(DB); c.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL)'); c.execute('CREATE TABLE IF NOT EXISTS memory (id INTEGER PRIMARY KEY CHECK (id=1), notes TEXT NOT NULL)'); c.commit(); return c

def authorized(): return bool(session.get('ok'))
@app.get('/')
def home(): return send_from_directory('.','index.html')

@app.get('/june.png')
def june_image(): return send_from_directory('.','june.png')
@app.get('/api/status')
def status(): return jsonify(locked=not authorized(),configured=bool(os.getenv('OPENAI_API_KEY')))
@app.post('/api/login')
def login():
 pw=os.getenv('JUNE_PASSWORD')
 if not pw: return jsonify(error='Set JUNE_PASSWORD on the server first.'),503
 if not hmac.compare_digest(str(request.json.get('password','')),pw):return jsonify(error='Wrong password'),401
 session['ok']=True;return jsonify(ok=True)
@app.post('/api/logout')
def logout():session.clear();return jsonify(ok=True)
@app.get('/api/history')
def history():
 if not authorized():return jsonify(error='Locked'),401
 c=db(); rows=c.execute('SELECT role,content FROM messages ORDER BY id DESC LIMIT 60').fetchall(); notes=c.execute('SELECT notes FROM memory WHERE id=1').fetchone();c.close()
 return jsonify(messages=[{'role':r,'content':t} for r,t in reversed(rows)],notes=notes[0] if notes else '')
@app.post('/api/memory')
def memory():
 if not authorized():return jsonify(error='Locked'),401
 notes=str((request.json or {}).get('notes',''))[:6000];c=db();c.execute('INSERT INTO memory(id,notes) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET notes=excluded.notes',(notes,));c.commit();c.close();return jsonify(ok=True)
@app.post('/api/clear')
def clear():
 if not authorized():return jsonify(error='Locked'),401
 c=db();c.execute('DELETE FROM messages');c.commit();c.close();return jsonify(ok=True)
@app.post('/api/chat')
def chat():
 if not authorized():return jsonify(error='Locked'),401
 if not os.getenv('OPENAI_API_KEY'):return jsonify(error='Add OPENAI_API_KEY on the server.'),503
 msg=str((request.json or {}).get('message','')).strip()[:2000]
 if not msg:return jsonify(error='Write a message first.'),400
 c=db();notes=c.execute('SELECT notes FROM memory WHERE id=1').fetchone();history=c.execute('SELECT role,content FROM messages ORDER BY id DESC LIMIT 24').fetchall()[::-1]
 instructions='You are June, a warm, capable AI assistant represented by a blue holographic avatar. Be honest, concise and helpful. Do not claim to be a human or that you have access to ChatGPT account memories. Do not pretend to remember things not provided. User-approved memory notes:\n'+(notes[0] if notes else '(none)')
 payload={'model':os.getenv('OPENAI_MODEL','gpt-4.1-mini'),'instructions':instructions,'input':[{'role':r,'content':t} for r,t in history]+[{'role':'user','content':msg}],'max_output_tokens':450}
 req=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY'],'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=45) as res: data=json.load(res)
 except urllib.error.HTTPError as e:
  c.close();return jsonify(error='OpenAI API error: '+e.read(350).decode('utf-8','replace')),502
 except Exception as e:c.close();return jsonify(error='Could not reach OpenAI: '+str(e)),502
 answer=' '.join(part.get('text','') for out in data.get('output',[]) for part in out.get('content',[]) if part.get('type')=='output_text').strip()
 if not answer:c.close();return jsonify(error='No text response returned.'),502
 c.executemany('INSERT INTO messages(role,content) VALUES(?,?)',[('user',msg),('assistant',answer)]);c.commit();c.close();return jsonify(reply=answer)
if __name__=='__main__':app.run(port=int(os.getenv('PORT','5000')),debug=False)
