"""Local desktop frontend around the unmodified open-source vehicle converter.

Requires Python >=3.11, tkinter, numpy. Does not modify the console or game.
"""
from __future__ import annotations
import hashlib
import importlib.util
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import traceback
import zipfile
from pathlib import Path

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
MOTOR = ROOT / 'motor'
WORK = ROOT / 'trabajo'
SUPPORTED = {'.rpf', '.zip', '.oiv', '.rar', '.7z'}


def copy_templates(selected: Path, destination: Path) -> Path:
    if not selected.exists():
        raise ValueError('No se encuentra el ZIP o carpeta de plantillas.')
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    if selected.is_dir():
        base = selected / 'plantillas' if (selected / 'plantillas' / 'corpus').is_dir() else selected
        for entry in base.rglob('*'):
            if entry.is_file():
                rel = entry.relative_to(base)
                if any(x in ('.', '..') for x in rel.parts):
                    raise ValueError('Ruta inválida en las plantillas.')
                out = destination / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry, out)
    elif selected.suffix.lower() == '.zip':
        with zipfile.ZipFile(selected) as z:
            for entry in z.infolist():
                if entry.is_dir():
                    continue
                name = entry.filename.replace('\\', '/')
                parts = name.split('/')
                if parts[0] == 'plantillas':
                    parts = parts[1:]
                if not parts or parts[0] not in ('corpus', 'razor-shader-database-source-a', 'wheels', 'retail-audio'):
                    continue
                if any(p in ('', '.', '..') for p in parts):
                    raise ValueError('Ruta no permitida en las plantillas.')
                dest = destination.joinpath(*parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if entry.file_size > 90_000_000:
                    raise ValueError('Una plantilla supera el límite de seguridad.')
                with z.open(entry) as source, dest.open('wb') as target:
                    shutil.copyfileobj(source, target)
    else:
        raise ValueError('Selecciona un ZIP de plantillas o una carpeta.')
    required = [
        'corpus/tornado6.pft', 'corpus/tornado6.ptd',
        'corpus/banshee-a.pft', 'corpus/banshee-a.ptd',
        'corpus/decal-schema-a.pft', 'corpus/vehshare-a.ptd',
        'razor-shader-database-source-a/sga_prospero_final.awc',
        'razor-shader-database-source-a/sga_prospero_final_init.awc',
        'corpus/vigero.pft', 'corpus/trailersmall.pft', 'corpus/trailers3.pft',
        'corpus/buc2_dl_camo2.pft', 'corpus/cheb_skirts.pft',
        'corpus/nemesis.pft', 'corpus/armytrailer_hi.pft',
    ]
    missing = [n for n in required if not (destination / n).is_file()]
    if missing:
        raise ValueError('Faltan plantillas: ' + ', '.join(missing))
    return destination


def find_7z() -> str | None:
    # The standalone EXE embeds the command-line extractor. In source builds,
    # development machines can use their own installed 7-Zip.
    bundled = ROOT / 'tools' / '7zip' / '7z.exe'
    if bundled.is_file() and (bundled.parent / '7z.dll').is_file():
        return str(bundled)
    found = shutil.which('7z') or shutil.which('7za')
    if found:
        return found
    for env_name in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        root = os.environ.get(env_name)
        if root:
            path = Path(root) / '7-Zip' / '7z.exe'
            if path.is_file():
                return str(path)
    return None


def prepare_mod(source: Path, target_root: Path, log) -> Path:
    if source.suffix.lower() not in ('.rar', '.7z'):
        return source
    exe = find_7z()
    if not exe:
        raise ValueError('No se encuentra 7-Zip. Instalalo en Windows para abrir RAR/7z o selecciona directamente dlc.rpf.')
    target_root.mkdir(parents=True, exist_ok=True)
    todo = [(source, target_root / 'extraido', 0)]
    seen = set()
    while todo:
        archive, dest, depth = todo.pop(0)
        if archive in seen:
            continue
        seen.add(archive)
        dest.mkdir(parents=True, exist_ok=True)
        log('Analizando seguridad del RAR/7z antes de extraer: '+archive.name)
        listing=subprocess.run([exe,'l','-slt',str(archive)],capture_output=True,
                               text=True,errors='replace',timeout=60)
        if listing.returncode:
            raise ValueError('No se pudo comprobar la estructura del archivo comprimido.')
        total_uncompressed=0;entries=0
        # 7-Zip emits file records after the first dashed separator. No remote
        # resources are required; this also covers archives nested inside others.
        in_records=False
        for line in listing.stdout.splitlines():
            line=line.strip()
            if line.startswith('----------'):
                in_records=True
                continue
            if not in_records:continue
            if line.startswith('Path = '):
                rel=line[7:].replace('\\','/')
                if (rel.startswith('/') or re.match(r'^[a-zA-Z]:',rel)
                    or any(piece in ('..','') for piece in rel.split('/'))):
                    raise ValueError('RAR/7z contiene una ruta peligrosa; extráelo manualmente en un entorno seguro.')
                entries+=1
                if entries>20000:raise ValueError('RAR/7z con demasiados archivos.')
            if line.startswith('Size = '):
                try:total_uncompressed+=int(line[7:])
                except ValueError:raise ValueError('Tamaño de archivo no válido en el RAR/7z.')
                if total_uncompressed>8_000_000_000:
                    raise ValueError('RAR/7z excede el límite de 8 GB descomprimidos.')
        if not in_records or not entries:
            raise ValueError('RAR/7z sin listado comprobable; extrae manualmente el DLC.RPF.')
        log('Extrayendo: ' + archive.name)
        result = subprocess.run([exe, 'x', '-y', '-bd', f'-o{dest}', str(archive)],
                                capture_output=True, text=True, errors='replace',timeout=600)
        if result.returncode:
            raise ValueError('7-Zip no pudo extraer ' + archive.name + ': ' + result.stderr[-500:])
        rpf = sorted(dest.rglob('dlc.rpf'), key=lambda p: (len(p.parts), len(str(p))))
        if len(rpf) == 1:
            return rpf[0]
        if len(rpf) > 1:
            log('Hay varios dlc.rpf: se utiliza ' + str(rpf[0]))
            return rpf[0]
        if depth < 2:
            children = sorted(p for p in dest.rglob('*') if p.is_file() and p.suffix.lower() in ('.rar', '.7z'))
            for child in children[:8]:
                todo.append((child, dest / ('nested-' + str(len(seen) + len(todo))), depth+1))
    raise ValueError('No hay dlc.rpf: el archivo puede ser un mod Replace (archivos YFT/YTD sueltos), no un Add-on Legacy compatible.')


def package_result(pack: Path, out: Path, target: str) -> Path:
    resources = pack / 'resources'
    if not (resources / 'pack.cfg').is_file():
        raise ValueError('El conversor no generó resources/pack.cfg')
    archive = out / (pack.name + '-PARA-PS5.zip')
    if archive.exists():
        raise ValueError('Ya existe el ZIP de salida. Elige otro ID de paquete.')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(resources.rglob('*')):
            if path.is_file():
                name = str(Path('GTAVMenu/custom/packs') / pack.name / 'resources' / path.relative_to(resources)).replace('\\', '/')
                z.write(path, name)
        z.writestr('LEEME-INSTALACION.txt',
            'Copia GTAVMenu dentro de /data/ en PS5 usando FTP.\n'
            'NO sobrescribas /data/GTAVMenu/custom/packs/installed.\n'
            f'Añade una nueva linea con este nombre al fichero installed: {pack.name}\n'
            'Luego: Custom Packs > Manage Packs > ON > Load packs.\n'
            f'Objetivo: {target}\n'
            'Prueba experimental. Utiliza el modo historia y conserva copias de seguridad.\n')
    with zipfile.ZipFile(archive) as z:
        bad = z.testzip()
        if bad:
            raise ValueError('Fallo CRC en el ZIP: ' + bad)
    return archive


def make_command(source: Path, model: str, packid: str, name: str,
                 templates: Path, layouts: Path | None, output_root: Path,
                 max_texture: int | None, dry_run=False) -> list[str]:
    cmd = [sys.executable, str(MOTOR / 'tools' / 'convert_vehicle.py'),
           '--source', str(source), '--model', model, '--id', packid,
           '--name', name, '--templates', str(templates),
           '--output-root', str(output_root), '--target', 'ppsa04264-01.010.002',
           '--repair', 'auto']
    if layouts:
        cmd.extend(['--retail-layouts', str(layouts)])
    if max_texture:
        cmd.extend(['--max-texture-size', str(max_texture)])
    if dry_run:
        cmd.append('--dry-run')
    return cmd


def check_fields(settings: dict):
    if sys.version_info < (3, 11):
        raise ValueError('Se necesita Python 3.11 o superior.')
    if importlib.util.find_spec('numpy') is None:
        raise ValueError('Falta NumPy. Ejecuta INSTALAR-NUMPY-SI-FALTA.bat y abre la aplicación otra vez.')
    source = Path(settings['source'].strip().strip('"'))
    templates = Path(settings['templates'].strip().strip('"'))
    layouts = Path(settings['layouts'].strip().strip('"')) if settings['layouts'].strip() else None
    output = Path(settings['output'].strip().strip('"'))
    model = settings['model'].strip().lower()
    packid = settings['packid'].strip().lower()
    name = settings['name'].strip()
    if not source.is_file() or source.suffix.lower() not in SUPPORTED:
        raise ValueError('Selecciona un dlc.rpf o archivo de mod ZIP/OIV/RAR/7z válido.')
    if not templates.exists():
        raise ValueError('Selecciona las 15 plantillas en ZIP o carpeta.')
    if layouts and not layouts.is_file():
        raise ValueError('No se encuentra vehiclelayouts.meta.')
    if not re.fullmatch(r'[a-z0-9_]+', model):
        raise ValueError('Modelo: utiliza letras minúsculas, números o _ (ejemplo m4comp).')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,63}', packid):
        raise ValueError('ID: utiliza letras minúsculas, números, guiones o _.')
    if not name or len(name) > 64:
        raise ValueError('Indica un nombre visible de hasta 64 caracteres.')
    if not output.is_dir():
        output.mkdir(parents=True)
    return source, templates, layouts, output, model, packid, name


