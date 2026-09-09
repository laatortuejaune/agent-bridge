"""Narrow bidirectional config adapter. Credentials and harness overrides stay native."""
import contextlib
import fcntl
import json
from pathlib import Path
import re
import tomllib

from bridge import atomic_write, now, sanitize, sha


def fingerprint(value):return sha(json.dumps(value,sort_keys=True))


def fields(server):
    out={}
    for key in ['command','args','url']:
        if key in server:out[key]=server[key]
    out.setdefault('args',[])
    for key,value in server.get('env',{}).items():
        if not re.search(r'key|token|secret|pass|auth|cookie|credential',key,re.I):out['env.'+key]=value
    # Even args or URLs can contain embedded credentials: never copy them.
    return {key:value for key,value in out.items() if sanitize(json.dumps(value,ensure_ascii=False))==json.dumps(value,ensure_ascii=False)
            and not re.search(r'password|api[_-]?key|access[_-]?token|client[_-]?secret',json.dumps(value),re.I)}


def set_toml(text,server,key,value):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',server):raise ValueError('Unsupported MCP name')
    env=key.startswith('env.');field=key[4:] if env else key
    section='mcp_servers.'+server+('.env' if env else '')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',field):raise ValueError('Unsupported field name')
    header=re.search(r'^\['+re.escape(section)+r'\]\s*$',text,re.M)
    if not header:raise ValueError('Unsupported TOML layout; preserve configuration')
    tail=text[header.end():];end=re.search(r'^\[',tail,re.M)
    end=header.end()+end.start() if end else len(text)
    part=text[header.end():end]
    row=re.search(r'^'+re.escape(field)+r'\s*=.*$',part,re.M)
    new=field+' = '+json.dumps(value,ensure_ascii=False)
    if row:
        # Refuse multiline TOML instead of guessing the extent of the field.
        try:tomllib.loads(row.group())
        except tomllib.TOMLDecodeError:raise ValueError('Multiline field requires manual reconciliation')
        part=part[:row.start()]+new+part[row.end():]
    else:part='\n'+new+'\n'+part
    updated=text[:header.end()]+part+text[end:]
    parsed=tomllib.loads(updated)['mcp_servers'][server]
    actual=parsed.get('env',{}).get(field) if env else parsed.get(field)
    if actual!=value:raise ValueError('TOML roundtrip mismatch')
    return updated


def sync(root,home,names=()):
    root=Path(root);home=Path(home)
    with (root/'configuration.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'busy':True}
        cp=home/'.claude.json';xp=home/'.codex/config.toml'
        if not cp.exists() or not xp.exists():return {'skipped':'configuration missing'}
        craw=cp.read_text();xraw=xp.read_text()
        c=json.loads(craw);x=tomllib.loads(xraw)
        statepath=root/'configuration-state.json'
        state=json.loads(statepath.read_text()) if statepath.exists() else {'baseline':{},'specific':[]}
        edits=[];conflicts=[];skipped=[];updated=xraw
        for name in names:
            cs=c.get('mcpServers',{}).get(name);xs=x.get('mcp_servers',{}).get(name)
            if cs is None or xs is None:
                skipped.append(name+': not configured on both agents');continue
            cf=fields(cs);xf=fields(xs)
            for key in sorted(set(cf)|set(xf)):
                ident=name+':'+key
                if ident in state['specific']:continue
                if key not in cf or key not in xf:
                    if ident in state['baseline']:conflicts.append(ident+': field removed on one side')
                    else:state['specific'].append(ident)
                    continue
                cv,xv=cf[key],xf[key];ch,xh=fingerprint(cv),fingerprint(xv)
                base=state['baseline'].get(ident)
                if ch==xh:state['baseline'][ident]=ch;continue
                if base is None:
                    state['specific'].append(ident);continue
                if ch!=base and xh!=base:
                    conflicts.append(ident+': both agents changed; both values retained');continue
                if ch!=base:
                    try:updated=set_toml(updated,name,key,cv)
                    except ValueError as e:
                        conflicts.append(ident+': '+str(e));continue
                    state['baseline'][ident]=ch;edits.append({'field':ident,'direction':'claude → codex'})
                else:
                    if key.startswith('env.'):cs.setdefault('env',{})[key[4:]]=xv
                    else:cs[key]=xv
                    state['baseline'][ident]=xh;edits.append({'field':ident,'direction':'codex → claude'})
        if edits:
            if cp.read_text()!=craw or xp.read_text()!=xraw:
                return {'at':now(),'conflicts':['native configuration changed during sync; no write'],'edits':[]}
            history=root/'configuration-history'/now().replace(':','-');history.mkdir(parents=True)
            atomic_write(history/'claude.json',craw);atomic_write(history/'codex.toml',xraw)
            if updated!=xraw:atomic_write(xp,updated)
            newc=json.dumps(c,ensure_ascii=False,indent=2)+'\n'
            if json.loads(craw)!=c:atomic_write(cp,newc)
            atomic_write(history/'changes.json',json.dumps(edits,ensure_ascii=False,indent=2))
        state['last']={'at':now(),'edits':edits,'conflicts':conflicts,'specific_fields':state['specific'],'skipped':skipped}
        atomic_write(statepath,json.dumps(state,ensure_ascii=False,indent=2))
        return state['last']
