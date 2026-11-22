#!/usr/bin/env python3
"""Finish independent tuning meshes in bounded, persistent worker processes."""
import argparse, concurrent.futures, contextlib, hashlib, io, json, os, re, shutil, subprocess, sys, time
from pathlib import Path
TOOLS=Path(__file__).resolve().parent


def finish_one(t, a):
    # One worker process handles its assigned meshes sequentially. These three
    # entry points use local Resource instances and the same validators as CLI.
    import native_drawable_model_split
    import native_drawable_part_textures
    import fill_drawable_lods
    stem=t['stem'];tmp=a.output/stem;tmp.mkdir()
    split=tmp/'split.pft';finished=a.output/(stem+'.pft')
    def run(module,*args):
        log=io.StringIO()
        try:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                rc=module.main(list(map(str,args)))
            if rc!=0:raise RuntimeError(f'return code {rc}')
        except (Exception,SystemExit) as e:
            raise RuntimeError(f'{stem} {module.__name__}: {e}\n{log.getvalue()[-12000:]}') from None
    started=time.perf_counter()
    run(native_drawable_model_split,'--input',t['input'],'--output',split)
    if t.get('embedded'):
        livery=tmp/'livery.pft';cmd=['--input',split,'--embedded',t['embedded'],'--output',livery]
        if a.max_size:cmd+=['--max-size',a.max_size]
        if a.templates:cmd+=['--templates',a.templates]
        run(native_drawable_part_textures,*cmd);split=livery
    run(fill_drawable_lods,'--input',split,'--output',finished)
    shutil.rmtree(tmp)
    print(f'TUNING_PART_OK {stem} seconds={time.perf_counter()-started:.3f}',flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--task-file',type=Path,required=True)
    p.add_argument('--task-sha256',required=True)
    p.add_argument('--templates',type=Path)
    p.add_argument('--max-size',type=int)
    p.add_argument('--worker-index',type=int,default=None,help=argparse.SUPPRESS)
    p.add_argument('--worker-count',type=int,default=None,help=argparse.SUPPRESS)
    a=p.parse_args(argv)
    raw=a.task_file.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=a.task_sha256:p.error('task manifest hash mismatch')
    tasks=json.loads(raw)
    if not isinstance(tasks,list) or not tasks:p.error('empty task list')
    names=[t['stem'] for t in tasks]
    if len(set(names))!=len(names) or any(not isinstance(n,str) or not re.fullmatch(r'[a-z0-9_][a-z0-9_.-]*',n) or n.endswith('.') for n in names):p.error('duplicate or invalid part name')
    if a.worker_index is not None:
        if not a.output.is_dir() or a.output.is_symlink() or a.worker_count is None or not 0<=a.worker_index<a.worker_count<=4:p.error('invalid worker assignment')
        try:
            for t in tasks[a.worker_index::a.worker_count]:finish_one(t,a)
        except Exception as e:
            print(f'TUNING_BATCH_FAILED: {e}',file=sys.stderr);return 1
        return 0
    a.output.mkdir(parents=True,exist_ok=False)
    workers=min(len(tasks),4,max(1,int(os.environ.get('GTAV_MODEL_WORKERS','2'))))
    from gtavmenu_tools.asset_formats import resource_header
    def expanded(task):
        with Path(task['input']).open('rb') as stream:h=resource_header(stream.read(16))
        return h['systemBytes']+h['graphicsBytes']
    if max(expanded(t) for t in tasks)>16*1024*1024 or any(t.get('embedded') for t in tasks):workers=1
    command=[sys.executable,str(Path(__file__).resolve()),'--output',str(a.output),'--task-file',str(a.task_file),'--task-sha256',a.task_sha256,'--worker-count',str(workers)]
    if a.max_size:command+=['--max-size',str(a.max_size)]
    if a.templates:command+=['--templates',str(a.templates)]
    def worker(i):
        with subprocess.Popen(command+['--worker-index',str(i)],cwd=TOOLS.parent,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace') as child:
            for line in child.stdout:print(line,end='',flush=True)
        return child.returncode
    print(f'PERF_TUNING_BATCH workers={workers} count={len(tasks)} persistent=1',flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        codes=list(pool.map(worker,range(workers)))
    if any(codes):return 1
    if any(not (a.output/(stem+'.pft')).is_file() for stem in names):
        print('TUNING_BATCH_FAILED: missing validated output',file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