def run_process(cmd: list[str], label: str, log, env=None):
    log('\n>>> ' + label)
    log('Ejecutando: ' + Path(cmd[1]).name)
    p = subprocess.Popen(cmd, cwd=MOTOR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         bufsize=1, text=True, errors='replace', env=env)
    assert p.stdout is not None
    from collections import deque
    tail=deque(maxlen=8)
    for line in p.stdout:
        line=line.rstrip()
        if line:tail.append(line)
        if line:
            log(line[:600] + (' ...[línea recortada]' if len(line)>600 else ''))
    status=p.wait()
    if status:
        details='; '.join(list(tail)[-3:]) if tail else ''
        raise RuntimeError(f'{label}: error del conversor (código {status}). {details[:650]}')


def convert(settings, log):
    source, tpl, layouts, out, model, packid, name = check_fields(settings)
    jobdir = WORK / packid
    if jobdir.exists():
        if (jobdir / 'paquetes' / packid / 'resources' / 'pack.cfg').exists():
            raise ValueError('Ya existe un paquete completo con este ID. Introduce otro ID.')
        log('Hay un intento anterior con este ID; se limpiará solo su carpeta temporal.')
        shutil.rmtree(jobdir)
    jobdir.mkdir(parents=True)
    tplpath = copy_templates(tpl, jobdir / 'plantillas')
    log('15 plantillas preparadas. El motor original comprobará sus hashes.')
    if layouts:
        log('Layout original: ' + str(layouts))
    prepared = prepare_mod(source, jobdir / 'importado', log)
    log('Archivo de origen: ' + str(prepared))
    outpacks = jobdir / 'paquetes'
    outpacks.mkdir()
    base=make_command(prepared, model, packid, name, tplpath, layouts, outpacks, 2048)
    run_process(base+['--dry-run'], 'Comprobación de requisitos', log)
    run_process(base, 'Conversión completa de modelos, texturas y metadatos', log)
    pack=outpacks / packid
    run_process([sys.executable, str(MOTOR / 'tools/validate_runtime_pack.py'),
                 str(pack), '--target', 'ppsa04263-01.010.002'], 'Validación del paquete', log)
    zipout=package_result(pack,out,'PPSA04263 01.010.002')
    log('\nLISTO: ' + str(zipout))
    return zipout


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)
        with zipfile.ZipFile(p/'plantillas.zip', 'w') as z:
            for name in ('corpus/tornado6.pft','corpus/tornado6.ptd',
                        'corpus/banshee-a.pft','corpus/banshee-a.ptd','corpus/decal-schema-a.pft',
                        'corpus/vehshare-a.ptd','razor-shader-database-source-a/sga_prospero_final.awc',
                        'razor-shader-database-source-a/sga_prospero_final_init.awc','corpus/vigero.pft',
                        'corpus/trailersmall.pft','corpus/trailers3.pft','corpus/buc2_dl_camo2.pft',
                        'corpus/cheb_skirts.pft','corpus/nemesis.pft','corpus/armytrailer_hi.pft'):
                z.writestr('plantillas/' + name, b'fixture')
        folder=copy_templates(p/'plantillas.zip',p/'out')
        assert len(list(folder.rglob('*.*')))==15
        assert (folder/'corpus/tornado6.pft').read_bytes()==b'fixture'
        args=make_command(p/'dlc.rpf','m4comp','bmw-m4-test','BMW M4',folder,None,p/'packs',2048,True)
        assert args[1].endswith('convert_vehicle.py') and '--dry-run' in args
        pack=p/'my-pack'/'resources';pack.mkdir(parents=True)
        (pack/'pack.cfg').write_text('unit test')
        (pack/'some.rpf').write_bytes(b'test')
        zipout=package_result(pack.parent,p,'ppsa04263')
        with zipfile.ZipFile(zipout) as z:
            assert z.testzip() is None
            assert 'GTAVMenu/custom/packs/my-pack/resources/pack.cfg' in z.namelist()
    print('SELF_TEST=PASS')


