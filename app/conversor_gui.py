"""GTAV PS5 Converter v4.8 — Windows desktop frontend.

Original conversion engine by RaringM (preserved in motor/).
Application UI: GTA V PS5 Converter contributors.
"""
from __future__ import annotations
import json
import hashlib
import os
import queue
import re
import threading
import time
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import v3_engine as engine
from progress_v4 import StageProgress, ftp_percent
from public_release import APP_TITLE, VERSION, friendly_error, export_support, qa_report, record_duration, median_duration
from gui_locales import translate, formatted, LANGUAGES
from drop_import import create_root, dropped_source, register_tree

BG='#0C111B'; SURF='#141E2C'; CARD='#192637'; INPUT='#202F42'; LINE='#324258'
FG='#EAF3FB'; DIM='#A7B7CA'; ACC='#68DDD0'; ACC2='#A4F1E8'; ERR='#FF8B97'
FONT='Segoe UI'; BLUE='#92BFFF'
CPU=max(1,os.cpu_count() or 1)
RECOMMENDED=max(1,min(4,CPU//2 if CPU>2 else CPU))
QUALITY={'Original · sin reducción':0,'Alta · máximo 2048 px (si hay mips)':2048,'Media · máximo 1024 px (si hay mips)':1024}


class ConverterUI:
    def __init__(self):
        self.root,self.drop_enabled=create_root()
        self.root.title(APP_TITLE+' · Community edition')
        self.root.geometry('1120x790')
        self.root.minsize(860,660)
        self.root.configure(bg=BG)
        # Icon for the title bar, task switcher and Windows installer.
        try:
            icon=engine.ROOT/'assets'/'app.png'
            self._icon_image=tk.PhotoImage(file=str(icon))
            self.root.iconphoto(True,self._icon_image)
        except (OSError,tk.TclError):pass
        self.language=self._load_language()
        self.language_choice=tk.StringVar(value=next(k for k,v in LANGUAGES.items() if v==self.language))
        self.queue=queue.Queue();self.working=False;self.records=[];self.started_at=None;self.next_timer_at=0;self.estimated_total=None
        self.rpf=None;self.photo=None;self.photo_tk=None;self.candidates=[]
        self.packages=[];self.last_zip=None
        self.v={k:tk.StringVar() for k in ('source','model','name','packid','output','ip','port','ftp_folder','ftp_pack')}
        self.v['output'].set(str(Path.home()/'Documents'/'GTAV-CarMods-PS5'))
        self.v['ftp_folder'].set(self.v['output'].get())
        self.v['port'].set('1337')
        self.quality=tk.StringVar(value=self.tr('Original · sin reducción'))
        self.auto_texture_fit=tk.BooleanVar(value=False)
        self.handling_mode=tk.StringVar(value=self.tr('Equilibrada (recomendada)'))
        self.include_tuning=tk.BooleanVar(value=False)
        self.cpu_label=self.fmt('Automático · {recommended} / {cpu}',recommended=RECOMMENDED,cpu=CPU)
        self.cpu_pick=tk.StringVar(value=self.cpu_label)
        self.percent=tk.IntVar(value=0)
        self.stage=tk.StringVar(value='Selecciona un coche de PC Legacy')
        self.ftp_stage=tk.StringVar(value='Selecciona un paquete convertido')
        self.ftp_percent=tk.IntVar(value=0)
        self.status=tk.StringVar(value='Preparado')
        self._style();self._layout();self._read_saved_ftp()
        self._log("DRAG_DROP="+str(self.drop_enabled)+" "+getattr(self.root,"drop_diagnostic",""))
        self._resources_state();self.show_page('conversion' if engine.configured() else 'setup')
        self.root.after(90,self._poll)

    def _load_language(self):
        try:
            data=json.loads((engine.cache_root()/'idioma-ui.json').read_text(encoding='utf-8'))
            if data.get('language') in LANGUAGES.values():return data['language']
        except (OSError,ValueError,TypeError):pass
        return 'en'

    def tr(self,text):
        return translate(text,self.language)

    def fmt(self,text,**values):
        return formatted(text,self.language,**values)

    def _language_changed(self,event=None):
        selected=LANGUAGES.get(self.language_choice.get(),'es')
        if selected==self.language:return
        if self.working:
            self.language_choice.set(next(k for k,v in LANGUAGES.items() if v==self.language))
            return
        q=next((k for k in QUALITY if self.quality.get()==translate(k,self.language)),list(QUALITY)[0])
        driving='Original del mod' if self.handling_mode.get()==translate('Original del mod',self.language) else 'Equilibrada (recomendada)'
        automatic=self.cpu_pick.get()==self.cpu_label
        core=self.workers() if not automatic else RECOMMENDED
        active=next((k for k,page in self.pages.items() if page.winfo_manager()),'setup')
        self.language=selected
        self.quality.set(self.tr(q))
        self.handling_mode.set(self.tr(driving))
        self.cpu_label=self.fmt('Automático · {recommended} / {cpu}',recommended=RECOMMENDED,cpu=CPU)
        self.cpu_pick.set(self.cpu_label if automatic else self.fmt('{n} núcleo' if core==1 else '{n} núcleos',n=core))
        cfg=engine.cache_root()/'idioma-ui.json'
        cfg.write_text(json.dumps({'language':selected},ensure_ascii=False)+'\n',encoding='utf-8')
        logs=self.records[-150:]
        for child in self.root.winfo_children():child.destroy()
        self.records=[]
        self._layout()
        for line in logs:self._log(line)
        self._resources_state()
        self._set_details(bool(self.rpf and self.candidates))
        if self.rpf and self.candidates:
            self.combo_model.configure(values=[r['model'] for r in self.candidates])
            row=next((x for x in self.candidates if x['model']==self.v['model'].get()),self.candidates[0])
            self._assign_row(row)
            self._photo(self.photo)
        self.show_page(active)

    def _translate_tree(self,widget):
        # ttk and tkinter buttons must be localised as well as plain labels.
        for child in widget.winfo_children():
            try:
                old=child.cget('text')
                new=self.tr(old)
                if old!=new:child.configure(text=new)
            except (tk.TclError,AttributeError):pass
            self._translate_tree(child)

    @staticmethod
    def _wheel_steps(event):
        """Tk on Windows reports delta in 120-point units; touchpads can report less.

        X11 sends Button-4/Button-5 instead. Never interpret a zero delta as a click.
        """
        num=getattr(event,'num',None)
        if num==4:return -1
        if num==5:return 1
        delta=getattr(event,'delta',0)
        if not delta:return 0
        return (-1 if delta>0 else 1)*max(1,round(abs(delta)/120))

    @staticmethod
    def _scroll_area(widget):
        # Canvas is an ancestor of the content in each scrolling view.
        # Widgets like the technical log outside these canvases keep native scrolling.
        while widget is not None:
            if getattr(widget,'_gtav_page_scroll',False):return widget
            widget=getattr(widget,'master',None)
        return None

    def _route_wheel(self,event):
        canvas=self._scroll_area(event.widget)
        steps=self._wheel_steps(event)
        if canvas is not None and steps:
            canvas.yview_scroll(steps,'units')
            return 'break'
        return None

    def _wheel_over_value(self,event):
        """Prevent readonly combobox, spinbox and scale from changing on page scroll."""
        self._route_wheel(event)
        return 'break'  # widget binding precedes the Tk/ttk class selection binding

    def _install_wheel_controls(self):
        protected=(ttk.Combobox,ttk.Spinbox,tk.Spinbox,tk.Scale,ttk.Scale)
        todo=list(self.root.winfo_children())
        while todo:
            widget=todo.pop()
            todo.extend(widget.winfo_children())
            if isinstance(widget,protected):
                widget.bind('<MouseWheel>',self._wheel_over_value)
                widget.bind('<Button-4>',self._wheel_over_value)
                widget.bind('<Button-5>',self._wheel_over_value)

    def _style(self):
        st=ttk.Style(self.root)
        if 'clam' in st.theme_names():st.theme_use('clam')
        st.configure('Dark.TEntry',fieldbackground=INPUT,foreground=FG,insertcolor=FG,padding=10,relief='flat',borderwidth=0)
        st.configure('Dark.TCombobox',fieldbackground=INPUT,foreground=FG,padding=9,relief='flat')
        st.map('Dark.TCombobox',fieldbackground=[('readonly',INPUT)],foreground=[('readonly',FG)])
        st.configure('Clean.TButton',font=(FONT,10),padding=11,background=INPUT,foreground=FG,relief='flat',borderwidth=0)
        st.map('Clean.TButton',background=[('active','#34516B'),('disabled','#172637')],foreground=[('disabled',DIM)])
        st.configure('Accent.TButton',font=(FONT,11,'bold'),padding=12,background=ACC,foreground=BG,relief='flat',borderwidth=0)
        st.map('Accent.TButton',background=[('active',ACC2),('disabled','#315451')])
        st.configure('Slim.Horizontal.TProgressbar',background=ACC,troughcolor='#26374A',borderwidth=0,thickness=13)

    def label(self,parent,text='',size=10,color=FG,bold=False,**kw):
        return tk.Label(parent,text=self.tr(text),font=(FONT,size,'bold' if bold else 'normal'),bg=parent['bg'],fg=color,**kw)

    def entry(self,parent,key):
        return ttk.Entry(parent,textvariable=self.v[key],style='Dark.TEntry')

    def card(self,parent,padx=19,pady=15):
        box=tk.Frame(parent,bg=CARD,highlightthickness=1,highlightbackground=LINE)
        inside=tk.Frame(box,bg=CARD,padx=padx,pady=pady);inside.pack(fill='both',expand=True)
        return box,inside

    def form(self,parent,title,key):
        self.label(parent,title,9,DIM).pack(anchor='w',pady=(8,4))
        f=self.entry(parent,key);f.pack(fill='x')
        return f

    def _layout(self):
        shell=tk.Frame(self.root,bg=BG);shell.pack(fill='both',expand=True)
        sidebar=tk.Frame(shell,bg=SURF,width=220);sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
        self.label(sidebar,'GTAV',27,bold=True).pack(anchor='w',padx=22,pady=(26,0))
        self.label(sidebar,'PS5 CONVERTER',11,color=ACC,bold=True).pack(anchor='w',padx=24,pady=(0,27))
        self.nav={}
        for key,title,icon in [('setup','Configuración','⚙'),('conversion','Conversión','◈'),('ftp','Enviar por FTP','⇧'),('about','Acerca de','ⓘ')]:
            btn=tk.Button(sidebar,text=f'{icon}   {self.tr(title)}',anchor='w',font=(FONT,11),bg=SURF,fg=FG,
                activebackground=INPUT,activeforeground=ACC,relief='flat',bd=0,highlightthickness=0,padx=22,pady=16,
                command=lambda k=key:self.show_page(k),cursor='hand2')
            btn.pack(fill='x',padx=7,pady=2);self.nav[key]=btn
        tk.Frame(sidebar,bg=LINE,height=1).pack(fill='x',padx=21,pady=(22,10))
        self.label(sidebar,'PPSA04263  ·  01.010.002',9,DIM).pack(anchor='w',padx=23)
        self.label(sidebar,'PC Legacy → PS5 nativa',9,DIM).pack(anchor='w',padx=23,pady=(5,0))
        tk.Frame(sidebar,bg=SURF).pack(fill='both',expand=True)
        self.label(sidebar,'CREADO POR',8,DIM).pack(anchor='w',padx=22)
        credit=self.label(sidebar,'Community edition',11,ACC,bold=True)
        credit.pack(anchor='w',padx=22,pady=(4,0))
        self.label(sidebar,'Motor de conversión: RaringM',8,DIM).pack(anchor='w',padx=22,pady=(4,25))
        content=tk.Frame(shell,bg=BG);content.pack(side='right',fill='both',expand=True)
        header=tk.Frame(content,bg=BG,padx=26,pady=21);header.pack(fill='x')
        self.page_title=self.label(header,'Conversión de vehículos',20,bold=True);self.page_title.pack(side='left')
        self.resource_badge=self.label(header,'● RECURSOS LISTOS',9,ACC,bold=True);self.resource_badge.pack(side='right',pady=8)
        self.body=tk.Frame(content,bg=BG);self.body.pack(fill='both',expand=True,padx=24,pady=(0,8))
        self.pages={key:tk.Frame(self.body,bg=BG) for key in ('setup','conversion','ftp','about')}
        self._setup_page(self.pages['setup'])
        self._conversion_page(self.pages['conversion'])
        self._ftp_page(self.pages['ftp'])
        self._about_page(self.pages['about'])
        footer=tk.Frame(content,bg=BG,padx=26,pady=12);footer.pack(fill='x')
        tk.Frame(footer,bg=LINE,height=1).pack(fill='x',pady=(0,8))
        self.footer_label=self.label(footer,'Preparado',9,DIM);self.footer_label.pack(side='left')
        self.log_btn=ttk.Button(footer,text=self.tr('Ver registro técnico'),style='Clean.TButton',command=self._toggle_log)
        self.log_btn.pack(side='right')
        ttk.Button(footer,text=self.tr('Exportar diagnóstico'),style='Clean.TButton',command=self.export_diagnostic).pack(side='right',padx=(0,8))
        self.timer_label=self.label(footer,'',9,DIM);self.timer_label.pack(side='right',padx=(0,12))
        self.logframe=tk.Frame(content,bg=BG,padx=25,pady=5)
        self.logbox=tk.Text(self.logframe,bg='#090E16',fg='#BBCBDA',height=8,font=('Consolas',9),wrap='word',relief='flat')
        self.logbox.pack(side='left',fill='both',expand=True)
        bar=ttk.Scrollbar(self.logframe,command=self.logbox.yview);bar.pack(side='right',fill='y')
        self.logbox.configure(yscrollcommand=bar.set,state='disabled')
        self.log_visible=False
        self._translate_tree(self.root)
        # One global scrolling route, not a temporary bind_all while hovering canvases.
        # Controls get their own binding so the class handler cannot change values.
        self.root.bind_all('<MouseWheel>',self._route_wheel)
        self.root.bind_all('<Button-4>',self._route_wheel)
        self.root.bind_all('<Button-5>',self._route_wheel)
        self._install_wheel_controls()

    def _setup_page(self,page):
        viewport=tk.Frame(page,bg=BG);viewport.pack(fill='both',expand=True)
        canvas=tk.Canvas(viewport,bg=BG,highlightthickness=0,borderwidth=0)
        canvas._gtav_page_scroll=True
        scrollbar=ttk.Scrollbar(viewport,orient='vertical',command=canvas.yview)
        scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        inner=tk.Frame(canvas,bg=BG);window=canvas.create_window((0,0),window=inner,anchor='nw')
        inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        page=inner
        self.label(page,'Configuración del programa',17,FG,True).pack(anchor='w',pady=(9,6))
        self.label(page,'Configura los recursos originales una sola vez. Se guardan en este ordenador.',10,DIM,wraplength=710,justify='left').pack(anchor='w',pady=(0,13))
        c,f=self.card(page);c.pack(fill='x',pady=(0,11))
        self.label(f,'IDIOMA DE LA APLICACIÓN',11,bold=True).pack(anchor='w',pady=(0,7))
        selector=ttk.Combobox(f,textvariable=self.language_choice,values=list(LANGUAGES),state='readonly',style='Dark.TCombobox')
        selector.pack(fill='x');selector.bind('<<ComboboxSelected>>',self._language_changed)
        self.label(f,'Los cambios de idioma se aplican inmediatamente.',9,DIM).pack(anchor='w',pady=(7,0))
        c,f=self.card(page);c.pack(fill='x',pady=(0,11))
        self.label(f,'RECURSOS OBLIGATORIOS',11,bold=True).pack(anchor='w')
        self.label(f,'recursos originales PS5 + vehiclelayouts.meta',10,DIM).pack(anchor='w',pady=(6,0))
        self.setup_resources=self.label(f,'PENDIENTE: recursos originales',10,ERR,True);self.setup_resources.pack(anchor='w',pady=(10,8))
        ttk.Button(f,text='Verificar e importar archivos originales…',style='Accent.TButton',command=self.configure_resources).pack(anchor='w')
        ttk.Button(f,text='Importar referencia de sonido o llantas…',style='Clean.TButton',command=self.configure_optional_reference).pack(anchor='w',pady=(7,0))
        self.label(f,'Estos archivos son necesarios para convertir. No se incluyen con la aplicación.',9,DIM,wraplength=690,justify='left').pack(anchor='w',pady=(8,0))
        c,f=self.card(page);c.pack(fill='x',pady=(0,11))
        self.label(f,'MATERIALES PS5 ADICIONALES · OPCIONAL',11,bold=True).pack(anchor='w')
        self.label(f,'Biblioteca de modelos originales .pft y .pdr',10,DIM).pack(anchor='w',pady=(6,0))
        self.setup_shaders=self.label(f,'Biblioteca opcional de materiales: no configurada',10,DIM,True);self.setup_shaders.pack(anchor='w',pady=(9,8))
        self.shader_library_button=ttk.Button(f,text='Indexar carpeta de modelos PS5…',style='Clean.TButton',command=self.configure_shader_library)
        self.shader_library_button.pack(anchor='w')
        self.label(f,'Opcional, pero recomendado: amplía los shaders reconocidos. No necesitas exactamente 800 coches.',9,DIM,wraplength=680,justify='left').pack(anchor='w',pady=(9,3))
        self.label(f,'Solo se almacenan índices y huellas digitales. Los archivos originales permanecen donde están.',9,DIM,wraplength=680,justify='left').pack(anchor='w',pady=(4,0))

    def _conversion_page(self,page):
        progress_card,pg=self.card(page,padx=19,pady=10)
        self.progress_card=progress_card
        top=tk.Frame(pg,bg=CARD);top.pack(fill='x')
        self.stage_label=self.label(top,'Selecciona un mod para comenzar',10,DIM);self.stage_label.pack(side='left')
        self.pct_label=self.label(top,'0%',13,ACC,True);self.pct_label.pack(side='right')
        ttk.Progressbar(pg,maximum=100,variable=self.percent,style='Slim.Horizontal.TProgressbar').pack(fill='x',pady=(9,0))
        scrollframe=tk.Frame(page,bg=BG);scrollframe.pack(fill='both',expand=True)
        canvas=tk.Canvas(scrollframe,bg=BG,highlightthickness=0,borderwidth=0)
        canvas._gtav_page_scroll=True
        scrollbar=ttk.Scrollbar(scrollframe,orient='vertical',command=canvas.yview)
        scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        outer=tk.Frame(canvas,bg=BG)
        wid=canvas.create_window((0,0),window=outer,anchor='nw')
        outer.bind('<Configure>',lambda ev:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda ev:canvas.itemconfigure(wid,width=ev.width))
        outer.grid_columnconfigure(0,weight=3);outer.grid_columnconfigure(1,weight=2)
        c,status=self.card(outer,padx=16,pady=12);c.grid(row=0,column=0,columnspan=2,sticky='ew',pady=(0,13))
        self.convert_resource_led=self.label(status,'● RECURSOS LISTOS',10,ACC,True)
        self.convert_resource_led.pack(anchor='w')
        self.convert_library_led=self.label(status,'Biblioteca opcional de materiales: no configurada',9,DIM)
        self.convert_library_led.pack(anchor='w',pady=(4,0))
        left=tk.Frame(outer,bg=BG);left.grid(row=1,column=0,sticky='nsew',padx=(0,12))
        right=tk.Frame(outer,bg=BG);right.grid(row=1,column=1,sticky='nsew')
        c,f=self.card(left);c.pack(fill='x',pady=(0,11))
        self.label(f,'01  IMPORTAR MOD',11,bold=True).pack(anchor='w')
        self.label(f,'ZIP · RAR · 7z · OIV · RPF',9,DIM).pack(anchor='w',pady=(4,9))
        line=tk.Frame(f,bg=CARD);line.pack(fill='x')
        # Filename is display only. The browse action performs detection automatically.
        entry=self.entry(line,'source');entry.pack(side='left',fill='x',expand=True);entry.configure(state='readonly')
        ttk.Button(line,text='Buscar…',style='Clean.TButton',command=self.choose_source).pack(side='right',padx=(7,0))
        drop_hint=self.label(f,'Arrastra aquí un RPF o un archivo de mod' if self.drop_enabled else 'Arrastrar y soltar no disponible; usa Buscar.',10,ACC if self.drop_enabled else DIM,True,wraplength=350,justify='left')
        drop_hint.pack(fill='x',pady=(12,0),ipady=8)
        if self.drop_enabled:
            try:register_tree(c,self._drop_source)
            except (tk.TclError,RuntimeError,AttributeError,OSError) as exc:
                self.root.drop_diagnostic += " register: "+repr(exc)
                self.drop_enabled=False
                drop_hint.configure(text=self.tr('Arrastrar y soltar no disponible; usa Buscar.'),fg=DIM)
        self.detail_left=tk.Frame(left,bg=BG)
        self.detail_right=tk.Frame(right,bg=BG)
        self.details_visible=False
        c,f=self.card(self.detail_left);c.pack(fill='x',pady=(0,11))
        self.label(f,'02  VEHÍCULO DETECTADO',11,bold=True).pack(anchor='w',pady=(0,8))
        self.label(f,'Modelo interno',9,DIM).pack(anchor='w',pady=(2,4))
        self.combo_model=ttk.Combobox(f,textvariable=self.v['model'],state='readonly',style='Dark.TCombobox')
        self.combo_model.pack(fill='x');self.combo_model.bind('<<ComboboxSelected>>',self._model_changed)
        self.form(f,'Nombre visible','name')
        self.form(f,'ID único del paquete','packid')
        c,f=self.card(self.detail_left);c.pack(fill='x',pady=(0,11))
        self.label(f,'03  OPCIONES RECOMENDADAS',11,bold=True).pack(anchor='w',pady=(0,7))
        self.recommended_label=self.label(f,'Calidad original · núcleos automáticos',10,DIM)
        self.recommended_label.pack(anchor='w',pady=(0,8))
        self.advanced_btn=ttk.Button(f,text='Mostrar opciones avanzadas',style='Clean.TButton',command=self._toggle_advanced)
        self.advanced_btn.pack(anchor='w')
        self.advanced=tk.Frame(f,bg=CARD)
        self.label(self.advanced,'Calidad de texturas',9,DIM).pack(anchor='w',pady=(12,4))
        self.quality_combo=ttk.Combobox(self.advanced,textvariable=self.quality,values=[self.tr(q) for q in QUALITY],state='readonly',style='Dark.TCombobox')
        self.quality_combo.pack(fill='x')
        self.quality_combo.bind('<<ComboboxSelected>>',self._update_recommended)
        self.label(self.advanced,'Núcleos para procesar texturas',9,DIM).pack(anchor='w',pady=(10,4))
        self.cpu_values=[self.cpu_label]+[self.fmt('{n} núcleo' if i==1 else '{n} núcleos',n=i) for i in range(1,CPU+1)]
        self.cpu_combo=ttk.Combobox(self.advanced,textvariable=self.cpu_pick,values=self.cpu_values,state='readonly',style='Dark.TCombobox')
        self.cpu_combo.pack(fill='x')
        self.cpu_combo.bind('<<ComboboxSelected>>',self._update_recommended)
        self.label(self.advanced,'Conducción del vehículo',9,DIM).pack(anchor='w',pady=(12,4))
        self.handling_combo=ttk.Combobox(self.advanced,textvariable=self.handling_mode,
            values=[self.tr('Equilibrada (recomendada)'),self.tr('Original del mod')],
            state='readonly',style='Dark.TCombobox')
        self.handling_combo.pack(fill='x')
        self.handling_combo.bind('<<ComboboxSelected>>',self._update_recommended)
        self.tuning_checkbox=tk.Checkbutton(self.advanced,
            text=self.tr('Incluir tuning propio compatible (experimental)'),
            variable=self.include_tuning,bg=CARD,fg=FG,selectcolor=INPUT,activebackground=CARD,
            activeforeground=ACC,highlightthickness=0,font=(FONT,9),anchor='w',
            command=self._update_recommended)
        self.tuning_checkbox.pack(anchor='w',pady=(12,0))
        self.tuning_hint=self.label(self.advanced,'El mod no incluye piezas de tuning detectables.',9,DIM)
        self.tuning_hint.pack(anchor='w',pady=(4,3))
        self.label(self.advanced,'Calidad original, sin reducción automática.',9,DIM).pack(anchor='w',pady=(9,0))
        c,f=self.card(self.detail_left);c.pack(fill='x',pady=(0,11))
        self.label(f,'CARPETA DE SALIDA',11,bold=True).pack(anchor='w')
        row=tk.Frame(f,bg=CARD);row.pack(fill='x',pady=(8,9))
        self.entry(row,'output').pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='…',width=3,style='Clean.TButton',command=self.choose_output).pack(side='right',padx=(6,0))
        self.convert_button=ttk.Button(f,text='CONVERT FOR PS5',style='Accent.TButton',command=self.start_convert)
        self.convert_button.pack(fill='x')
        c,f=self.card(self.detail_right);c.pack(fill='x',pady=(0,11))
        self.label(f,'VISTA PREVIA',11,bold=True).pack(anchor='w',pady=(0,10))
        self.preview=tk.Label(f,text=self.tr('Foto no incluida en este mod'),font=(FONT,11),bg='#101B28',fg=DIM,height=10,justify='center')
        self.preview.pack(fill='x')
        self.preview_title=self.label(f,'Sin vehículo',12,bold=True);self.preview_title.pack(anchor='w',pady=(11,0))
        self.preview_info=self.label(f,'Modelo: {name}',9,DIM);self.preview_info.pack(anchor='w',pady=(4,0))

    def _update_recommended(self,event=None):
        original=self.quality.get()==self.tr('Original · sin reducción')
        auto=self.cpu_pick.get()==self.cpu_label
        text=self.tr('Calidad original · núcleos automáticos' if original and auto else 'Opciones personalizadas')
        text += ' · '+self.tr('Conducción original' if self.handling_mode.get()==self.tr('Original del mod') else 'Conducción equilibrada')
        self.recommended_label.configure(text=text)

    def _set_details(self,visible):
        self.details_visible=visible
        if visible:
            if not self.detail_left.winfo_manager():self.detail_left.pack(fill='x')
            if not self.detail_right.winfo_manager():self.detail_right.pack(fill='x')
        else:
            self.detail_left.pack_forget();self.detail_right.pack_forget()

    def _show_progress(self):
        if not self.progress_card.winfo_manager():self.progress_card.pack(side='bottom',fill='x',pady=(6,0))

    def _toggle_advanced(self):
        if self.advanced.winfo_manager():
            self.advanced.pack_forget()
            self.advanced_btn.configure(text=self.tr('Mostrar opciones avanzadas'))
        else:
            self.advanced.pack(fill='x',pady=(4,0))
            self.advanced_btn.configure(text=self.tr('Ocultar opciones avanzadas'))

    def _ftp_page(self,page):
        viewport=tk.Frame(page,bg=BG);viewport.pack(fill='both',expand=True)
        canvas=tk.Canvas(viewport,bg=BG,highlightthickness=0,borderwidth=0)
        canvas._gtav_page_scroll=True
        scrollbar=ttk.Scrollbar(viewport,orient='vertical',command=canvas.yview)
        scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        inner=tk.Frame(canvas,bg=BG)
        win=canvas.create_window((0,0),window=inner,anchor='nw')
        inner.bind('<Configure>',lambda ev:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda ev:canvas.itemconfigure(win,width=ev.width))
        page=inner
        self.label(page,'Enviar a PS5 por FTP',13,FG,True).pack(anchor='w',pady=(8,4))
        self.label(page,'Coches convertidos · FTP anónimo · solo IP y puerto · red local',10,DIM).pack(anchor='w',pady=(0,18))
        c,f=self.card(page);c.pack(fill='x',pady=(0,15))
        self.label(f,'CARPETA DE COCHES CONVERTIDOS',11,bold=True).pack(anchor='w')
        row=tk.Frame(f,bg=CARD);row.pack(fill='x',pady=(10,5))
        self.entry(row,'ftp_folder').pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Elegir carpeta',style='Clean.TButton',command=self.choose_ftp_folder).pack(side='right',padx=(7,0))
        self.label(f,'Paquete a enviar',9,DIM).pack(anchor='w',pady=(11,5))
        self.ftp_combo=ttk.Combobox(f,state='readonly',textvariable=self.v['ftp_pack'],style='Dark.TCombobox')
        self.ftp_combo.pack(fill='x')
        ttk.Button(f,text='Actualizar lista de coches',style='Clean.TButton',command=self.refresh_packages).pack(anchor='w',pady=(10,0))
        c,f=self.card(page);c.pack(fill='x',pady=(0,15))
        self.label(f,'CONEXIÓN A LA CONSOLA',11,bold=True).pack(anchor='w',pady=(0,6))
        grid=tk.Frame(f,bg=CARD);grid.pack(fill='x')
        portbox=tk.Frame(grid,bg=CARD);portbox.pack(side='right')
        self.label(portbox,'Puerto',9,DIM).pack(anchor='w',pady=(0,5))
        ttk.Entry(portbox,textvariable=self.v['port'],style='Dark.TEntry',width=8).pack(fill='x')
        ipbox=tk.Frame(grid,bg=CARD);ipbox.pack(side='left',fill='x',expand=True,padx=(0,12))
        self.label(ipbox,'IP de la PS5',9,DIM).pack(anchor='w',pady=(0,5))
        self.entry(ipbox,'ip').pack(fill='x')
        self.label(f,'No se solicita usuario ni contraseña: el servidor PS5 debe aceptar FTP anónimo.',9,DIM,wraplength=620,justify='left').pack(anchor='w',pady=(11,14))
        self.ftp_button=ttk.Button(f,text='SEND SELECTED VEHICLE',style='Accent.TButton',command=self.start_ftp)
        self.ftp_button.pack(fill='x')
        c,f=self.card(page);c.pack(fill='x')
        self.label(f,'TRANSFERENCIA',11,bold=True).pack(anchor='w')
        self.ftp_status_label=self.label(f,'Selecciona un paquete convertido',10,DIM)
        self.ftp_status_label.pack(anchor='w',pady=(9,8))
        ttk.Progressbar(f,maximum=100,variable=self.ftp_percent,style='Slim.Horizontal.TProgressbar').pack(fill='x')
        self.label(f,'FTP anónimo sin cifrar: utilízalo únicamente en tu red local. El espacio libre remoto no se puede verificar con FTP estándar.',9,DIM,wraplength=650,justify='left').pack(anchor='w',pady=(12,0))
        buttons=tk.Frame(f,bg=CARD);buttons.pack(fill='x',pady=(12,0))
        self.ftp_test_button=ttk.Button(buttons,text='CHECK CONNECTION',style='Clean.TButton',command=self.start_ftp_test)
        self.ftp_test_button.pack(side='left',padx=(0,8))
        self.ftp_uninstall_button=ttk.Button(buttons,text='UNINSTALL SELECTED',style='Clean.TButton',command=self.start_ftp_uninstall)
        self.ftp_uninstall_button.pack(side='left')
        self.balance_existing_button=ttk.Button(f,text=self.tr('Equilibrar conducción de ZIP (sin reconvertir)'),
                                                  style='Clean.TButton',command=self.start_balance_existing)
        self.balance_existing_button.pack(anchor='w',pady=(9,2))
        self.label(f,'Uninstalling keeps a recoverable backup on PS5.',9,DIM,wraplength=650,justify='left').pack(anchor='w',pady=(10,0))
        self.refresh_packages()

    def _about_page(self,page):
        c,f=self.card(page,padx=26,pady=24);c.pack(fill='x',pady=(10,0))
        self.label(f,'GTA V PS5 Converter',21,bold=True).pack(anchor='w')
        self.label(f,VERSION+' · '+self.tr('Conversor de vehículos de PC Legacy para PS5'),11,DIM).pack(anchor='w',pady=(5,20))
        self.label(f,'OPEN-SOURCE COMMUNITY EDITION',15,ACC,bold=True).pack(anchor='w',pady=(0,6))
        self.label(f,'Original conversion engine and tools: RaringM / ps5-gtav-menu.',10,DIM,wraplength=660,justify='left').pack(anchor='w',pady=(22,6))
        author=self.label(f,'github.com/RaringM/ps5-gtav-menu',10,BLUE,cursor='hand2')
        author.pack(anchor='w');author.bind('<Button-1>',lambda e:webbrowser.open('https://github.com/RaringM/ps5-gtav-menu'))
        self.label(f,'The application does not include GTA V game files. Import original resources from your own game.',10,DIM,wraplength=650,justify='left').pack(anchor='w',pady=(22,0))
        self.label(f,'Paint, tuning, audio, LOD and damage features require additional PS5 testing.',10,DIM,wraplength=650,justify='left').pack(anchor='w',pady=(15,0))
        self.label(f,'See README.md and motor/THIRD_PARTY_NOTICES for documentation and licenses.',9,DIM,wraplength=650,justify='left').pack(anchor='w',pady=(11,0))

    def show_page(self,key):
        for other,p in self.pages.items():p.pack_forget()
        self.pages[key].pack(fill='both',expand=True)
        for k,btn in self.nav.items():btn.configure(bg=INPUT if k==key else SURF,fg=ACC if k==key else FG)
        self.page_title.configure(text=self.tr({'setup':'Configuración y recursos','conversion':'Conversión de vehículos','ftp':'Enviar coches por FTP','about':'Acerca del proyecto'}[key]))
        if key=='ftp':self.refresh_packages()

    def _log(self,message):
        self.records.append(str(message))
        if len(self.records)>2200:self.records=self.records[-2000:]
        self.logbox.config(state='normal')
        self.logbox.insert('end',str(message).rstrip()+'\n');self.logbox.see('end')
        if int(self.logbox.index('end-1c').split('.')[0])>3500:self.logbox.delete('1.0','500.0')
        self.logbox.config(state='disabled')

    def _toggle_log(self):
        self.log_visible=not self.log_visible
        if self.log_visible:self.logframe.pack(fill='x',side='bottom',before=self.body)
        else:self.logframe.pack_forget()
        self.log_btn.config(text=self.tr('Ocultar registro' if self.log_visible else 'Ver registro técnico'))

    def _shader_status(self):
        """Three states: optional missing (neutral), indexed and hash-valid (green), corrupt (red).

        This is a lightweight, read-only fingerprint verification; the engine still checks
        the actual shader schemas when it converts a mod.
        """
        index=engine.library_catalog()
        if not index.is_file():return 'missing',0
        try:
            data=json.loads(index.read_text(encoding='utf-8'))
            if data.get('format')!='gtav-ps5-user-shader-library-v1' or data.get('target')!='PPSA04263-01.010.002':
                return 'invalid',0
            refs=data.get('references')
            if not isinstance(refs,list) or not 0<=len(refs)<=256:return 'invalid',0
            from user_shader_library import read_materials
            for ref in refs:
                path=Path(ref['path'])
                if not path.is_absolute() or path.suffix.lower() not in ('.pft','.pdr') or path.is_symlink() or not path.is_file():return 'invalid',0
                if path.stat().st_size!=ref['bytes']:return 'invalid',0
                digest,rows=read_materials(path)
                schemas=sorted({row['schema']['nameHash'] for row in rows})
                if digest!=ref['sha256'] or schemas!=ref['shaders']:return 'invalid',0
            return 'valid',int(data.get('shaderTypes',0))
        except (ValueError,TypeError,KeyError,OSError,ImportError,IndexError):return 'invalid',0

    def _resources_state(self):
        ok=engine.configured()
        heading=self.tr('● RECURSOS LISTOS' if ok else '● FALTAN RECURSOS')
        self.resource_badge.configure(text=heading,fg=ACC if ok else ERR)
        self.convert_resource_led.configure(text=self.tr('Todos los recursos obligatorios verificados' if ok else 'Faltan recursos obligatorios: abre Configuración'),fg=ACC if ok else ERR)
        self.setup_resources.configure(text=self.tr('RECURSOS VERIFICADOS' if ok else 'PENDIENTE: recursos originales'),fg=ACC if ok else ERR)
        status,types=self._shader_status()
        if status=='valid':
            txt=self.tr('Biblioteca opcional de materiales: lista')+f' · {types} shaders'
            color=ACC
        elif status=='invalid':
            txt=self.tr('Biblioteca de materiales dañada o modificada')
            color=ERR
        else:
            txt=self.tr('Biblioteca opcional de materiales: no configurada')
            color=DIM
        self.setup_shaders.configure(text=txt,fg=color)
        self.convert_library_led.configure(text=txt,fg=color)

    def _busy(self,value):
        self.working=value
        self.convert_button.config(state='disabled' if value else 'normal')
        self.ftp_button.config(state='disabled' if value else 'normal')
        self.shader_library_button.config(state='disabled' if value else 'normal')
        self.ftp_test_button.config(state='disabled' if value else 'normal')
        self.ftp_uninstall_button.config(state='disabled' if value else 'normal')
        self.balance_existing_button.config(state='disabled' if value else 'normal')

    def _localize_progress(self,label):
        """Translate visible progress, retaining unmodified engine logs for diagnostics.

        Progress is an *estimate* during running stages; completion is shown only
        after the engine actually validates its output. Unknown stage names are
        described generically rather than displayed in English to French users.
        """
        label=str(label)
        stage=re.fullmatch(r'(.+) · etapa (\d+) \(estimación\)',label)
        if stage:
            action=stage.group(1).lower()
            exact={
                'stage retail templates':'Preparando recursos PS5',
                'import pc add-on':'Importando coche de PC',
                'material report':'Analizando materiales',
                'repair auto':'Reparando el modelo',
                'validate target pack':'Validando el paquete',
                'pack':'Creando el paquete final',
                'vehicle layouts':'Preparando asientos y configuraciones',
                'carcols + kit':'Preparando piezas y colores',
                'collision octants':'Comprobando colisiones',
            }
            if action in exact:description=exact[action]
            elif action.startswith('repair '):description='Reparando el modelo'
            elif action.startswith('convert '):description='Convirtiendo el modelo'
            elif action.startswith(('textures','embedded textures','livery texture')):description='Convirtiendo texturas'
            elif action.startswith(('tuning','validate optional tuning','mod text table')):description='Preparando piezas de personalización'
            elif action.startswith(('collision','collisions')):description='Comprobando colisiones'
            else:description='Procesando archivos del vehículo'
            return self.fmt('Paso {n} · {action} (estimación)',n=stage.group(2),action=self.tr(description))
        tuning=re.fullmatch(r'Tuning: (\d+)/(\d+) piezas procesadas',label)
        if tuning:return self.fmt('Piezas de personalización: {done}/{total}',done=tuning.group(1),total=tuning.group(2))
        return self.tr(label)

    def _set_progress(self,n,label,ftp=False):
        text=self._localize_progress(label)
        if ftp:
            self.ftp_percent.set(int(n));self.ftp_status_label.config(text=text,fg=ACC)
        else:
            self.percent.set(int(n));self.pct_label.config(text=f'{int(n)}%');self.stage_label.config(text=text,fg=DIM)

    def _photo(self,path):
        self.photo_tk=None;self.preview.config(image='',text=self.tr('Foto no incluida en este mod'),height=10)
        if path is None:return
        try:
            from PIL import Image,ImageTk
            with Image.open(path) as img:
                copy=img.copy();copy.thumbnail((335,195))
                self.photo_tk=ImageTk.PhotoImage(copy)
            self.preview.config(image=self.photo_tk,text='',height=195)
        except Exception as exc:self._log('Fotografía no disponible: '+str(exc))

    def choose_source(self):
        if self.working:return
        p=filedialog.askopenfilename(title=self.tr('Seleccionar coche o llantas PC Legacy'),parent=self.root,
               filetypes=[(self.tr('Mods PC Legacy'),'*.rpf *.zip *.rar *.7z *.oiv'),(self.tr('Todos los archivos'),'*.*')])
        if p:self._load_source(p)

    def _drop_source(self,event):
        if self.working:return 'refuse_drop'
        try:
            path=dropped_source(self.root.tk,event.data)
        except (ValueError, OSError, tk.TclError) as exc:
            msg='Arrastra un solo archivo cada vez.' if str(exc)=='single' else 'Selecciona un archivo RPF, ZIP, RAR, 7z u OIV válido.'
            messagebox.showwarning(self.tr('Importar mod'),self.tr(msg),parent=self.root)
            return 'refuse_drop'
        self._load_source(str(path))
        return 'copy'

    def _load_source(self,p):
        if self.working:return
        self.v['source'].set(p);self.rpf=None;self.photo=None;self.candidates=[]
        self._set_details(False);self._show_progress();self._set_progress(0,self.tr('Analizando el mod…'));self._busy(True);self.preview.config(image='',text=self.tr('Analizando el mod…'))
        def worker():
            try:
                rpf,pic=engine.prepared_rpf(Path(p),lambda s:self.queue.put(('log',s)))
                rows=engine.scan_rpf(rpf)
                self.queue.put(('models',(rpf,pic,rows)))
            except Exception as exc:self.queue.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def _model_changed(self,_=None):
        row=next((r for r in self.candidates if r['model']==self.v['model'].get()),None)
        if row:self._assign_row(row)

    def _assign_row(self,row):
        for k in ('model','name','packid'):self.v[k].set(row[k])
        self.preview_title.config(text=row['name']);self.preview_info.config(text=self.fmt('Modelo: {name}',name=row['model']))
        count=int(row.get('tuning_parts',0))
        self.include_tuning.set(bool(count))  # automatically include detected compatible tuning
        self.tuning_checkbox.configure(state='normal' if count else 'disabled')
        self.tuning_hint.configure(text=(self.fmt('{n} piezas especiales detectadas (compatibilidad en PS5 por verificar)',n=count)
                        if count else self.tr('El mod no incluye piezas de tuning detectables.')))
        if row.get('wheel_count'):
            self.tuning_hint.configure(text=self.fmt('{n} llantas personalizadas · LS Customs de GTAV Menu',n=row['wheel_count']))
            self.v['name'].set(self.fmt('Llantas personalizadas ({n})',n=row['wheel_count']))
            self.preview_title.config(text=self.v['name'].get())
        self._update_recommended()

    def choose_output(self):
        p=filedialog.askdirectory(title=self.tr('Guardar paquetes PS5'),parent=self.root)
        if p:
            self.v['output'].set(p);self.v['ftp_folder'].set(p);self.refresh_packages()

    def choose_ftp_folder(self):
        p=filedialog.askdirectory(title=self.tr('Carpeta con ZIPs convertidos'),parent=self.root)
        if p:self.v['ftp_folder'].set(p);self.refresh_packages()

    def refresh_packages(self):
        folder=Path(self.v['ftp_folder'].get())
        self.packages=engine.list_packages(folder)
        values=[f'{ident}   •   {p.name}' for ident,p in self.packages]
        self.ftp_combo.configure(values=values)
        current=self.v['ftp_pack'].get()
        if current not in values:self.v['ftp_pack'].set(values[0] if values else '')
        self.ftp_status_label.configure(text=self.fmt('{n} paquete(s) encontrados en la carpeta',n=len(values)) if values else self.tr('No hay paquetes convertidos en esta carpeta'),fg=DIM)

    def configure_resources(self):
        if self.working:return
        a,b=engine.auto_resource_candidates()
        if not a or not b or not messagebox.askyesno(self.tr('Recursos PS5'),self.fmt('¿Importar estos archivos?\n{first}\n{second}',first=a,second=b),parent=self.root):
            a=filedialog.askopenfilename(title=self.tr('Paquete de recursos del juego PS5'),parent=self.root,filetypes=[('ZIP','*.zip')])
            if not a:return
            b=filedialog.askopenfilename(title='vehiclelayouts.meta',parent=self.root,filetypes=[('META','*.meta')])
            if not b:return
        self._busy(True)
        def worker():
            try:
                engine.import_resources(Path(a),Path(b),lambda x:self.queue.put(('log',x)))
                self.queue.put(('resources',None))
            except Exception as e:self.queue.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def configure_optional_reference(self):
        if self.working:return
        if not engine.configured():
            messagebox.showinfo(self.tr('Recursos PS5'),self.tr('Importa primero las plantillas obligatorias.'),parent=self.root);return
        paths=filedialog.askopenfilenames(title=self.tr('Referencias originales PS5'),parent=self.root,filetypes=[('PDR / REL','*.pdr *.rel')])
        if not paths:return
        try:
            for path in paths:engine.import_optional_reference(Path(path),self._log)
            messagebox.showinfo(self.tr('Recursos PS5'),self.tr('Referencias verificadas. Audio disponible; llantas personalizadas aún experimentales.'),parent=self.root)
        except Exception as exc:messagebox.showerror(self.tr('Recursos PS5'),str(exc),parent=self.root)

    def configure_shader_library(self):
        if self.working:return
        folder=filedialog.askdirectory(title=self.tr('Carpeta con modelos PS5 originales .pft y .pdr'),parent=self.root)
        if not folder:return
        self._busy(True)
        self.footer_label.config(text=self.tr('Indexando materiales PS5…'),fg=BLUE)
        def worker():
            try:
                result=engine.index_user_shader_library(Path(folder),lambda x:self.queue.put(('log',x)))
                self.queue.put(('shader_library',result))
            except Exception as e:self.queue.put(('error','Biblioteca de materiales: '+str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def workers(self):
        text=self.cpu_pick.get()
        return RECOMMENDED if text==self.cpu_label else int(text.split()[0])

    def start_convert(self):
        if self.working:return
        if not self.rpf or not self.candidates:
            messagebox.showwarning(self.tr('Conversión'),self.tr('Selecciona primero un mod PC Legacy.'),parent=self.root);return
        if not engine.configured():
            messagebox.showwarning(self.tr('Recursos PS5'),self.tr('Configura primero los recursos originales del juego.'),parent=self.root);return
        model=self.v['model'].get()
        if model not in [r['model'] for r in self.candidates]:
            messagebox.showwarning(self.tr('Modelo interno'),self.tr('Selecciona un modelo detectado.'),parent=self.root);return
        args=(self.rpf,model,self.v['name'].get().strip(),self.v['packid'].get().strip(),Path(self.v['output'].get()))
        driving_mode='original' if self.handling_mode.get()==self.tr('Original del mod') else 'balanced'
        include_tuning=self.include_tuning.get()
        quality=next(v for k,v in QUALITY.items() if self.quality.get()==self.tr(k));cores=self.workers()
        self._show_progress();self._busy(True);self._set_progress(0,self.tr('Analizando materiales y shaders…'))
        self.started_at=time.monotonic()
        historic=median_duration(engine.cache_root())
        self.estimated_total=historic
        self.timer_label.config(text=self.fmt('Últimas conversiones: ~{seconds} s',seconds=int(historic)) if historic else self.tr('Midiendo tiempo real…'))
        self.footer_label.config(text=self.tr('Convirtiendo…'),fg=BLUE)
        def worker():
            tracker=StageProgress(lambda n,s:self.queue.put(('progress',(n,s))),expected_steps=2 if model=='@wheels' else 24)
            warnings=[]
            def write(text):
                if any(mark in text for mark in ("WARNING_TUNING_EXCLUDED:", "WARNING: tuning excluded", "left out (", "WARNING_TEXTURE_CHAIN:", "all custom tuning models are unsupported")):
                    warnings.append(text)
                tracker.line(text)
                self.queue.put(('log',text))
            try:
                if model=='@wheels':
                    res=engine.convert_wheel_pack(args[0],args[3],args[4],log=write,texture_size=quality,workers=cores)
                else:
                    res=engine.convert(*args,log=write,texture_size=quality,workers=cores,auto_texture_fit=self.auto_texture_fit.get(),handling_mode=driving_mode,include_tuning=include_tuning)
                tracker.complete()
                duration=time.monotonic()-self.started_at
                if not res[1]:record_duration(engine.cache_root(),duration)
                try:
                    qa=qa_report(res[0],res[0].with_name(res[0].stem+'-QA.json'))
                    self.queue.put(('log','Informe de revisión PS5: '+str(qa)))
                except Exception as exc:self.queue.put(('log','No se pudo generar el informe QA: '+str(exc)))
                self.queue.put(('converted',(res[0],res[1],duration,warnings)))
            except Exception as exc:self.queue.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def export_diagnostic(self):
        path=filedialog.asksaveasfilename(parent=self.root,title=self.tr('Guardar informe privado de soporte'),
               defaultextension='.json',filetypes=[('Informe JSON','*.json')],
               initialfile='GTAV-PS5-DIAGNOSTICO.json')
        if not path:return
        try:
            export_support(self.records,Path(path),{'version':VERSION,'shaders_indexed':engine.library_catalog().is_file()})
            messagebox.showinfo(self.tr('Exportar diagnóstico'),self.tr('Informe guardado con rutas e IPs ocultas. Revísalo antes de compartirlo.'),parent=self.root)
        except Exception as exc:messagebox.showerror(self.tr('Diagnóstico'),str(exc),parent=self.root)

    def _selected_package(self):
        chosen=self.v['ftp_pack'].get()
        return next(((ident,p) for ident,p in self.packages if chosen.startswith(ident+'   •')),None)

    def _ftp_values(self):
        try:port=int(self.v['port'].get())
        except ValueError:raise ValueError(self.tr('El puerto debe ser un número entero.'))
        return self.v['ip'].get().strip(),port

    def start_balance_existing(self):
        if self.working:return
        choice=self._selected_package()
        if choice is None:
            messagebox.showwarning(self.tr('FTP'),self.tr('Selecciona un coche convertido de tu lista local.'),parent=self.root)
            return
        if not messagebox.askyesno(self.tr('Conducción equilibrada'),
            self.tr('Se creará otro ZIP sin reconstruir modelos ni texturas. ¿Continuar?'),parent=self.root):return
        self._busy(True)
        def worker():
            try:
                result=engine.rebalance_existing_zip(choice[1],lambda line:self.queue.put(('log',line)))
                self.queue.put(('balanced_zip',result))
            except Exception as exc:self.queue.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def start_ftp_test(self):
        if self.working:return
        try:ip,port=self._ftp_values()
        except ValueError as exc:messagebox.showerror(self.tr('FTP'),str(exc),parent=self.root);return
        self._busy(True)
        def worker():
            try:self.queue.put(('ftp_test',engine.ftp_preflight(ip,port)))
            except Exception as exc:self.queue.put(('error','FTP: '+str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def start_ftp_uninstall(self):
        if self.working:return
        selected=self._selected_package()
        if selected is None:
            messagebox.showwarning(self.tr('FTP'),self.tr('Selecciona un coche convertido de tu lista local.'),parent=self.root);return
        try:ip,port=self._ftp_values()
        except ValueError as exc:messagebox.showerror(self.tr('FTP'),str(exc),parent=self.root);return
        ident=selected[0]
        if not messagebox.askyesno(self.tr('Desinstalación recuperable'),self.fmt('¿Quitar {ident} de installed y respaldar sus archivos en PS5?\nNo se borrará nada definitivamente.',ident=ident),parent=self.root):return
        self._busy(True)
        def worker():
            try:
                backup=engine.ftp_uninstall(ident,ip,port,lambda s:self.queue.put(('log',s)))
                self.queue.put(('ftp_uninstalled',str(backup)))
            except Exception as exc:self.queue.put(('error','FTP: '+str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def _read_saved_ftp(self):
        try:
            data=json.loads((engine.cache_root()/'conexion-v4.json').read_text(encoding='utf-8'))
            self.v['ip'].set(data['ip']);self.v['port'].set(str(data['port']))
        except (OSError,ValueError,KeyError):pass

    def start_ftp(self):
        if self.working:return
        selected=self._selected_package()
        if selected is None:
            messagebox.showwarning(self.tr('FTP'),self.tr('Selecciona un coche convertido de la lista.'),parent=self.root);return
        try:ip,port=self._ftp_values()
        except ValueError as exc:
            messagebox.showerror(self.tr('FTP'),str(exc),parent=self.root);return
        if not messagebox.askyesno(self.tr('Enviar a PS5'),self.fmt('Paquete: {ident}\nDestino: {ip}:{port}\n\nSe hará copia de seguridad. ¿Continuar?',ident=selected[0],ip=ip,port=port),parent=self.root):return
        self._busy(True);self._set_progress(0,self.tr('Conectando con PS5…'),ftp=True)
        def worker():
            try:
                def report(n,t):self.queue.put(('ftp_progress',(ftp_percent(n,t),self.fmt('Transferidos {done} de {total} MiB',done=n//1048576,total=max(1,t//1048576)))))
                backup=engine.ftp_install(selected[1],ip,port,lambda s:self.queue.put(('log',s)),progress=report)
                (engine.cache_root()/'conexion-v4.json').write_text(json.dumps({'ip':ip,'port':port}),encoding='utf-8')
                self.queue.put(('ftp_ok',str(backup)))
            except Exception as exc:self.queue.put(('error','FTP: '+str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def _poll(self):
        try:
            for _ in range(150):
                name,value=self.queue.get_nowait()
                if name=='log':self._log(value)
                elif name=='models':
                    self._busy(False);self.rpf,self.photo,self.candidates=value
                    self.combo_model.configure(values=[r['model'] for r in self.candidates])
                    if self.candidates:
                        self._assign_row(self.candidates[0]);self._photo(self.photo);self._set_details(True)
                        self.footer_label.config(text=self.tr('Paquete de llantas identificado' if self.candidates[0].get('wheel_count') else 'Vehículo identificado'),fg=ACC)
                    else:self.footer_label.config(text=self.tr('Faltan modelos/archivos del coche'),fg=ERR)
                elif name=='progress':self._set_progress(*value)
                elif name=='ftp_progress':self._set_progress(*value,ftp=True)
                elif name=='resources':self._busy(False);self._resources_state();self.footer_label.config(text=self.tr('Recursos verificados'),fg=ACC)
                elif name=='shader_library':
                    self._busy(False);self._resources_state()
                    self.footer_label.config(text=self.tr('Biblioteca de materiales indexada'),fg=ACC)
                    self._log(f"PS5 materials: {value['shaderTypes']} shader types, {value.get('newShaderTypes',0)} new, {len(value['references'])} external references. Original files remain in their folder.")
                elif name=='converted':
                    self._busy(False);zipfile_path,reused,duration,warnings=value;self.last_zip=zipfile_path
                    self._set_progress(100,self.tr('Paquete generado y validado')+(' · '+self.tr('caché reutilizada') if reused else ''))
                    self.footer_label.config(text=self.fmt('Conversión completada en {seconds:.1f} s',seconds=duration),fg=ACC)
                    self.v['ftp_folder'].set(str(zipfile_path.parent));self.refresh_packages()
                    if warnings:
                        omitted=list(dict.fromkeys(x for x in warnings if x.startswith(('WARNING_TUNING_EXCLUDED:', 'WARNING_OPTIONAL_EXCLUDED:'))))
                        if omitted:
                            self.footer_label.config(text=self.tr('Conversión completada parcialmente'),fg=ERR)
                            title=self.tr('Conversión completada con piezas omitidas')
                            notice=self.tr('El coche principal se ha convertido y el ZIP se ha validado en PC.\n'
                                           'Los siguientes elementos opcionales NO están incluidos en esta conversión:')
                            messagebox.showwarning(title,str(zipfile_path)+'\n\n'+notice+'\n'+
                                '\n'.join(omitted[:16])+('\n…' if len(omitted)>16 else '')+
                                '\n\n'+self.tr('Consulta AVISO-CONVERSION-PARCIAL.txt dentro del ZIP. '
                                               'Comprueba luces, manejo y modificaciones en PS5 antes de compartirlo.'),parent=self.root)
                        else:
                            self.footer_label.config(text=self.tr('Paquete generado con advertencias'),fg=ERR)
                            messagebox.showwarning(self.tr('Conversión con advertencias'),str(zipfile_path)+'\n\n'+'\n'.join(warnings[:8])+'\n\n'+self.tr('Revisa el registro y verifica el resultado en PS5 antes de compartirlo.'),parent=self.root)
                    else:
                        messagebox.showinfo(self.tr('Conversión completa'),self.fmt('ZIP validado:\n{path}\n\nPuedes enviarlo en Enviar por FTP.',path=zipfile_path),parent=self.root)
                elif name=='balanced_zip':
                    self._busy(False)
                    updated,report=value
                    self._log(self.fmt('Conducción equilibrada: {n} ajustes; revisa el comportamiento en PS5.',n=len(report['changes'])))
                    self.refresh_packages()
                    self.footer_label.config(text=self.tr('ZIP de conducción equilibrada creado'),fg=ACC)
                    messagebox.showinfo(self.tr('Conducción equilibrada'),
                        self.fmt('Nuevo ZIP guardado: {path}\nEl original permanece intacto.',path=updated),parent=self.root)
                elif name=='ftp_test':
                    self._busy(False)
                    self._log('FTP: connection and installed index verified; standard FTP cannot report remote free space.')
                    messagebox.showinfo(self.tr('FTP verificado'),self.fmt('Conexión correcta. Entradas en installed: {count}\nEspacio libre: no verificable por FTP estándar.',count=value['installed_entries']),parent=self.root)
                elif name=='ftp_uninstalled':
                    self._busy(False)
                    self.footer_label.config(text=self.tr('Pack desinstalado y respaldado'),fg=ACC)
                    messagebox.showinfo(self.tr('FTP PS5'),self.tr('Pack retirado; los archivos permanecen recuperables en PS5.\nCopia local: ')+value,parent=self.root)
                elif name=='ftp_ok':
                    self._busy(False);self._set_progress(100,self.tr('Transferencia completada'),ftp=True)
                    self.footer_label.config(text=self.tr('FTP finalizado'),fg=ACC)
                    messagebox.showinfo(self.tr('FTP PS5'),self.tr('Paquete enviado y registrado.\nCopia local: ')+value,parent=self.root)
                elif name=='error':
                    self._busy(False);self.footer_label.config(text=self.tr('Operación detenida'),fg=ERR)
                    self._log('ERROR: '+value)
                    if 'shader' in value.lower():
                        self._set_progress(self.percent.get(),self.tr('Shader sin referencia original compatible'))
                    if not self.log_visible:self._toggle_log()
                    messagebox.showerror(self.tr('Operación detenida'),self.tr(friendly_error(value))+'\n\n'+self.tr('Consulta el registro o exporta el diagnóstico.'),parent=self.root)
        except queue.Empty:pass
        if self.started_at and self.working and self.percent.get()<100 and time.monotonic()>=self.next_timer_at:
            elapsed=int(time.monotonic()-self.started_at)
            forecast=(' · '+self.fmt('restante estimado ~{seconds} s',seconds=int(self.estimated_total-elapsed)) if self.estimated_total and elapsed<self.estimated_total else '')
            self.timer_label.config(text=self.fmt('Transcurrido: {seconds} s',seconds=elapsed)+forecast)
            self.next_timer_at=time.monotonic()+1
        self.root.after(90,self._poll)

if __name__=='__main__':ConverterUI().root.mainloop()