def start_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    class UI:
        def __init__(self):
            self.root=tk.Tk()
            self.root.title('GTA V PS5 · Conversor PC Legacy — v2 (BMW M4 + Espace V)')
            self.root.geometry('900x710')
            self.root.minsize(790,610)
            self.root.configure(bg='#141a27')
            self.vars={k:tk.StringVar() for k in ('source','model','packid','name','templates','layouts','output')}
            self.vars['output'].set(str(Path.home()/'Desktop'/'GTAV-CarMods-PS5'))
            self.messages=queue.Queue()
            self.busy=False
            self.make_layout(ttk)
            self.root.after(90,self.poll)
        def make_layout(self,ttk):
            style=ttk.Style(self.root)
            if 'clam' in style.theme_names():style.theme_use('clam')
            style.configure('TFrame', background='#141a27')
            style.configure('TLabel', background='#141a27', foreground='#e2e8f0', font=('Segoe UI',10))
            style.configure('TEntry', fieldbackground='#243047', foreground='#f8fafc', padding=7)
            style.configure('TButton',font=('Segoe UI',10),padding=7)
            style.configure('Accent.TButton',background='#008dcb',foreground='white',font=('Segoe UI',11,'bold'))
            body=ttk.Frame(self.root,padding=20);body.pack(fill='both',expand=True)
            title=ttk.Label(body,text='GTA V PS5  |  CONVERSOR DE VEHÍCULOS',font=('Segoe UI',17,'bold'))
            title.pack(anchor='w')
            ttk.Label(body,text='Motor abierto RaringM · PC Legacy → PPSA04263 01.010.002 · Solo modo historia',
                      foreground='#9caac0').pack(anchor='w',pady=(4,14))
            f=ttk.Frame(body);f.pack(fill='x')
            self.add_path(f,0,'1. Mod de PC  (dlc.rpf, ZIP, OIV o RAR)','source','file')
            self.add_entry(f,1,'2. Modelo exacto  (ej. m4comp)','model')
            self.add_entry(f,2,'3. Nombre para mostrar','name')
            self.add_entry(f,3,'4. ID único del paquete','packid')
            self.add_path(f,4,'5. Plantillas PS5  (ZIP de 15 recursos o carpeta)','templates','templates')
            self.add_path(f,5,'6. vehiclelayouts.meta original  (si está disponible)','layouts','file')
            self.add_path(f,6,'7. Carpeta donde guardar el resultado','output','dir')
            buttons=ttk.Frame(body);buttons.pack(fill='x',pady=(17,8))
            self.go=ttk.Button(buttons,text='CONVERTIR COCHE',style='Accent.TButton',command=self.begin)
            self.go.pack(side='left')
            ttk.Button(buttons,text='Abrir carpeta de salida',command=self.open_output).pack(side='left',padx=12)
            self.status=ttk.Label(body,text='Preparado para seleccionar un coche',foreground='#7dd3fc')
            self.status.pack(anchor='w',pady=(2,6))
            frame=ttk.Frame(body);frame.pack(fill='both',expand=True)
            self.logbox=tk.Text(frame,bg='#0b1220',fg='#e2e8f0',insertbackground='white',
                                wrap='word',font=('Consolas',9),height=10,relief='flat')
            self.logbox.pack(side='left',fill='both',expand=True)
            scroll=ttk.Scrollbar(frame,command=self.logbox.yview);scroll.pack(side='right',fill='y')
            self.logbox.configure(yscrollcommand=scroll.set,state='disabled')
            self.append('Selecciona un coche Legacy. Las plantillas deben proceder de tu propia copia del juego.\n')
        def add_entry(self,parent,row,label,key):
            ttk.Label(parent,text=label).grid(row=row*2,column=0,columnspan=3,sticky='w',pady=(4,2))
            ent=ttk.Entry(parent,textvariable=self.vars[key])
            ent.grid(row=row*2+1,column=0,columnspan=3,sticky='we')
            parent.columnconfigure(0,weight=1)
        def add_path(self,parent,row,label,key,typ):
            ttk.Label(parent,text=label).grid(row=row*2,column=0,columnspan=3,sticky='w',pady=(4,2))
            ent=ttk.Entry(parent,textvariable=self.vars[key]);ent.grid(row=row*2+1,column=0,sticky='we')
            ttk.Button(parent,text='Buscar…',command=lambda:self.browse(key,typ)).grid(row=row*2+1,column=1,padx=(8,0))
            if typ=='templates':
                ttk.Button(parent,text='Carpeta',command=lambda:self.browse(key,'dir')).grid(row=row*2+1,column=2,padx=(6,0))
            parent.columnconfigure(0,weight=1)
        def browse(self,key,typ):
            if typ=='dir':
                value=filedialog.askdirectory(title='Selecciona la carpeta',parent=self.root)
            elif typ=='templates':
                value=filedialog.askopenfilename(title='Selecciona el ZIP de plantillas',filetypes=[('ZIP','*.zip'),('Todos','*.*')],parent=self.root)
            else:
                value=filedialog.askopenfilename(title='Selecciona el archivo',filetypes=[('Mod / META','*.rpf *.rar *.7z *.zip *.oiv *.meta'),('Todos','*.*')],parent=self.root)
            if value:
                self.vars[key].set(value)
                if key=='source':
                    p=Path(value)
                    guess=p.parent.name if p.stem.lower()=='dlc' else p.stem
                    guess=re.sub('[^a-z0-9_]', '', guess.lower().replace(' ', '_'))[:32]
                    if not self.vars['model'].get() and guess:
                        self.vars['model'].set(guess)
                    if not self.vars['name'].get():
                        self.vars['name'].set(p.parent.name if p.stem.lower()=='dlc' else p.stem[:64])
                    if not self.vars['packid'].get() and guess:
                        self.vars['packid'].set('gtavmenu-'+guess)
        def append(self,text):
            self.logbox.configure(state='normal')
            self.logbox.insert('end',text+'\n')
            self.logbox.see('end');self.logbox.configure(state='disabled')
        def begin(self):
            if self.busy:return
            values={k:v.get() for k,v in self.vars.items()}
            self.busy=True;self.go.configure(state='disabled')
            self.status.configure(text='Convirtiendo… no cierres esta ventana')
            threading.Thread(target=self.worker,args=(values,),daemon=True).start()
        def worker(self,settings):
            try:
                result=convert(settings,lambda s:self.messages.put(('log',s)))
                self.messages.put(('success',str(result)))
            except Exception as error:
                self.messages.put(('error',str(error)))
                self.messages.put(('log',traceback.format_exc(limit=3)))
        def poll(self):
            try:
                while True:
                    name,value=self.messages.get_nowait()
                    if name=='log':self.append(value)
                    elif name=='success':
                        self.busy=False;self.go.configure(state='normal')
                        self.status.configure(text='Conversión y validación terminadas')
                        messagebox.showinfo('Paquete terminado','ZIP generado y validado:\n'+value,parent=self.root)
                    elif name=='error':
                        self.busy=False;self.go.configure(state='normal')
                        self.status.configure(text='No convertido: revisa el registro')
                        self.append('ERROR: '+value)
                        messagebox.showerror('No se pudo convertir',value,parent=self.root)
            except queue.Empty:pass
            self.root.after(100,self.poll)
        def open_output(self):
            path=Path(self.vars['output'].get())
            path.mkdir(parents=True,exist_ok=True)
            if os.name=='nt':os.startfile(str(path))
            else:messagebox.showinfo('Carpeta de salida',str(path))
    app=UI();app.root.mainloop()


if __name__=='__main__':
    if sys.argv[1:2]==['--self-test']:
        self_test()
    else:
        start_gui()
